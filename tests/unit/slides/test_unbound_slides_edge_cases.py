# ruff: noqa: E501, F811 — длинные имена тестов; prompts_dir импортирован как фикстура
"""Краевые случаи тикета 05: непривязанный слайд в галерее раздела.

Тесты описывают тихие отказы: результат выглядит правдоподобно, а слайд
оказывается не там или пропадает без следа.
"""

import json
import random

import pytest

from lecturelog.domain.models import Section, Topic
from lecturelog.domain.slides import (
    SlideAsset,
    SlideAssignment,
    SlideCandidate,
    SlidePlacement,
    SlideRelation,
    StructurizeContext,
)
from lecturelog.infrastructure.export.obsidian_exporter import ObsidianExporter
from lecturelog.infrastructure.slides.alignment.anchoring import anchor_assignment
from lecturelog.infrastructure.slides.alignment.diagnostics import write_diagnostic
from lecturelog.infrastructure.slides.alignment.sequence import (
    AlignmentWeights,
    align_sequence,
    strongest_candidate,
)
from lecturelog.infrastructure.slides.alignment.service import (
    AlignmentResult,
    DocumentAlignmentService,
)
from lecturelog.infrastructure.structurize.gemini_structurizer import (
    GeminiStructurizer,  # noqa: F401
)
from tests.unit.slides.test_unbound_slides import (
    _COURSE_SLIDE,
    _COURSE_VERDICT,
    ScriptedLlm,
    _assets,
    _catalog_response,
    _layout,
    _prompts,
    _semantic,
    _srt,
)
from tests.unit.test_gemini_structurizer import (  # noqa: F401
    ScriptedGemini,
    _make_structurizer,
    prompts_dir,
)

W = AlignmentWeights()


def _cand(
    slide, section, lexical, tier="strong", quote="цитата", blocks=None, visual=None, cm=None
):
    return SlideCandidate(
        slide,
        section,
        (section + 1,) if blocks is None else blocks,
        quote,
        section * 10.0,
        section * 10.0 + 5,
        lexical,
        tier,
        visual_score=visual,
        competition_margin=cm,
    )


# ── sequence: ничья силы ───────────────────────────────────────────


def test_ничья_силы_без_пути_отдаёт_более_ранний_раздел_независимо_от_порядка_пула():
    """Порядок кандидатов в пуле — случайность реализации; от него не должен зависеть раздел галереи."""
    early, late = _cand(1, 1, 3.0), _cand(1, 4, 3.0)
    for pool in ((early, late), (late, early)):
        assert strongest_candidate(pool, W).global_section_id == 1


def test_ничья_силы_отдаёт_выбор_пути_а_не_более_ранний_раздел():
    """Слайд (strong без цитаты) выбран путём в раздел 3; равный по силе кандидат раздела 1 не должен его перебить."""
    chosen = _cand(1, 3, 3.0, quote=None)  # unresolved: нет цитаты
    other = _cand(1, 1, 3.0, quote=None)
    result = align_sequence([1], {1: (chosen, other)})
    assert result[0].match_status == "unbound"
    assert result[0].global_section_id == 3


def test_ничья_с_плавающей_точкой_не_ломает_правило_раннего_раздела():
    """0.1+0.2 != 0.3 в float: фактически равные по силе кандидаты не должны решаться шумом округления."""
    a = _cand(1, 4, 0.1 + 0.2)  # поздний раздел, «больше» на 1 ulp
    b = _cand(1, 1, 0.3)
    assert strongest_candidate((a, b), W).global_section_id == 1


def test_кандидат_ровно_на_пороге_unmatched_score_не_доказательство():
    """weak с lexical=0 имеет силу 0 == unmatched_score: слайд уходит в приложение, а не в случайный раздел."""
    result = align_sequence([1], {1: (_cand(1, 2, 0.0, tier="weak"),)})
    assert result[0].match_status == "unmentioned"
    assert result[0].global_section_id is None
    assert result[0].status_reason == "no_candidates"


def test_кандидат_чуть_выше_порога_становится_непривязанным_а_не_теряется():
    result = align_sequence([1], {1: (_cand(1, 2, 0.01, tier="weak"),)})
    assert result[0].match_status == "unbound"
    assert result[0].global_section_id == 2


def test_кандидат_с_отрицательной_силой_не_попадает_в_галерею_даже_если_единственный():
    result = align_sequence([1], {1: (_cand(1, 2, 0.5, tier="none"),)})
    assert result[0].match_status == "unmentioned"


