"""Визуальное описание слайда как доказательство привязки.

Каталог уже описывает картинку каждой страницы (`visual_summary`). Слайд-схема
почти без текста должен привязываться к разделу, где лектор её описывал: описание
участвует в поиске кандидатов и в семантической проверке наравне с видимым
текстом и заполняет визуальную оценку кандидата. Новых вызовов LLM при этом нет.
Проверяется через сервис выравнивания со скриптованной LLM.
"""

import json

import pytest

from lecturelog.domain.slides import SlideAsset
from lecturelog.infrastructure.slides.alignment.diagnostics import write_diagnostic
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


# Разделы по 20 секунд без общих реплик на границах: в каждом одна
# содержательная реплика (блок 2k+1) и пауза.
_LAYOUT = [
    [
        {
            "title": f"Раздел {index}",
            "start": f"0:{index * 20 + 1:02d}",
            "end": f"0:{index * 20 + 19:02d}",
        }
        for index in range(4)
    ]
]

_SRT = _srt(
    "Сегодня говорим про организацию курса.",
    "Пауза.",
    "Клиент отправляет запрос серверу, а сервер читает базу данных и возвращает ответ.",
    "Пауза.",
    "Сортировка пузырьком сравнивает соседние элементы массива.",
    "Пауза.",
    "Итоги и домашнее задание.",
    "Пауза.",
)

_COURSE_SLIDE = {
    "slide_num": 1,
    "title": "Организация курса",
    "visible_text": "Сегодня говорим про организацию курса",
}

# Страница-схема: видимого текста нет, содержание — только в описании картинки.
_DIAGRAM_SLIDE = {
    "slide_num": 2,
    "title": None,
    "visible_text": "",
    "visual_summary": (
        "Схема: клиент отправляет запрос серверу, сервер обращается к базе данных"
        " и возвращает ответ клиенту."
    ),
}


def _prompts(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir(exist_ok=True)
    (prompts / "document_slide_catalog_v3.md").write_text("catalog")
    (prompts / "document_slide_semantic_match_v1.md").write_text("semantic")
    return prompts


def _assets(tmp_path, count: int) -> list[SlideAsset]:
    assets = []
    for num in range(1, count + 1):
        image = tmp_path / f"slide{num}.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + image.name.encode())
        assets.append(
            SlideAsset(num, image, "document", extracted_text="", native_text_quality="none")
        )
    return assets


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


_COURSE_VERDICT = _semantic(1, 0, [1], "Сегодня говорим про организацию курса.", "explicit")
_DIAGRAM_QUOTE = "Клиент отправляет запрос серверу"


@pytest.mark.asyncio
async def test_diagram_slide_without_text_gets_candidate_and_evidence_in_its_section(tmp_path):
    """Пустой видимый текст, содержательное описание схемы.

    Поиск кандидатов оставляет один раздел: без описания все оценки нулевые и
    выбирается первый раздел, где про схему ни слова. Описание выводит в пул
    раздел 1, судья видит описание в запросе и подтверждает раздел цитатой.
    Вызовов LLM ровно столько же, сколько у колоды без описаний: один каталог
    на пару страниц и одна проверка на слайд.
    """
    llm = ScriptedLlm(
        [
            _catalog_response(_COURSE_SLIDE, _DIAGRAM_SLIDE),
            _COURSE_VERDICT,
            _semantic(2, 1, [3], _DIAGRAM_QUOTE, "explicit"),
        ]
    )
    service = DocumentAlignmentService(
        llm=llm,
        models=["m"],
        prompts_dir=_prompts(tmp_path),
        tuning=AlignmentTuning(candidate_limit=1, neighbor_radius=0),
    )

    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_SRT
    )
    _, diagram = result.assignments

    assert (diagram.match_status, diagram.global_section_id) == ("discussed", 1)
    assert diagram.evidence_block_ids == (3,)
    assert len(llm.calls) == 3
    assert llm.responses == []
    # Судья видит описание картинки и кандидата из нужного раздела.
    payload = json.loads(llm.calls[2]["prompt"].split("\n", 1)[1])
    assert payload["slide"]["visual_summary"] == _DIAGRAM_SLIDE["visual_summary"]
    assert [item["global_section_id"] for item in payload["candidates"]] == [1]
    assert 3 in [block["block_id"] for block in payload["candidates"][0]["evidence_blocks"]]


