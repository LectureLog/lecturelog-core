"""Неупомянутый и непривязанный слайд: маршрут в галерею раздела или в приложение.

Непривязанный слайд (кандидат с доказательством есть, уверенность `unresolved`)
идёт в галерею раздела с самым сильным доказательством; неупомянутый (кандидатов
нет или страница служебная) — в приложение. Проверяется через сервис выравнивания
со скриптованной LLM и размещение в разделе.
"""

import json

import pytest

from lecturelog.domain.slides import SlideAsset, SlideCatalogEntry
from lecturelog.infrastructure.slides.alignment.anchoring import anchor_assignment
from lecturelog.infrastructure.slides.alignment.service import DocumentAlignmentService


class ScriptedLlm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _srt(*texts: str) -> str:
    return "".join(
        f"{index}\n00:00:{(index - 1) * 10:02d},000 --> 00:00:{index * 10:02d},000\n{text}\n\n"
        for index, text in enumerate(texts, start=1)
    )


def _layout(count: int) -> list[list[dict[str, object]]]:
    return [
        [
            {"title": f"Раздел {index}", "start": f"0:{index * 10:02d}", "end": f"0:{index * 10 + 10:02d}"}
            for index in range(count)
        ]
    ]


def _prompts(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "document_slide_catalog_v3.md").write_text("catalog")
    (prompts / "document_slide_semantic_match_v1.md").write_text("semantic")
    return prompts


def _image(tmp_path, name: str = "slide.png"):
    image = tmp_path / name
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())
    return image


def _catalog_response(*slides: dict) -> str:
    return json.dumps(
        {
            "slides": [
                {
                    "role": "content",
                    "title": None,
                    "visible_text": "",
                    "source_concepts": [],
                    "transcript_language_terms": [],
                    "visual_summary": "",
                    "formulas": [],
                    **slide,
                }
                for slide in slides
            ]
        }
    )


def _semantic(slide_num: int, section: int, blocks: list[int], quote: str, tier: str) -> str:
    return json.dumps(
        {
            "slide_num": slide_num,
            "global_section_id": section,
            "evidence_block_ids": blocks,
            "evidence_quote": quote,
            "semantic_tier": tier,
        }
    )


# Второй слайд колоды, уверенно обсуждённый в разделе 0: без него колода
# целиком признаётся посторонней (deck guard) и маршрут не проверить.
_COURSE_SLIDE = {
    "slide_num": 2,
    "title": "Организация курса",
    "visible_text": "Сегодня говорим про организацию курса",
}
_COURSE_VERDICT = _semantic(2, 0, [1], "Сегодня говорим про организацию курса.", "explicit")


def _assets(tmp_path, count: int) -> list[SlideAsset]:
    return [
        SlideAsset(
            num,
            _image(tmp_path, f"slide{num}.png"),
            "document",
            extracted_text="",
            native_text_quality="none",
        )
        for num in range(1, count + 1)
    ]


@pytest.mark.asyncio
async def test_weak_evidence_slide_goes_to_gallery_of_its_section(tmp_path):
    """Судья дважды подтвердил раздел, но без цитаты: уверенность unresolved.

    Раньше такой слайд объявлялся неупомянутым и уходил в приложение, хотя
    лектор его обсуждал. Теперь он непривязанный и стоит в галерее раздела.
    """
    srt = _srt(
        "Сегодня говорим про организацию курса.",
        "Разберём бинарное дерево поиска и его вершины.",
    )
    entry_fields = {
        "slide_num": 1,
        "title": "Бинарное дерево",
        "visible_text": "Бинарное дерево поиска",
        "source_concepts": ["дерево поиска"],
    }
    llm = ScriptedLlm(
        [
            _catalog_response(entry_fields, _COURSE_SLIDE),
            _semantic(1, 1, [2], "", "strong"),
            _semantic(1, 1, [2], "", "strong"),
            _COURSE_VERDICT,
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))

    result = await service.align(
        assets=_assets(tmp_path, 2),
        section_layout=_layout(2),
        srt_content=srt,
    )
    assignment = result.assignments[0]

    assert assignment.match_status == "unbound"
    assert assignment.assignment_confidence == "unresolved"
    assert assignment.global_section_id == 1
    assert assignment.status_reason == "weak_evidence"

    _, placement = anchor_assignment(
        assignment,
        result.catalog[1],
        "Разберём бинарное дерево поиска и его вершины.",
    )
    assert placement.output_kind == "section_gallery"
    assert placement.global_section_id == 1
    assert placement.anchor_confidence == "fallback"
    assert placement.fallback_reason == "unbound:weak_evidence"