def test_пустой_пул_и_слайд_без_ключа_в_словаре_дают_неупомянутый_без_падения():
    result = align_sequence([1, 2], {1: ()})
    assert [a.match_status for a in result] == ["unmentioned", "unmentioned"]
    assert all(a.status_reason == "no_candidates" for a in result)


def test_пустая_колода_не_падает():
    assert align_sequence([], {}) == ()


def test_visual_score_входит_в_силу_и_переносит_слайд_в_раздел_с_визуальным_доказательством():
    """Слабое лексическое совпадение + сильный visual должны обыграть чисто лексическое."""
    lexical_only = _cand(1, 0, 4.0, tier="weak")
    visual = _cand(1, 5, 0.5, tier="weak", visual=0.9)  # 0.5 + 2.7 = 3.2 < 4.0
    assert strongest_candidate((lexical_only, visual), W).global_section_id == 0
    visual2 = _cand(1, 5, 0.5, tier="weak", visual=1.0)  # 3.5 < 4.0
    assert strongest_candidate((lexical_only, visual2), W).global_section_id == 0
    visual3 = _cand(1, 5, 2.0, tier="weak", visual=1.0)  # 5.0 > 4.0
    assert strongest_candidate((lexical_only, visual3), W).global_section_id == 5


# ── sequence: инварианты результата ────────────────────────────────


def test_инварианты_статусов_на_случайных_входах():
    """unbound всегда с разделом, причиной и без якоря; unmentioned/discussed не несут чужих полей."""
    rng = random.Random(7)
    tiers = ["explicit", "strong", "weak", "none"]
    for _ in range(300):
        n = rng.randint(1, 6)
        cands = {}
        for slide in range(1, n + 1):
            pool = tuple(
                _cand(
                    slide,
                    rng.randint(0, 5),
                    rng.choice([0.0, 0.5, 1.0, 3.0, 8.0]),
                    tier=rng.choice(tiers),
                    quote=rng.choice([None, "q"]),
                    cm=rng.choice([None, -1.0, 0.0, 2.0]),
                )
                for _ in range(rng.randint(0, 3))
            )
            cands[slide] = pool
        for item in align_sequence(list(range(1, n + 1)), cands):
            if item.match_status == "unbound":
                assert item.global_section_id is not None
                assert item.anchor_s is None
                assert item.assignment_confidence == "unresolved"
                assert item.status_reason in {
                    "weak_evidence",
                    "deck_order_conflict",
                    "stronger_competitor",
                }
                assert item.score > 0
            elif item.match_status == "unmentioned":
                assert item.global_section_id is None
                assert item.evidence_block_ids == ()
                assert item.status_reason == "no_candidates"
            elif item.match_status == "discussed":
                assert item.status_reason is None
                assert item.global_section_id is not None


def test_дубль_с_кандидатами_остаётся_дублем_и_не_попадает_в_галерею():
    """Иначе одна и та же страница окажется в тексте дважды."""
    rel = SlideRelation(2, "exact_duplicate", "g1", 1)
    result = align_sequence(
        [1, 2],
        {1: (_cand(1, 0, 6.0, quote=None),), 2: (_cand(2, 3, 6.0),)},
        (rel,),
    )
    assert result[1].match_status == "duplicate"
    assert result[1].global_section_id is None
    assert result[1].status_reason is None


def test_дубль_непривязанного_слайда_не_дублируется_в_галерее():
    rel = SlideRelation(2, "exact_duplicate", "g1", 1)
    result = align_sequence(
        [1, 2],
        {1: (_cand(1, 0, 6.0, quote=None),), 2: (_cand(2, 0, 6.0, quote=None),)},
        (rel,),
    )
    assert result[0].match_status == "unbound"
    assert result[1].match_status == "duplicate"


def test_reason_code_пропущенного_путём_слайда_не_содержит_margin_выбора_которого_не_было():
    result = align_sequence(
        [1, 2],
        {
            1: (_cand(1, 5, 9.0, tier="explicit", cm=3.0),),
            2: (_cand(2, 0, 2.0, tier="weak"),),
        },
    )
    assert result[1].status_reason == "deck_order_conflict"
    assert "margin=none" in result[1].reason_code
    assert "nan" not in result[1].reason_code.lower()


def test_раздел_непривязанного_берётся_из_сильнейшего_кандидата_а_не_из_последнего_раздела_колоды():
    """Слайд 2 пропущен путём (возврат на 5 разделов назад) — галерея раздела 0, а не раздела соседа."""
    result = align_sequence(
        [1, 2],
        {
            1: (_cand(1, 5, 9.0, tier="explicit", cm=3.0),),
            2: (_cand(2, 0, 3.0, tier="strong"),),
        },
    )
    assert (result[1].match_status, result[1].global_section_id) == ("unbound", 0)


