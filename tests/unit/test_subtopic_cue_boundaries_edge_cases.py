# ruff: noqa: E501
"""Краевые случаи нарезки подтем по границе реплики (slide-matcher-fixes/02).

Главный инвариант тикета: каждая реплика транскрипта попадает в конспект
ровно в одну подтему, границы монотонны, пустых подтем нет. Ниже — проверки
этого инварианта на нестандартных транскриптах и на стыках со слайдами
(legacy и v2), кадрами видео и нарезкой медиа.
"""

import json

import pytest

from lecturelog.domain.ports import SlideImage
from lecturelog.domain.slides import SlideAsset, SlideAssignment, StructurizeContext
from lecturelog.infrastructure.frames.binding import bind_frames_to_sections
from lecturelog.infrastructure.slides.alignment.service import (
    AlignmentResult,
    DocumentAlignmentService,
)
from lecturelog.infrastructure.srt import (
    extract_srt_cue_range,
    parse_srt_blocks,
    parse_srt_time,
    snap_sections_to_cues,
)
from lecturelog.infrastructure.structurize.gemini_structurizer import GeminiStructurizer

# ── helpers ──────────────────────────────────────────────────────────────


def _stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(*cues):
    """cues: (начало, конец, текст) в секундах, в порядке записи в файл."""
    return "\n\n".join(
        f"{i}\n{_stamp(a)} --> {_stamp(b)}\n{text}" for i, (a, b, text) in enumerate(cues, start=1)
    )


def _sec(title, start, end):
    return {"title": title, "start": _stamp(start), "end": _stamp(end)}


def _texts_in_range(srt, rng):
    fragment = extract_srt_cue_range(srt, *rng)
    return [block.text for block in parse_srt_blocks(fragment)]


class ScriptedGemini:
    def __init__(self, responses):
        self._responses = list(responses)
        self.recorded_calls = []

    async def call(
        self, prompt, models, images=None, *, on_usage=None, response_json=False, effort=None
    ):
        self.recorded_calls.append({"prompt": prompt, "images": images})
        return self._responses[len(self.recorded_calls) - 1]


def _make(gemini, prompts_dir):
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
        # Маркер отделяет шаблон от фрагмента транскрипта в записанном промпте.
        (d / name).write_text("PROMPT {title} {start} {end}", encoding="utf-8")
    return d


def _cue_count(prompts, text):
    return sum(text in prompt for prompt in prompts)


# ── extract_srt_cue_range ───────────────────────────────────────────────


def test_диапазон_реплик_включает_оба_края_чтобы_крайние_реплики_подтемы_не_выпадали():
    srt = _srt((0, 1, "р1"), (1, 2, "р2"), (2, 3, "р3"), (3, 4, "р4"))
    assert _texts_in_range(srt, (2, 3)) == ["р2", "р3"]


def test_соседние_диапазоны_на_стыке_реплик_не_делят_реплику_в_отличие_от_фрагмента_по_таймкодам():
    srt = _srt((0, 60, "первая"), (60, 120, "вторая"), (120, 180, "третья"))
    left, right = _texts_in_range(srt, (1, 2)), _texts_in_range(srt, (3, 3))
    assert set(left).isdisjoint(right)


def test_диапазон_вне_транскрипта_и_перевёрнутый_диапазон_дают_пусто_а_не_чужие_реплики():
    srt = _srt((0, 1, "р1"), (1, 2, "р2"))
    assert extract_srt_cue_range(srt, 5, 9) == ""
    assert extract_srt_cue_range(srt, 2, 1) == ""


def test_нумерация_диапазона_совпадает_с_parse_srt_blocks_даже_если_есть_пустые_блоки_и_чужие_номера():
    """Если бы диапазон считал по номерам из файла, а сдвиг — по parse_srt_blocks,
    подтема получила бы соседнюю реплику вместо своей."""
    srt = (
        "17\n00:00:00,000 --> 00:00:01,000\nр1\n\n"
        "18\n00:00:01,000 --> 00:00:02,000\n\n\n"  # блок без текста отбрасывается
        "42\n00:00:02,000 --> 00:00:03,000\nр2\n\n"
        "43\n00:00:03,000 --> 00:00:04,000\nр3"
    )
    assert _texts_in_range(srt, (2, 2)) == ["р2"]


