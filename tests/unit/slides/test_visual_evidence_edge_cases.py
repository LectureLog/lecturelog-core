# ruff: noqa: E501
"""Краевые случаи тикета 07: визуальное описание слайда как доказательство.

Тихие отказы: описание-«мусор» поднимает оценку у всех разделов сразу,
привязка получает verified без подтверждения модели, описание-утверждение
ставит картинку в абзац, где о ней не говорили.
"""

import json
import subprocess
import sys
import textwrap

import pytest

from lecturelog.domain.slides import SectionRef, SlideAssignment, SlideCatalogEntry, TranscriptBlock
from lecturelog.infrastructure.slides.alignment.anchoring import anchor_assignment
from lecturelog.infrastructure.slides.alignment.confidence import calibrate
from lecturelog.infrastructure.slides.alignment.diagnostics import write_diagnostic
from lecturelog.infrastructure.slides.alignment.retrieval import generate_candidates
from lecturelog.infrastructure.slides.alignment.service import DocumentAlignmentService
from tests.unit.slides.test_visual_evidence import (
    _COURSE_SLIDE,
    _COURSE_VERDICT,
    _DIAGRAM_QUOTE,
    _DIAGRAM_SLIDE,
    _LAYOUT,
    _SRT,
    ScriptedLlm,
    _assets,
    _catalog_response,
    _prompts,
    _semantic,
    _srt,
)


def _sections(count=4):
    return [
        SectionRef(index, 0, index, index * 20.0, index * 20.0 + 19.0) for index in range(count)
    ]


