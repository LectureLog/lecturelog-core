# ruff: noqa: E501, F811 — длинные имена тестов
"""Краевые случаи тикета 06: отрицательный margin делает слайд непривязанным.

Тесты описывают тихие отказы: слайд выглядит привязанным (или уходит в галерею)
правдоподобно, а на деле порог, конкурент или причина посчитаны неверно.
"""

import dataclasses
import itertools
import json
import random
import tempfile
from pathlib import Path

import pytest

from lecturelog.domain.slides import SlideAssignment, SlideCandidate, SlideRelation
from lecturelog.infrastructure.slides.alignment.anchoring import anchor_assignment
from lecturelog.infrastructure.slides.alignment.confidence import calibrate
from lecturelog.infrastructure.slides.alignment.diagnostics import write_diagnostic
from lecturelog.infrastructure.slides.alignment.sequence import (
    AlignmentWeights,
    align_sequence,
    strongest_candidate,
)
from lecturelog.infrastructure.slides.alignment.service import (
    AlignmentTuning,
    DocumentAlignmentService,
)
from tests.unit.slides.test_unbound_slides import (
    _COURSE_SLIDE,
    _COURSE_VERDICT,
    ScriptedLlm,
    _assets,
    _catalog_response,
    _prompts,
    _semantic,
    _srt,
)

W = AlignmentWeights()


def _c(slide, section, lexical, tier="explicit", cm=None, comps=(), visual=None, quote="цитата"):
    return SlideCandidate(
        slide,
        section,
        (section + 1,),
        quote,
        section * 10.0,
        section * 10.0 + 5,
        lexical,
        tier,
        visual_score=visual,
        competition_margin=cm,
        competitors=tuple(comps),
    )


def _rival(slide, section, lexical, tier="none", visual=None):
    """Конкурент из retrieval: судья его не подтверждал, tier none, цитаты нет."""
    return _c(slide, section, lexical, tier=tier, visual=visual, quote=None)


def _one(chosen, weights=W, relations=()):
    return align_sequence([1], {1: (chosen,)}, relations, weights)[0]


# ── порог: ровно на границе и рядом ─────────────────────────────────


def test_margin_ровно_на_пороге_не_делает_слайд_непривязанным_потому_что_сравнение_строгое():
    """Сравнение «<», а не «<=»: слайд на пороге остаётся привязанным; иначе порог −5 молча превращается в −4.99."""
    item = _one(_c(1, 1, 3.0, cm=-5.0, comps=(_rival(1, 2, 8.0),)))
    assert item.match_status == "discussed"


def test_margin_чуть_ниже_порога_делает_слайд_непривязанным_с_причиной_конкурента():
    item = _one(_c(1, 1, 3.0, cm=-5.0001, comps=(_rival(1, 2, 8.0001),)))
    assert (item.match_status, item.status_reason) == ("unbound", "stronger_competitor")


@pytest.mark.parametrize("cm", [-0.4, -1.0, -4.999])
def test_шумовой_отрицательный_margin_в_допуске_не_роняет_верный_выбор_в_непривязанные(cm):
    """Верный выбор получает до −0.4 из-за шума лексики: ложный unbound убирает слайд из текста без следа."""
    item = _one(_c(1, 1, 3.0, cm=cm, comps=(_rival(1, 2, 3.0 - cm),)))
    assert item.match_status == "discussed"
    assert item.assignment_confidence != "unresolved"


def test_нулевой_порог_нулевой_margin_остаётся_привязанным():
    """Ничья с конкурентом — не «конкурент сильнее»."""
    item = _one(_c(1, 1, 3.0, cm=0.0, comps=(_rival(1, 2, 3.0),)), AlignmentWeights(min_margin=0.0))
    assert item.match_status == "discussed"


def test_нулевой_порог_минус_эпсилон_уже_непривязанный():
    item = _one(
        _c(1, 1, 3.0, cm=-0.001, comps=(_rival(1, 2, 3.001),)), AlignmentWeights(min_margin=0.0)
    )
    assert item.status_reason == "stronger_competitor"


