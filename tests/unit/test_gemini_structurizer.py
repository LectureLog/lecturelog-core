import json

import pytest

from lecturelog.domain.slides import SlideAsset, StructurizeContext
from lecturelog.infrastructure.structurize.gemini_structurizer import (
    GeminiStructurizer,
    _parse_json,
)


@pytest.mark.asyncio
async def test_v2_uses_evidence_and_does_not_send_slide_to_render(tmp_path, prompts_dir):
    srt = tmp_path / "t.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\nТеперь разберём бинарное дерево поиска и его вершины.\n",
        encoding="utf-8",
    )
    slide = tmp_path / "slide.png"
    slide.write_bytes(b"slide")
    topics_json = json.dumps([{"title": "Деревья", "start": "0:00", "end": "0:10"}])
    sections_json = json.dumps([{"title": "Поиск", "start": "0:00", "end": "0:10"}])
    gemini = ScriptedGemini([topics_json, sections_json, "Бинарное дерево поиска.\n\nВершины."])
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = "v2"

    result = await structurizer.structurize(
        srt_path=srt,
        slide_assets=[
            SlideAsset(
                1,
                slide,
                "document",
                extracted_text="Бинарное дерево поиска. Вершины.",
                native_text_quality="good",
            )
        ],
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )

    assert result.slide_assignments[0].match_status == "discussed"
    assert result.slide_assignments[0].assignment_confidence == "probable"
    assert result.slide_placements[0].output_kind == "section_gallery"
    assert "<!-- slide:1 -->" not in result.topics[0].sections[0].content
    assert result.topics[0].sections[0].slide_indices == [1]
    assert all(not call["images"] for call in gemini.recorded_calls)


@pytest.mark.asyncio
async def test_v2_alignment_failure_falls_back_to_appendix(tmp_path, prompts_dir, monkeypatch):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:10,000\ntext\n", encoding="utf-8")
    slide = tmp_path / "slide.png"
    slide.write_bytes(b"slide")
    topics_json = json.dumps([{"title": "T", "start": "0:00", "end": "0:10"}])
    sections_json = json.dumps([{"title": "S", "start": "0:00", "end": "0:10"}])
    gemini = ScriptedGemini([topics_json, sections_json, "Rendered only from SRT."])
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = "v2"

    def fail(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(structurizer._document_alignment, "align", fail)
    result = await structurizer.structurize(
        srt_path=srt,
        slide_assets=[
            SlideAsset(
                1,
                slide,
                "document",
                extracted_text="slide-only claim",
                native_text_quality="good",
            )
        ],
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )
    assert result.slide_placements[0].output_kind == "appendix"
    assert result.topics[0].sections[0].slide_indices == []


@pytest.mark.asyncio
async def test_v2_diagnostics_include_final_placements(tmp_path, prompts_dir):
    srt = tmp_path / "t.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\nРазбираем бинарное дерево.\n",
        encoding="utf-8",
    )
    slide = tmp_path / "slide.png"
    slide.write_bytes(b"slide")
    gemini = ScriptedGemini(
        [
            json.dumps([{"title": "T", "start": "0:00", "end": "0:10"}]),
            json.dumps([{"title": "S", "start": "0:00", "end": "0:10"}]),
            "Бинарное дерево.",
        ]
    )
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = "v2"
    output_dir = tmp_path / "out"

    result = await structurizer.structurize(
        srt_path=srt,
        slide_assets=[
            SlideAsset(
                1,
                slide,
                "document",
                extracted_text="Бинарное дерево",
                native_text_quality="good",
            )
        ],
        context=StructurizeContext("audio"),
        output_dir=output_dir,
    )

    diagnostic = json.loads(
        (output_dir / "document-slide-alignment.json").read_text(encoding="utf-8")
    )
    assert diagnostic["placements"] == [
        {
            "slide_num": result.slide_placements[0].slide_num,
            "output_kind": result.slide_placements[0].output_kind,
            "global_section_id": result.slide_placements[0].global_section_id,
            "block_index": result.slide_placements[0].block_index,
            "side": result.slide_placements[0].side,
            "gallery_position": result.slide_placements[0].gallery_position,
            "anchor_confidence": result.slide_placements[0].anchor_confidence,
            "fallback_reason": result.slide_placements[0].fallback_reason,
        }
    ]