def test_диапазон_сохраняет_эмодзи_rtl_и_crlf_чтобы_рендер_получил_реплику_дословно():
    srt = "1\r\n00:00:00,000 --> 00:00:01,000\r\nשלום 🙂 мир\r\n\r\n2\r\n00:00:01,000 --> 00:00:02,000\r\nдва"
    assert _texts_in_range(srt, (1, 1)) == ["שלום 🙂 мир"]


# ── snap_sections_to_cues: данные ──────────────────────────────────────


def test_пустой_транскрипт_не_трогает_подтемы_и_возвращает_None_чтобы_работало_старое_поведение():
    layout = [[_sec("А", 0, 60), _sec("Б", 60, 120)]]
    before = json.dumps(layout)
    assert snap_sections_to_cues(layout, "") is None
    assert json.dumps(layout) == before


def test_без_подтем_сдвиг_возвращает_None_и_не_падает_на_пустом_списке():
    assert snap_sections_to_cues([], _srt((0, 1, "р"))) is None
    assert snap_sections_to_cues([[], []], _srt((0, 1, "р"))) is None


def test_одна_реплика_на_несколько_подтем_оставляет_одну_подтему_чтобы_реплика_не_рендерилась_трижды():
    srt = _srt((0, 60, "единственная"))
    layout = [[_sec("А", 0, 20), _sec("Б", 20, 40), _sec("В", 40, 60)]]
    ranges = snap_sections_to_cues(layout, srt)
    assert ranges == [(1, 1)]
    assert sum(len(s) for s in layout) == 1


def test_граница_ровно_посередине_реплики_оставляет_её_в_предыдущей_подтеме_по_правилу_вправо():
    srt = _srt((0, 10, "до"), (10, 20, "середина"), (20, 30, "после"))
    layout = [[_sec("А", 0, 15), _sec("Б", 15, 30)]]
    ranges = snap_sections_to_cues(layout, srt)
    assert _texts_in_range(srt, ranges[0]) == ["до", "середина"]
    assert _texts_in_range(srt, ranges[1]) == ["после"]


def test_граница_чуть_левее_середины_отдаёт_реплику_следующей_подтеме_к_ближайшему_краю():
    srt = _srt((0, 10, "до"), (10, 20, "середина"), (20, 30, "после"))
    layout = [[_sec("А", 0, 14.999), _sec("Б", 14.999, 30)]]
    ranges = snap_sections_to_cues(layout, srt)
    assert _texts_in_range(srt, ranges[1]) == ["середина", "после"]


def test_граница_в_паузе_между_репликами_отдаёт_следующую_реплику_следующей_подтеме():
    srt = _srt((0, 10, "до паузы"), (30, 40, "после паузы"))
    layout = [[_sec("А", 0, 20), _sec("Б", 20, 40)]]
    ranges = snap_sections_to_cues(layout, srt)
    assert _texts_in_range(srt, ranges[0]) == ["до паузы"]
    assert _texts_in_range(srt, ranges[1]) == ["после паузы"]


def test_реплики_с_одинаковым_началом_попадают_ровно_в_одну_подтему_каждая():
    srt = _srt((0, 10, "р1"), (10, 10, "нулевая"), (10, 20, "р2"), (20, 30, "р3"))
    layout = [[_sec("А", 0, 10), _sec("Б", 10, 30)]]
    ranges = snap_sections_to_cues(layout, srt)
    all_texts = [t for rng in ranges for t in _texts_in_range(srt, rng)]
    assert sorted(all_texts) == sorted(["р1", "нулевая", "р2", "р3"])


def test_подтема_из_одной_нулевой_реплики_получает_конец_строго_позже_начала_иначе_выравнивание_отбросит_колоду():
    srt = _srt((0, 10, "р1"), (10, 10, "нулевая"), (10.5, 20, "р2"))
    layout = [[_sec("А", 0, 10), _sec("Б", 10, 10.4), _sec("В", 10.4, 20)]]
    snap_sections_to_cues(layout, srt)
    for section in layout[0]:
        assert parse_srt_time(section["end"]) > parse_srt_time(section["start"])
    # шкала принимается v2-выравниванием (end <= start там фатально)
    DocumentAlignmentService._section_refs(layout, parse_srt_blocks(srt))