def test_порог_ниже_любого_margin_отключает_правило_и_слайд_остаётся_привязанным():
    item = _one(
        _c(1, 1, 3.0, cm=-22.0, comps=(_rival(1, 2, 25.0),)),
        AlignmentWeights(min_margin=-float("inf")),
    )
    assert item.match_status == "discussed"


@pytest.mark.parametrize("tier", ["explicit", "strong", "weak"])
def test_отрицательный_margin_ниже_порога_действует_на_каждом_уровне_уверенности(tier):
    item = _one(_c(1, 1, 3.0, tier=tier, cm=-18.0, comps=(_rival(1, 2, 21.0),)))
    assert (item.match_status, item.assignment_confidence) == ("unbound", "unresolved")


def test_calibrate_без_min_margin_ведёт_себя_по_старому_для_отрицательного_margin():
    """Обратная совместимость вызова: дефолт 0.0 не должен включать правило для margin == 0."""
    result = calibrate(
        semantic_tier="explicit", margin=0.0, has_grounded_evidence=True, has_competing_context=True
    )
    assert result.unbound_reason is None


def test_calibrate_не_падает_на_nan_margin_и_не_объявляет_конкурента():
    """NaN не «меньше порога»: если он дойдёт до калибровки, это не повод выдумывать конкурента."""
    result = calibrate(
        semantic_tier="explicit",
        margin=float("nan"),
        has_grounded_evidence=True,
        has_competing_context=True,
        min_margin=-5.0,
    )
    assert result.unbound_reason != "stronger_competitor"


def test_margin_берётся_минимумом_из_пути_и_конкурента_и_положительный_путь_не_маскирует_отрицательный_конкурент():
    item = align_sequence(
        [1, 2],
        {
            1: (_c(1, 0, 9.0, cm=2.0),),
            2: (_c(2, 1, 3.0, cm=-9.0, comps=(_rival(2, 3, 12.0),)),),
        },
    )[1]
    assert item.status_reason == "stronger_competitor"


# ── куда уходит слайд ───────────────────────────────────────────────


def test_слайд_уходит_в_галерею_конкурента_с_его_доказательством_а_не_выбора_судьи():
    """Иначе evidence_block_ids указывают на блок чужого раздела, и диагностика врёт, почему слайд тут."""
    item = _one(_c(1, 1, 2.0, cm=-18.0, comps=(_rival(1, 4, 20.0),)))
    assert (item.match_status, item.global_section_id) == ("unbound", 4)
    assert item.evidence_block_ids == (5,)
    assert item.anchor_s is None


def test_при_нескольких_конкурентах_выигрывает_самый_сильный_а_не_первый_в_списке():
    rivals = (_rival(1, 2, 9.0), _rival(1, 3, 20.0), _rival(1, 4, 11.0))
    item = _one(_c(1, 1, 2.0, cm=-18.0, comps=rivals))
    assert item.global_section_id == 3


def test_ничья_конкурентов_решается_ранним_разделом_при_любом_порядке_конкурентов():
    """Порядок пула retrieval — случайность; раздел галереи от него зависеть не должен."""
    rivals = [_rival(1, 5, 20.0), _rival(1, 2, 20.0), _rival(1, 7, 20.0)]
    for perm in itertools.permutations(rivals):
        item = _one(_c(1, 1, 2.0, cm=-18.0, comps=perm))
        assert item.global_section_id == 2


def test_ничья_выбора_и_конкурента_оставляет_слайд_в_разделе_выбора():
    """Порог −4: конкурент отстоит на −5, но tier none (−1) уравнивает силу с explicit (+4) — побеждает выбор пути."""
    item = _one(
        _c(1, 1, 2.0, cm=-5.0, comps=(_rival(1, 4, 7.0),)), AlignmentWeights(min_margin=-4.0)
    )
    assert item.status_reason == "stronger_competitor"
    assert item.global_section_id == 1