@pytest.mark.asyncio
async def test_visual_evidence_reaches_verified_and_diagnostic_shows_its_contribution(tmp_path):
    """Strong-вердикт с цитатой сам по себе даёт лишь probable.

    Описание схемы полностью совпадает с речью раздела 1 и не совпадает с
    остальными: визуальная оценка высокая, отрыв от конкурентов есть — срабатывает
    ветка калибровки по визуальному доказательству, и привязка verified.
    Диагностика показывает визуальную оценку и её вклад в силу доказательства.
    """
    strong = _semantic(2, 1, [3], _DIAGRAM_QUOTE, "strong")
    llm = ScriptedLlm(
        [_catalog_response(_COURSE_SLIDE, _DIAGRAM_SLIDE), _COURSE_VERDICT, strong, strong]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))

    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_SRT
    )
    _, diagram = result.assignments

    assert (diagram.match_status, diagram.global_section_id) == ("discussed", 1)
    assert diagram.assignment_confidence == "verified"
    assert ":visual=1.000:" in diagram.reason_code
    assert diagram.visual_contribution == pytest.approx(3.0)

    path = tmp_path / "diagnostic.json"
    write_diagnostic(path, mode="document", assignments=result.assignments)
    saved = json.loads(path.read_text(encoding="utf-8"))["assignments"]
    assert saved[1]["visual_contribution"] == pytest.approx(3.0)
    # У слайда без описания вклада нет.
    assert saved[0]["visual_contribution"] is None


# Слайд с богатым текстом. Лектор назвал тему в разделе 1 (так подтвердил
# судья), а в разделе 2 нарисовал схему и повторил термины страницы — по
# лексике раздел 2 чуть сильнее (margin около −2.3, в пределах допуска шума).
_HTTP_SRT = _srt(
    "Сегодня говорим про организацию курса.",
    "Пауза.",
    "Протокол HTTP, метод запроса.",
    "Пауза.",
    "Нарисуем: прямоугольники браузера и веб-сервера, стрелки сообщений; запрос HTTP:"
    " метод, заголовки, тело; ответ: код статуса, заголовки, тело.",
    "Пауза.",
    "Итоги и домашнее задание.",
    "Пауза.",
)
_HTTP_SLIDE = {
    "slide_num": 2,
    "title": "Протокол HTTP",
    "visible_text": "Запрос HTTP: метод, заголовки, тело\nОтвет: код статуса, заголовки, тело",
    "source_concepts": ["метод запроса", "код статуса"],
}
_HTTP_VERDICT = _semantic(2, 1, [3], "Протокол HTTP, метод запроса.", "explicit")


async def _align_http_slide(tmp_path, visual_summary: str):
    llm = ScriptedLlm(
        [
            _catalog_response(_COURSE_SLIDE, {**_HTTP_SLIDE, "visual_summary": visual_summary}),
            _COURSE_VERDICT,
            _HTTP_VERDICT,
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_HTTP_SRT
    )
    return result.assignments[1], len(llm.calls)


@pytest.mark.asyncio
async def test_visual_summary_of_text_rich_slide_does_not_create_stronger_competitor(tmp_path):
    """Описание картинки целиком совпадает с речью раздела-конкурента.

    Будь его вес полным (+3), отрыв выбора упал бы ниже порога margin (−5) и
    слайд ушёл бы непривязанным к конкуренту, хотя текст страницы и цитата
    судьи указывают на раздел 1. Вес описания пропорционален его доле в
    содержании страницы, поэтому у слайда с богатым текстом оно остаётся
    добавкой: привязка и уверенность те же, что и без описания, вызовов LLM
    столько же.
    """
    without, calls_without = await _align_http_slide(tmp_path, "")
    with_visual, calls_with = await _align_http_slide(
        tmp_path, "Схема: прямоугольники браузера и веб-сервера соединены стрелками сообщений."
    )

    assert (without.match_status, without.global_section_id) == ("discussed", 1)
    assert (with_visual.match_status, with_visual.global_section_id) == ("discussed", 1)
    assert with_visual.assignment_confidence == without.assignment_confidence
    assert with_visual.status_reason is None
    assert calls_with == calls_without == 3
