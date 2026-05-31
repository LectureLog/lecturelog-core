from lecturelog.infrastructure.media.ffmpeg_utils import ffmpeg_timestamp


def test_ffmpeg_timestamp_converts_comma_to_dot():
    # SRT-таймкод HH:MM:SS,mmm -> формат ffmpeg HH:MM:SS.mmm
    assert ffmpeg_timestamp("01:02:03,500") == "01:02:03.500"


def test_ffmpeg_timestamp_pads_short_form():
    # ММ:СС -> нормализуется к HH:MM:SS.mmm
    assert ffmpeg_timestamp("2:03") == "00:02:03.000"