def test_конкурент_слабее_по_силе_но_лексически_сильнее_оставляет_слайд_в_своём_разделе_с_причиной_конкурента():
    """Решённая развилка: tier none вычитает 1, а у выбора с визуальным бонусом сила выше — слайд в своей галерее, но не привязан."""
    item = _one(_c(1, 1, 2.0, cm=-6.0, visual=1.0, comps=(_rival(1, 4, 8.0),)))
    assert (item.match_status, item.global_section_id) == ("unbound", 1)
    assert item.status_reason == "stronger_competitor"


def test_визуальный_бонус_конкурента_входит_в_силу_и_переносит_галерею():
    item = _one(_c(1, 1, 2.0, cm=-6.0, comps=(_rival(1, 4, 8.0, visual=0.5),)))
    assert item.global_section_id == 4


def test_конкуренты_без_доказательства_не_утаскивают_слайд_в_приложение():
    """Выбор с доказательством не должен превращаться в unmentioned оттого, что конкуренты слабы."""
    item = _one(_c(1, 1, 3.0, cm=-6.0, comps=(_rival(1, 4, 0.2),)))
    assert item.match_status == "unbound"
    assert item.global_section_id == 1


def test_конкурент_не_попадает_в_пул_при_weak_evidence():
    """Конкурент нужен только при stronger_competitor; при слабом доказательстве слайд остаётся у своего раздела."""
    item = _one(_c(1, 1, 3.0, tier="strong", quote=None, cm=-1.0, comps=(_rival(1, 4, 4.0),)))
    assert (item.status_reason, item.global_section_id) == ("weak_evidence", 1)


def test_конкуренты_не_смешиваются_с_пулом_для_следующего_слайда():
    """Конкуренты слайда 1 не должны всплыть в галерее слайда 2."""
    result = align_sequence(
        [1, 2],
        {
            1: (_c(1, 1, 2.0, cm=-18.0, comps=(_rival(1, 4, 20.0),)),),
            2: (_c(2, 2, 3.0, tier="strong", quote=None),),
        },
    )
    assert result[1].global_section_id == 2


def test_пропущенный_путём_слайд_с_сильно_отрицательным_margin_уходит_в_раздел_конкурента():
    """Слайд пропущен путём (deck_order_conflict), но у выбора судьи margin −20: по спеке «отрицательный margin
    уводит в галерею раздела конкурента». Сейчас пул пропущенного слайда — только выбор судьи, конкурент
    теряется, и слайд тихо оседает в слабом разделе."""
    result = align_sequence(
        [1, 2],
        {
            1: (_c(1, 5, 9.0, cm=3.0),),
            2: (_c(2, 0, 3.0, tier="strong", cm=-20.0, comps=(_rival(2, 3, 23.0),)),),
        },
    )
    assert result[1].match_status == "unbound"
    assert result[1].global_section_id == 3


# ── дубли, прогрессивные сборки ──────────────────────────────────────


def test_дубль_остаётся_дублем_даже_если_его_кандидат_с_конкурентом_ниже_порога():
    rel = SlideRelation(2, "exact_duplicate", "g", 1)
    result = align_sequence(
        [1, 2],
        {
            1: (_c(1, 1, 3.0),),
            2: (_c(2, 1, 3.0, cm=-18.0, comps=(_rival(2, 4, 21.0),)),),
        },
        (rel,),
    )
    assert result[1].match_status == "duplicate"
    assert result[1].global_section_id is None


def test_progressive_build_с_конкурентом_ниже_порога_не_остаётся_discussed():
    """Бонус прогрессивной сборки двигает путь, но не отменяет отрицательный margin."""
    rel = SlideRelation(2, "progressive_build", "g", 1)
    result = align_sequence(
        [1, 2],
        {
            1: (_c(1, 1, 3.0),),
            2: (_c(2, 1, 3.0, cm=-18.0, comps=(_rival(2, 4, 21.0),)),),
        },
        (rel,),
    )
    assert result[1].status_reason == "stronger_competitor"


