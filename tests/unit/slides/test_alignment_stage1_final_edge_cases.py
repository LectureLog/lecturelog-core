# ruff: noqa: E501, F811 — длинные имена тестов
"""Финальная охота на краевые случаи этапа 1 (после калибровки min_margin=-2.5, visual_weight=2.25).

Здесь только тихие отказы: слайд встаёт в правдоподобное, но неверное место,
уверенность завышена или причина статуса не совпадает с тем, что произошло.
Порядок: (1) стыки стадий (подтемы <-> доказательства, связи страниц <-> коллизии),
(2) порог и калибровка, (3) маршрут непривязанного, (4) контракты глоссария,
(5) данные и отказы.
"""

import json
import random
import re
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

from lecturelog.domain.slides import (
    SectionRef,
    SlideAsset,
    SlideAssignment,
    SlideCandidate,
    SlideCatalogEntry,
    SlideRelation,
    SlideStatusReason,
)
from lecturelog.infrastructure.slides.alignment.anchoring import anchor_assignment
from lecturelog.infrastructure.slides.alignment.catalog import (
    detect_boilerplate_lines,
    detect_progressive_builds,
)
from lecturelog.infrastructure.slides.alignment.confidence import calibrate
from lecturelog.infrastructure.slides.alignment.retrieval import generate_candidates
from lecturelog.infrastructure.slides.alignment.sequence import (
    AlignmentWeights,
    align_sequence,
)
from lecturelog.infrastructure.slides.alignment.service import (
    AlignmentTuning,
    DocumentAlignmentService,
)
from lecturelog.infrastructure.slides.alignment.transcript import blocks_for_section
from lecturelog.infrastructure.srt import parse_srt_blocks, snap_sections_to_cues
from tests.unit.slides.test_unbound_slides import (
    ScriptedLlm,
    _assets,
    _catalog_response,
    _prompts,
    _semantic,
)

W = AlignmentWeights()
_GLOSSARY = Path(__file__).resolve().parents[3] / "GLOSSARY.md"


# ── общие помощники ──────────────────────────────────────────────────


def _cue_srt(*texts: str, step: int = 10) -> str:
    """Реплики подряд без пауз: конец каждой равен началу следующей."""
    return "".join(
        f"{i}\n00:{(i - 1) * step // 60:02d}:{(i - 1) * step % 60:02d},000 --> "
        f"00:{i * step // 60:02d}:{i * step % 60:02d},000\n{text}\n\n"
        for i, text in enumerate(texts, start=1)
    )


def _snapped(srt: str, *sections: tuple[str, str, str]):
    """Раскладка подтем так, как её отдаёт структуризатор алайнменту: после сдвига к репликам."""
    layout = [[{"title": t, "start": s, "end": e} for t, s, e in sections]]
    ranges = snap_sections_to_cues(layout, srt)
    return layout, ranges


def _text_asset(tmp_path: Path, num: int, text: str) -> SlideAsset:
    image = tmp_path / f"text-slide{num}.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + f"text-{num}".encode())
    return SlideAsset(num, image, "document", extracted_text=text, native_text_quality="good")


def _cand(
    slide: int,
    section: int,
    lexical: float,
    tier: str = "explicit",
    *,
    cm: float | None = None,
    comps: tuple[SlideCandidate, ...] = (),
    visual: float | None = None,
    quote: str | None = "цитата",
    confirmed: bool = True,
) -> SlideCandidate:
    return SlideCandidate(
        slide,
        section,
        (section + 1,),
        quote,
        section * 10.0,
        section * 10.0 + 5,
        lexical,
        tier,  # type: ignore[arg-type]
        visual_score=visual,
        competition_margin=cm,
        competitors=comps,
        model_confirmed=confirmed,
    )


def _rival(slide: int, section: int, lexical: float, visual: float | None = None) -> SlideCandidate:
    return _cand(slide, section, lexical, "none", visual=visual, quote=None, confirmed=False)


def _margin_of(reason_code: str) -> float | None:
    match = re.search(r":margin=(-?\d+\.\d+|none)", reason_code)
    assert match, reason_code
    return None if match.group(1) == "none" else float(match.group(1))


# ═════════════════════════════════════════════════════════════════════
# 1. Стыки стадий
# ═════════════════════════════════════════════════════════════════════

# Пара «нарезка подтем» <-> «доказательства слайда». Нарезка (srt.snap_sections_to_cues)
# делает границы подтем смежными: конец подтемы = начало следующей, и каждая реплика
# принадлежит ровно одной подтеме — рендер получает текст по номерам реплик
# (extract_srt_cue_range). Поиск кандидатов берёт реплики раздела по включительному
# пересечению времени, и реплики у границы попадают в обе подтемы.

