from __future__ import annotations

from lecturelog.domain.models import Topic
from lecturelog.domain.slides import SectionRef, TranscriptBlock
from lecturelog.infrastructure.srt import parse_srt_time


def build_section_refs(topics: list[Topic]) -> tuple[SectionRef, ...]:
    refs: list[SectionRef] = []
    previous_start = -1.0
    for topic_index, topic in enumerate(topics):
        for local_index, section in enumerate(topic.sections):
            start = parse_srt_time(section.start)
            end = parse_srt_time(section.end)
            if end < start or start < previous_start:
                raise ValueError("Некорректная или немонотонная шкала sections")
            refs.append(SectionRef(len(refs), topic_index, local_index, start, end))
            previous_start = start
    return tuple(refs)


def blocks_for_section(
    blocks: list[TranscriptBlock], section: SectionRef
) -> tuple[TranscriptBlock, ...]:
    """Реплики раздела — ровно те, что получает его рендер.

    Реплика принадлежит разделу, в который попадает её середина, по полуоткрытому
    интервалу [начало, конец). Так реплика никогда не достаётся двум разделам:
    после `snap_sections_to_cues` границы смежные (конец подтемы = начало первой
    реплики следующей), и пересечение «включительно» отдавало реплику стыка обоим
    соседям — в доказательства и в запрос судье под двумя разделами. Середина
    повторяет правило самой нарезки: реплика, которую граница режет, уходит к той
    стороне, где её большая часть, а при равенстве — к следующей подтеме.
    """
    return tuple(
        block
        for block in blocks
        if section.start_s <= (block.start_s + block.end_s) / 2 < section.end_s
    )