# ── _decorate_roles / deck guard ───────────────────────────────────


def test_blank_с_непривязанным_назначением_уходит_в_приложение_без_раздела_и_доказательств():
    """Служебная страница не должна оказаться в галерее раздела и тащить за собой evidence."""
    from lecturelog.domain.slides import SlideCatalogEntry

    unbound = SlideAssignment(
        1, "unbound", 2, (3,), None, "unresolved", 5.0, "semantic", status_reason="weak_evidence"
    )
    entry = SlideCatalogEntry(1, "blank", "", "", (), (), "", (), ())
    [out] = DocumentAlignmentService._decorate_roles((unbound,), {1: entry})
    assert out.match_status == "unmentioned"
    assert out.global_section_id is None
    assert out.evidence_block_ids == ()
    assert out.status_reason == "service_role"
    _, placement = anchor_assignment(out, entry, "текст")
    assert placement.output_kind == "appendix"


@pytest.mark.asyncio
async def test_колода_только_из_непривязанных_признаётся_посторонней_и_не_попадает_в_галереи(
    tmp_path,
):
    """Непривязанные не делают колоду «своей»: иначе чужая колода целиком осядет в галереях."""
    srt = _srt(
        "Сегодня говорим про организацию курса.", "Разберём бинарное дерево поиска и его вершины."
    )
    entry = {
        "slide_num": 1,
        "title": "Бинарное дерево",
        "visible_text": "Бинарное дерево поиска",
        "source_concepts": ["дерево поиска"],
    }
    llm = ScriptedLlm(
        [
            _catalog_response(entry),
            _semantic(1, 1, [2], "", "strong"),
            _semantic(1, 1, [2], "", "strong"),
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 1), section_layout=_layout(2), srt_content=srt
    )
    [item] = result.assignments
    assert item.match_status == "deck_mismatch"
    assert item.global_section_id is None
    assert item.status_reason is None
    assert result.catalog == {}
    _, placement = anchor_assignment(item, None, "текст")
    assert placement.output_kind == "appendix"