def _blocks(*texts):
    return [
        TranscriptBlock(
            i + 1, (i // 2) * 20.0 + (i % 2) * 5.0, (i // 2) * 20.0 + (i % 2) * 5.0 + 4.0, text
        )
        for i, text in enumerate(texts)
    ]


_TEXTS = (
    "Сегодня говорим про организацию курса.",
    "Пауза.",
    "Клиент отправляет запрос серверу, а сервер читает базу данных и возвращает ответ.",
    "Пауза.",
    "Сортировка пузырьком сравнивает соседние элементы массива.",
    "Пауза.",
    "Итоги и домашнее задание.",
    "Пауза.",
)


def _entry(visual="", visible="", title=None, **kwargs):
    return SlideCatalogEntry(2, "content", title, visible, visual_summary=visual, **kwargs)


def _cands(entry, texts=_TEXTS, **kwargs):
    return generate_candidates(entry, _sections(), _blocks(*texts), visual_weight=3.0, **kwargs)


# ── ось данных: пустое, короткое, дубль ─────────────────────────────


@pytest.mark.parametrize("visual", ["", "   ", "\n\t", "...!!!", "🙂🙂🙂", "на ту и по за из"])
def test_описание_без_содержательных_слов_не_даёт_визуальной_оценки_потому_что_иначе_пустая_оценка_превратится_в_нулевую_улику(
    visual,
):
    """Нечем сравнивать — должно быть None, не число: диагностика не должна врать, что визуал «проверен и равен нулю»."""
    result = _cands(_entry(visual=visual, visible="Сортировка пузырьком"))
    assert all(c.visual_score is None for c in result)


def test_описание_целиком_дублирующее_видимый_текст_не_считается_второй_раз():
    """Двойной счёт одного и того же слова даёт слайду с текстом лишнюю силу доказательства."""
    entry = _entry(
        visual="Сортировка пузырьком", visible="Сортировка пузырьком сравнивает элементы"
    )
    assert all(c.visual_score is None for c in _cands(entry))


def test_описание_не_в_латинице_а_в_иероглифах_не_роняет_поиск_и_не_даёт_оценки():
    result = _cands(_entry(visual="服务器 数据库 请求 响应", visible=""))
    assert result and all(not c.visual_score for c in result)


def test_описание_на_10к_символов_из_одного_слова_не_даёт_полной_оценки_без_трёх_разных_основ():
    """Повтор одного слова — не три разные основы: насыщение не должно срабатывать от количества повторов."""
    result = _cands(_entry(visual="сервер " * 1500))
    assert max(c.visual_score or 0.0 for c in result) < 1.0


# ── общие слова описаний как ложные совпадения со всеми разделами ────


def test_общие_слова_описаний_звучащие_в_каждом_разделе_не_дают_высокой_визуальной_оценки():
    """«слайд/схема/изображение/диаграмма» звучат везде: оценка 1.0 у всех разделов подменяет различение и открывает verified-ветку."""
    texts = tuple(
        f"На этом слайде схема и диаграмма, изображение номер {i}." if i % 2 == 0 else "Пауза."
        for i in range(8)
    )
    entry = _entry(visual="Слайд: схема и диаграмма, изображение.")
    result = _cands(entry, texts)
    assert max(c.visual_score or 0.0 for c in result) < 0.85


def test_общие_слова_описания_не_создают_кандидата_с_силой_выше_порога_лексического_пути_в_каждом_разделе():
    """Без различающих слов сила 3·1.0 у всех разделов проходит порог >1.0 в _lexical_ground: слайд «подтверждён» любым разделом."""
    texts = tuple(
        f"На слайде схема, диаграмма и изображение {i}." if i % 2 == 0 else "Пауза."
        for i in range(8)
    )
    result = _cands(_entry(visual="Слайд: схема, диаграмма, изображение."), texts)
    strong = [c for c in result if (c.visual_score or 0.0) * 3.0 > 1.0]
    assert len(strong) <= 1


def test_одно_общее_слово_не_даёт_полной_оценки():
    result = _cands(_entry(visual="Схема: сервер."))
    assert max(c.visual_score or 0.0 for c in result) < 0.5


# ── язык и алфавит ───────────────────────────────────────────────────


def test_английское_описание_при_русской_речи_не_даёт_ложной_оценки_через_кириллическую_основу():
    result = _cands(
        _entry(visual="Diagram: client sends request to server, server reads database.")
    )
    assert all(not c.visual_score for c in result)


def test_смешанная_латиница_и_кириллица_в_основе_не_склеивает_разные_слова():
    """«сервер» кириллицей и «cepвep» с латинскими буквами-двойниками — разные токены, совпадения быть не должно."""
    latin_lookalike = "cepвep"  # c, e, p латинские
    result = _cands(_entry(visual=f"{latin_lookalike} {latin_lookalike}a базaданных"))
    assert all(not c.visual_score for c in result)


def test_регистр_и_ё_не_ломают_совпадение_основ():
    texts = ("Пауза.", "Пауза.", "ЖЁЛТЫЙ СЕРВЕР принимает ЗАПРОС и ХРАНИТ данные.", "Пауза.") + (
        "Пауза.",
    ) * 4
    result = _cands(_entry(visual="жёлтый сервер принимает запрос и хранит данные"), texts)
    best = max(result, key=lambda c: c.visual_score or 0.0)
    assert best.global_section_id == 1 and best.visual_score > 0.9


# ── одинаковые описания у нескольких слайдов ────────────────────────


@pytest.mark.asyncio
async def test_два_слайда_с_одинаковым_описанием_не_получают_оба_verified_на_одной_реплике(
    tmp_path,
):
    """Одно и то же описание на двух разных страницах не должно считаться уникальным доказательством для каждой: коллизия доказательства понижается."""
    twin = {**_DIAGRAM_SLIDE, "slide_num": 3}
    strong = _semantic(2, 1, [3], _DIAGRAM_QUOTE, "strong")
    strong3 = _semantic(3, 1, [3], _DIAGRAM_QUOTE, "strong")
    llm = ScriptedLlm(
        [
            _catalog_response(_COURSE_SLIDE, _DIAGRAM_SLIDE, twin),
            _COURSE_VERDICT,
            strong,
            strong,
            strong3,
            strong3,
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 3), section_layout=_LAYOUT, srt_content=_SRT
    )
    verified = [a for a in result.assignments[1:] if a.assignment_confidence == "verified"]
    assert len(verified) < 2


# ── решение оркестратора: verified только с подтверждением модели ───


@pytest.mark.parametrize("tier", ["weak", "none"])
def test_calibrate_не_выдаёт_verified_слабому_вердикту_с_высокой_визуальной_оценкой_потому_что_модель_не_подтверждала(
    tier,
):
    result = calibrate(
        semantic_tier=tier,
        margin=3.0,
        has_grounded_evidence=True,
        has_competing_context=True,
        visual_score=0.95,
        min_margin=-5.0,
    )
    assert result.confidence != "verified"


def test_calibrate_не_выдаёт_verified_без_цитаты_и_вердикта_даже_при_идеальной_визуальной_оценке():
    result = calibrate(
        semantic_tier="none",
        margin=3.0,
        has_grounded_evidence=False,
        has_competing_context=True,
        visual_score=1.0,
        min_margin=-5.0,
    )
    assert result.confidence != "verified"


@pytest.mark.asyncio
async def test_кандидат_глобального_восстановления_после_weak_судьи_не_становится_verified_по_описанию(
    tmp_path,
):
    """Судья сказал weak — _global_recovery находит раздел лексикой+описанием; verified здесь = утверждение без единого подтверждения модели."""
    llm = ScriptedLlm(
        [
            _catalog_response(_COURSE_SLIDE, _DIAGRAM_SLIDE),
            _COURSE_VERDICT,
            _semantic(2, 1, [3], _DIAGRAM_QUOTE, "weak"),
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_SRT
    )
    diagram = result.assignments[1]
    assert diagram.assignment_confidence != "verified"


@pytest.mark.asyncio
async def test_без_llm_вообще_лексика_и_описание_не_дают_verified_потому_что_модель_не_участвовала(
    tmp_path,
):
    service = DocumentAlignmentService(llm=None, models=[], prompts_dir=_prompts(tmp_path))
    entries = {
        2: SlideCatalogEntry(
            2, "content", None, "", visual_summary=_DIAGRAM_SLIDE["visual_summary"]
        )
    }
    # без каталога путь лексики недоступен через align; проверяем сам лексический путь
    sections = _sections()
    blocks = _blocks(*_TEXTS)
    pool = generate_candidates(entries[2], sections, blocks, visual_weight=3.0)
    grounded = service._lexical_ground(entries[2], pool, blocks, 3.0)
    assert grounded is not None
    from lecturelog.infrastructure.slides.alignment.sequence import AlignmentWeights, align_sequence

    others = service._with_competition(grounded, pool, 3.0)
    item = align_sequence([2], {2: (others,)}, (), AlignmentWeights())[0]
    assert item.assignment_confidence != "verified"


# ── детерминизм ─────────────────────────────────────────────────────


def test_визуальная_оценка_не_зависит_от_PYTHONHASHSEED_потому_что_сумма_idf_идёт_по_множеству():
    """Порядок суммирования float по set меняется между процессами; оценка у порога 0.85 может дрогнуть и сменить уверенность между прогонами."""
    code = textwrap.dedent(
        """
        from lecturelog.domain.slides import SlideCatalogEntry, SectionRef, TranscriptBlock
        from lecturelog.infrastructure.slides.alignment.retrieval import generate_candidates
        words = "альфа бета гамма дельта эпсилон дзета тета йота каппа лямбда сигма омега".split()
        sections = [SectionRef(i, 0, i, i*20.0, i*20.0+19.0) for i in range(6)]
        texts = [" ".join(words[: 3 + (i * 2) % 9]) + " " + " ".join(words[i:i+2]) for i in range(6)]
        blocks = [TranscriptBlock(i+1, i*20.0+1, i*20.0+9, t) for i, t in enumerate(texts)]
        e = SlideCatalogEntry(1, "content", None, "", visual_summary=" ".join(words))
        r = generate_candidates(e, sections, blocks, visual_weight=3.0, limit=6)
        print([(c.global_section_id, repr(c.visual_score), repr(c.lexical_score)) for c in r])
        """
    )
    outputs = set()
    for seed in ("1", "2", "3", "4", "5", "6", "7", "8"):
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "", "PYTHONPATH": ":".join(sys.path)},
            check=True,
        )
        outputs.add(proc.stdout)
    assert len(outputs) == 1


