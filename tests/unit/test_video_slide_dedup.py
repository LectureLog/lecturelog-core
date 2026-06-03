from lecturelog.infrastructure.slides.video_slide_utils import merge_and_dedup


def test_merges_chunks_and_sorts_by_time():
    chunks = [
        [{"timestamp_finalized": "01:00"}],
        [{"timestamp_finalized": "00:30"}],
    ]
    out = merge_and_dedup(chunks)
    times = [s["timestamp_finalized"] for s in out]
    assert times == ["00:30", "01:00"]


def test_dedups_near_duplicates_within_threshold():
    # два слайда в пределах 10с -> остаётся один (последний)
    chunks = [
        [{"timestamp_finalized": "01:00", "tag": "a"}, {"timestamp_finalized": "01:05", "tag": "b"}]
    ]
    out = merge_and_dedup(chunks)
    assert len(out) == 1
    assert out[0]["tag"] == "b"


def test_keeps_distant_slides():
    chunks = [[{"timestamp_finalized": "00:00"}, {"timestamp_finalized": "01:00"}]]
    out = merge_and_dedup(chunks)
    assert len(out) == 2


def test_assigns_sequential_index():
    chunks = [[{"timestamp_finalized": "00:10"}, {"timestamp_finalized": "02:00"}]]
    out = merge_and_dedup(chunks)
    assert [s["index"] for s in out] == [1, 2]


def test_empty_input_returns_empty():
    assert merge_and_dedup([]) == []
    assert merge_and_dedup([[], []]) == []