_BOUNDARY_TEXTS = (
    "Сегодня говорим про организацию курса.",
    "Пауза пауза пауза пауза пауза пауза пауза пауза пауза.",
    "Бинарное дерево поиска хранит ключи упорядоченно.",
    "Дальше разбор сортировки пузырьком и вставками, сравниваем соседние элементы массива "
    "и меняем их местами при необходимости. Ещё долго рассказываем про сортировки.",
)
_BOUNDARY_SECTIONS = (("A", "0:00", "0:19"), ("B", "0:21", "0:40"))


def test_доказательства_раздела_это_ровно_те_реплики_которые_рендер_получает_для_этого_раздела_потому_что_граница_подтем_принадлежит_одной_стороне():
    """Реплика у стыка подтем попадает в доказательства обоих соседей.

    Что тихо ломается: слайд про реплику из подтемы B получает кандидата-конкурента A с тем же
    доказательством (A короче, BM25 даёт ей больше), margin выбора уходит в минус и верный
    verified падает до probable, а при длинных запросах — ниже -2.5 и слайд теряет абзац.
    Судья видит одну и ту же реплику под двумя разделами; якорь `discussed` в A не находит
    своей реплики в отрендеренном тексте A и падает в галерею.
    """
    srt = _cue_srt(*_BOUNDARY_TEXTS)
    layout, ranges = _snapped(srt, *_BOUNDARY_SECTIONS)
    blocks = parse_srt_blocks(srt)
    refs = DocumentAlignmentService._section_refs(layout, blocks)

    assert ranges is not None
    for ref, (first, last) in zip(refs, ranges, strict=True):
        evidence_ids = {block.block_id for block in blocks_for_section(blocks, ref)}
        rendered_ids = set(range(first, last + 1))
        assert evidence_ids == rendered_ids, (
            f"раздел {ref.global_section_id}: доказательства {sorted(evidence_ids)}, "
            f"рендер получает реплики {sorted(rendered_ids)}"
        )


def test_реплики_двух_разных_подтем_без_стыка_не_пересекаются_в_доказательствах_контроль():
    """Контроль: при паузе между подтемами пересечения нет — тест выше красный именно из-за стыка."""
    srt = "1\n00:00:00,000 --> 00:00:04,000\nпервая\n\n2\n00:00:10,000 --> 00:00:14,000\nвторая\n"
    blocks = parse_srt_blocks(srt)
    first = SectionRef(0, 0, 0, 0.0, 5.0)
    second = SectionRef(1, 0, 1, 9.0, 15.0)
    assert [b.block_id for b in blocks_for_section(blocks, first)] == [1]
    assert [b.block_id for b in blocks_for_section(blocks, second)] == [2]


