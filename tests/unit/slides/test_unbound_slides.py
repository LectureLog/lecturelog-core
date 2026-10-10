"""Неупомянутый и непривязанный слайд: маршрут в галерею раздела или в приложение.

Непривязанный слайд (кандидат с доказательством есть, уверенность `unresolved`)
идёт в галерею раздела с самым сильным доказательством; неупомянутый (кандидатов
нет или страница служебная) — в приложение. Проверяется через сервис выравнивания
со скриптованной LLM и размещение в разделе.
"""

import json

import pytest

from lecturelog.domain.slides import SlideAsset
from lecturelog.infrastructure.slides.alignment.anchoring import anchor_assignment
from lecturelog.infrastructure.slides.alignment.diagnostics import write_diagnostic
from lecturelog.infrastructure.slides.alignment.sequence import AlignmentWeights
from lecturelog.infrastructure.slides.alignment.service import (
    AlignmentTuning,
    DocumentAlignmentService,
)


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
            {
                "title": f"Раздел {index}",
                "start": f"0:{index * 10:02d}",
                "end": f"0:{index * 10 + 10:02d}",
            }
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


@pytest.mark.asyncio
async def test_slide_skipped_by_deck_order_goes_to_gallery_of_its_section(tmp_path):
    """Лектор вернулся к слайду 2 после слайда 1 из последнего раздела.

    Путь по порядку колоды выгоднее пропускает слайд 2, чем возвращается на
    пять разделов назад. Но у слайда есть кандидат с доказательством — значит,
    он непривязанный и стоит в галерее раздела 0, а не в приложении.
    """
    srt = _srt(
        "Вспомним про жизненный цикл программы.",
        "Пауза.",
        "Пауза.",
        "Пауза.",
        "Пауза.",
        "Подробно разбираем спиральную модель Боэма, витки спиральной модели и риски.",
    )
    service = DocumentAlignmentService()

    result = await service.align(
        assets=[
            SlideAsset(
                1,
                _image(tmp_path, "spiral.png"),
                "document",
                extracted_text="Спиральная модель Боэма\nВитки спиральной модели и риски",
                native_text_quality="good",
            ),
            SlideAsset(
                2,
                _image(tmp_path, "cycle.png"),
                "document",
                extracted_text="Жизненный цикл программы",
                native_text_quality="good",
            ),
        ],
        section_layout=_layout(6),
        srt_content=srt,
    )
    spiral, cycle = result.assignments

    assert spiral.match_status == "discussed"
    assert spiral.global_section_id == 5
    assert cycle.match_status == "unbound"
    assert cycle.global_section_id == 0
    assert cycle.status_reason == "deck_order_conflict"

    _, placement = anchor_assignment(cycle, result.catalog[2], "Вспомним про жизненный цикл.")
    assert placement.output_kind == "section_gallery"
    assert placement.global_section_id == 0


@pytest.mark.asyncio
async def test_slide_without_candidates_and_blank_page_stay_in_appendix(tmp_path):
    """Неупомянутые слайды по-прежнему в приложении, с различимой причиной."""
    llm = ScriptedLlm(
        [
            # Каталог идёт пачками по два слайда.
            _catalog_response(
                {
                    "slide_num": 1,
                    "title": "Квантовая хромодинамика",
                    "visible_text": "Глюоны и кварки",
                },
                _COURSE_SLIDE,
            ),
            _catalog_response({"slide_num": 3, "role": "blank"}),
            # Судья не нашёл слайду 1 доказательства ни в одном разделе.
            _semantic(1, 0, [], "", "none"),
            _COURSE_VERDICT,
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))

    result = await service.align(
        assets=_assets(tmp_path, 3),
        section_layout=_layout(2),
        srt_content=_srt(
            "Сегодня говорим про организацию курса.",
            "Разберём бинарное дерево поиска и его вершины.",
        ),
    )
    unrelated, course, blank = result.assignments

    assert course.match_status == "discussed"
    assert course.status_reason is None
    assert (unrelated.match_status, unrelated.status_reason) == ("unmentioned", "no_candidates")
    assert unrelated.reason_code == unrelated.status_reason
    assert (blank.match_status, blank.status_reason) == ("unmentioned", "service_role")
    for assignment in (unrelated, blank):
        _, placement = anchor_assignment(
            assignment, result.catalog[assignment.slide_num], "Любой текст раздела."
        )
        assert placement.output_kind == "appendix"
        assert placement.global_section_id is None


# Сценарий слайда 16 лекции 02-12: профстандарт 3-го уровня. Судья подтвердил
# раздел 1, где термин лишь упомянут мимоходом, а целиком слайд разбирается в
# разделе 3 — уже после следующего по колоде слайда (раздел 2).
_STANDARD_SLIDE = {
    "slide_num": 2,
    "title": "Профессиональный стандарт программиста",
    "visible_text": (
        "Третий уровень квалификации\nТрудовые функции\nКодирование программных модулей\n"
        "Отладка и тестирование компонентов\nОформление документации"
    ),
    "source_concepts": ["профессиональный стандарт", "уровень квалификации"],
}
_STANDARD_SRT = _srt(
    "Сегодня говорим про организацию курса.",
    "Пауза.",
    "Типы программных продуктов; профессиональный стандарт упомянем позже.",
    "Пауза.",
    "Модели жизненного цикла: водопадная модель, итеративная модель, спиральная модель.",
    "Пауза.",
    "Профессиональный стандарт программиста: третий уровень квалификации, трудовые"
    " функции — кодирование программных модулей, отладка и тестирование компонентов,"
    " оформление документации.",
    "Пауза.",
)


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