# ── стабильность пути, детерминизм ──────────────────────────────────


def test_конкуренты_не_влияют_на_путь_и_соседей():
    """Если конкуренты просочатся в DP, соседние слайды поменяют раздел при тех же кандидатах."""
    base = {
        1: (_c(1, 0, 6.0, cm=2.0),),
        2: (_c(2, 1, 3.0, cm=-18.0),),
        3: (_c(3, 2, 6.0, cm=2.0),),
    }
    with_rivals = dict(base)
    with_rivals[2] = (_c(2, 1, 3.0, cm=-18.0, comps=(_rival(2, 7, 21.0),)),)
    a = align_sequence([1, 2, 3], base)
    b = align_sequence([1, 2, 3], with_rivals)
    assert a[0] == b[0] and a[2] == b[2]
    assert (a[1].match_status, a[1].status_reason) == ("unbound", "stronger_competitor")
    assert a[1].global_section_id == 1


def test_непривязанный_по_конкуренту_слайд_не_меняет_уверенность_соседей():
    near = {1: (_c(1, 0, 6.0, cm=2.0),), 2: (_c(2, 1, 3.0, cm=-18.0),), 3: (_c(3, 1, 6.0, cm=2.0),)}
    ok = {**near, 2: (_c(2, 1, 3.0, cm=2.0),)}
    a = align_sequence([1, 2, 3], near)
    b = align_sequence([1, 2, 3], ok)
    assert (a[0], a[2]) == (b[0], b[2])


def test_повторный_прогон_и_перестановка_конкурентов_дают_идентичный_результат():
    rng = random.Random(11)
    for _ in range(120):
        n = rng.randint(1, 5)
        cands, shuffled = {}, {}
        for slide in range(1, n + 1):
            rivals = [
                _rival(slide, rng.randint(0, 6), rng.choice([0.0, 2.0, 5.0, 12.0, 20.0]))
                for _ in range(rng.randint(0, 4))
            ]
            own = _c(
                slide,
                rng.randint(0, 6),
                rng.choice([1.0, 3.0, 6.0]),
                tier=rng.choice(["explicit", "strong"]),
                cm=rng.choice([None, 2.0, -1.0, -9.0, -18.0]),
                comps=rivals,
            )
            cands[slide] = (own,)
            shuffled[slide] = (dataclasses.replace(own, competitors=tuple(reversed(rivals))),)
        order = list(range(1, n + 1))
        assert align_sequence(order, cands) == align_sequence(order, cands)
        assert align_sequence(order, cands) == align_sequence(order, shuffled)


def test_инварианты_на_случайных_входах_с_конкурентами():
    """discussed не бывает ниже порога; unbound/stronger_competitor всегда с разделом из пула∪конкурентов и без якоря."""
    rng = random.Random(23)
    for _ in range(400):
        n = rng.randint(1, 5)
        cands = {}
        for slide in range(1, n + 1):
            rivals = [
                _rival(slide, rng.randint(0, 6), rng.choice([0.0, 2.0, 12.0, 25.0]))
                for _ in range(rng.randint(0, 3))
            ]
            cands[slide] = (
                _c(
                    slide,
                    rng.randint(0, 6),
                    rng.choice([1.0, 3.0, 6.0]),
                    tier=rng.choice(["explicit", "strong", "weak"]),
                    quote=rng.choice([None, "q"]),
                    cm=rng.choice([None, 0.0, -0.4, -5.0, -6.0, -20.0]),
                    comps=rivals,
                ),
            )
        for slide, item in zip(
            range(1, n + 1), align_sequence(list(range(1, n + 1)), cands), strict=True
        ):
            own = cands[slide][0]
            if item.match_status == "discussed":
                assert own.competition_margin is None or own.competition_margin >= W.min_margin
            if item.status_reason == "stronger_competitor":
                assert item.match_status == "unbound"
                assert item.anchor_s is None
                allowed = {own.global_section_id, *(r.global_section_id for r in own.competitors)}
                assert item.global_section_id in allowed
                assert item.assignment_confidence == "unresolved"


