from __future__ import annotations


def normalize_slide_mapping(
    llm_mapping: dict[int, list[int]],
    section_count: int,
    slide_numbers: list[int],
) -> dict[int, list[int]]:
    """Нормализует маппинг слайдов: каждый слайд → ровно одна секция, монотонно."""
    # 1) Каждый слайд в ОДИН подраздел: если LLM назначила в несколько — берём самый ранний
    chosen: dict[int, int] = {}
    for sec_idx, slides in sorted(llm_mapping.items()):
        for s in slides:
            chosen.setdefault(s, sec_idx)

    # 2) Монотонизация: назначение секции не убывает по мере роста номера слайда
    prev_section = 0
    monotonic: dict[int, int] = {}
    for s in slide_numbers:
        target = chosen.get(s, prev_section)
        if target < prev_section:
            target = prev_section
        # Не выходим за пределы количества секций
        target = min(target, section_count - 1)
        monotonic[s] = target
        prev_section = target

    # 3) Собираем обратно в {section_idx: [slide_nums]}, номера внутри отсортированы
    result: dict[int, list[int]] = {i: [] for i in range(section_count)}
    for s, sec in monotonic.items():
        result[sec].append(s)
    for sec in result:
        result[sec].sort()
    return result
