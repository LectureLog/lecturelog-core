import json
from pathlib import Path

import pytest

from lecturelog.infrastructure.slides.video_provider import VideoSlideProvider


class FakeGemini:
    """Возвращает один и тот же JSON со слайдами на любой generate."""

    def __init__(self, slides_json: str):
        self._json = slides_json
        self.calls = 0

    async def generate(self, models, prepare, *, response_json=False, label="gemini"):
        self.calls += 1
        return self._json


def _const(value):
    async def _f(*a, **k):
        return value

    return _f


@pytest.mark.asyncio
async def test_extracts_one_png_per_slide(tmp_path, monkeypatch):
    slides_json = json.dumps({"slides": [
        {"timestamp_finalized": "00:30"},
        {"timestamp_finalized": "05:00"},
    ]})
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fakevideo")

    provider = VideoSlideProvider(
        gemini_client=FakeGemini(slides_json),
        video_path=video, models=["m"], concurrency=1,
        prompts_dir=Path("prompts"),
    )

    monkeypatch.setattr(provider, "_get_video_duration", _const(120))

    async def fake_extract(video_path, sec, target, duration=None):
        Path(target).write_bytes(b"png")

    monkeypatch.setattr(provider, "_ffmpeg_extract_frame", fake_extract)

    out = await provider.get_slides(output_dir=tmp_path / "slides")
    assert len(out) == 2
    assert all(p.exists() and p.suffix == ".png" for p in out)
    assert out[0].name == "slide-01.png"


@pytest.mark.asyncio
async def test_no_slides_returns_empty_list(tmp_path, monkeypatch):
    provider = VideoSlideProvider(
        gemini_client=FakeGemini(json.dumps({"slides": []})),
        video_path=tmp_path / "v.mp4", models=["m"], concurrency=1,
        prompts_dir=Path("prompts"),
    )
    (tmp_path / "v.mp4").write_bytes(b"x")
    monkeypatch.setattr(provider, "_get_video_duration", _const(60))
    out = await provider.get_slides(output_dir=tmp_path / "slides")
    assert out == []  # видео без слайдов — валидно, не ошибка


@pytest.mark.asyncio
async def test_all_chunks_failed_raises(tmp_path, monkeypatch):
    class FailingGemini:
        async def generate(self, models, prepare, *, response_json=False, label="gemini"):
            raise RuntimeError("gemini down")

    provider = VideoSlideProvider(
        gemini_client=FailingGemini(), video_path=tmp_path / "v.mp4",
        models=["m"], concurrency=1, prompts_dir=Path("prompts"),
    )
    (tmp_path / "v.mp4").write_bytes(b"x")
    monkeypatch.setattr(provider, "_get_video_duration", _const(60))
    with pytest.raises(RuntimeError):
        await provider.get_slides(output_dir=tmp_path / "slides")
