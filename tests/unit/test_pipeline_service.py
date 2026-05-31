import pytest
from pathlib import Path
from lecturelog.application.pipeline_service import PipelineService
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.models import Task, Topic, Section
from lecturelog.domain.enums import TaskStatus, PipelineStage
from lecturelog.domain.media_source import AudioSource


class InMemoryRepo:
    def __init__(self): self.tasks = {}
    async def create(self, task): self.tasks[task.task_id] = task
    async def get(self, tid): return self.tasks.get(tid)
    async def update(self, task): self.tasks[task.task_id] = task
    async def mark_stale_as_interrupted(self): return 0


class FakeTranscriber:
    def __init__(self, srt): self._srt = srt
    async def transcribe(self, audio_path, output_dir, on_progress=None):
        if on_progress:
            r = on_progress(100)
            if r is not None: await r
        return self._srt


class FakeStructurizer:
    def __init__(self, topics): self._topics = topics
    async def structurize(self, srt_path, slide_images, output_dir, on_progress=None):
        return self._topics


class FakeCutter:
    async def cut(self, source_path, sections, output_dir):
        return [Path(f"frag_{i}.mp3") for i in range(len(sections))]


class FakeExporter:
    def __init__(self, zip_path): self._zip = zip_path
    async def export(self, topics, media_fragments, slide_images, output_dir, media_kind):
        return self._zip


class FailingTranscriber:
    async def transcribe(self, audio_path, output_dir, on_progress=None):
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


@pytest.mark.asyncio
async def test_audio_pipeline_completes_and_sets_done(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="t1", source_kind="audio")
    await repo.create(task)
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    topics = [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]
    zip_path = tmp_path / "result.zip"; zip_path.write_bytes(b"zip")

    service = _service(repo, FakeTranscriber(tmp_path / "t.srt"),
                       FakeStructurizer(topics), FakeCutter(), FakeExporter(zip_path))
    await service.run(task=task, source=AudioSource(path=tmp_path / "a.mp3"),
                      slide_provider=None, work_dir=tmp_path)

    final = await repo.get("t1")
    assert final.status == TaskStatus.DONE
    assert final.progress_pct == 100
    assert final.result_path == str(zip_path)


@pytest.mark.asyncio
async def test_critical_failure_marks_task_failed(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="t2", source_kind="audio")
    await repo.create(task)
    service = _service(repo, FailingTranscriber(),
                       FakeStructurizer([]), FakeCutter(), FakeExporter(tmp_path / "z.zip"))
    with pytest.raises(RuntimeError):
        await service.run(task=task, source=AudioSource(path=tmp_path / "a.mp3"),
                          slide_provider=None, work_dir=tmp_path)
    final = await repo.get("t2")
    assert final.status == TaskStatus.FAILED
    assert final.error is not None and "groq down" in final.error


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
    zip_path = tmp_path / "r.zip"; zip_path.write_bytes(b"z")
    service = _service(repo, FakeTranscriber(tmp_path / "t.srt"),
                       FakeStructurizer(topics), FakeCutter(), FakeExporter(zip_path))
    await service.run(task=task, source=AudioSource(path=tmp_path / "a.mp3"),
                      slide_provider=None, work_dir=tmp_path)
    assert progress_log == sorted(progress_log)  # неубывающий прогресс
    assert progress_log[-1] == 100