def test_подтема_начинающаяся_за_концом_транскрипта_удаляется_а_не_рендерится_по_пустому_фрагменту():
    srt = _srt((0, 60, "р1"), (60, 120, "р2"))
    layout = [[_sec("А", 0, 120), _sec("Галлюцинация", 500, 600)]]
    ranges = snap_sections_to_cues(layout, srt)
    assert [s["title"] for s in layout[0]] == ["А"]
    assert _texts_in_range(srt, ranges[0]) == ["р1", "р2"]


def test_все_подтемы_до_первой_реплики_возвращают_None_и_не_портят_таймкоды():
    srt = _srt((100, 110, "поздняя"))
    layout = [[_sec("А", 0, 10), _sec("Б", 10, 20)]]
    before = json.dumps(layout)
    assert snap_sections_to_cues(layout, srt) is None
    assert json.dumps(layout) == before


def test_диапазоны_идут_подряд_без_дыр_и_пересечений_чтобы_ни_одна_реплика_не_потерялась_и_не_задвоилась():
    cues = [(i * 7.3, i * 7.3 + 7.3, f"р{i:03d}") for i in range(60)]
    srt = _srt(*cues)
    layout = [
        [_sec("А", 0, 100.1), _sec("Б", 100.1, 200.7)],
        [_sec("В", 200.7, 301.2), _sec("Г", 301.2, 438)],
    ]
    ranges = snap_sections_to_cues(layout, srt)
    assert ranges[0][0] == 1
    for (_, last), (first, _) in zip(ranges, ranges[1:], strict=False):
        assert first == last + 1
    assert ranges[-1][1] == len(cues)


def test_таймкоды_подтем_после_сдвига_совпадают_с_краями_их_реплик_с_миллисекундами():
    srt = _srt((0.04, 10.5, "р1"), (10.5, 21.25, "р2"), (21.25, 30.672, "р3"))
    layout = [[_sec("А", 0, 12), _sec("Б", 12, 30.672)]]
    snap_sections_to_cues(layout, srt)
    assert [(s["start"], s["end"]) for s in layout[0]] == [
        ("00:00:00,040", "00:00:10,500"),
        ("00:00:10,500", "00:00:30,672"),
    ]


def test_граница_в_формате_мм_сс_и_с_точкой_разбирается_так_же_как_полный_таймкод():
    srt = _srt((0, 60, "р1"), (60, 120, "р2"), (120, 180, "р3"))
    layout = [
        [
            {"title": "А", "start": "0:00", "end": "1:00"},
            {"title": "Б", "start": "00:01:00.000", "end": "3:00"},
        ]
    ]
    ranges = snap_sections_to_cues(layout, srt)
    assert ranges == [(1, 1), (2, 3)]


def test_удаляется_именно_схлопнувшаяся_подтема_даже_если_у_другой_темы_есть_побайтно_такая_же():
    """Удаление идёт по объекту: при сравнении по значению пропала бы и живая
    подтема соседней темы с тем же JSON."""
    srt = _srt((0, 60, "р1"), (60, 120, "р2"), (120, 180, "р3"))
    twin = {"title": "Повтор", "start": _stamp(60), "end": _stamp(120)}
    layout = [[_sec("А", 0, 60), dict(twin)], [dict(twin), _sec("В", 120, 180)]]
    ranges = snap_sections_to_cues(layout, srt)
    assert [s["title"] for s in layout[0]] == ["А"]
    assert [s["title"] for s in layout[1]] == ["Повтор", "В"]
    assert len(ranges) == 3


# ── snap_sections_to_cues: нестандартный порядок и перекрытия ──────────