# ── якорение: описание как утверждение ──────────────────────────────


def _assignment(confidence):
    return SlideAssignment(2, "discussed", 1, (3,), 30.0, confidence, 5.0, "r")


_MD = (
    "# Тема\n\n"
    "Здесь мы обсуждаем протокол и его заголовки.\n\n"
    "На слайде пока видно только заголовок, схема будет потом.\n\n"
    "Итоги."
)


def test_описание_из_общих_слов_не_ставит_verified_картинку_в_абзац_где_о_ней_не_говорили():
    """Схема без текста, нужного абзаца в конспекте нет. Без описания картинка в галерее; с описанием «На слайде изображена схема» два общих слова абзаца про «слайде… схема» считаются утверждением, и verified (специфичность не проверяется) якорит картинку в чужой абзац."""
    without = _entry(visual="")
    with_visual = _entry(visual="На слайде изображена схема с тремя блоками")
    _, before = anchor_assignment(_assignment("verified"), without, _MD)
    _, after = anchor_assignment(_assignment("verified"), with_visual, _MD)
    assert before.output_kind == "section_gallery"
    assert after.output_kind == "section_gallery"


def test_описание_из_общих_слов_не_переносит_probable_картинку_из_галереи_в_абзац():
    """Для probable нужна дословная фраза/редкий токен; предложение-описание из двух общих слов не должно её давать."""
    entry = _entry(visual="На слайде изображена схема", title=None, visible="")
    _, placement = anchor_assignment(_assignment("probable"), entry, _MD)
    assert placement.output_kind != "inline"


