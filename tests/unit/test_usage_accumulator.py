from lecturelog.application.usage_accumulator import UsageAccumulator


def test_record_transcribe_shape():
    acc = UsageAccumulator()
    acc.record_transcribe({"audio_seconds": 120, "provider": "groq", "model": "whisper-large-v3"})
    assert acc.usage["transcribe"] == {
        "audio_seconds": 120,
        "provider": "groq",
        "model": "whisper-large-v3",
        "raw": {},
    }


def test_record_llm_by_model_increments_calls_and_tokens():
    acc = UsageAccumulator()
    acc.record_llm("structurize", {"model": "gemini-3", "prompt": 100, "output": 40})
    acc.record_llm("structurize", {"model": "gemini-3", "prompt": 50, "output": 10})
    acc.record_llm("structurize", {"model": "gemini-2", "prompt": 7, "output": 3})

    st = acc.usage["structurize"]
    assert st["provider"] == "gemini"
    assert st["raw"] == {}
    assert st["by_model"]["gemini-3"] == {"prompt": 150, "output": 50, "calls": 2}
    assert st["by_model"]["gemini-2"] == {"prompt": 7, "output": 3, "calls": 1}


def test_record_llm_separate_stages():
    acc = UsageAccumulator()
    acc.record_llm("structurize", {"model": "g", "prompt": 1, "output": 1})
    acc.record_llm("video_slides", {"model": "g", "prompt": 2, "output": 2})
    assert "structurize" in acc.usage
    assert "video_slides" in acc.usage
    assert acc.usage["video_slides"]["by_model"]["g"]["calls"] == 1


def test_compute_total_sums_across_stages_with_mode():
    acc = UsageAccumulator()
    acc.record_transcribe({"audio_seconds": 120, "provider": "groq", "model": "w"})
    acc.record_llm("structurize", {"model": "g1", "prompt": 100, "output": 40})
    acc.record_llm("video_slides", {"model": "g2", "prompt": 10, "output": 5})
    acc.set_mode(source="video", slides_origin="video_extracted")
    acc.compute_total()

    assert acc.usage["total"] == {
        "audio_seconds": 120,
        "gemini_prompt": 110,
        "gemini_output": 45,
        "source": "video",
        "slides_origin": "video_extracted",
    }


def test_video_slides_absent_when_not_recorded():
    acc = UsageAccumulator()
    acc.record_transcribe({"audio_seconds": 10, "provider": "groq", "model": "w"})
    acc.record_llm("structurize", {"model": "g", "prompt": 1, "output": 1})
    acc.set_mode(source="audio", slides_origin="document")
    acc.compute_total()
    assert "video_slides" not in acc.usage
    assert acc.usage["total"]["slides_origin"] == "document"
    assert acc.usage["total"]["source"] == "audio"


def test_compute_total_with_only_transcribe():
    acc = UsageAccumulator()
    acc.record_transcribe({"audio_seconds": 30, "provider": "groq", "model": "w"})
    acc.set_mode(source="audio", slides_origin="none")
    acc.compute_total()
    assert acc.usage["total"] == {
        "audio_seconds": 30,
        "gemini_prompt": 0,
        "gemini_output": 0,
        "source": "audio",
        "slides_origin": "none",
    }