@pytest.mark.asyncio
async def test_судья_видит_реплику_стыка_под_одним_разделом_а_не_под_двумя_потому_что_иначе_соседний_раздел_становится_конкурентом_с_тем_же_доказательством(
    tmp_path,
):
    srt = _cue_srt(*_BOUNDARY_TEXTS)
    layout, _ = _snapped(srt, *_BOUNDARY_SECTIONS)
    organisation = {
        "slide_num": 1,
        "title": "Организация курса",
        "visible_text": "Сегодня говорим про организацию курса",
    }
    tree = {
        "slide_num": 2,
        "title": "Бинарное дерево поиска",
        "visible_text": "Бинарное дерево поиска\nключи упорядочены",
        "source_concepts": ["бинарное дерево поиска"],
    }
    llm = ScriptedLlm(
        [
            _catalog_response(organisation, tree),
            _semantic(1, 0, [1], "Сегодня говорим про организацию курса.", "explicit"),
            _semantic(2, 1, [3], "Бинарное дерево поиска хранит ключи упорядоченно.", "explicit"),
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=layout, srt_content=srt
    )

    payload = json.loads(llm.calls[-1]["prompt"].split("\n", 1)[1])
    owners: dict[int, list[int]] = {}
    for candidate in payload["candidates"]:
        for block in candidate["evidence_blocks"]:
            owners.setdefault(block["block_id"], []).append(candidate["global_section_id"])
    shared = {block_id: sections for block_id, sections in owners.items() if len(sections) > 1}
    assert not shared, f"реплики под несколькими разделами в запросе судье: {shared}"
    margin = _margin_of(result.assignments[1].reason_code)
    assert margin is not None and margin > 0, result.assignments[1].reason_code


@pytest.mark.asyncio
async def test_слайд_про_первую_реплику_подтемы_привязывается_к_этой_подтеме_а_не_к_предыдущей_потому_что_реплика_стыка_принадлежит_следующей(
    tmp_path,
):
    """Без модели (лексический путь): стык подтем не должен отдавать реплику предыдущему разделу.

    Что тихо ломается: слайд «Сортировка пузырьком» встаёт в галерею/абзац раздела про организацию
    курса — правдоподобно по виду (probable, inline не находит блока), а на деле чужой раздел.
    """
    srt = _cue_srt(
        "Сегодня говорим про организацию курса и расписание занятий.",
        "Сортировка пузырьком сравнивает соседние элементы массива.",
        "Дальше меняем элементы местами при необходимости и повторяем проход.",
    )
    layout, _ = _snapped(srt, ("A", "0:00", "0:09"), ("B", "0:10", "0:29"))
    assets = [
        _text_asset(tmp_path, 1, "Организация курса\nСегодня говорим про организацию курса"),
        _text_asset(tmp_path, 2, "Сортировка пузырьком\nсравнивает соседние элементы массива"),
    ]
    result = await DocumentAlignmentService().align(
        assets=assets, section_layout=layout, srt_content=srt
    )
    sorting = result.assignments[1]
    assert (sorting.match_status, sorting.global_section_id) == ("discussed", 1)
    assert sorting.evidence_block_ids == (2,)


# Пара «обнаружение связей страниц» <-> «защита от коллизий доказательств».


def test_цепочка_из_трёх_шагов_сборки_на_одной_реплике_остаётся_verified_у_всех_потому_что_это_одна_страница_в_трёх_видах(
    tmp_path,
):
    """Группа связи у progressive build — «предыдущий шаг», поэтому цепочка 3->4->5 не замкнута.

    Что тихо ломается: у шагов сборки на одной реплике крайние слайды (3 и 5) понижаются до
    probable, средний (4) остаётся verified; anchoring потом ставит средний inline без проверки
    специфичности, а крайние уходят в галерею. Одна и та же страница разъезжается по разным местам.
    """
    assets = [
        _text_asset(
            tmp_path, 3, "Бинарное дерево поиска\nключи слева меньше корня\nключи справа больше"
        ),
        _text_asset(
            tmp_path,
            4,
            "Бинарное дерево поиска\nключи слева меньше корня\nключи справа больше\nобход дерева",
        ),
        _text_asset(
            tmp_path,
            5,
            "Бинарное дерево поиска\nключи слева меньше корня\nключи справа больше\nобход дерева\nбалансировка",
        ),
    ]
    relations = detect_progressive_builds(assets)
    assert {r.slide_num for r in relations} == {4, 5}, "предпосылка: обе пары распознаны как сборка"
    assignments = tuple(
        SlideAssignment(n, "discussed", 1, (7,), 10.0, "verified", 9.0, "semantic_explicit")
        for n in (3, 4, 5)
    )

    result = DocumentAlignmentService._downgrade_evidence_collisions(assignments, relations)

    assert {item.slide_num: item.assignment_confidence for item in result} == {
        3: "verified",
        4: "verified",
        5: "verified",
    }


def test_страницы_у_которых_общий_только_колонтитул_не_считаются_шагами_сборки_потому_что_иначе_коллизия_доказательств_между_ними_прощается(
    tmp_path,
):
    """Колонтитул курса на каждой странице + короткое разное тело: containment по сырым токенам ≥ 0.72.

    Что тихо ломается: два слайда про РАЗНЫЕ темы, попавшие на одну реплику, считаются «одной
    страницей в двух видах» — защита от коллизий их не понижает, оба остаются verified, и в конспект
    встают inline две картинки на один абзац, одна из которых точно не про него.
    """
    footer = "Алгоритмы и структуры данных 2026 кафедра информатики"
    assets = [
        _text_asset(tmp_path, 1, f"Деревья\n{footer}"),
        _text_asset(tmp_path, 2, f"Графы обход\n{footer}"),
        _text_asset(tmp_path, 3, f"Сортировки быстрые медленные\n{footer}"),
    ]
    assert detect_boilerplate_lines(assets) == {footer}, "предпосылка: колонтитул распознан"
    relations = detect_progressive_builds(assets)
    assignments = tuple(
        SlideAssignment(n, "discussed", 1, (7,), 10.0, "verified", 9.0, "semantic_explicit")
        for n in (1, 2)
    )

    result = DocumentAlignmentService._downgrade_evidence_collisions(assignments, relations)

    assert [item.assignment_confidence for item in result] == ["probable", "probable"]


# ═════════════════════════════════════════════════════════════════════
# 2. Порог −2.5 × путь × конкуренты × визуальная оценка
# ═════════════════════════════════════════════════════════════════════


def _skip_scenario(cm: float):
    """Слайд 2 пропущен путём (возврат на три раздела дороже его выгоды), margin конкурента — cm."""
    return align_sequence(
        [1, 2],
        {
            1: (_cand(1, 5, 9.0, cm=3.0),),
            2: (_cand(2, 0, 0.0, "strong", cm=cm, comps=(_rival(2, 3, 3.0 - cm),)),),
        },
    )[1]


def test_пропущенный_путём_слайд_на_пороге_margin_остаётся_конфликтом_порядка_потому_что_сравнение_строгое_и_в_ветке_пропуска():
    """Ветка пропуска сравнивает порог отдельно от calibrate: `<=` там превратил бы -2.5 в -2.49 без следа."""
    item = _skip_scenario(W.min_margin)
    assert (item.match_status, item.status_reason) == ("unbound", "deck_order_conflict")


def test_пропущенный_путём_слайд_чуть_ниже_порога_получает_причину_конкурента():
    item = _skip_scenario(W.min_margin - 0.001)
    assert (item.match_status, item.status_reason) == ("unbound", "stronger_competitor")


def test_малая_выгода_пути_не_даёт_verified_даже_при_сильном_отрыве_от_конкурента_потому_что_margin_это_минимум_из_двух():
    """Слайд 2 explicit без лексики, возврат на 2 раздела стоит 3.0: выгода пути 1.0 < 1.5."""
    result = align_sequence(
        [1, 2],
        {
            1: (_cand(1, 2, 9.0, cm=3.0),),
            2: (_cand(2, 0, 0.0, "explicit", cm=5.0, comps=(_rival(2, 4, 0.0),)),),
        },
    )
    assert result[1].match_status == "discussed"
    assert result[1].assignment_confidence == "probable"
    assert _margin_of(result[1].reason_code) == pytest.approx(1.0)


def test_visual_один_и_margin_ниже_порога_не_спасают_verified_потому_что_порог_проверяется_раньше_визуальной_ветки():
    item = align_sequence(
        [1],
        {1: (_cand(1, 1, 3.0, "strong", cm=-2.6, visual=1.0, comps=(_rival(1, 2, 5.6),)),)},
    )[0]
    assert (item.match_status, item.status_reason) == ("unbound", "stronger_competitor")
    assert item.assignment_confidence == "unresolved"


@pytest.mark.parametrize(
    ("visual", "margin", "expected"),
    [
        (0.85, 1.0, "verified"),
        (0.8499, 1.0, "probable"),
        (0.85, 0.9999, "probable"),
        (None, 5.0, "probable"),
        (0.0, 5.0, "probable"),
        (1.0, 1.0, "verified"),
    ],
)
def test_визуальная_ветка_verified_включительна_по_обеим_границам_и_none_не_равно_полной_оценке(
    visual, margin, expected
):
    """strong + подтверждение судьи: verified только при visual ≥ 0.85 и margin ≥ 1.0."""
    result = calibrate(
        semantic_tier="strong",
        margin=margin,
        has_grounded_evidence=True,
        has_competing_context=True,
        visual_score=visual,
        min_margin=W.min_margin,
        model_confirmed=True,
    )
    assert result.confidence == expected


def test_visual_score_ноль_и_none_дают_одинаковую_силу_но_разный_вклад_в_диагностике():
    """None — «описания нет», 0.0 — «описание есть, в речи не нашлось»: диагностика должна их различать."""
    without = align_sequence([1], {1: (_cand(1, 1, 3.0, visual=None),)})[0]
    zero = align_sequence([1], {1: (_cand(1, 1, 3.0, visual=0.0),)})[0]
    assert without.score == zero.score
    assert without.visual_contribution is None
    assert zero.visual_contribution == 0.0


def test_визуальная_добавка_конкурента_одна_не_переводит_в_stronger_competitor_при_нулевой_лексике():
    """Инвариант владельца: visual_weight < |min_margin|. Слайд-схема без текста, конкурент с полным визуальным совпадением."""
    own = _cand(1, 1, 0.0, cm=-W.visual_weight, visual=0.0, comps=(_rival(1, 2, 0.0, visual=1.0),))
    item = align_sequence([1], {1: (own,)})[0]
    assert item.match_status == "discussed"


def test_конкурент_без_доказательства_не_меняет_уверенность_выбора_с_положительным_margin():
    """Конкурент со слабой силой — не повод понижать: margin остаётся положительным и verified сохраняется."""
    own = _cand(1, 1, 3.0, cm=3.0 - 0.2, comps=(_rival(1, 4, 0.2),))
    item = align_sequence([1], {1: (own,)})[0]
    assert (item.match_status, item.assignment_confidence) == ("discussed", "verified")


def test_прогрессивная_сборка_с_выбором_в_том_же_разделе_получает_бонус_но_не_обходит_порог():
    """Бонус сборки двигает путь, но margin слайда с конкурентом ниже порога остаётся решающим."""
    relation = SlideRelation(2, "progressive_build", "g", 1)
    result = align_sequence(
        [1, 2],
        {
            1: (_cand(1, 1, 3.0, cm=3.0),),
            2: (_cand(2, 1, 3.0, cm=-2.51, comps=(_rival(2, 4, 5.51),)),),
        },
        (relation,),
    )
    assert result[0].match_status == "discussed"
    assert result[1].status_reason == "stronger_competitor"


# ═════════════════════════════════════════════════════════════════════
# 3. Маршрут непривязанного: что видит потребитель
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "scenario",
    ["weak_evidence", "deck_order_conflict", "stronger_competitor"],
)
def test_каждая_причина_непривязанного_ведёт_в_галерею_раздела_с_той_же_причиной_в_размещении(
    scenario,
):
    """Потребитель (anchoring) получает причину только через fallback_reason: расхождение с status_reason слепит диагностику."""
    if scenario == "weak_evidence":
        item = align_sequence([1], {1: (_cand(1, 1, 3.0, "strong", quote=None, cm=-0.5),)})[0]
    elif scenario == "deck_order_conflict":
        item = _skip_scenario(-1.0)
    else:
        item = align_sequence([1], {1: (_cand(1, 1, 3.0, cm=-9.0, comps=(_rival(1, 4, 12.0),)),)})[
            0
        ]
    assert item.status_reason == scenario
    markdown = "Абзац один.\n\nАбзац два."
    new_markdown, placement = anchor_assignment(item, None, markdown)
    assert new_markdown == markdown
    assert (placement.output_kind, placement.global_section_id) == (
        "section_gallery",
        item.global_section_id,
    )
    assert placement.fallback_reason == f"unbound:{scenario}"