@pytest.mark.asyncio
async def test_слайд_c_пустой_цитатой_после_двух_вердиктов_не_получает_якорь_и_доказательство_остаётся(
    tmp_path,
):
    """Непривязанный несёт evidence_block_ids судьи (для диагностики), но не anchor_s."""
    srt = _srt(
        "Сегодня говорим про организацию курса.", "Разберём бинарное дерево поиска и его вершины."
    )
    entry = {
        "slide_num": 1,
        "title": "Бинарное дерево",
        "visible_text": "Бинарное дерево поиска",
        "source_concepts": ["дерево поиска"],
    }
    llm = ScriptedLlm(
        [
            _catalog_response(entry, _COURSE_SLIDE),
            _semantic(1, 1, [2], "", "strong"),
            _semantic(1, 1, [2], "", "strong"),
            _COURSE_VERDICT,
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_layout(2), srt_content=srt
    )
    unbound = result.assignments[0]
    assert unbound.match_status == "unbound"
    assert unbound.anchor_s is None
    assert unbound.evidence_block_ids == (2,)


@pytest.mark.asyncio
async def test_непривязанный_с_одним_блоком_с_discussed_слайдом_не_понижает_его_до_probable(
    tmp_path,
):
    """Коллизия доказательств считается только среди discussed: непривязанный не отнимает verified."""
    srt = _srt(
        "Сегодня говорим про организацию курса.", "Разберём бинарное дерево поиска и его вершины."
    )
    entry = {
        "slide_num": 1,
        "title": "Организация",
        "visible_text": "организацию курса",
        "source_concepts": ["организация курса"],
    }
    llm = ScriptedLlm(
        [
            _catalog_response(entry, _COURSE_SLIDE),
            _semantic(1, 0, [1], "", "strong"),
            _semantic(1, 0, [1], "", "strong"),
            _COURSE_VERDICT,
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_layout(2), srt_content=srt
    )
    first, second = result.assignments
    assert first.match_status == "unbound"
    assert second.match_status == "discussed"
    assert second.assignment_confidence != "unresolved"
    assert "evidence_collision" not in second.reason_code


# ── anchoring ──────────────────────────────────────────────────────


def test_непривязанный_не_меняет_markdown_раздела_и_не_вставляет_маркер():
    unbound = SlideAssignment(
        1, "unbound", 0, (1,), None, "unresolved", 5.0, "x", status_reason="weak_evidence"
    )
    md = "Абзац про дерево поиска.\n\nВторой абзац."
    new_md, placement = anchor_assignment(unbound, None, md)
    assert new_md == md
    assert "<!-- slide:" not in new_md
    assert placement.output_kind == "section_gallery"
    assert placement.gallery_position == "after_content"


def test_непривязанный_без_раздела_не_попадает_в_галерею_никакого_раздела():
    """Защита от разъехавшегося состояния: unbound с global_section_id=None обязан уйти в приложение."""
    odd = SlideAssignment(
        1, "unbound", None, (), None, "unresolved", 1.0, "x", status_reason="weak_evidence"
    )
    _, placement = anchor_assignment(odd, None, "текст")
    assert placement.output_kind == "appendix"
    assert placement.global_section_id is None


# ── структуризатор v2 ──────────────────────────────────────────────


def _assets_for(tmp_path, count):
    out = []
    for num in range(1, count + 1):
        path = tmp_path / f"slide{num}.png"
        path.write_bytes(f"slide{num}".encode())
        out.append(
            SlideAsset(num, path, "document", extracted_text="text", native_text_quality="good")
        )
    return out


async def _run_v2(tmp_path, prompts_dir, monkeypatch, assignments, count, sections=1):
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:10,000\ntext\n", encoding="utf-8")
    gemini = ScriptedGemini(
        [
            json.dumps([{"title": "T", "start": "0:00", "end": "0:10"}]),
            json.dumps(
                [{"title": f"S{i}", "start": "0:00", "end": "0:10"} for i in range(sections)]
            ),
            *(["Rendered text."] * sections),
        ]
    )
    structurizer = _make_structurizer(gemini, prompts_dir)
    structurizer._document_alignment_mode = "v2"

    async def align(**_kwargs):
        return AlignmentResult(tuple(assignments), {})

    monkeypatch.setattr(structurizer._document_alignment, "align", align)
    out = tmp_path / "out"
    result = await structurizer.structurize(
        srt_path=srt,
        slide_assets=_assets_for(tmp_path, count),
        context=StructurizeContext("audio"),
        output_dir=out,
    )
    return result, out


def _unb(num, section, reason="weak_evidence"):
    return SlideAssignment(
        num, "unbound", section, (1,), None, "unresolved", 3.0, "semantic", status_reason=reason
    )


@pytest.mark.asyncio
async def test_раздел_победитель_за_пределами_числа_разделов_уводит_слайд_в_приложение(
    tmp_path, prompts_dir, monkeypatch
):
    """Слайд не должен пропасть: global_section_id=7 при одном разделе -> appendix, в slide_indices не попасть."""
    result, _ = await _run_v2(tmp_path, prompts_dir, monkeypatch, [_unb(1, 7)], 1)
    [placement] = result.slide_placements
    assert placement.output_kind == "appendix"
    assert result.topics[0].sections[0].slide_indices == []
    assert result.topics[0].slide_indices == []


@pytest.mark.asyncio
async def test_непривязанный_и_discussed_в_одном_разделе_оба_в_slide_indices_без_дублей(
    tmp_path, prompts_dir, monkeypatch
):
    discussed = SlideAssignment(1, "discussed", 0, (1,), 1.0, "probable", 9.0, "m")
    result, _ = await _run_v2(
        tmp_path,
        prompts_dir,
        monkeypatch,
        [_unb(2, 0), discussed, _unb(3, 0, "deck_order_conflict")],
        3,
    )
    # Порядок assignments намеренно не по номеру слайда
    assert result.topics[0].sections[0].slide_indices == [1, 2, 3]
    assert result.topics[0].slide_indices == [1, 2, 3]
    assert len({p.slide_num for p in result.slide_placements}) == 3


@pytest.mark.asyncio
async def test_непривязанные_не_уходят_в_render_как_привязанные_к_тексту(
    tmp_path, prompts_dir, monkeypatch
):
    """Render получает только discussed; непривязанный слайд не должен менять промпт раздела."""
    result, _ = await _run_v2(tmp_path, prompts_dir, monkeypatch, [_unb(1, 0)], 1)
    assert "<!-- slide:" not in result.topics[0].sections[0].content


@pytest.mark.asyncio
async def test_диагностика_с_unbound_записывает_и_читается_json_обратно(tmp_path):
    path = tmp_path / "d.json"
    write_diagnostic(path, mode="v2", assignments=(_unb(1, 0),), placements=())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    item = data["assignments"][0]
    assert item["match_status"] == "unbound"
    assert item["status_reason"] == "weak_evidence"
    # Старый читатель, не знающий status_reason, получает прежний набор ключей плюс один.
    old_keys = {
        "slide_num",
        "match_status",
        "global_section_id",
        "evidence_block_ids",
        "anchor_s",
        "assignment_confidence",
        "score",
        "reason_code",
    }
    assert old_keys <= item.keys()


def test_старая_диагностика_без_status_reason_восстанавливается_в_assignment():
    """Обратная совместимость: запись без нового поля собирается и status_reason=None."""
    old = {
        "slide_num": 1,
        "match_status": "unmentioned",
        "global_section_id": None,
        "evidence_block_ids": [],
        "anchor_s": None,
        "assignment_confidence": "unresolved",
        "score": 0.0,
        "reason_code": "no_supported_evidence",
    }
    assert SlideAssignment(**old).status_reason is None


def test_schema_version_диагностики_не_изменился_хотя_появился_новый_статус_и_поле():
    """Читатель, различающий форматы по schema_version, не узнает о новом статусе unbound."""
    from lecturelog.infrastructure.slides.alignment.diagnostics import SCHEMA_VERSION

    assert SCHEMA_VERSION == 1  # зафиксировано как сознательное решение (формат не меняется)


# ── экспорт obsidian ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_экспорт_ставит_непривязанный_после_контента_раздела_один_раз_и_не_в_приложение(
    tmp_path,
):
    frag = tmp_path / "f.mp3"
    frag.write_bytes(b"a")
    paths = []
    for i in (1, 2, 3):
        p = tmp_path / f"s{i}.png"
        p.write_bytes(b"png")
        paths.append(p)
    sec = Section(
        title="В",
        start="0:00",
        end="5:00",
        content="Абзац раз.\n\n<!-- slide:1 -->\n\nАбзац два.",
        slide_indices=[1, 2, 3],
    )
    topic = Topic(title="Т", start="0:00", end="5:00", sections=[sec], slide_indices=[1, 2, 3])
    placements = (
        SlidePlacement(1, "inline", 0, anchor_confidence="probable"),
        SlidePlacement(
            2, "section_gallery", 0, gallery_position="after_content", anchor_confidence="fallback"
        ),
        SlidePlacement(3, "appendix", None, anchor_confidence="none"),
    )
    assets = [
        SlideAsset(i, p, "document", extracted_text="", native_text_quality="none")
        for i, p in enumerate(paths, 1)
    ]
    result = await ObsidianExporter().export(
        topics=[topic],
        media_fragments=[frag],
        slide_assets=assets,
        slide_placements=placements,
        output_dir=tmp_path / "e",
        media_kind="audio",
    )
    md = (result.output_root / "конспект.md").read_text(encoding="utf-8")
    for n in (1, 2, 3):
        assert md.count(f"slides/slide-0{n}.png") == 1
    assert md.index("slide-02") > md.index("Абзац два.")
    assert md.index("slide-03") > md.index("Непривязанные слайды")
    assert md.index("slide-02") < md.index("Непривязанные слайды")


@pytest.mark.asyncio
async def test_экспорт_не_падает_если_у_непривязанного_раздела_нет_media_и_секции_пустой(tmp_path):
    p = tmp_path / "s1.png"
    p.write_bytes(b"png")
    sec = Section(title="В", start="0:00", end="5:00", content="", slide_indices=[1])
    topic = Topic(title="Т", start="0:00", end="5:00", sections=[sec], slide_indices=[1])
    result = await ObsidianExporter().export(
        topics=[topic],
        media_fragments=[],
        slide_assets=[SlideAsset(1, p, "document", extracted_text="", native_text_quality="none")],
        slide_placements=(
            SlidePlacement(
                1,
                "section_gallery",
                0,
                gallery_position="after_content",
                anchor_confidence="fallback",
            ),
        ),
        output_dir=tmp_path / "e",
        media_kind="audio",
    )
    md = (result.output_root / "конспект.md").read_text(encoding="utf-8")
    assert md.count("slides/slide-01.png") == 1


# ── legacy / no-llm ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_без_llm_слайд_без_лексических_совпадений_остаётся_неупомянутым_а_не_непривязанным(
    tmp_path,
):
    from tests.unit.slides.test_unbound_slides import _image

    service = DocumentAlignmentService()
    result = await service.align(
        assets=[
            SlideAsset(
                1,
                _image(tmp_path, "a.png"),
                "document",
                extracted_text="Квантовая хромодинамика глюоны",
                native_text_quality="good",
            ),
        ],
        section_layout=_layout(2),
        srt_content=_srt("Говорим про организацию курса.", "Разбираем деревья поиска."),
    )
    assert result.assignments[0].match_status != "unbound"
    assert result.assignments[0].global_section_id is None
