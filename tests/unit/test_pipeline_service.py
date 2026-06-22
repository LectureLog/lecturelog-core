from pathlib import Path

import pytest

from lecturelog.application.pipeline_service import PipelineService
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.enums import ErrorCode, TaskStatus
from lecturelog.domain.media_source import AudioSource, S3ObjectSource
from lecturelog.domain.models import Section, Task, Topic
from tests.support.fake_storage import FakeStorage


class InMemoryRepo:
    def __init__(self):
        self.tasks = {}

    async def create(self, task):
        self.tasks[task.task_id] = task

    async def get(self, tid):
        return self.tasks.get(tid)

    async def update(self, task):
        self.tasks[task.task_id] = task

    async def mark_stale_as_interrupted(self):
        return 0


class FakeTranscriber:
    def __init__(self, srt):
        self._srt = srt

    async def transcribe(self, audio_path, output_dir, on_progress=None, on_usage=None):
        if on_progress:
            r = on_progress(100)
            if r is not None:
                await r
        if on_usage:
            r = on_usage({"audio_seconds": 120, "provider": "groq", "model": "whisper-large-v3"})
            if r is not None:
                await r
        return self._srt


class FakeStructurizer:
    def __init__(self, topics):
        self._topics = topics

    async def structurize(
        self, srt_path, slide_images, output_dir, on_progress=None, on_usage=None
    ):
        if on_usage:
            r = on_usage({"model": "gemini-3", "prompt": 100, "output": 40})
            if r is not None:
                await r
        return self._topics


class FakeCutter:
    async def cut(self, source_path, sections, output_dir):
        return [Path(f"frag_{i}.mp3") for i in range(len(sections))]


class FakeExporter:
    def __init__(self, zip_path):
        self._zip = zip_path

    async def export(self, topics, media_fragments, slide_images, output_dir, media_kind):
        return self._zip


class FailingTranscriber:
    async def transcribe(self, audio_path, output_dir, on_progress=None, on_usage=None):
        raise RuntimeError("groq down")


def _service(repo, transcriber, structurizer, cutter, exporter):
    return PipelineService(
        repository=repo,
        transcriber=transcriber,
        structurizer=structurizer,
        audio_cutter=cutter,
        exporter=exporter,
        progress_plan_factory=ProgressPlan.for_audio,
    )


def _topics_single():
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    return [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]


@pytest.mark.asyncio
async def test_zip_uploaded_to_s3_and_result_path_is_key(tmp_path):
    # При наличии storage ZIP заливается в results/<task_id>/result.zip,
    # а result_path = этот S3-ключ (не локальный путь).
    repo = InMemoryRepo()
    task = Task(task_id="s1", source_kind="audio")
    await repo.create(task)
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"PK-zip-bytes")
    storage = FakeStorage()
    service = PipelineService(
        repository=repo,
        transcriber=FakeTranscriber(tmp_path / "t.srt"),
        structurizer=FakeStructurizer(_topics_single()),
        audio_cutter=FakeCutter(),
        exporter=FakeExporter(zip_path),
        progress_plan_factory=ProgressPlan.for_audio,
        storage=storage,
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )
    final = await repo.get("s1")
    assert final.status == TaskStatus.DONE
    assert final.result_path == "results/s1/result.zip"
    assert storage.objects["results/s1/result.zip"] == b"PK-zip-bytes"


@pytest.mark.asyncio
async def test_s3_object_source_downloaded_before_pipeline(tmp_path):
    # S3ObjectSource(media=audio): исходник скачивается из storage перед транскрибацией,
    # transcribe получает локальный путь к скачанному файлу.
    repo = InMemoryRepo()
    task = Task(task_id="s2", source_kind="s3_object")
    await repo.create(task)
    storage = FakeStorage()
    storage.objects["uploads/abc/lecture.mp3"] = b"audio-bytes"
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"z")

    transcriber = FakeTranscriber(tmp_path / "t.srt")
    received = {}
    orig = transcriber.transcribe

    async def spy(audio_path, output_dir, on_progress=None, on_usage=None):
        received["audio_path"] = audio_path
        return await orig(audio_path, output_dir, on_progress, on_usage)

    transcriber.transcribe = spy

    service = PipelineService(
        repository=repo,
        transcriber=transcriber,
        structurizer=FakeStructurizer(_topics_single()),
        audio_cutter=FakeCutter(),
        exporter=FakeExporter(zip_path),
        progress_plan_factory=ProgressPlan.for_audio,
        storage=storage,
    )
    await service.run(
        task=task,
        source=S3ObjectSource(key="uploads/abc/lecture.mp3", media="audio"),
        slide_provider=None,
        work_dir=tmp_path,
    )
    final = await repo.get("s2")
    assert final.status == TaskStatus.DONE
    # transcribe получил локальный путь к скачанному файлу
    local = received["audio_path"]
    assert local.read_bytes() == b"audio-bytes"
    assert "uploads/abc/lecture.mp3" not in str(local)


@pytest.mark.asyncio
async def test_audio_pipeline_completes_and_sets_done(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="t1", source_kind="audio")
    await repo.create(task)
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    topics = [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")

    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(topics),
        FakeCutter(),
        FakeExporter(zip_path),
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )

    final = await repo.get("t1")
    assert final.status == TaskStatus.DONE
    assert final.progress_pct == 100
    assert final.result_path == str(zip_path)