def test_unbound_из_ветки_конкурента_несёт_доказательство_того_раздела_куда_ушёл():
    """evidence_block_ids и global_section_id одного кандидата: иначе диагностика указывает на реплику чужого раздела."""
    item = align_sequence([1], {1: (_cand(1, 1, 2.0, cm=-18.0, comps=(_rival(1, 4, 20.0),)),)})[0]
    assert (item.global_section_id, item.evidence_block_ids) == (4, (5,))


# ═════════════════════════════════════════════════════════════════════
# 4. Контракты: глоссарий <-> код
# ═════════════════════════════════════════════════════════════════════


def _glossary_reasons() -> dict[str, str]:
    text = _GLOSSARY.read_text(encoding="utf-8")
    block = text.split("**Причина статуса**", 1)[1].split("\n\n**", 1)[0]
    return dict(re.findall(r"^- `(\w+)` \(`(\w+)`\)", block, flags=re.MULTILINE))


def test_причины_статуса_в_глоссарии_и_в_коде_совпадают_как_множества_и_по_статусу():
    """Глоссарий — единственное описание причин для человека, читающего диагностику."""
    reasons = _glossary_reasons()
    assert set(reasons) == set(get_args(SlideStatusReason))
    statuses = set(get_args(get_type_hints(SlideAssignment)["match_status"]))
    assert set(reasons.values()) <= statuses


