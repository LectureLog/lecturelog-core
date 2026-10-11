from __future__ import annotations

import logging
import re
from bisect import bisect_left
from typing import Any

from lecturelog.domain.slides import TranscriptBlock

logger = logging.getLogger(__name__)

_TIMELINE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[.,]\d{3})"
)


def parse_srt_blocks(srt: str) -> list[TranscriptBlock]:
    """Parse SRT once into stable, 1-based evidence blocks."""
    normalized = srt.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    result: list[TranscriptBlock] = []
    for raw_block in re.split(r"\n\s*\n+", normalized):
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        timeline_pos = next((i for i, line in enumerate(lines) if _TIMELINE_RE.search(line)), None)
        if timeline_pos is None:
            continue
        match = _TIMELINE_RE.search(lines[timeline_pos])
        assert match is not None
        text = " ".join(lines[timeline_pos + 1 :]).strip()
        if not text:
            continue
        result.append(
            TranscriptBlock(
                block_id=len(result) + 1,
                start_s=parse_srt_time(match.group("start")),
                end_s=parse_srt_time(match.group("end")),
                text=text,
            )
        )
    return result


def extract_plain_text(srt: str) -> str:
    """Извлекает чистый текст из SRT, убирая нумерацию и таймкоды."""
    return " ".join(block.text for block in parse_srt_blocks(srt))


def srt_to_plain_text(srt: str) -> str:
    """Преобразует SRT в plain-text: одна строка на блок, без номеров и таймкодов.

    Многострочные подписи внутри блока склеиваются через пробел.
    Между блоками — перевод строки.
    """
    return "\n".join(block.text for block in parse_srt_blocks(srt))


def parse_srt_time(time_str: str) -> float:
    """Переводит таймкод SRT (ЧЧ:ММ:СС,МСС или ММ:СС,МСС) в секунды."""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def format_time(time_str: str) -> str:
    """Нормализует формат таймкода до ЧЧ:ММ:СС."""
    return time_str.split(",")[0].split(".")[0]


def extract_srt_fragment(srt: str, start: str, end: str) -> str:
    """Вырезает фрагмент SRT по таймкодам."""
    start_sec = parse_srt_time(start.replace(".", ",") if "," not in start else start)
    end_sec = parse_srt_time(end.replace(".", ",") if "," not in end else end)

    result = []
    for block in parse_srt_blocks(srt):
        if block.end_s >= start_sec and block.start_s <= end_sec:
            result.append(
                f"{block.block_id}\n"
                f"{format_srt_seconds(block.start_s)} --> {format_srt_seconds(block.end_s)}\n"
                f"{block.text}"
            )
    return "\n\n".join(result)


def extract_srt_cue_range(srt: str, first: int, last: int) -> str:
    """Вырезает реплики с позициями first..last включительно (с 1, в порядке начала).

    Позиция — номер в списке реплик, отсортированном по времени начала (стабильно),
    как его видит нарезка подтем; номера из файла и порядок записи не важны.
    В отличие от extract_srt_fragment не зависит от таймкодов: соседние реплики
    с совпадающими границами не попадают сразу в два фрагмента.
    """
    blocks = sorted(parse_srt_blocks(srt), key=lambda block: block.start_s)
    return "\n\n".join(
        f"{block.block_id}\n"
        f"{format_srt_seconds(block.start_s)} --> {format_srt_seconds(block.end_s)}\n"
        f"{block.text}"
        for position, block in enumerate(blocks, start=1)
        if first <= position <= last
    )