@pytest.mark.asyncio
async def test_v2_diagnostics_failure_is_warning_only(tmp_path, prompts_dir, monkeypatch):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:10,000\ntext\n", encoding="utf-8")
    slide = tmp_path / "slide.png"
    slide.write_bytes(b"slide")
    gemini = ScriptedGemini(
        [
            json.dumps([{"title": "T", "start": "0:00", "end": "0:10"}]),
            json.dumps([{"title": "S", "start": "0:00", "end": "0:10"}]),
            "Rendered text.",
        ]
    )
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = "v2"

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "lecturelog.infrastructure.structurize.gemini_structurizer.write_diagnostic", fail
    )
    result = await structurizer.structurize(
        srt_path=srt,
        slide_assets=[
            SlideAsset(
                1,
                slide,
                "document",
                extracted_text="text",
                native_text_quality="good",
            )
        ],
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )

    assert result.slide_assignments


def test_parse_json_strips_code_fence():
    assert _parse_json("```json\n[1, 2]\n```") == [1, 2]


def test_parse_json_plain():
    assert _parse_json('{"a": 1}') == {"a": 1}


class ScriptedGemini:
    """Отдаёт ответы по очереди в порядке вызовов и фиксирует параметры каждого вызова."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.on_usage_seen = []
        self.recorded_calls = []

    async def call(
        self, prompt, models, images=None, *, on_usage=None, response_json=False, effort=None
    ):
        self.on_usage_seen.append(on_usage)
        self.recorded_calls.append(
            {"models": list(models), "effort": effort, "images": images, "prompt": prompt}
        )
        r = self._responses[self.calls]
        self.calls += 1
        return r


def _make_structurizer(gemini, prompts_dir):
    return GeminiStructurizer(
        gemini_client=gemini,
        split_models=["m"],
        subsplit_models=["m"],
        render_models=["m"],
        concurrency_subsplit=1,
        concurrency_render=1,
        prompts_dir=prompts_dir,
        effort_split="low",
        effort_subsplit="low",
        effort_render="low",
    )


def _make_structurizer_distinct_stages(gemini, prompts_dir):
    """Structurizer с РАЗНЫМИ model-списками и effort по стадиям — чтобы тест мог
    отличить, какой .call принадлежит какой стадии, и поймать перепутанный effort."""
    return GeminiStructurizer(
        gemini_client=gemini,
        split_models=["split-model"],
        subsplit_models=["subsplit-model"],
        render_models=["render-model"],
        concurrency_subsplit=1,
        concurrency_render=1,
        prompts_dir=prompts_dir,
        effort_split="low",
        effort_subsplit="medium",
        effort_render="high",
    )


@pytest.fixture
def prompts_dir(tmp_path):
    d = tmp_path / "prompts"
    d.mkdir()
    for name in (
        "split_topics_v1.md",
        "split_v1.md",
        "slide_match_topics_v1.md",
        "slide_match_v1.md",
        "section_v1.md",
    ):
        (d / name).write_text("prompt {title} {start} {end}", encoding="utf-8")
    return d


@pytest.mark.asyncio
async def test_structurize_without_slides_builds_topics(tmp_path, prompts_dir):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:05:00,000\nтекст лекции\n", encoding="utf-8")

    # порядок вызовов: split_topics -> subsplit(тема0) -> render(секция0)
    topics_json = json.dumps([{"title": "Тема 1", "start": "0:00", "end": "5:00"}])
    sections_json = json.dumps([{"title": "Подтема 1", "start": "0:00", "end": "5:00"}])
    rendered_md = "## Подтема 1\nсодержание"
    gemini = ScriptedGemini([topics_json, sections_json, rendered_md])

    structurizer = _make_structurizer(gemini, prompts_dir)
    topics = await structurizer.structurize(
        srt_path=srt, slide_images=[], output_dir=tmp_path / "out"
    )

    assert len(topics) == 1
    assert topics[0].title == "Тема 1"
    assert len(topics[0].sections) == 1
    assert topics[0].sections[0].title == "Подтема 1"
    assert "содержание" in topics[0].sections[0].content


@pytest.mark.asyncio
async def test_structurize_normalizes_srt_timecodes_with_milliseconds(tmp_path, prompts_dir):
    """Регресс фазы 2: модель может скопировать полный SRT-таймкод (ЧЧ:ММ:СС,МСС),
    а ридер веба принимает только ЧЧ:ММ:СС. Ядро обязано нормализовать start/end
    и в Topic, и в Section, иначе structure.json ломает ридер («Внутренняя ошибка»)."""
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,040 --> 00:05:00,672\nтекст\n", encoding="utf-8")

    topics_json = json.dumps([{"title": "Тема 1", "start": "00:00:00,040", "end": "00:05:00,672"}])
    sections_json = json.dumps(
        [{"title": "Подтема 1", "start": "00:00:00,040", "end": "00:05:00,672"}]
    )
    rendered_md = "контент"
    gemini = ScriptedGemini([topics_json, sections_json, rendered_md])

    structurizer = _make_structurizer(gemini, prompts_dir)
    topics = await structurizer.structurize(
        srt_path=srt, slide_images=[], output_dir=tmp_path / "out"
    )

    assert topics[0].start == "00:00:00"
    assert topics[0].end == "00:05:00"
    assert topics[0].sections[0].start == "00:00:00"
    assert topics[0].sections[0].end == "00:05:00"


@pytest.mark.asyncio
async def test_structurize_repairs_inverted_section_range(tmp_path, prompts_dir):
    """Сплиттер иногда выдаёт секцию с end <= start.

    Такая шкала роняла ffmpeg («-to value smaller than -ss») уже после того, как
    потрачены транскрипция и все LLM-стадии, и заодно обнуляла выравнивание всей
    колоды. Границу чиним по соседям: конец битой секции — начало следующей.
    """
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:10:00,000\nтекст\n", encoding="utf-8")

    topics_json = json.dumps([{"title": "Тема 1", "start": "00:00:00", "end": "00:10:00"}])
    sections_json = json.dumps(
        [
            {"title": "Подтема 1", "start": "00:00:00", "end": "00:04:00"},
            {"title": "Подтема 2", "start": "00:04:00", "end": "00:03:00"},
            {"title": "Подтема 3", "start": "00:07:00", "end": "00:10:00"},
        ]
    )
    gemini = ScriptedGemini([topics_json, sections_json, "к1", "к2", "к3"])

    structurizer = _make_structurizer(gemini, prompts_dir)
    topics = await structurizer.structurize(
        srt_path=srt, slide_images=[], output_dir=tmp_path / "out"
    )

    sections = topics[0].sections
    assert [(s.start, s.end) for s in sections] == [
        ("00:00:00", "00:04:00"),
        ("00:04:00", "00:07:00"),
        ("00:07:00", "00:10:00"),
    ]


@pytest.mark.asyncio
async def test_structurize_repairs_inverted_range_in_last_section(tmp_path, prompts_dir):
    """У последней секции соседа справа нет — границу берём из конца транскрипта."""
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:10:00,000\nтекст\n", encoding="utf-8")

    topics_json = json.dumps([{"title": "Тема 1", "start": "00:00:00", "end": "00:10:00"}])
    sections_json = json.dumps(
        [
            {"title": "Подтема 1", "start": "00:00:00", "end": "00:06:00"},
            {"title": "Подтема 2", "start": "00:06:00", "end": "00:06:00"},
        ]
    )
    gemini = ScriptedGemini([topics_json, sections_json, "к1", "к2"])

    structurizer = _make_structurizer(gemini, prompts_dir)
    topics = await structurizer.structurize(
        srt_path=srt, slide_images=[], output_dir=tmp_path / "out"
    )

    assert [(s.start, s.end) for s in topics[0].sections] == [
        ("00:00:00", "00:06:00"),
        ("00:06:00", "00:10:00"),
    ]


@pytest.mark.asyncio
async def test_structurize_subsplit_fallback_on_bad_json(tmp_path, prompts_dir):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:05:00,000\nтекст\n", encoding="utf-8")
    topics_json = json.dumps([{"title": "Тема 1", "start": "0:00", "end": "5:00"}])
    bad_subsplit = "это не json"
    rendered_md = "контент"
    gemini = ScriptedGemini([topics_json, bad_subsplit, rendered_md])

    structurizer = _make_structurizer(gemini, prompts_dir)
    topics = await structurizer.structurize(
        srt_path=srt, slide_images=[], output_dir=tmp_path / "out"
    )
    # fallback: тема целиком становится одной секцией с её title/start/end
    assert len(topics) == 1
    assert len(topics[0].sections) == 1
    assert topics[0].sections[0].title == "Тема 1"


@pytest.mark.asyncio
async def test_structurize_forwards_on_usage_to_every_gemini_call(tmp_path, prompts_dir):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:05:00,000\nтекст\n", encoding="utf-8")
    topics_json = json.dumps([{"title": "Тема 1", "start": "0:00", "end": "5:00"}])
    sections_json = json.dumps([{"title": "Подтема 1", "start": "0:00", "end": "5:00"}])
    gemini = ScriptedGemini([topics_json, sections_json, "контент"])

    async def on_usage(payload):
        return None

    structurizer = _make_structurizer(gemini, prompts_dir)
    await structurizer.structurize(
        srt_path=srt, slide_images=[], output_dir=tmp_path / "out", on_usage=on_usage
    )

    # каждый вызов gemini получил наш non-None on_usage
    assert gemini.on_usage_seen
    assert all(cb is on_usage for cb in gemini.on_usage_seen)


@pytest.mark.asyncio
async def test_structurize_with_slides_uses_per_stage_effort_and_models(tmp_path, prompts_dir):
    """Ветка со слайд-картинками: split -> subsplit -> rough slide-match ->
    fine slide-match -> render. Проверяем, что КАЖДЫЙ .call получил effort и
    models своей стадии (split/subsplit/render не перепутаны), и что вызовы
    с картинками (rough/fine slide-match, render с привязанным слайдом)
    действительно происходят."""
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:05:00,000\nтекст лекции\n", encoding="utf-8")

    slide_path = tmp_path / "slide1.png"
    slide_path.write_bytes(b"fake-slide-bytes")

    topics_json = json.dumps([{"title": "Тема 1", "start": "0:00", "end": "5:00"}])
    sections_json = json.dumps([{"title": "Подтема 1", "start": "0:00", "end": "5:00"}])
    rough_mapping_json = json.dumps({"0": [1]})
    fine_mapping_json = json.dumps({"0": [1]})
    rendered_md = "## Подтема 1\nсодержание"

    gemini = ScriptedGemini(
        [topics_json, sections_json, rough_mapping_json, fine_mapping_json, rendered_md]
    )

    structurizer = _make_structurizer_distinct_stages(gemini, prompts_dir)
    topics = await structurizer.structurize(
        srt_path=srt, slide_images=[slide_path], output_dir=tmp_path / "out"
    )

    assert len(topics) == 1
    assert topics[0].sections[0].slide_indices == [1]

    assert gemini.calls == 5
    calls = gemini.recorded_calls

    # Сопоставляем стадию по models-списку в записанном вызове.
    split_calls = [c for c in calls if c["models"] == ["split-model"]]
    subsplit_calls = [c for c in calls if c["models"] == ["subsplit-model"]]
    render_calls = [c for c in calls if c["models"] == ["render-model"]]

    # split_topics: 1 вызов, без картинок, effort_split
    assert len(split_calls) == 1
    assert split_calls[0]["effort"] == "low"
    assert split_calls[0]["images"] is None

    # subsplit + rough slide-match + fine slide-match: 3 вызова, effort_subsplit
    assert len(subsplit_calls) == 3
    assert all(c["effort"] == "medium" for c in subsplit_calls)
    # среди subsplit-вызовов есть вызовы с картинками (rough и fine slide-match)
    with_images = [c for c in subsplit_calls if c["images"]]
    assert len(with_images) == 2

    # render: 1 вызов, effort_render, с привязанным слайдом -> есть картинки
    assert len(render_calls) == 1
    assert render_calls[0]["effort"] == "high"
    assert render_calls[0]["images"]


def test_slide_matcher_effort_is_independent_from_subsplit(tmp_path):
    """Поднятие effort контентных стадий не должно менять effort матчера слайдов."""
    structurizer = GeminiStructurizer(
        gemini_client=object(),
        split_models=["m"],
        subsplit_models=["m"],
        render_models=["m"],
        concurrency_subsplit=1,
        concurrency_render=1,
        prompts_dir=tmp_path,
        effort_split="medium",
        effort_subsplit="medium",
        effort_render="medium",
        effort_slide_match="low",
    )

    assert structurizer._document_alignment._effort == "low"


def test_slide_matcher_models_are_independent_from_subsplit(tmp_path):
    """У матчера своя ротация: в неё добавляется модель, не подверженная RECITATION."""
    structurizer = GeminiStructurizer(
        gemini_client=object(),
        split_models=["m"],
        subsplit_models=["google/gemini-3.6-flash"],
        render_models=["m"],
        concurrency_subsplit=1,
        concurrency_render=1,
        prompts_dir=tmp_path,
        effort_split="medium",
        effort_subsplit="medium",
        effort_render="medium",
        slide_match_models=["google/gemini-3.6-flash", "google/gemma-4-31b-it:free"],
    )

    assert structurizer._document_alignment._models == [
        "google/gemini-3.6-flash",
        "google/gemma-4-31b-it:free",
    ]


def test_slide_matcher_models_fall_back_to_subsplit(tmp_path):
    """Без явного списка поведение прежнее — модели стадии SUBSPLIT."""
    structurizer = GeminiStructurizer(
        gemini_client=object(),
        split_models=["m"],
        subsplit_models=["google/gemini-3.6-flash", "google/gemini-3.5-flash"],
        render_models=["m"],
        concurrency_subsplit=1,
        concurrency_render=1,
        prompts_dir=tmp_path,
        effort_split="medium",
        effort_subsplit="medium",
        effort_render="medium",
    )

    assert structurizer._document_alignment._models == [
        "google/gemini-3.6-flash",
        "google/gemini-3.5-flash",
    ]


def test_slide_context_block_limits_usage_to_spelling():
    """Блок обязан ограничивать применение: иначе рендер пересказывает слайды."""
    from lecturelog.domain.slides import SlideCatalogEntry
    from lecturelog.infrastructure.structurize.gemini_structurizer import _slide_context_block

    entry = SlideCatalogEntry(
        7,
        "content",
        "ENIAC",
        "первая ЭВМ, программирование переключателями",
        source_concepts=("ENIAC", "перфокарты"),
        transcript_language_terms=("ЭНИАК",),
        proper_nouns=("ENIAC",),
    )

    block = _slide_context_block([entry])

    assert "ENIAC" in block
    assert "не добавляй" in block.lower()


def test_slide_context_block_is_empty_without_entries():
    from lecturelog.infrastructure.structurize.gemini_structurizer import _slide_context_block

    assert _slide_context_block([]) == ""


@pytest.mark.asyncio
async def test_v2_render_prompt_carries_slide_spellings(tmp_path, prompts_dir):
    """Сквозная проверка: написания со слайда доходят до промпта рендера."""
    srt = tmp_path / "t.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\nРазберём бинарное дерево поиска и его вершины.\n",
        encoding="utf-8",
    )
    slide = tmp_path / "slide.png"
    slide.write_bytes(b"slide")
    topics_json = json.dumps([{"title": "Деревья", "start": "0:00", "end": "0:10"}])
    sections_json = json.dumps([{"title": "Поиск", "start": "0:00", "end": "0:10"}])
    gemini = ScriptedGemini([topics_json, sections_json, "Бинарное дерево поиска.\n\nВершины."])
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = "v2"

    await structurizer.structurize(
        srt_path=srt,
        slide_assets=[
            SlideAsset(
                1,
                slide,
                "document",
                extracted_text="Бинарное дерево поиска. Реализация на Fortran.",
                native_text_quality="good",
            )
        ],
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )

    render_prompt = gemini.recorded_calls[-1]["prompt"]
    assert "Написания имён и терминов из презентации" in render_prompt
    assert "Fortran" in render_prompt
    # Картинки в рендер по-прежнему не уходят: контекст передаётся текстом.
    assert all(not call["images"] for call in gemini.recorded_calls)


@pytest.mark.asyncio
async def test_render_context_covers_unassigned_slides(tmp_path, prompts_dir):
    """Потерянный соседний слайд обязан подсказывать написание.

    Слайд 2 (ENIAC) не привязался именно потому, что ASR дал «Мониак». Если
    подсказки брать только с привязанных слайдов, круг не разорвать: искажение
    мешает матчингу, а без матчинга нет подсказки для его исправления. Поэтому
    справочник раздела берёт и страницы ±1 от привязанных.
    """
    srt = tmp_path / "t.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\nРазберём бинарное дерево поиска и его вершины.\n",
        encoding="utf-8",
    )
    matched = tmp_path / "slide1.png"
    matched.write_bytes(b"slide")
    lost = tmp_path / "slide2.png"
    lost.write_bytes(b"slide")
    topics_json = json.dumps([{"title": "Деревья", "start": "0:00", "end": "0:10"}])
    sections_json = json.dumps([{"title": "Поиск", "start": "0:00", "end": "0:10"}])
    gemini = ScriptedGemini([topics_json, sections_json, "Бинарное дерево поиска.\n\nВершины."])
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = "v2"

    await structurizer.structurize(
        srt_path=srt,
        slide_assets=[
            SlideAsset(
                1,
                matched,
                "document",
                extracted_text="Бинарное дерево поиска. Вершины.",
                native_text_quality="good",
            ),
            SlideAsset(
                2,
                lost,
                "document",
                extracted_text="ENIAC и перфокарты",
                native_text_quality="good",
            ),
        ],
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )

    render_prompt = gemini.recorded_calls[-1]["prompt"]
    assert "ENIAC" in render_prompt


def test_slide_context_block_lists_only_proper_nouns():
    """В справочник идут только имена и аббревиатуры.

    Целые формулировки со слайда рендер переносил в конспект как сказанное
    лектором: словарь из отдельных токенов переносить нечего.
    """
    from lecturelog.domain.slides import SlideCatalogEntry
    from lecturelog.infrastructure.structurize.gemini_structurizer import _slide_context_block

    entry = SlideCatalogEntry(
        14,
        "content",
        "Востребованные компетенции",
        "владение более чем одним языком программирования",
        source_concepts=("владение более чем одним языком программирования",),
        proper_nouns=("ENIAC", "Fortran"),
    )

    block = _slide_context_block([entry])

    assert "ENIAC" in block
    assert "Fortran" in block
    assert "владение более чем одним" not in block
    assert "Востребованные компетенции" not in block


def _scoped_glossary_deck(tmp_path, nouns):
    """Колода, где у каждой страницы ровно одно имя собственное в каталоге."""
    from lecturelog.domain.slides import SlideCatalogEntry

    assets = []
    catalog = {}
    for num, noun in enumerate(nouns, start=1):
        path = tmp_path / f"slide{num}.png"
        path.write_bytes(b"slide")
        assets.append(
            SlideAsset(num, path, "document", extracted_text=noun, native_text_quality="good")
        )
        catalog[num] = SlideCatalogEntry(num, "content", noun, noun, proper_nouns=(noun,))
    return assets, catalog


def _bound(slide_num, section_id, confidence="probable"):
    from lecturelog.domain.slides import SlideAssignment

    return SlideAssignment(slide_num, "discussed", section_id, (1,), 1.0, confidence, 1.0, "test")


def _unmentioned(slide_num):
    from lecturelog.domain.slides import SlideAssignment

    return SlideAssignment(
        slide_num, "unmentioned", None, (), None, "unresolved", 0.0, "no_supported_evidence"
    )


async def _render_prompts_with_alignment(
    tmp_path, prompts_dir, monkeypatch, sections, assets, assignments, catalog, mode="v2"
):
    """Прогоняет структуризатор с заданным результатом выравнивания.

    Возвращает промпты рендера по названию раздела: названия уникальны и
    попадают в промпт через шаблон, поэтому порядок рендера не важен.
    """
    from lecturelog.infrastructure.slides.alignment.service import AlignmentResult

    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:30,000\nтекст\n", encoding="utf-8")
    topics_json = json.dumps([{"title": "Тема", "start": "0:00", "end": "0:30"}])
    renders = [f"Текст {section['title']}." for section in sections]
    responses = [topics_json, json.dumps(sections)]
    if mode != "v2":
        # legacy-матч слайдов: грубый по темам и точный по подтемам — пустые.
        responses += ["{}", "{}"]
    gemini = ScriptedGemini([*responses, *renders])
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = mode

    async def align(**_kwargs):
        return AlignmentResult(tuple(assignments), catalog)

    monkeypatch.setattr(structurizer._document_alignment, "align", align)
    await structurizer.structurize(
        srt_path=srt,
        slide_assets=assets,
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )
    prompts = {}
    for call in gemini.recorded_calls:
        for section in sections:
            if call["prompt"].startswith(f"prompt {section['title']} "):
                prompts[section["title"]] = call["prompt"]
    assert set(prompts) == {section["title"] for section in sections}
    return prompts


_THREE_SECTIONS = [
    {"title": "Первый", "start": "0:00", "end": "0:10"},
    {"title": "Второй", "start": "0:10", "end": "0:20"},
    {"title": "Третий", "start": "0:20", "end": "0:30"},
]


@pytest.mark.asyncio
async def test_render_glossary_is_scoped_to_section_slides_and_neighbours(
    tmp_path, prompts_dir, monkeypatch
):
    """Имена с чужих слайдов не попадают в справочник раздела.

    Регрессия судьи: «Уолли» вместо Alice и «JetBrains» вместо ЯДРО — имена со
    слайдов из другой части лекции. В справочник раздела идут только слайды,
    привязанные к нему, и страницы колоды с номером ±1 от них.
    """
    nouns = ["Alice", "Bob", "Wally", "Charlie", "ЯДРО", "Kotlin", "JetBrains"]
    assets, catalog = _scoped_glossary_deck(tmp_path, nouns)
    assignments = [
        _bound(1, 0),
        _unmentioned(2),
        _unmentioned(3),
        _unmentioned(4),
        _bound(5, 2),
        _unmentioned(6),
        _unmentioned(7),
    ]

    prompts = await _render_prompts_with_alignment(
        tmp_path, prompts_dir, monkeypatch, _THREE_SECTIONS, assets, assignments, catalog
    )

    first = prompts["Первый"]
    assert "Alice" in first and "Bob" in first
    assert not any(name in first for name in ("Wally", "Charlie", "ЯДРО", "JetBrains"))
    third = prompts["Третий"]
    assert "Charlie" in third and "ЯДРО" in third and "Kotlin" in third
    assert not any(name in third for name in ("Alice", "Bob", "Wally", "JetBrains"))


@pytest.mark.asyncio
async def test_section_without_bound_slides_gets_empty_glossary(tmp_path, prompts_dir, monkeypatch):
    nouns = ["Alice", "Bob", "Wally", "Charlie", "ЯДРО"]
    assets, catalog = _scoped_glossary_deck(tmp_path, nouns)
    assignments = [_bound(1, 0), *(_unmentioned(num) for num in (2, 3, 4)), _bound(5, 2)]

    prompts = await _render_prompts_with_alignment(
        tmp_path, prompts_dir, monkeypatch, _THREE_SECTIONS, assets, assignments, catalog
    )

    second = prompts["Второй"]
    assert "Написания имён и терминов из презентации" not in second
    assert not any(name in second for name in nouns)


@pytest.mark.asyncio
async def test_glossary_counts_section_gallery_slide_as_bound(tmp_path, prompts_dir, monkeypatch):
    """Слайд в галерее раздела — слайд этого раздела.

    Непривязанный слайд (уверенность unresolved) идёт в галерею раздела с самым
    сильным доказательством: там его и показывают, там о нём и говорили, так
    что его написания нужны именно этому разделу.
    """
    nouns = ["Alice", "Bob", "Wally", "Charlie", "ЯДРО"]
    assets, catalog = _scoped_glossary_deck(tmp_path, nouns)
    assignments = [
        _unmentioned(1),
        _unmentioned(2),
        _bound(3, 1, confidence="unresolved"),
        _unmentioned(4),
        _unmentioned(5),
    ]

    prompts = await _render_prompts_with_alignment(
        tmp_path, prompts_dir, monkeypatch, _THREE_SECTIONS, assets, assignments, catalog
    )

    second = prompts["Второй"]
    assert all(name in second for name in ("Bob", "Wally", "Charlie"))
    assert "Alice" not in second and "ЯДРО" not in second
    assert "Wally" not in prompts["Первый"]


@pytest.mark.asyncio
async def test_shadow_mode_scopes_glossary_by_v2_alignment(tmp_path, prompts_dir, monkeypatch):
    """В shadow рендер идёт по legacy-маршруту, а справочник — по выравниванию v2."""
    nouns = ["Alice", "Bob", "Wally", "Charlie", "ЯДРО"]
    assets, catalog = _scoped_glossary_deck(tmp_path, nouns)
    assignments = [_bound(1, 0), *(_unmentioned(num) for num in (2, 3, 4)), _bound(5, 2)]

    prompts = await _render_prompts_with_alignment(
        tmp_path,
        prompts_dir,
        monkeypatch,
        _THREE_SECTIONS,
        assets,
        assignments,
        catalog,
        mode="shadow",
    )

    assert "Alice" in prompts["Первый"] and "ЯДРО" not in prompts["Первый"]
    assert not any(name in prompts["Второй"] for name in nouns)
    assert "ЯДРО" in prompts["Третий"] and "Alice" not in prompts["Третий"]


def test_render_prompt_allows_name_fix_only_on_phonetic_similarity():
    """Правило фонетического сходства живёт в тексте промпта рендера."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "prompts" / "section_v1.md").read_text(
        encoding="utf-8"
    )

    assert "только при фонетическом сходстве" in text.lower()
