from lecturelog.domain.models import Section, Topic
from lecturelog.infrastructure.structurize.slide_backfill import backfill_missing_slides


def _topic(title, sections):
    return Topic(
        title=title,
        start="0:00",
        end="9:00",
        sections=sections,
        slide_indices=sorted({s for sec in sections for s in sec.slide_indices}),
    )


def test_missing_slide_attached_to_nearest_predecessor():
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[1, 3])
    topics = [_topic("t", [sec])]
    backfill_missing_slides(topics, total_slides=3)
    # слайд 2 потерян -> прикрепляется к секции, где есть предшественник (слайд 1)
    assert 2 in topics[0].sections[0].slide_indices
    assert topics[0].sections[0].slide_indices == [1, 2, 3]


def test_no_missing_slides_leaves_unchanged():
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[1, 2])
    topics = [_topic("t", [sec])]
    backfill_missing_slides(topics, total_slides=2)
    assert topics[0].sections[0].slide_indices == [1, 2]


def test_leading_missing_slide_goes_to_first_section():
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[2])
    topics = [_topic("t", [sec])]
    backfill_missing_slides(topics, total_slides=2)
    # слайд 1 без предшественника -> в первую секцию
    assert 1 in topics[0].sections[0].slide_indices