def test_инварианты_исходов_на_случайных_входах_со_связями_и_конкурентами_согласованы_с_глоссарием():
    """Статус, причина, уверенность, раздел, якорь и reason_code не противоречат друг другу."""
    glossary = _glossary_reasons()
    rng = random.Random(2026)
    for _ in range(500):
        n = rng.randint(1, 7)
        candidates: dict[int, tuple[SlideCandidate, ...]] = {}
        for slide in range(1, n + 1):
            rivals = tuple(
                _rival(
                    slide,
                    rng.randint(0, 7),
                    rng.choice([0.0, 1.0, 4.0, 9.0, 20.0]),
                    visual=rng.choice([None, 0.0, 0.5, 1.0]),
                )
                for _ in range(rng.randint(0, 3))
            )
            candidates[slide] = tuple(
                _cand(
                    slide,
                    rng.randint(0, 7),
                    rng.choice([0.0, 1.0, 3.0, 8.0]),
                    rng.choice(["explicit", "strong", "weak"]),
                    cm=rng.choice([None, 4.0, 1.4, 1.5, 0.0, -2.0, -2.5, -2.51, -9.0]),
                    comps=rivals,
                    visual=rng.choice([None, 0.0, 0.9, 1.0]),
                    quote=rng.choice([None, "q"]),
                    confirmed=rng.choice([True, False]),
                )
                for _ in range(rng.randint(0, 2))
            )
        relations = tuple(
            SlideRelation(
                s,
                rng.choice(["exact_duplicate", "progressive_build"]),
                f"g{s}",
                s - 1,
            )
            for s in range(2, n + 1)
            if rng.random() < 0.3
        )
        for item in align_sequence(list(range(1, n + 1)), candidates, relations):
            if item.match_status == "discussed":
                assert item.status_reason is None
                assert item.assignment_confidence in {"probable", "verified"}
                assert item.global_section_id is not None and item.anchor_s is not None
                margin = _margin_of(item.reason_code)
                assert margin is None or margin >= W.min_margin
                if item.assignment_confidence == "verified":
                    assert margin is not None and margin >= 1.0
            elif item.match_status == "unbound":
                assert glossary[item.status_reason or ""] == "unbound"
                assert item.assignment_confidence == "unresolved"
                assert item.global_section_id is not None and item.anchor_s is None
                assert item.reason_code.startswith("semantic_")
            elif item.match_status == "unmentioned":
                assert glossary[item.status_reason or ""] == "unmentioned"
                assert item.reason_code == item.status_reason
                assert item.global_section_id is None and item.evidence_block_ids == ()
            else:
                assert item.match_status == "duplicate"
                assert item.status_reason is None and item.global_section_id is None
                assert item.reason_code.startswith("duplicate_of:")


