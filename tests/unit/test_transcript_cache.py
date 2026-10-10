import contextlib
import shutil
from pathlib import Path

import pytest

from lecturelog.application.factories import transcribe_cache_settings, transcriber_factory
from lecturelog.application.pipeline_service import PipelineService
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.config.settings import TranscribeConfig
from lecturelog.domain.enums import TaskStatus
from lecturelog.domain.media_source import AudioSource
from lecturelog.domain.models import Section, Task, Topic
from lecturelog.infrastructure.transcribe.cache import CachingTranscriber
from tests.unit.test_pipeline_service import (
    FakeCutter,
    FakeExporter,
    InMemoryRepo,
)

SRT = "1\n00:00:00,000 --> 00:00:01,000\nпривет\n"


class CountingTranscriber:
    """Поддельный транскрибер: считает вызовы и шлёт usage, как настоящий."""

    def __init__(self):
        self.calls = 0

    async def transcribe(self, audio_path, output_dir, on_progress=None, on_usage=None):
        self.calls += 1
        if on_usage:
            await on_usage({"audio_seconds": 120, "provider": "groq", "model": "whisper-large-v3"})
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "transcript.srt"
        target.write_text(SRT, encoding="utf-8")
        return target


class OkStructurizer:
    async def structurize(
        self, srt_path, slide_images, output_dir, on_progress=None, on_usage=None
    ):
        sec = Section(title="s", start="0:00", end="1:00", content="c", slide_indices=[])
        return [Topic(title="T", start="0:00", end="1:00", sections=[sec], slide_indices=[])]


class BrokenStructurizer:
    async def structurize(
        self, srt_path, slide_images, output_dir, on_progress=None, on_usage=None
    ):
        raise RuntimeError("llm down")


class BrokenCutter:
    async def cut(self, source_path, sections, output_dir):
        raise RuntimeError("ffmpeg down")


def _audio(tmp_path: Path, payload: bytes = b"audio-bytes") -> Path:
    path = tmp_path / "a.mp3"
    path.write_bytes(payload)
    return path


def _cached(inner, tmp_path, **settings):
    return CachingTranscriber(inner, cache_dir=tmp_path / "cache", settings=settings or {"m": "a"})


async def _run(tmp_path, transcriber, task_id, *, structurizer=None, cutter=None, audio=None):
    repo = InMemoryRepo()
    task = Task(task_id=task_id, source_kind="audio")
    await repo.create(task)
    service = PipelineService(
        repository=repo,
        transcriber=transcriber,
        structurizer=structurizer or OkStructurizer(),
        audio_cutter=cutter or FakeCutter(),
        exporter=FakeExporter(),
        progress_plan_factory=ProgressPlan.for_audio,
    )
    with contextlib.suppress(RuntimeError):
        await service.run(
            task=task,
            source=AudioSource(path=audio or _audio(tmp_path)),
            slide_provider=None,
            work_dir=tmp_path / "work" / task_id,
        )
    return await repo.get(task_id)


@pytest.mark.asyncio
async def test_rerun_after_structurize_failure_does_not_transcribe_again(tmp_path):
    inner = CountingTranscriber()
    transcriber = _cached(inner, tmp_path)

    failed = await _run(tmp_path, transcriber, "t1", structurizer=BrokenStructurizer())
    assert failed.status == TaskStatus.FAILED
    retry = await _run(tmp_path, transcriber, "t2")

    assert retry.status == TaskStatus.DONE
    assert inner.calls == 1
    # транскрипт попал в рабочий каталог новой задачи (его читает /transcript)
    assert (tmp_path / "work" / "t2" / "transcribe" / "transcript.srt").read_text(
        encoding="utf-8"
    ) == SRT


@pytest.mark.asyncio
async def test_transcript_survives_failure_at_later_stage(tmp_path):
    # падение на нарезке (стадия после структуризации) тоже не теряет транскрипт
    inner = CountingTranscriber()
    transcriber = _cached(inner, tmp_path)

    failed = await _run(tmp_path, transcriber, "t1", cutter=BrokenCutter())
    assert failed.status == TaskStatus.FAILED
    await _run(tmp_path, transcriber, "t1")  # ретрай той же задачи

    assert inner.calls == 1


@pytest.mark.asyncio
async def test_survives_new_service_instance_and_wiped_work_dir(tmp_path):
    # кеш лежит вне workspace задачи: пересоздание сервиса и удаление work_dir его не трогают
    inner = CountingTranscriber()
    await _run(tmp_path, _cached(inner, tmp_path), "t1", structurizer=BrokenStructurizer())
    shutil.rmtree(tmp_path / "work")
    await _run(tmp_path, _cached(inner, tmp_path), "t2")

    assert inner.calls == 1