def test_неупорядоченный_srt_не_даёт_одной_реплике_попасть_в_две_подтемы():
    """Сдвиг сортирует реплики по времени, а диапазон режет по номерам в
    порядке файла: при неупорядоченном SRT номера в отсортированном срезе не
    подряд, и диапазон (первый..последний) захватывает чужие реплики."""
    srt = _srt((60, 120, "вторая"), (0, 60, "первая"), (120, 180, "третья"))
    layout = [[_sec("А", 0, 60), _sec("Б", 60, 180)]]
    ranges = snap_sections_to_cues(layout, srt)
    fragments = [_texts_in_range(srt, rng) for rng in ranges]
    for text in ("первая", "вторая", "третья"):
        assert sum(text in frag for frag in fragments) == 1, (text, fragments)


def test_вложенная_длинная_реплика_не_делает_шкалу_подтем_неприемлемой_для_v2_выравнивания():
    """Конец подтемы = максимум концов её реплик. Если в предыдущей подтеме есть
    реплика, накрывающая следующую, у следующей конец раньше конца предыдущей,
    и _section_refs роняет выравнивание всей колоды (все слайды в приложение).
    До сдвига та же разметка модели проходила."""
    srt = _srt((0, 100, "длинная"), (10, 20, "вложенная"), (100, 200, "дальше"))
    layout = [[_sec("А", 0, 12), _sec("Б", 12, 100), _sec("В", 100, 200)]]
    blocks = parse_srt_blocks(srt)
    DocumentAlignmentService._section_refs(json.loads(json.dumps(layout)), blocks)  # до сдвига ок
    snap_sections_to_cues(layout, srt)
    DocumentAlignmentService._section_refs(layout, blocks)


def test_неупорядоченные_подтемы_модели_не_теряют_реплики_покрытые_их_интервалами():
    """Модель вернула подтемы не по порядку времени. Монотонизация начал
    схлопывает подтемы, а стоп берётся из конца последней по списку — и
    реплика, лежащая внутри интервала одной из подтем, не попадает никуда."""
    srt = _srt((0, 60, "а"), (60, 120, "б"), (120, 180, "в"))
    layout = [[_sec("А", 0, 60), _sec("В", 120, 180), _sec("Б", 60, 120)]]
    ranges = snap_sections_to_cues(layout, srt) or []
    fragments = [_texts_in_range(srt, rng) for rng in ranges]
    for text in ("а", "б", "в"):
        assert sum(text in frag for frag in fragments) == 1, (text, fragments)


# ── structurize: стыки рендера, тем, слайдов и кадров ───────────────────


async def _structurize(tmp_path, prompts_dir, srt_text, topics, subsplits, tail, **kw):
    srt = tmp_path / "t.srt"
    srt.write_text(srt_text, encoding="utf-8")
    gemini = ScriptedGemini([json.dumps(topics), *map(json.dumps, subsplits), *tail])
    structurizer = _make(gemini, prompts_dir)
    mode = kw.pop("mode", None)
    if mode:
        structurizer._document_alignment_mode = mode
    align = kw.pop("align", None)
    if align:
        structurizer._document_alignment.align = align
    result = await structurizer.structurize(srt_path=srt, output_dir=tmp_path / "out", **kw)
    return result, gemini


def _render_prompts(gemini):
    return [c["prompt"] for c in gemini.recorded_calls if c["prompt"].startswith("PROMPT ")]


async def test_реплика_на_стыке_двух_тем_рендерится_ровно_в_одной_подтеме(tmp_path, prompts_dir):
    srt = _srt((0, 60, "р1"), (60, 120, "стык"), (120, 180, "р3"), (180, 240, "р4"))
    topics = [
        {"title": "Т1", "start": "00:00:00", "end": "00:01:50"},
        {"title": "Т2", "start": "00:01:50", "end": "00:04:00"},
    ]
    subs = [[_sec("А", 0, 110)], [_sec("Б", 110, 240)]]
    result, gemini = await _structurize(
        tmp_path, prompts_dir, srt, topics, subs, ["a", "b"], slide_images=[]
    )
    prompts = _render_prompts(gemini)[-2:]
    for text in ("р1", "стык", "р3", "р4"):
        assert _cue_count(prompts, text) == 1, text
    assert [t.title for t in result.topics] == ["Т1", "Т2"]


