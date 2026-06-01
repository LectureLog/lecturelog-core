from __future__ import annotations

from lecturelog.domain.models import Topic


def backfill_missing_slides(topics: list[Topic], total_slides: int) -> None:
    """Вставляет слайды, потерянные LLM: каждый непривязанный слайд идёт
    к секции его ближайшего предшественника (или в первую секцию).

    Мутирует topics на месте.
    """
    if total_slides <= 0:
        return

    assigned: set[int] = {
        s
        for topic in topics
        for section in topic.sections
        for s in section.slide_indices
    }
    missing = sorted(n for n in range(1, total_slides + 1) if n not in assigned)
    if not missing:
        return

    # Строим плоскую карту: slide_num → (topic_idx, section_idx)
    slide_location: dict[int, tuple[int, int]] = {}
    for ti, topic in enumerate(topics):
        for si, section in enumerate(topic.sections):
            for s in section.slide_indices:
                slide_location[s] = (ti, si)

    for n in missing:
        # Ищем ближайшего предшественника
        pred = next((k for k in range(n - 1, 0, -1) if k in slide_location), None)
        if pred is not None:
            ti, si = slide_location[pred]
        elif topics and topics[0].sections:
            ti, si = 0, 0
        else:
            continue

        # Вставляем в найденную секцию в правильной позиции
        topics[ti].sections[si].slide_indices.append(n)
        topics[ti].sections[si].slide_indices.sort()
        # Обновляем topic.slide_indices
        if n not in topics[ti].slide_indices:
            topics[ti].slide_indices.append(n)
            topics[ti].slide_indices.sort()
        slide_location[n] = (ti, si)
