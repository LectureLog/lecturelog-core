"""Краевые случаи справочника написаний по слайдам раздела ±1 (тикет 08).

Справочник раздела — имена собственные со слайдов, у назначения которых задан
этот раздел, и со страниц колоды с номером ±1 от них. Тесты проверяют границы
колоды, дыры каталога, отказы выравнивания, детерминизм и место блока в промпте.
"""

import json
from pathlib import Path

import pytest

from lecturelog.domain.slides import (
    SlideAsset,
    SlideAssignment,
    SlideCatalogEntry,
    StructurizeContext,
)
from lecturelog.infrastructure.slides.alignment.service import AlignmentResult
from lecturelog.infrastructure.structurize.gemini_structurizer import (
    GeminiStructurizer,
    _section_spelling_slides,
    _slide_context_block,
)

_HEADING = "Написания имён и терминов из презентации"
_REAL_PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


class _ScriptedLlm:
    """Отдаёт ответы по очереди и запоминает промпты."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    async def call(
        self, prompt, models, images=None, *, on_usage=None, response_json=False, effort=None
    ):
        self.prompts.append(prompt)
        return self._responses[len(self.prompts) - 1]


def _entry(num, *nouns, role="content"):
    return SlideCatalogEntry(num, role, f"title{num}", f"text{num}", proper_nouns=tuple(nouns))


def _catalog(nouns_by_page):
    return {num: _entry(num, *nouns) for num, nouns in nouns_by_page.items()}


def _bound(slide_num, section_id):
    return SlideAssignment(slide_num, "discussed", section_id, (1,), 1.0, "probable", 1.0, "t")


def _free(slide_num, status="unmentioned"):
    return SlideAssignment(slide_num, status, None, (), None, "unresolved", 0.0, "t")


def _assets(tmp_path, count):
    assets = []
    for num in range(1, count + 1):
        path = tmp_path / f"slide{num}.png"
        path.write_bytes(f"slide{num}".encode())
        assets.append(
            SlideAsset(num, path, "document", extracted_text=f"p{num}", native_text_quality="good")
        )
    return assets


def _prompts_dir(tmp_path, *, real_section_prompt=False):
    d = tmp_path / "prompts"
    d.mkdir(exist_ok=True)
    for name in (
        "split_topics_v1.md",
        "split_v1.md",
        "slide_match_topics_v1.md",
        "slide_match_v1.md",
        "section_v1.md",
    ):
        (d / name).write_text("prompt {title} {start} {end}", encoding="utf-8")
    if real_section_prompt:
        (d / "section_v1.md").write_text(
            (_REAL_PROMPTS / "section_v1.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
    return d


async def _render_prompts(
    tmp_path,
    monkeypatch,
    topics,
    assets,
    *,
    align_result=None,
    align_error=None,
    mode="v2",
    real_section_prompt=False,
):
    """Прогоняет structurize с подменённым выравниванием.

    topics — список тем, каждая — список названий разделов (по 10 секунд).
    Возвращает промпты рендера по названию раздела и итоговый StructurizeResult.
    """
    total = sum(len(sections) for sections in topics)
    srt = tmp_path / "t.srt"
    srt.write_text(
        "".join(
            f"{i + 1}\n00:00:{i * 10:02d},000 --> 00:00:{i * 10 + 10:02d},000\nреплика {i}\n\n"
            for i in range(total)
        ),
        encoding="utf-8",
    )
    topics_json = []
    subsplits = []
    renders = []
    offset = 0
    titles = []
    for t_index, sections in enumerate(topics):
        start = offset
        section_list = []
        for title in sections:
            section_list.append(
                {"title": title, "start": f"0:{offset:02d}", "end": f"0:{offset + 10:02d}"}
            )
            renders.append(f"Текст {title}.")
            titles.append(title)
            offset += 10
        topics_json.append(
            {"title": f"Тема{t_index}", "start": f"0:{start:02d}", "end": f"0:{offset:02d}"}
        )
        subsplits.append(json.dumps(section_list, ensure_ascii=False))
    responses = [json.dumps(topics_json, ensure_ascii=False), *subsplits]
    if mode != "v2":
        # legacy-матч: грубый по темам; точный при пустом грубом не вызывается,
        # лишние ответы безвредны — рендеры ищутся по названию раздела.
        responses += ["{}"] + ["{}"] * len(topics)
    llm = _ScriptedLlm([*responses, *renders])
    structurizer = GeminiStructurizer(
        gemini_client=llm,
        split_models=["m"],
        subsplit_models=["m"],
        render_models=["m"],
        concurrency_subsplit=1,
        concurrency_render=1,
        prompts_dir=_prompts_dir(tmp_path, real_section_prompt=real_section_prompt),
        effort_split="low",
        effort_subsplit="low",
        effort_render="low",
    )
    structurizer._document_alignment_mode = mode

    async def align(**_kwargs):
        if align_error is not None:
            raise align_error
        return align_result

    monkeypatch.setattr(structurizer._document_alignment, "align", align)
    result = await structurizer.structurize(
        srt_path=srt,
        slide_assets=assets,
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )
    prompts = {}
    for prompt in llm.prompts:
        for title in titles:
            if f'"{title}"' in prompt or prompt.startswith(f"prompt {title} "):
                prompts[title] = prompt
    assert set(prompts) == set(titles)
    return prompts, result


# ── Границы колоды ──────────────────────────────────────────────────────────


def test_первая_страница_колоды_берёт_только_себя_и_вторую_потому_что_страницы_0_нет():
    catalog = _catalog({1: ("Alice",), 2: ("Bob",), 3: ("Wally",)})

    assert _section_spelling_slides((_bound(1, 0),), catalog) == {0: [1, 2]}


def test_последняя_страница_берёт_себя_и_предыдущую_потому_что_страницы_N_плюс_1_нет():
    catalog = _catalog({1: ("Alice",), 2: ("Bob",), 3: ("Wally",)})

    assert _section_spelling_slides((_bound(3, 0),), catalog) == {0: [2, 3]}


def test_колода_из_одной_страницы_даёт_справочник_из_неё_самой_без_выхода_за_границы():
    catalog = _catalog({1: ("ENIAC",)})

    assert _section_spelling_slides((_bound(1, 0),), catalog) == {0: [1]}


def test_сосед_без_записи_в_каталоге_пропускается_а_не_роняет_рендер_на_KeyError():
    # Страница 2 unresolved: ни LLM, ни нативного текста — записи в каталоге нет.
    catalog = _catalog({1: ("Alice",), 3: ("Wally",), 4: ("Charlie",)})

    assert _section_spelling_slides((_bound(3, 0),), catalog) == {0: [3, 4]}


def test_привязанный_слайд_без_записи_в_каталоге_оставляет_разделу_только_соседей():
    catalog = _catalog({1: ("Alice",), 3: ("Wally",)})

    assert _section_spelling_slides((_bound(2, 0),), catalog) == {0: [1, 3]}


def test_страница_за_пределами_каталога_даёт_разделу_пустой_список_а_не_чужие_страницы():
    catalog = _catalog({1: ("Alice",), 2: ("Bob",)})

    assert _section_spelling_slides((_bound(99, 0),), catalog) == {0: []}


# ── Статусы без раздела ─────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["unmentioned", "duplicate", "deck_mismatch"])
def test_назначение_без_раздела_не_даёт_справочника_ни_одному_разделу(status):
    catalog = _catalog({1: ("Alice",), 2: ("Bob",), 3: ("Wally",)})

    assert _section_spelling_slides((_free(2, status),), catalog) == {}


def test_пустое_выравнивание_не_возвращает_справочник_со_всей_колоды():
    catalog = _catalog({1: ("Alice",), 2: ("Bob",)})

    assert _section_spelling_slides((), catalog) == {}


# ── Пересечения разделов и повторы ──────────────────────────────────────────


def test_общий_сосед_двух_разделов_попадает_в_справочник_обоих():
    catalog = _catalog({n: (f"N{n}",) for n in range(1, 6)})

    result = _section_spelling_slides((_bound(2, 0), _bound(4, 1)), catalog)

    assert result == {0: [1, 2, 3], 1: [3, 4, 5]}


def test_страница_повторно_назначенная_в_два_раздела_попадает_в_справочник_каждого():
    catalog = _catalog({n: (f"N{n}",) for n in range(1, 6)})

    result = _section_spelling_slides((_bound(3, 0), _bound(3, 2)), catalog)

    assert result == {0: [2, 3, 4], 2: [2, 3, 4]}


def test_соседние_привязанные_слайды_одного_раздела_не_дублируют_страницы():
    catalog = _catalog({n: (f"N{n}",) for n in range(1, 6)})

    result = _section_spelling_slides((_bound(2, 0), _bound(3, 0)), catalog)

    assert result == {0: [1, 2, 3, 4]}


# ── Детерминизм ─────────────────────────────────────────────────────────────


def test_порядок_назначений_не_меняет_справочник_иначе_перезапуск_даёт_другой_промпт():
    catalog = _catalog({n: (f"N{n}",) for n in range(1, 8)})
    forward = (_bound(2, 0), _bound(6, 0), _bound(4, 1))

    first = _section_spelling_slides(forward, catalog)
    second = _section_spelling_slides(tuple(reversed(forward)), catalog)

    assert first == second
    assert all(pages == sorted(pages) for pages in first.values())
    block_a = _slide_context_block([catalog[n] for n in first[0]])
    block_b = _slide_context_block([catalog[n] for n in second[0]])
    assert block_a == block_b


def test_дубль_имени_у_привязанного_слайда_и_соседа_выводится_один_раз_в_порядке_страниц():
    entries = [_entry(1, "Kotlin", "ENIAC"), _entry(2, "ENIAC", "Alice"), _entry(3, " Kotlin ")]

    block = _slide_context_block(entries)

    assert block.count("ENIAC") == 1
    assert block.count("Kotlin") == 1
    assert block.rstrip().endswith("Kotlin, ENIAC, Alice")


def test_пустые_и_пробельные_имена_не_дают_блок_с_пустым_списком():
    assert _slide_context_block([_entry(1, "", "   "), _entry(2)]) == ""


# ── Сквозной рендер ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_раздел_во_второй_теме_получает_свой_справочник_по_плоской_нумерации(
    tmp_path, monkeypatch
):
    """global_section_id выравнивания — плоский номер по всем темам; сдвиг на тему
    отдал бы справочник соседнему разделу, и это не упало бы."""
    assets = _assets(tmp_path, 7)
    catalog = _catalog(
        {
            1: ("Alice",),
            2: ("Bob",),
            3: ("Wally",),
            4: ("Ч",),
            5: ("ЯДРО",),
            6: ("Kotlin",),
            7: ("JetBrains",),
        }
    )
    assignments = (_bound(1, 0), *(_free(n) for n in (2, 3, 4, 5)), _bound(7, 2))

    prompts, _ = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["А1", "А2"], ["Б1", "Б2"]],
        assets,
        align_result=AlignmentResult(assignments, catalog),
    )

    assert "JetBrains" in prompts["Б1"] and "Kotlin" in prompts["Б1"]
    assert "JetBrains" not in prompts["А2"] and "JetBrains" not in prompts["Б2"]
    assert _HEADING not in prompts["Б2"] and _HEADING not in prompts["А2"]
    assert "Alice" in prompts["А1"] and "Alice" not in prompts["Б1"]


@pytest.mark.asyncio
async def test_раздел_за_пределами_числа_разделов_не_роняет_рендер_и_не_утекает_в_другие(
    tmp_path, monkeypatch
):
    assets = _assets(tmp_path, 3)
    catalog = _catalog({1: ("Alice",), 2: ("Bob",), 3: ("Wally",)})
    assignments = (_free(1), _bound(2, 7), _free(3))

    prompts, result = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1", "Р2"]],
        assets,
        align_result=AlignmentResult(assignments, catalog),
    )

    assert all(_HEADING not in prompt for prompt in prompts.values())
    assert [p.output_kind for p in result.slide_placements if p.slide_num == 2] == ["appendix"]


@pytest.mark.asyncio
async def test_чужая_колода_с_пустым_каталогом_не_даёт_справочника_ни_одному_разделу(
    tmp_path, monkeypatch
):
    assets = _assets(tmp_path, 3)
    assignments = tuple(_free(n, "deck_mismatch") for n in (1, 2, 3))

    prompts, _ = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1", "Р2"]],
        assets,
        align_result=AlignmentResult(assignments, {}),
    )

    assert all(_HEADING not in prompt for prompt in prompts.values())


@pytest.mark.asyncio
async def test_пустые_назначения_при_полном_каталоге_не_возвращают_справочник_всей_колоды(
    tmp_path, monkeypatch
):
    """Регрессия к старому поведению (вся колода в каждый раздел) прошла бы тихо."""
    assets = _assets(tmp_path, 2)
    catalog = _catalog({1: ("Alice",), 2: ("Bob",)})

    prompts, _ = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1", "Р2"]],
        assets,
        align_result=AlignmentResult((), catalog),
    )

    assert all("Alice" not in prompt and "Bob" not in prompt for prompt in prompts.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["v2", "shadow"])
async def test_падение_выравнивания_не_роняет_рендер_и_не_даёт_справочника(
    tmp_path, monkeypatch, mode
):
    assets = _assets(tmp_path, 2)

    prompts, result = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1", "Р2"]],
        assets,
        align_error=RuntimeError("boom"),
        mode=mode,
    )

    assert all(_HEADING not in prompt for prompt in prompts.values())
    assert [s.title for t in result for s in t.sections] == ["Р1", "Р2"]


@pytest.mark.asyncio
async def test_привязанный_раздел_без_имён_на_страницах_не_получает_пустой_заголовок(
    tmp_path, monkeypatch
):
    assets = _assets(tmp_path, 3)
    catalog = {n: _entry(n) for n in (1, 2, 3)}

    prompts, _ = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1"]],
        assets,
        align_result=AlignmentResult((_bound(2, 0), _free(1), _free(3)), catalog),
    )

    assert _HEADING not in prompts["Р1"]


@pytest.mark.asyncio
async def test_порядок_имён_в_промпте_по_страницам_а_не_по_порядку_назначений(
    tmp_path, monkeypatch
):
    assets = _assets(tmp_path, 5)
    catalog = _catalog({1: ("Alice",), 2: ("Bob",), 3: ("Wally",), 4: ("Charlie",), 5: ("ЯДРО",)})
    assignments = (_bound(4, 0), _free(1), _bound(2, 0), _free(3), _free(5))

    prompts, _ = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1"]],
        assets,
        align_result=AlignmentResult(assignments, catalog),
    )

    assert "Alice, Bob, Wally, Charlie, ЯДРО" in prompts["Р1"]


@pytest.mark.asyncio
async def test_слайд_размещённый_в_разделе_всегда_есть_в_справочнике_этого_раздела(
    tmp_path, monkeypatch
):
    """Стык рендер ↔ размещение: если раздел показывает слайд, а написаний с него
    в справочнике нет, исправить искажённое имя рядом с картинкой нечем."""
    assets = _assets(tmp_path, 6)
    catalog = _catalog({n: (f"Name{n}",) for n in range(1, 7)})
    assignments = (_bound(1, 0), _free(2), _free(3), _bound(4, 1), _free(5), _bound(6, 1))

    prompts, result = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1", "Р2"]],
        assets,
        align_result=AlignmentResult(assignments, catalog),
    )

    titles = ["Р1", "Р2"]
    for placement in result.slide_placements:
        if placement.output_kind in {"inline", "section_gallery"}:
            title = titles[placement.global_section_id]
            assert f"Name{placement.slide_num}" in prompts[title]


# ── Реальный шаблон промпта ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_реальный_шаблон_с_фигурными_скобками_в_имени_не_ломает_рендер_и_несёт_правило(
    tmp_path, monkeypatch
):
    assets = _assets(tmp_path, 1)
    catalog = _catalog({1: ("{title}", "ENIAC")})

    prompts, _ = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1"]],
        assets,
        align_result=AlignmentResult((_bound(1, 0),), catalog),
        real_section_prompt=True,
    )

    prompt = prompts["Р1"]
    assert "{title}" in prompt and "ENIAC" in prompt
    assert "только при фонетическом сходстве" in prompt


@pytest.mark.asyncio
async def test_справочник_не_под_заголовком_транскрипта_иначе_имена_читаются_как_речь(
    tmp_path, monkeypatch
):
    """Шаблон заканчивается заголовком «Фрагмент транскрипта (SRT):». Всё, что идёт
    между ним и самим SRT, модель читает как сказанное лектором, а промпт велит
    сохранять всю речь — имена со слайдов уходят в конспект как факты речи, ровно
    то, против чего вводился справочник по разделу. При любом месте блока (до
    заголовка или после SRT) между заголовком и фрагментом имён быть не должно."""
    assets = _assets(tmp_path, 1)
    catalog = _catalog({1: ("JetBrains",)})

    prompts, _ = await _render_prompts(
        tmp_path,
        monkeypatch,
        [["Р1"]],
        assets,
        align_result=AlignmentResult((_bound(1, 0),), catalog),
        real_section_prompt=True,
    )

    prompt = prompts["Р1"]
    after_heading = prompt.split("## Фрагмент транскрипта (SRT):", 1)[1]
    before_fragment = after_heading.split("00:00:00,000 -->", 1)[0]
    assert "JetBrains" not in before_fragment
    assert _HEADING not in before_fragment


# ── Стык с настоящим сервисом выравнивания (без LLM, нативный текст) ─────────


@pytest.mark.asyncio
async def test_настоящее_выравнивание_не_отдаёт_имена_привязанного_слайда_разделу_без_слайдов(
    tmp_path,
):
    """Сквозной путь: номер раздела из сервиса выравнивания совпадает с номером
    рендера. Расхождение нумерации отдало бы справочник соседнему разделу молча."""
    srt = tmp_path / "t.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\nРазберём бинарное дерево поиска и его вершины.\n\n"
        "2\n00:00:10,000 --> 00:00:20,000\nТеперь поговорим о погоде и расписании занятий.\n\n"
        "3\n00:00:20,000 --> 00:00:30,000\nКомпилятор Fortran написала команда Бэкуса в IBM.\n",
        encoding="utf-8",
    )
    texts = [
        "Бинарное дерево поиска. Вершины. AVL",
        "Хеш-таблицы Knuth",
        "Графы Dijkstra",
        "Компилятор Fortran. Команда Бэкуса. IBM",
    ]
    assets = []
    for num, text in enumerate(texts, start=1):
        path = tmp_path / f"s{num}.png"
        path.write_bytes(f"s{num}".encode())
        assets.append(
            SlideAsset(num, path, "document", extracted_text=text, native_text_quality="good")
        )
    sections = [
        {"title": "Деревья", "start": "0:00", "end": "0:10"},
        {"title": "Орг", "start": "0:10", "end": "0:20"},
        {"title": "Фортран", "start": "0:20", "end": "0:30"},
    ]
    topics = [{"title": "Тема", "start": "0:00", "end": "0:30"}]
    llm = _ScriptedLlm(
        [json.dumps(topics), json.dumps(sections, ensure_ascii=False), "a", "b", "c"]
    )
    structurizer = GeminiStructurizer(
        gemini_client=llm,
        split_models=["m"],
        subsplit_models=["m"],
        render_models=["m"],
        concurrency_subsplit=1,
        concurrency_render=1,
        prompts_dir=_prompts_dir(tmp_path),
        effort_split="low",
        effort_subsplit="low",
        effort_render="low",
    )
    structurizer._document_alignment_mode = "v2"

    result = await structurizer.structurize(
        srt_path=srt,
        slide_assets=assets,
        context=StructurizeContext("audio"),
        output_dir=tmp_path / "out",
    )

    bound = {a.slide_num: a.global_section_id for a in result.slide_assignments}
    prompts = {
        title: next(p for p in llm.prompts if p.startswith(f"prompt {title} "))
        for title in ("Деревья", "Орг", "Фортран")
    }
    # Предусловие сценария: слайды 1 и 4 привязались к своим разделам.
    assert bound[1] == 0 and bound[4] == 2, bound
    assert _HEADING not in prompts["Орг"]
    assert "Fortran" in prompts["Фортран"] and "Dijkstra" in prompts["Фортран"]
    assert "Fortran" not in prompts["Деревья"] and "Dijkstra" not in prompts["Деревья"]
    assert "Knuth" in prompts["Деревья"]
