from lecturelog.infrastructure.media.video_cutter import _fragment_suffix_and_flags


def test_mp4_gets_faststart_flag():
    suffix, flags = _fragment_suffix_and_flags(".mp4")
    assert suffix == ".mp4"
    assert "+faststart" in flags


def test_webm_keeps_container_no_faststart():
    suffix, flags = _fragment_suffix_and_flags(".webm")
    assert suffix == ".webm"
    assert flags == []


def test_unknown_suffix_falls_back_to_mp4():
    suffix, flags = _fragment_suffix_and_flags(".bin")
    assert suffix == ".mp4"
    assert "+faststart" in flags