# Разделы по 20 секунд без общих реплик на границах: в каждом одна
# содержательная реплика и пауза, чтобы лексика раздела не подмешивалась соседу.
_STANDARD_LAYOUT = [
    [
        {
            "title": f"Раздел {index}",
            "start": _clock(index * 20 + 1),
            "end": _clock(index * 20 + 19),
        }
        for index in range(4)
    ]
]


def _standard_llm(*standard_verdicts: str) -> ScriptedLlm:
    return ScriptedLlm(
        [
            _catalog_response({**_COURSE_SLIDE, "slide_num": 1}, _STANDARD_SLIDE),
            _catalog_response(
                {
                    "slide_num": 3,
                    "title": "Модели жизненного цикла",
                    "visible_text": "Водопадная модель\nИтеративная модель\nСпиральная модель",
                }
            ),
            _semantic(1, 0, [1], "Сегодня говорим про организацию курса.", "explicit"),
            *standard_verdicts,
            _semantic(3, 2, [5], "Модели жизненного цикла", "explicit"),
        ]
    )


@pytest.mark.asyncio
async def test_stronger_competitor_sends_slide_to_competitor_gallery(tmp_path):
    """Отрицательный margin: конкурент совпадает с речью заметно сильнее выбора.

    Путь по порядку колоды держит слайд в разделе 1 — так подтвердил судья, —
    но раздел 3 говорит о слайде намного больше. Уверенность падает до
    unresolved, и слайд уходит в галерею раздела конкурента, хотя раздел 3
    идёт после раздела следующего слайда и нарушает порядок колоды.
    """
    llm = _standard_llm(_semantic(2, 1, [3], "профессиональный стандарт", "explicit"))
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))

    result = await service.align(
        assets=_assets(tmp_path, 3),
        section_layout=_STANDARD_LAYOUT,
        srt_content=_STANDARD_SRT,
    )
    course, standard, lifecycle = result.assignments

    assert (course.match_status, course.global_section_id) == ("discussed", 0)
    assert (lifecycle.match_status, lifecycle.global_section_id) == ("discussed", 2)
    assert standard.match_status == "unbound"
    assert standard.assignment_confidence == "unresolved"
    assert standard.status_reason == "stronger_competitor"
    assert standard.global_section_id == 3

    _, placement = anchor_assignment(standard, result.catalog[2], "Профессиональный стандарт.")
    assert placement.output_kind == "section_gallery"
    assert placement.global_section_id == 3
    assert placement.fallback_reason == "unbound:stronger_competitor"

    # Диагностика называет причину и честно разводит, куда ушёл слайд
    # (сильнейший кандидат, без своего margin) и какой выбор пути проиграл.
    assert standard.reason_code.startswith("semantic_none:")
    assert ":margin=none:path_section=1:path_min_margin=-" in standard.reason_code
    diagnostic = tmp_path / "alignment.json"
    write_diagnostic(diagnostic, mode="v2", assignments=result.assignments)
    payload = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert payload["assignments"][1]["status_reason"] == "stronger_competitor"


@pytest.mark.asyncio
async def test_stronger_competitor_unbinds_double_confirmed_strong_verdict(tmp_path):
    """Margin действует на всех уровнях: strong-вердикт с цитатой раньше давал probable."""
    verdict = _semantic(2, 1, [3], "профессиональный стандарт", "strong")
    llm = _standard_llm(verdict, verdict)
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))

    result = await service.align(
        assets=_assets(tmp_path, 3),
        section_layout=_STANDARD_LAYOUT,
        srt_content=_STANDARD_SRT,
    )
    standard = result.assignments[1]

    assert (standard.match_status, standard.status_reason) == ("unbound", "stronger_competitor")
    assert standard.global_section_id == 3


@pytest.mark.asyncio
async def test_margin_threshold_is_tunable_next_to_alignment_weights(tmp_path):
    """Порог margin задаётся рядом с весами: ниже него — уже не конкурент."""
    llm = _standard_llm(_semantic(2, 1, [3], "профессиональный стандарт", "explicit"))
    service = DocumentAlignmentService(
        llm=llm,
        models=["m"],
        prompts_dir=_prompts(tmp_path),
        tuning=AlignmentTuning(weights=AlignmentWeights(min_margin=-100.0)),
    )

    result = await service.align(
        assets=_assets(tmp_path, 3),
        section_layout=_STANDARD_LAYOUT,
        srt_content=_STANDARD_SRT,
    )
    standard = result.assignments[1]

    assert standard.match_status == "discussed"
    assert standard.assignment_confidence == "probable"
    assert standard.global_section_id == 1