# ═════════════════════════════════════════════════════════════════════
# 5. Данные и отказы
# ═════════════════════════════════════════════════════════════════════


def test_эмодзи_rtl_и_длинное_описание_не_роняют_поиск_кандидатов_и_дают_конечные_оценки():
    sections = (SectionRef(0, 0, 0, 0.0, 10.0), SectionRef(1, 0, 1, 10.0, 20.0))
    blocks = parse_srt_blocks(
        "1\n00:00:00,000 --> 00:00:09,000\nсервер 🙂 клиент базу данных запрос\n\n"
        "2\n00:00:10,000 --> 00:00:19,000\nשלום עולם сортировка массива\n"
    )
    entry = SlideCatalogEntry(
        1,
        "content",
        "🙂🙂🙂 שלום",
        "ключ" * 2500,
        visual_summary="клиент отправляет запрос серверу " * 300 + "שלום 🙂",
    )
    candidates = generate_candidates(entry, sections, blocks, weights=W)
    assert candidates
    for candidate in candidates:
        assert candidate.lexical_score == candidate.lexical_score  # не NaN
        assert candidate.visual_score is not None and 0.0 <= candidate.visual_score <= 1.0


@pytest.mark.asyncio
async def test_отказ_судьи_на_одном_слайде_не_меняет_результат_соседнего_потому_что_пакет_падает_по_элементам(
    tmp_path,
):
    srt = _cue_srt(
        "Сегодня говорим про организацию курса.",
        "Пауза.",
        "Бинарное дерево поиска хранит ключи упорядоченно.",
        "Пауза.",
    )
    layout = [
        [
            {"title": "A", "start": "00:00:00,000", "end": "00:00:19,000"},
            {"title": "B", "start": "00:00:20,000", "end": "00:00:40,000"},
        ]
    ]
    organisation = {
        "slide_num": 1,
        "title": "Организация курса",
        "visible_text": "Сегодня говорим про организацию курса",
    }
    tree = {
        "slide_num": 2,
        "title": "Бинарное дерево поиска",
        "visible_text": "Бинарное дерево поиска",
        "source_concepts": ["бинарное дерево поиска"],
    }

    class FailingJudge(ScriptedLlm):
        async def call(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 3:
                raise TimeoutError("судья не ответил")
            return self.responses.pop(0)

    verdict = _semantic(1, 0, [1], "Сегодня говорим про организацию курса.", "explicit")
    tree_verdict = _semantic(
        2, 1, [3], "Бинарное дерево поиска хранит ключи упорядоченно.", "explicit"
    )
    prompts = _prompts(tmp_path)
    baseline = await DocumentAlignmentService(
        llm=ScriptedLlm([_catalog_response(organisation, tree), verdict, tree_verdict]),
        models=["m"],
        prompts_dir=prompts,
    ).align(assets=_assets(tmp_path, 2), section_layout=layout, srt_content=srt)
    failing = await DocumentAlignmentService(
        llm=FailingJudge([_catalog_response(organisation, tree), verdict]),
        models=["m"],
        prompts_dir=prompts,
    ).align(assets=_assets(tmp_path, 2), section_layout=layout, srt_content=srt)

    assert failing.assignments[0] == baseline.assignments[0]
    assert failing.assignments[1].match_status in {"discussed", "unbound", "unmentioned"}
    assert failing.assignments[1].assignment_confidence != "verified"


@pytest.mark.asyncio
async def test_повторный_прогон_с_теми_же_ответами_модели_даёт_тот_же_результат_до_бита(tmp_path):
    srt = _cue_srt("Сегодня говорим про организацию курса.", "Бинарное дерево поиска и ключи.")
    layout = [[{"title": "A", "start": "00:00:00,000", "end": "00:00:20,000"}]]
    slide = {
        "slide_num": 1,
        "title": "Организация курса",
        "visible_text": "Сегодня говорим про организацию курса",
    }
    outcomes = []
    prompts = _prompts(tmp_path)
    for _ in range(2):
        llm = ScriptedLlm(
            [
                _catalog_response(slide),
                _semantic(1, 0, [1], "Сегодня говорим про организацию курса.", "explicit"),
            ]
        )
        service = DocumentAlignmentService(
            llm=llm, models=["m"], prompts_dir=prompts, tuning=AlignmentTuning()
        )
        result = await service.align(
            assets=_assets(tmp_path, 1), section_layout=layout, srt_content=srt
        )
        outcomes.append(result.assignments)
    assert outcomes[0] == outcomes[1]


# ═════════════════════════════════════════════════════════════════════
# 6. Судья: вердикт без доказательств, порядок id, контракт вызова
# ═════════════════════════════════════════════════════════════════════

_JUDGE_SRT = (
    "1\n00:00:00,000 --> 00:00:10,000\nСегодня говорим про организацию курса.\n\n"
    "2\n00:00:10,000 --> 00:00:20,000\nРазбираем сортировку пузырьком.\n"
)
_JUDGE_LAYOUT = [
    [
        {"title": "A", "start": "00:00:00,000", "end": "00:00:10,000"},
        {"title": "B", "start": "00:00:11,000", "end": "00:00:20,000"},
    ]
]
_ORGANISATION = {
    "slide_num": 1,
    "title": "Организация курса",
    "visible_text": "Сегодня говорим про организацию курса",
}
_ORGANISATION_VERDICT = _semantic(1, 0, [1], "Сегодня говорим про организацию курса.", "explicit")


@pytest.mark.asyncio
async def test_дважды_повторённый_strong_без_цитат_и_без_лексики_не_кладёт_слайд_в_галерею_раздела_потому_что_непривязанный_это_слайд_с_доказательством(
    tmp_path,
):
    """Слайд про квантовую запутанность в лекции про сортировку: судья дважды ответил strong без блоков.

    GLOSSARY: непривязанный — «слайд с кандидатом и доказательством». Здесь доказательств ноль:
    evidence_block_ids пуст, цитаты нет, lexical_score 0.000; единственное, что держит слайд, —
    бонус самого вердикта (+2). Что тихо ломается: недискутировавшийся слайд встаёт в галерею
    раздела вместо приложения; deck guard и диагностика видят «weak_evidence», а не галлюцинацию.
    Вторая «независимая» проверка при temperature=0 на том же промпте возвращает тот же ответ.
    """
    foreign = {
        "slide_num": 2,
        "title": "Zyxwv quantum",
        "visible_text": "Zyxwv quantum entanglement",
    }
    strong_without_evidence = _semantic(2, 1, [], "", "strong")
    llm = ScriptedLlm(
        [
            _catalog_response(_ORGANISATION, foreign),
            _ORGANISATION_VERDICT,
            strong_without_evidence,
            strong_without_evidence,
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_JUDGE_LAYOUT, srt_content=_JUDGE_SRT
    )

    item = result.assignments[1]
    assert item.match_status != "unbound" or item.evidence_block_ids, (
        f"слайд без единой цитаты и без лексики оказался в галерее раздела {item.global_section_id}: "
        f"{item.reason_code}"
    )


@pytest.mark.asyncio
async def test_якорь_диагностики_лежит_внутри_интервала_доказательств_даже_если_судья_назвал_блоки_не_по_порядку(
    tmp_path,
):
    srt = _cue_srt(
        "Сегодня говорим про организацию курса.",
        "Бинарное дерево поиска хранит ключи.",
        "Дерево поиска обходят в глубину и в ширину.",
    )
    layout = [[{"title": "A", "start": "00:00:00,000", "end": "00:00:30,000"}]]
    tree = {
        "slide_num": 2,
        "title": "Бинарное дерево поиска",
        "visible_text": "Бинарное дерево поиска",
        "source_concepts": ["бинарное дерево поиска"],
    }
    unsorted = json.dumps(
        {
            "slide_num": 2,
            "global_section_id": 0,
            "evidence_block_ids": [3, 2],
            "evidence_quote": "Бинарное дерево поиска хранит ключи.",
            "semantic_tier": "explicit",
        }
    )
    llm = ScriptedLlm([_catalog_response(_ORGANISATION, tree), _ORGANISATION_VERDICT, unsorted])
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=layout, srt_content=srt
    )

    item = result.assignments[1]
    assert item.match_status == "discussed"
    assert 10.0 <= item.anchor_s <= 30.0


@pytest.mark.asyncio
async def test_все_вызовы_модели_используют_только_параметры_которые_принимает_llm_client(tmp_path):
    """ScriptedLlm принимает любые kwargs, поэтому опечатка в имени параметра в тестах не видна; боевой клиент упадёт."""
    import inspect

    from lecturelog.infrastructure.llm.llm_client import LlmClient

    allowed = set(inspect.signature(LlmClient.call).parameters) - {"self"}
    tree = {"slide_num": 2, "title": "Сортировка", "visible_text": "Сортировка пузырьком"}
    strong = _semantic(2, 1, [2], "Разбираем сортировку пузырьком.", "strong")
    llm = ScriptedLlm(
        [_catalog_response(_ORGANISATION, tree), _ORGANISATION_VERDICT, strong, strong]
    )
    service = DocumentAlignmentService(
        llm=llm, models=["m"], prompts_dir=_prompts(tmp_path), effort="low"
    )
    await service.align(
        assets=_assets(tmp_path, 2), section_layout=_JUDGE_LAYOUT, srt_content=_JUDGE_SRT
    )
    assert len(llm.calls) == 4, "каталог, судья, судья, перепроверка strong"
    for call in llm.calls:
        assert set(call) <= allowed, set(call) - allowed


def test_слайд_после_отвергнутого_системой_слайда_остаётся_в_своём_разделе_хотя_бы_галереей():
    """Слайд 2 с конкурентом -20 отвергнут (unbound), но его раздел 9 остаётся в пути и выталкивает слайд 3.

    Всё, что гарантируется при любом исходе развилки «пересчитывать ли путь без отвергнутых»:
    слайд 3 не уходит в приложение и не теряет свой раздел.
    """
    result = align_sequence(
        [1, 2, 3],
        {
            1: (_cand(1, 2, 6.0, cm=3.0),),
            2: (_cand(2, 9, 3.0, cm=-20.0, comps=(_rival(2, 2, 23.0),)),),
            3: (_cand(3, 3, 4.0, "strong", cm=3.0),),
        },
    )
    assert result[1].status_reason == "stronger_competitor"
    assert result[2].match_status in {"discussed", "unbound"}
    assert result[2].global_section_id == 3


# ═════════════════════════════════════════════════════════════════════
# 7. Пары (статус, причина) сквозь сервис и границы пула
# ═════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_пары_статус_причина_которые_выдаёт_сервис_совпадают_с_глоссарием(tmp_path):
    """Неупомянутый без кандидатов, служебная пустая страница и колода-чужак — каждая пара из глоссария."""
    glossary = _glossary_reasons()
    prompts = _prompts(tmp_path)
    blank = {"slide_num": 3, "role": "blank", "visible_text": ""}
    foreign = {
        "slide_num": 2,
        "title": "Zyxwv quantum",
        "visible_text": "Zyxwv quantum entanglement",
    }
    llm = ScriptedLlm(
        [
            _catalog_response(_ORGANISATION, foreign),
            _catalog_response(blank),
            _ORGANISATION_VERDICT,
            _semantic(2, 1, [], "", "none"),
        ]
    )
    result = await DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=prompts).align(
        assets=_assets(tmp_path, 3), section_layout=_JUDGE_LAYOUT, srt_content=_JUDGE_SRT
    )
    pairs = {(item.match_status, item.status_reason) for item in result.assignments}
    assert ("discussed", None) in pairs
    for status, reason in pairs - {("discussed", None)}:
        assert glossary[reason or ""] == status, (status, reason)
    assert ("unmentioned", "no_candidates") in pairs
    assert ("unmentioned", "service_role") in pairs


@pytest.mark.asyncio
async def test_колода_с_числом_разделов_меньше_лимита_кандидатов_даёт_конкурентов_из_всех_разделов(
    tmp_path,
):
    """Граница лимита: разделов (2) меньше candidate_limit (5) — пул целиком, margin конечный."""
    tree = {
        "slide_num": 2,
        "title": "Разбираем сортировку",
        "visible_text": "Разбираем сортировку пузырьком",
    }
    llm = ScriptedLlm(
        [
            _catalog_response(_ORGANISATION, tree),
            _ORGANISATION_VERDICT,
            _semantic(2, 1, [2], "Разбираем сортировку пузырьком.", "explicit"),
        ]
    )
    result = await DocumentAlignmentService(
        llm=llm, models=["m"], prompts_dir=_prompts(tmp_path), tuning=AlignmentTuning()
    ).align(assets=_assets(tmp_path, 2), section_layout=_JUDGE_LAYOUT, srt_content=_JUDGE_SRT)
    margin = _margin_of(result.assignments[1].reason_code)
    assert margin is not None and margin > 0
