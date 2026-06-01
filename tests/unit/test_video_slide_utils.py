from lecturelog.infrastructure.slides.video_slide_utils import (
    seconds_to_timestamp,
    timestamp_to_seconds,
)


def test_mmss_to_seconds():
    assert timestamp_to_seconds("02:03") == 123


def test_hhmmss_to_seconds():
    assert timestamp_to_seconds("01:02:03") == 3723


def test_bare_seconds():
    assert timestamp_to_seconds("45") == 45


def test_seconds_to_mmss_under_hour():
    assert seconds_to_timestamp(123) == "02:03"


def test_seconds_to_hhmmss_over_hour():
    assert seconds_to_timestamp(3723) == "01:02:03"


def test_round_trip_under_hour():
    assert timestamp_to_seconds(seconds_to_timestamp(599)) == 599
