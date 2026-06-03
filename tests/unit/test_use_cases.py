from pathlib import Path

import pytest

from lecturelog.application.use_cases.create_task import CreateTaskUseCase
from lecturelog.application.use_cases.get_result import GetResultUseCase
from lecturelog.application.use_cases.get_status import GetStatusUseCase
from lecturelog.application.use_cases.get_transcript import GetTranscriptUseCase
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.exceptions import ResultNotReady, TaskNotFound, TranscribeFailed
from lecturelog.domain.media_source import AudioSource
from lecturelog.domain.models import Task


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


@pytest.mark.asyncio
async def test_get_status_missing_raises():
    uc = GetStatusUseCase(repository=InMemoryRepo())
    with pytest.raises(TaskNotFound):
        await uc.execute("nope")


@pytest.mark.asyncio
async def test_get_status_returns_task():
    repo = InMemoryRepo()
    await repo.create(Task(task_id="t", source_kind="audio"))
    uc = GetStatusUseCase(repository=repo)
    assert (await uc.execute("t")).task_id == "t"


@pytest.mark.asyncio
async def test_get_result_not_ready_raises():
    repo = InMemoryRepo()
    await repo.create(Task(task_id="t", source_kind="audio"))
    uc = GetResultUseCase(repository=repo)
    with pytest.raises(ResultNotReady):
        await uc.execute("t")


@pytest.mark.asyncio
async def test_get_result_missing_raises():
    uc = GetResultUseCase(repository=InMemoryRepo())
    with pytest.raises(TaskNotFound):
        await uc.execute("nope")


@pytest.mark.asyncio
async def test_get_result_returns_path_when_ready():
    repo = InMemoryRepo()
    await repo.create(
        Task(task_id="t", source_kind="audio", status=TaskStatus.DONE, result_path="/r.zip")
    )
    uc = GetResultUseCase(repository=repo)
    assert await uc.execute("t") == Path("/r.zip")


@pytest.mark.asyncio
async def test_create_task_enqueues_and_returns_id():
    repo = InMemoryRepo()
    enqueued = []

    async def enqueue(tid):
        enqueued.append(tid)

    uc = CreateTaskUseCase(repository=repo, enqueue=enqueue)
    tid = await uc.execute(source=AudioSource(path=Path("/a.mp3")), slides_path=None)
    assert tid in enqueued
    assert (await repo.get(tid)).status == TaskStatus.PENDING
    assert (await repo.get(tid)).source_kind == "audio"


@pytest.mark.asyncio
async def test_transcript_missing_task_raises():
    uc = GetTranscriptUseCase(repository=InMemoryRepo(), srt_path_for=lambda tid: Path("/nope.srt"))
    with pytest.raises(TaskNotFound):
        await uc.execute("nope")


@pytest.mark.asyncio
async def test_transcript_failed_on_transcribe_raises(tmp_path):
    repo = InMemoryRepo()
    await repo.create(
        Task(
            task_id="t",
            source_kind="audio",
            status=TaskStatus.FAILED,
            stage=PipelineStage.TRANSCRIBE,
            error="groq down",
        )
    )
    uc = GetTranscriptUseCase(repository=repo, srt_path_for=lambda tid: tmp_path / "x.srt")
    with pytest.raises(TranscribeFailed):
        await uc.execute("t")


@pytest.mark.asyncio
async def test_transcript_in_progress_when_srt_absent(tmp_path):
    repo = InMemoryRepo()
    await repo.create(
        Task(
            task_id="t",
            source_kind="audio",
            status=TaskStatus.PROCESSING,
            stage=PipelineStage.TRANSCRIBE,
            progress_pct=10,
        )
    )
    uc = GetTranscriptUseCase(repository=repo, srt_path_for=lambda tid: tmp_path / "absent.srt")
    result = await uc.execute("t")
    assert result.ready is False
    assert result.progress_pct == 10
    assert result.path is None


@pytest.mark.asyncio
async def test_transcript_ready_returns_path(tmp_path):
    srt = tmp_path / "transcript.srt"
    srt.write_text("1\n00:00\n", encoding="utf-8")
    repo = InMemoryRepo()
    await repo.create(
        Task(
            task_id="t",
            source_kind="audio",
            status=TaskStatus.PROCESSING,
            stage=PipelineStage.STRUCTURIZE,
        )
    )
    uc = GetTranscriptUseCase(repository=repo, srt_path_for=lambda tid: srt)
    result = await uc.execute("t")
    assert result.ready is True
    assert result.path == srt