def test_описание_не_ломается_на_пустом_markdown_и_пустом_описании():
    _, placement = anchor_assignment(_assignment("verified"), _entry(visual=""), "")
    assert placement.output_kind == "section_gallery"


# ── диагностика ─────────────────────────────────────────────────────


def test_старое_назначение_без_visual_contribution_сериализуется_с_null_а_не_падает(tmp_path):
    old = SlideAssignment(1, "unmentioned", None, (), None, "unresolved", 0.0, "x")
    path = tmp_path / "d.json"
    write_diagnostic(path, mode="document", assignments=(old,))
    saved = json.loads(path.read_text(encoding="utf-8"))["assignments"][0]
    assert saved["visual_contribution"] is None


@pytest.mark.asyncio
async def test_визуальный_вклад_виден_и_у_непривязанного_слайда(tmp_path):
    """unbound с описанием: диагностика должна показать вклад, иначе причину «слабо» не разобрать."""
    llm = ScriptedLlm(
        [
            _catalog_response(_COURSE_SLIDE, _DIAGRAM_SLIDE),
            _COURSE_VERDICT,
            _semantic(2, 1, [3], _DIAGRAM_QUOTE, "weak"),
        ]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_SRT
    )
    diagram = result.assignments[1]
    if diagram.match_status in {"unbound", "discussed"}:
        assert diagram.visual_contribution is not None


@pytest.mark.asyncio
async def test_описание_без_слов_в_речи_не_привязывает_слайд_к_случайному_разделу(tmp_path):
    """Описание не про лекцию: слайд не должен стать discussed только из-за описания."""
    slide = {"slide_num": 2, "visual_summary": "Фотография горного озера на закате с лодкой."}
    llm = ScriptedLlm(
        [_catalog_response(_COURSE_SLIDE, slide), _COURSE_VERDICT, _semantic(2, 1, [3], "", "none")]
    )
    service = DocumentAlignmentService(llm=llm, models=["m"], prompts_dir=_prompts(tmp_path))
    result = await service.align(
        assets=_assets(tmp_path, 2), section_layout=_LAYOUT, srt_content=_SRT
    )
    assert result.assignments[1].match_status != "discussed"
    assert _srt  # импорт используется