# ── reason_code / диагностика / размещение ───────────────────────────


def test_reason_code_ушедшего_к_конкуренту_слайда_называет_раздел_пути_и_не_приписывает_конкуренту_чужой_margin():
    item = _one(_c(1, 1, 2.0, cm=-18.0, comps=(_rival(1, 4, 20.0),)))
    assert "margin=none" in item.reason_code
    assert "path_section=1" in item.reason_code
    assert "path_min_margin=-18.000" in item.reason_code
    assert "lexical=20.000" in item.reason_code


def test_reason_code_оставшегося_в_своём_разделе_слайда_несёт_реальный_margin():
    item = _one(_c(1, 1, 2.0, cm=-6.0, visual=1.0, comps=(_rival(1, 4, 8.0),)))
    assert "margin=-6.000" in item.reason_code
    assert "path_section" not in item.reason_code


def test_диагностика_сериализуется_без_конкурентов_и_с_причиной():
    """competitors — внутреннее поле кандидата; в json присваиваний утечь не должно (рост файла, рекурсия)."""
    item = _one(_c(1, 1, 2.0, cm=-18.0, comps=(_rival(1, 4, 20.0),)))
    assert not any(f.name == "competitors" for f in dataclasses.fields(SlideAssignment))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a" / "alignment.json"
        write_diagnostic(path, mode="v2", assignments=(item,))
        payload = json.loads(path.read_text(encoding="utf-8"))
    row = payload["assignments"][0]
    assert row["status_reason"] == "stronger_competitor"
    assert "competitors" not in row


def test_размещение_ушедшего_к_конкуренту_слайда_это_галерея_без_маркера_в_тексте():
    item = _one(_c(1, 1, 2.0, cm=-18.0, comps=(_rival(1, 4, 20.0),)))
    md = "Абзац.\n\nВторой."
    new_md, placement = anchor_assignment(item, None, md)
    assert new_md == md
    assert (placement.output_kind, placement.global_section_id) == ("section_gallery", 4)
    assert placement.fallback_reason == "unbound:stronger_competitor"


def test_strongest_candidate_не_падает_и_детерминирован_на_пуле_с_конкурентами_и_выбором():
    chosen = _c(1, 1, 2.0)
    pool = (chosen, _rival(1, 3, 9.0), _rival(1, 2, 9.0))
    for perm in itertools.permutations(pool):
        assert strongest_candidate(perm, W, preferred=chosen).global_section_id == 2


# ── сервис: _with_competition ────────────────────────────────────────


def test_with_competition_исключает_свой_раздел_из_конкурентов_и_считает_margin_по_сильнейшему():
    me = _c(1, 1, 5.0, tier="none", quote=None)
    pool = (me, _rival(1, 1, 99.0), _rival(1, 2, 9.0), _rival(1, 3, 7.0))
    out = DocumentAlignmentService._with_competition(me, pool, AlignmentWeights())
    assert {c.global_section_id for c in out.competitors} == {2, 3}
    assert out.competition_margin == pytest.approx(5.0 - 9.0)


def test_with_competition_без_конкурентов_даёт_margin_none_и_пустой_кортеж():
    me = _c(1, 1, 5.0)
    out = DocumentAlignmentService._with_competition(me, (me,), AlignmentWeights())
    assert out.competition_margin is None
    assert out.competitors == ()


def test_with_competition_не_вкладывает_конкурентов_друг_в_друга_иначе_раздувается_память_и_repr():
    me = _c(1, 1, 5.0)
    pool = (me, _rival(1, 2, 9.0), _rival(1, 3, 7.0))
    out = DocumentAlignmentService._with_competition(me, pool, AlignmentWeights())
    assert all(c.competitors == () for c in out.competitors)


def test_with_competition_повторный_вызов_на_результате_идемпотентен():
    me = _c(1, 1, 5.0)
    pool = (me, _rival(1, 2, 9.0))
    once = DocumentAlignmentService._with_competition(me, pool, AlignmentWeights())
    assert DocumentAlignmentService._with_competition(once, pool, AlignmentWeights()) == once