async def test_пропуск_схлопнувшейся_темы_посередине_сохраняет_порядок_и_заголовки_остальных(
    tmp_path, prompts_dir
):
    srt = _srt((0, 120, "р1"), (120, 240, "р2"), (240, 360, "р3"))
    topics = [
        {"title": "Т1", "start": "00:00:00", "end": "00:01:50"},
        {"title": "Т2", "start": "00:01:50", "end": "00:01:55"},
        {"title": "Т3", "start": "00:01:55", "end": "00:06:00"},
    ]
    subs = [[_sec("А", 0, 110)], [_sec("Б", 110, 115)], [_sec("В", 115, 360)]]
    result, gemini = await _structurize(
        tmp_path, prompts_dir, srt, topics, subs, ["рендер-А", "рендер-В"], slide_images=[]
    )
    assert [(t.title, [s.title for s in t.sections]) for t in result.topics] == [
        ("Т1", ["А"]),
        ("Т3", ["В"]),
    ]
    # рендер-ответ достаётся своей подтеме, а не соседней
    assert result.topics[1].sections[0].content == "рендер-В"


async def test_пустой_транскрипт_не_роняет_структуризацию_и_рендерит_все_подтемы(
    tmp_path, prompts_dir
):
    topics = [{"title": "Т", "start": "00:00:00", "end": "00:02:00"}]
    subs = [[_sec("А", 0, 60), _sec("Б", 60, 120)]]
    result, _ = await _structurize(
        tmp_path, prompts_dir, "", topics, subs, ["a", "b"], slide_images=[]
    )
    assert [s.title for s in result.topics[0].sections] == ["А", "Б"]


async def test_начала_подтем_в_результате_монотонны_по_всем_темам_чтобы_кадры_не_прыгали_назад(
    tmp_path, prompts_dir
):
    cues = [(i * 9.5, i * 9.5 + 9.5, f"р{i:02d}") for i in range(30)]
    topics = [
        {"title": "Т1", "start": "00:00:00", "end": "00:02:31"},
        {"title": "Т2", "start": "00:02:31", "end": "00:04:45"},
    ]
    subs = [
        [_sec("А", 0, 73), _sec("Б", 73, 151)],
        [_sec("В", 149, 210), _sec("Г", 210, 285)],
    ]
    result, gemini = await _structurize(
        tmp_path, prompts_dir, _srt(*cues), topics, subs, ["a", "b", "c", "d"], slide_images=[]
    )
    starts = [parse_srt_time(s.start) for t in result.topics for s in t.sections]
    assert starts == sorted(starts)
    prompts = _render_prompts(gemini)[-4:]
    for _, _, text in cues:
        assert _cue_count(prompts, text) <= 1, text


async def test_подтема_из_одной_короткой_реплики_не_получает_нулевую_длительность_для_нарезки_медиа(
    tmp_path, prompts_dir
):
    """Section.start/end нормализуются до ЧЧ:ММ:СС. Сдвиг к краям реплик может
    сжать подтему до реплики короче секунды — тогда start == end, и нарезка
    видео (-t 0.000) / аудио (-ss == -to) даёт пустой клип без ошибки."""
    srt = _srt((0, 10.2, "р1"), (10.2, 10.7, "Так."), (10.7, 18, "длинная"), (18, 40, "р4"))
    topics = [{"title": "Т", "start": "00:00:00", "end": "00:00:40"}]
    subs = [[_sec("А", 0, 10.3), _sec("Б", 10.3, 12), _sec("В", 12, 40)]]
    result, _ = await _structurize(
        tmp_path, prompts_dir, srt, topics, subs, ["a", "b", "c"], slide_images=[]
    )
    for section in result.topics[0].sections:
        assert parse_srt_time(section.end) > parse_srt_time(section.start), section