@pytest.mark.asyncio
async def test_critical_failure_marks_task_failed(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="t2", source_kind="audio")
    await repo.create(task)
    service = _service(
        repo,
        FailingTranscriber(),
        FakeStructurizer([]),
        FakeCutter(),
        FakeExporter(tmp_path / "z.zip"),
    )
    with pytest.raises(RuntimeError):
        await service.run(
            task=task,
            source=AudioSource(path=tmp_path / "a.mp3"),
            slide_provider=None,
            work_dir=tmp_path,
        )
    final = await repo.get("t2")
    assert final.status == TaskStatus.FAILED
    assert final.error is not None and "groq down" in final.error
    # RuntimeError("groq down") без распознаваемых сигналов -> internal.
    assert final.error_code is ErrorCode.INTERNAL


@pytest.mark.asyncio
async def test_progress_is_monotonic_and_persisted(tmp_path):
    repo = InMemoryRepo()
    progress_log = []

    class RecordingRepo(InMemoryRepo):
        async def update(self, task):
            progress_log.append(task.progress_pct)
            await super().update(task)

    repo = RecordingRepo()
    task = Task(task_id="t3", source_kind="audio")
    await repo.create(task)
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    topics = [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]
    zip_path = tmp_path / "r.zip"
    zip_path.write_bytes(b"z")
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(topics),
        FakeCutter(),
        FakeExporter(zip_path),
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )
    assert progress_log == sorted(progress_log)  # неубывающий прогресс
    assert progress_log[-1] == 100


class FakeDocumentSlideProvider:
    """Имитирует DocumentSlideProvider по имени класса (для slides_origin=document)."""

    def __init__(self, slides):
        self._slides = slides

    async def get_slides(self, output_dir, on_progress=None, on_usage=None):
        return self._slides


class StructurizerFailsAfterTranscribe:
    async def structurize(
        self, srt_path, slide_images, output_dir, on_progress=None, on_usage=None
    ):
        raise RuntimeError("structurize boom")


@pytest.mark.asyncio
async def test_usage_persisted_incrementally_transcribe_before_structurize(tmp_path):
    # Снимок task.usage в момент каждого update — проверяем, что transcribe
    # появляется в usage ДО того, как появится structurize.
    snapshots = []

    class SnapshotRepo(InMemoryRepo):
        async def update(self, task):
            import copy

            snapshots.append(copy.deepcopy(task.usage))
            await super().update(task)

    repo = SnapshotRepo()
    task = Task(task_id="u1", source_kind="audio")
    await repo.create(task)
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    topics = [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]
    zip_path = tmp_path / "r.zip"
    zip_path.write_bytes(b"z")
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(topics),
        FakeCutter(),
        FakeExporter(zip_path),
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )

    # Должен быть снимок, где transcribe есть, а structurize ещё нет
    transcribe_only = [s for s in snapshots if "transcribe" in s and "structurize" not in s]
    assert transcribe_only, "transcribe должен персиститься ДО появления structurize"
    assert transcribe_only[0]["transcribe"]["audio_seconds"] == 120

    final = await repo.get("u1")
    assert final.usage["transcribe"]["audio_seconds"] == 120
    assert final.usage["structurize"]["by_model"]["gemini-3"]["calls"] == 1
    assert final.usage["total"]["audio_seconds"] == 120
    assert final.usage["total"]["gemini_prompt"] == 100
    assert final.usage["total"]["source"] == "audio"
    assert final.usage["total"]["slides_origin"] == "none"
    assert final.usage["transcribe"]["raw"] == {}
    assert final.usage["structurize"]["raw"] == {}


@pytest.mark.asyncio
async def test_partial_usage_persisted_on_failure(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="u2", source_kind="audio")
    await repo.create(task)
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        StructurizerFailsAfterTranscribe(),
        FakeCutter(),
        FakeExporter(tmp_path / "z.zip"),
    )
    with pytest.raises(RuntimeError):
        await service.run(
            task=task,
            source=AudioSource(path=tmp_path / "a.mp3"),
            slide_provider=None,
            work_dir=tmp_path,
        )
    final = await repo.get("u2")
    assert final.status == TaskStatus.FAILED
    # частичный расход доехал: transcribe есть, total пересчитан в except
    assert final.usage["transcribe"]["audio_seconds"] == 120
    assert final.usage["total"]["audio_seconds"] == 120
    assert "structurize" not in final.usage


@pytest.mark.asyncio
async def test_mode_axes_audio_document(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="u3", source_kind="audio")
    await repo.create(task)
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    topics = [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]
    zip_path = tmp_path / "r.zip"
    zip_path.write_bytes(b"z")
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(topics),
        FakeCutter(),
        FakeExporter(zip_path),
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=FakeDocumentSlideProvider([tmp_path / "s1.png"]),
        work_dir=tmp_path,
    )
    final = await repo.get("u3")
    assert final.usage["total"]["source"] == "audio"
    assert final.usage["total"]["slides_origin"] == "document"
    assert "video_slides" not in final.usage