def format_srt_seconds(value: float) -> str:
    milliseconds = round(value * 1000)
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def snap_sections_to_cues(
    topics_sections: list[list[dict[str, Any]]], srt_content: str
) -> list[tuple[int, int]] | None:
    """Сдвигает начала подтем к границам реплик, чтобы реплика была ровно в одной подтеме.

    Модель режет по таймкодам и нередко попадает посреди реплики: фрагмент по
    перекрытию тогда достаётся обеим соседним подтемам, и на стыке текст повторяется.
    Начало каждой подтемы переносится к ближайшей границе реплики (начало реплики
    или её конец = начало следующей). Реплики между двумя началами принадлежат
    предыдущей подтеме, поэтому зазоры между подтемами тоже не теряются.

    Подтема, в которой после сдвига не осталось ни одной реплики (две границы
    упали на одну, подтема короче реплики), удаляется вместе с заголовком: её
    нечем наполнить, а рендер по пустому фрагменту выдумывает текст. Реплики
    остаются у тех подтем, которым достались.

    Меняет topics_sections на месте (start/end у выживших, удаляет схлопнувшиеся)
    и возвращает для каждой оставшейся подтемы в плоском порядке диапазон
    номеров реплик (первая, последняя) для рендера. Без реплик в транскрипте
    или если не осталось ни одной подтемы с репликами — ничего не меняет и
    возвращает None (работаем по таймкодам, как раньше).
    """

    # Модель может вернуть подтемы не по порядку времени: упорядочиваем внутри темы,
    # иначе монотонизация границ схлопнет подтемы и потеряет их реплики.
    # Работаем с копией порядка: при возврате None исходный порядок не трогаем.
    ordered = [
        sorted(sections, key=lambda section: parse_srt_time(str(section["start"])))
        for sections in topics_sections
    ]
    flat = [section for sections in ordered for section in sections]
    blocks = sorted(parse_srt_blocks(srt_content), key=lambda block: block.start_s)
    if not flat or not blocks:
        return None

    starts = [block.start_s for block in blocks]

    def boundary(seconds: float) -> int:
        # Индекс первой реплики подтемы: все реплики левее принадлежат предыдущей.
        k = bisect_left(starts, seconds)
        # Граница посреди реплики — к ближайшему краю, при равенстве вправо.
        if (
            k > 0
            and blocks[k - 1].end_s > seconds
            and seconds - starts[k - 1] < blocks[k - 1].end_s - seconds
        ):
            return k - 1
        return k

    firsts: list[int] = []
    for section in flat:
        index = boundary(parse_srt_time(str(section["start"])))
        # Первая подтема забирает всё с начала транскрипта: реплика не может
        # остаться вне подтем только потому, что модель начала не с неё.
        firsts.append(max(index, firsts[-1]) if firsts else 0)
    # Хвост после конца последней подтемы достаётся ей же, симметрично началу.
    # Если подтемы целиком лежат до первой реплики, их разметка не относится к
    # транскрипту — оставляем таймкоды как есть.
    if bisect_left(starts, parse_srt_time(str(flat[-1]["end"]))) == 0:
        return None
    stop = len(blocks)
    edges = [*firsts[1:], stop]

    kept = [i for i, (first, edge) in enumerate(zip(firsts, edges, strict=True)) if first < edge]
    if not kept:
        return None

    for sections, original in zip(ordered, topics_sections, strict=True):
        original[:] = sections

    ranges: list[tuple[int, int]] = []
    kept_set = set(kept)
    previous_end = 0.0
    for position, i in enumerate(kept):
        section = flat[i]
        covered = blocks[firsts[i] : edges[i]]
        start_s = covered[0].start_s
        if position + 1 < len(kept):
            # Интервалы для медиа-нарезки смежные: конец = начало следующей подтемы,
            # без пауз вне клипов. Текст при этом режется по репликам (cue_range).
            end_s = blocks[firsts[kept[position + 1]]].start_s
        else:
            end_s = max(block.end_s for block in covered)
        # Секции режут медиа по ЧЧ:ММ:СС: после усечения до секунд конец обязан быть
        # строго позже начала (иначе пустой клип; только для подтем короче секунды
        # конец заходит на соседа), а концы строго возрастают (требование v2).
        end_s = max(end_s, float(int(start_s) + 1), previous_end + 0.001)
        previous_end = end_s
        section["start"] = format_srt_seconds(start_s)
        section["end"] = format_srt_seconds(end_s)
        ranges.append((firsts[i] + 1, edges[i]))
    if len(kept) < len(flat):
        logger.warning(
            "после сдвига к границам реплик удалено подтем без реплик: %d",
            len(flat) - len(kept),
        )
        dropped = {id(flat[i]) for i in range(len(flat)) if i not in kept_set}
        for sections in topics_sections:
            sections[:] = [section for section in sections if id(section) not in dropped]
    return ranges
