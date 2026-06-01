from lecturelog.infrastructure.transcribe.groq_transcriber import _build_srt_from_words


def test_build_srt_groups_words_into_captions():
    words = [{"word": f"w{i}", "start": float(i), "end": float(i) + 0.5} for i in range(8)]
    srt = _build_srt_from_words(words, words_per_caption=7)
    # 8 слов при 7/блок -> 2 блока
    assert "1\n" in srt and "2\n" in srt
    assert "w0" in srt and "w7" in srt
    assert "-->" in srt


def test_build_srt_empty_returns_empty():
    assert _build_srt_from_words([]) == ""