async def test_legacy_слайды_темы_целиком_схлопнувшейся_при_сдвиге_не_пропадают_из_конспекта(
    tmp_path, prompts_dir
):
    srt = _srt((0, 120, "одна"), (120, 240, "вторая"))
    slides = []
    for i in (1, 2):
        p = tmp_path / f"s{i}.png"
        p.write_bytes(b"x")
        slides.append(p)
    topics = [
        {"title": "Т1", "start": "00:00:00", "end": "00:03:50"},
        {"title": "Т2", "start": "00:03:50", "end": "00:04:00"},
    ]
    subs = [[_sec("А", 0, 230)], [_sec("Б", 230, 235), _sec("В", 235, 240)]]
    tail = [
        json.dumps({"0": [1], "1": [2]}),  # грубый матч тем
        json.dumps({"0": [1]}),  # точный матч Т1
        json.dumps({}),  # точный матч Т2 (подтем не осталось)
        "рендер",
    ]
    result, _ = await _structurize(
        tmp_path, prompts_dir, srt, topics, subs, tail, slide_images=slides
    )
    placed = {n for t in result.topics for s in t.sections for n in s.slide_indices}
    assert placed == {1, 2}


async def test_legacy_индекс_подтемы_из_точного_матча_совпадает_с_подтемой_после_удаления_схлопнувшейся(
    tmp_path, prompts_dir
):
    srt = _srt((0, 60, "первая"), (60, 180, "длинная"), (180, 240, "последняя"))
    slides = []
    for i in (1, 2):
        p = tmp_path / f"s{i}.png"
        p.write_bytes(b"x")
        slides.append(p)
    topics = [{"title": "Т", "start": "00:00:00", "end": "00:04:00"}]
    subs = [[_sec("А", 0, 80), _sec("Б", 80, 100), _sec("В", 100, 240)]]
    tail = [
        json.dumps({"0": [1, 2]}),
        json.dumps({"0": [1], "1": [2]}),  # модель видит подтемы [А, В]
        "ra",
        "rv",
    ]
    result, gemini = await _structurize(
        tmp_path, prompts_dir, srt, topics, subs, tail, slide_images=slides
    )
    fine_prompt = gemini.recorded_calls[3]["prompt"]
    assert '"Б"' not in fine_prompt
    sections = {s.title: s.slide_indices for s in result.topics[0].sections}
    assert sections == {"А": [1], "В": [2]}


def _v2_asset(tmp_path):
    p = tmp_path / "slide.png"
    p.write_bytes(b"x")
    return SlideAsset(1, p, "document", extracted_text="Деревья", native_text_quality="good")


async def test_v2_выравнивание_видит_раскладку_без_схлопнувшихся_подтем_и_слайд_ложится_на_нужную(
    tmp_path, prompts_dir
):
    """global_section_id считается по плоскому порядку раскладки, переданной в
    align; рендер и сборка — по той же раскладке. Рассинхрон положил бы слайд
    в чужую подтему."""
    srt = _srt((0, 60, "первая"), (60, 180, "длинная"), (180, 240, "последняя"))
    topics = [
        {"title": "Т1", "start": "00:00:00", "end": "00:01:40"},
        {"title": "Т2", "start": "00:01:40", "end": "00:04:00"},
    ]
    subs = [[_sec("А", 0, 80), _sec("Б", 80, 100)], [_sec("В", 100, 240)]]
    seen = {}

    async def align(*, assets, section_layout, srt_content, on_usage=None):
        seen["titles"] = [s["title"] for sections in section_layout for s in sections]
        return AlignmentResult(
            (SlideAssignment(1, "discussed", 1, (), None, "verified", 1.0, "ok"),), {}
        )

    result, _ = await _structurize(
        tmp_path,
        prompts_dir,
        srt,
        topics,
        subs,
        ["ra", "rv"],
        mode="v2",
        align=align,
        slide_assets=[_v2_asset(tmp_path)],
        context=StructurizeContext("audio"),
    )
    assert seen["titles"] == ["А", "В"]
    by_title = {s.title: s.slide_indices for t in result.topics for s in t.sections}
    assert by_title == {"А": [], "В": [1]}


