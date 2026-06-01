from lecturelog.infrastructure.srt import (
    srt_to_plain_text, parse_srt_time, extract_srt_fragment,
)

SAMPLE = """1
00:00:00,000 --> 00:00:05,000
Первое предложение

2
00:00:05,000 --> 00:00:10,000
Второе
предложение"""


def test_srt_to_plain_text_one_line_per_block_multiline_joined():
    out = srt_to_plain_text(SAMPLE)
    assert out == "Первое предложение\nВторое предложение"


def test_parse_srt_time_hms():
    assert parse_srt_time("01:02:03,500") == 3723.5


def test_parse_srt_time_ms():
    assert parse_srt_time("02:03,000") == 123.0


def test_extract_fragment_returns_overlapping_blocks_only():
    frag = extract_srt_fragment(SAMPLE, "00:00:05,000", "00:00:10,000")
    assert "Второе" in frag
    # первый блок (0-5) граничит, второй (5-10) точно попадает
    assert "предложение" in frag