# ── сервис целиком: коллизии, deck guard, порог из tuning ────────────

_STD = {
    "slide_num": 2,
    "title": "Профессиональный стандарт программиста",
    "visible_text": "Третий уровень квалификации\nТрудовые функции\nКодирование программных модулей\nОтладка и тестирование компонентов\nОформление документации",
    "source_concepts": ["профессиональный стандарт", "уровень квалификации"],
}
_SRT = _srt(
    "Сегодня говорим про организацию курса.",
    "Пауза.",
    "Типы программных продуктов; профессиональный стандарт упомянем позже.",
    "Пауза.",
    "Модели жизненного цикла: водопадная модель, итеративная модель.",
    "Пауза.",
    "Профессиональный стандарт программиста: третий уровень квалификации, трудовые функции — кодирование программных модулей, отладка и тестирование компонентов, оформление документации.",
    "Пауза.",
)
_LAYOUT = [
    [
        {
            "title": f"Раздел {i}",
            "start": f"{(i * 20 + 1) // 60}:{(i * 20 + 1) % 60:02d}",
            "end": f"{(i * 20 + 19) // 60}:{(i * 20 + 19) % 60:02d}",
        }
        for i in range(4)
    ]
]


def _svc(tmp_path, responses, tuning=AlignmentTuning()):
    return DocumentAlignmentService(
        llm=ScriptedLlm(responses),
        models=["m"],
        prompts_dir=_prompts(tmp_path),
        tuning=tuning,
    )


@pytest.mark.asyncio
async def test_колода_где_все_слайды_ушли_к_конкурентам_признаётся_посторонней_и_галереи_не_остаются(
    tmp_path,
):
    """Единственный слайд колоды с stronger_competitor: discussed нет, deck guard обязан убрать и галерею, и справочник."""
    entry = dict(_STD, slide_num=1)
    svc = _svc(
        tmp_path,
        [_catalog_response(entry), _semantic(1, 1, [3], "профессиональный стандарт", "explicit")],
    )
    result = await svc.align(assets=_assets(tmp_path, 1), section_layout=_LAYOUT, srt_content=_SRT)
    [item] = result.assignments
    assert item.match_status == "deck_mismatch"
    assert item.global_section_id is None
    assert result.catalog == {}


@pytest.mark.asyncio
async def test_unbound_по_конкуренту_не_понижает_соседа_с_общим_блоком_и_сам_не_считается_discussed(
    tmp_path,
):
    """Коллизия доказательств — только среди discussed: слайд, ушедший к конкуренту, не отнимает verified у соседа."""
    course = dict(_COURSE_SLIDE, slide_num=2)
    std = dict(_STD, slide_num=1)
    svc = _svc(
        tmp_path,
        [
            _catalog_response(std, course),
            _semantic(1, 1, [3], "профессиональный стандарт", "explicit"),
            _COURSE_VERDICT,
        ],
    )
    result = await svc.align(assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_SRT)
    std_item, course_item = result.assignments
    assert std_item.match_status == "unbound"
    assert course_item.match_status == "discussed"
    assert "evidence_collision" not in course_item.reason_code


@pytest.mark.asyncio
async def test_порог_из_tuning_доходит_до_выравнивания_и_дефолт_равен_допуску_владельца(tmp_path):
    assert AlignmentTuning().weights.min_margin == -5.0
    course = dict(_COURSE_SLIDE, slide_num=2)
    std = dict(_STD, slide_num=1)
    responses = [
        _catalog_response(std, course),
        _semantic(1, 1, [3], "профессиональный стандарт", "explicit"),
        _COURSE_VERDICT,
    ]
    strict = _svc(
        tmp_path, list(responses), AlignmentTuning(weights=AlignmentWeights(min_margin=-5.0))
    )
    result = await strict.align(
        assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_SRT
    )
    assert result.assignments[0].status_reason == "stronger_competitor"