async def test_v2_слайд_после_целиком_выпавшей_темы_ложится_на_свою_подтему(tmp_path, prompts_dir):
    srt = _srt((0, 120, "р1"), (120, 240, "р2"), (240, 360, "р3"))
    topics = [
        {"title": "Т1", "start": "00:00:00", "end": "00:01:50"},
        {"title": "Т2", "start": "00:01:50", "end": "00:01:55"},
        {"title": "Т3", "start": "00:01:55", "end": "00:06:00"},
    ]
    subs = [[_sec("А", 0, 110)], [_sec("Б", 110, 115)], [_sec("В", 115, 360)]]

    async def align(*, assets, section_layout, srt_content, on_usage=None):
        return AlignmentResult(
            (SlideAssignment(1, "discussed", 1, (), None, "verified", 1.0, "ok"),), {}
        )

    result, _ = await _structurize(
        tmp_path,
        prompts_dir,
        srt,
        topics,
        subs,
        ["ra", "rv"],
        mode="v2",
        align=align,
        slide_assets=[_v2_asset(tmp_path)],
        context=StructurizeContext("audio"),
    )
    by_title = {s.title: s.slide_indices for t in result.topics for s in t.sections}
    assert by_title == {"А": [], "В": [1]}
    assert result.topics[1].slide_indices == [1]


async def test_v2_реальная_проверка_шкалы_принимает_сдвинутые_подтемы_на_стыках_реплик(
    tmp_path, prompts_dir
):
    """Сдвиг не должен превращать допустимую разметку в такую, которую
    _section_refs отвергает: иначе все слайды молча уходят в приложение."""
    cues = [(i * 6.4, i * 6.4 + 6.4, f"р{i:02d}") for i in range(40)]
    srt = _srt(*cues)
    layout = [[_sec("А", 0, 61), _sec("Б", 61, 130)], [_sec("В", 128, 200), _sec("Г", 200, 256)]]
    snap_sections_to_cues(layout, srt)
    refs = DocumentAlignmentService._section_refs(layout, parse_srt_blocks(srt))
    assert len(refs) == 4


async def test_кадр_из_интервала_удалённой_подтемы_привязывается_к_подтеме_с_той_же_репликой(
    tmp_path, prompts_dir
):
    """Видео: кадры вяжутся по Section.start. Кадр, снятый внутри удалённой
    подтемы, должен оказаться рядом с текстом того же момента лекции."""
    srt = _srt((0, 60, "первая"), (60, 180, "длинная"), (180, 240, "последняя"))
    topics = [{"title": "Т", "start": "00:00:00", "end": "00:04:00"}]
    subs = [[_sec("А", 0, 80), _sec("Б", 80, 100), _sec("В", 100, 240)]]
    result, gemini = await _structurize(
        tmp_path, prompts_dir, srt, topics, subs, ["ra", "rv"], slide_images=[]
    )
    bind_frames_to_sections([SlideImage(path=tmp_path / "f.png", timestamp=90.0)], result.topics)
    prompts = dict(
        zip([s.title for s in result.topics[0].sections], _render_prompts(gemini)[-2:], strict=True)
    )
    holder = [s for s in result.topics[0].sections if s.slide_indices == [1]]
    assert len(holder) == 1
    assert "длинная" in prompts[holder[0].title]


async def test_фолбэк_сабсплита_одной_темы_не_задваивает_реплики_на_стыке_с_соседней(
    tmp_path, prompts_dir
):
    """Сабсплит упал — подтема = вся тема по таймкодам темы. Такая подтема
    тоже должна резаться по репликам, иначе стык с соседней темой задвоится."""
    srt = _srt((0, 60, "р1"), (60, 120, "стык"), (120, 180, "р3"))
    topics = [
        {"title": "Т1", "start": "00:00:00", "end": "00:01:30"},
        {"title": "Т2", "start": "00:01:30", "end": "00:03:00"},
    ]
    srt_path = tmp_path / "t.srt"
    srt_path.write_text(srt, encoding="utf-8")
    gemini = ScriptedGemini(
        [json.dumps(topics), "не json", json.dumps([_sec("Б", 90, 180)]), "a", "b"]
    )
    await _make(gemini, prompts_dir).structurize(
        srt_path=srt_path, output_dir=tmp_path / "out", slide_images=[]
    )
    prompts = _render_prompts(gemini)[-2:]
    for text in ("р1", "стык", "р3"):
        assert _cue_count(prompts, text) == 1, text