@pytest.mark.asyncio
async def test_different_audio_content_transcribes_again(tmp_path):
    inner = CountingTranscriber()
    transcriber = _cached(inner, tmp_path)

    await _run(tmp_path, transcriber, "t1")
    await _run(tmp_path, transcriber, "t2", audio=_audio(tmp_path, b"other-audio"))

    assert inner.calls == 2


@pytest.mark.asyncio
async def test_same_content_under_other_filename_hits_cache(tmp_path):
    inner = CountingTranscriber()
    transcriber = _cached(inner, tmp_path)
    other = tmp_path / "renamed.wav"
    other.write_bytes(b"audio-bytes")

    await _run(tmp_path, transcriber, "t1")
    await _run(tmp_path, transcriber, "t2", audio=other)

    assert inner.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [{"model": "nova-2"}, {"language": "en"}, {"provider": "groq"}, {"detect_language": True}],
)
async def test_changed_transcription_setting_transcribes_again(tmp_path, changed):
    base = {"provider": "deepgram", "model": "nova-3", "language": "ru", "detect_language": False}
    inner = CountingTranscriber()

    await _run(tmp_path, _cached(inner, tmp_path, **base), "t1")
    await _run(tmp_path, _cached(inner, tmp_path, **{**base, **changed}), "t2")

    assert inner.calls == 2


@pytest.mark.asyncio
async def test_cache_hit_does_not_record_transcribe_usage_again(tmp_path):
    inner = CountingTranscriber()
    transcriber = _cached(inner, tmp_path)

    first = await _run(tmp_path, transcriber, "t1")
    second = await _run(tmp_path, transcriber, "t2")

    assert first.usage["transcribe"]["audio_seconds"] == 120
    assert "transcribe" not in second.usage
    assert second.usage["total"]["audio_seconds"] == 0


@pytest.mark.asyncio
async def test_failed_transcription_is_not_cached(tmp_path):
    class Flaky(CountingTranscriber):
        async def transcribe(self, *args, **kwargs):
            if self.calls == 0:
                self.calls += 1
                raise RuntimeError("groq down")
            return await super().transcribe(*args, **kwargs)

    inner = Flaky()
    transcriber = _cached(inner, tmp_path)

    first = await _run(tmp_path, transcriber, "t1")
    second = await _run(tmp_path, transcriber, "t2")

    assert first.status == TaskStatus.FAILED
    assert second.status == TaskStatus.DONE
    assert inner.calls == 2


@pytest.mark.asyncio
async def test_corrupt_cache_entry_is_treated_as_miss(tmp_path):
    inner = CountingTranscriber()
    transcriber = _cached(inner, tmp_path)
    await _run(tmp_path, transcriber, "t1")
    for entry in (tmp_path / "cache").rglob("*.srt"):
        entry.write_text("", encoding="utf-8")

    await _run(tmp_path, transcriber, "t2")

    assert inner.calls == 2


@pytest.mark.asyncio
async def test_unwritable_cache_does_not_fail_transcription(tmp_path):
    blocker = tmp_path / "cache"
    blocker.write_text("файл вместо каталога", encoding="utf-8")
    inner = CountingTranscriber()

    result = await _run(tmp_path, CachingTranscriber(inner, cache_dir=blocker, settings={}), "t1")

    assert result.status == TaskStatus.DONE
    assert inner.calls == 1


def test_cache_settings_cover_deepgram_options(monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "secret-token")

    def settings(**env):
        for name in ("DEEPGRAM_MODEL", "DEEPGRAM_LANGUAGE", "DEEPGRAM_UTT_SPLIT"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return transcribe_cache_settings(TranscribeConfig(_env_file=None))

    base = settings()
    assert settings(DEEPGRAM_MODEL="nova-2") != base
    assert settings(DEEPGRAM_LANGUAGE="en") != base
    assert settings(DEEPGRAM_UTT_SPLIT="1.2") != base
    assert "secret-token" not in str(base)  # секреты в ключ не попадают


def test_cache_settings_differ_between_providers(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEYS", "k1")
    monkeypatch.setenv("TRANSCRIBE_PROVIDER", "groq")
    groq = transcribe_cache_settings(TranscribeConfig(_env_file=None))
    monkeypatch.setenv("TRANSCRIBE_PROVIDER", "deepgram")
    deepgram = transcribe_cache_settings(TranscribeConfig(_env_file=None))

    assert groq != deepgram


def test_factory_wraps_transcriber_only_when_cache_dir_given(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSCRIBE_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEYS", "k1")
    config = TranscribeConfig(_env_file=None)

    assert not isinstance(transcriber_factory(config), CachingTranscriber)
    assert isinstance(transcriber_factory(config, cache_dir=tmp_path), CachingTranscriber)
