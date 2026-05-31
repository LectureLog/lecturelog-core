from lecturelog.infrastructure.structurize.slide_mapping import normalize_slide_mapping


def test_each_slide_assigned_exactly_once():
    result = normalize_slide_mapping({0: [1, 2], 1: [3]}, section_count=2, slide_numbers=[1, 2, 3])
    all_slides = [s for slides in result.values() for s in slides]
    assert sorted(all_slides) == [1, 2, 3]
    assert len(all_slides) == len(set(all_slides))  # без дублей


def test_conflict_resolved_to_earliest_section():
    # слайд 1 назначен и в секцию 0, и в секцию 1 -> берётся 0
    result = normalize_slide_mapping({0: [1], 1: [1, 2]}, section_count=2, slide_numbers=[1, 2])
    assert 1 in result[0]
    assert 1 not in result[1]


def test_monotonic_non_decreasing_assignment():
    # если LLM назначила слайд 3 в секцию 0, а слайд 2 в секцию 1 — монотонизация чинит
    result = normalize_slide_mapping({1: [2], 0: [3]}, section_count=2, slide_numbers=[2, 3])
    # секция слайда 3 >= секции слайда 2
    sec_of = {s: sec for sec, slides in result.items() for s in slides}
    assert sec_of[3] >= sec_of[2]


def test_all_sections_present_in_result():
    result = normalize_slide_mapping({}, section_count=3, slide_numbers=[1])
    assert set(result.keys()) == {0, 1, 2}
