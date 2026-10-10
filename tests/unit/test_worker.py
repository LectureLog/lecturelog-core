import asyncio
from pathlib import Path

import pytest

from lecturelog.application.worker import PipelineJob, PipelineWorker
from lecturelog.domain.media_source import AudioSource


class RecordingService:
    def __init__(self):
        self.processed = []
        self.lock = asyncio.Lock()

    async def run(self, task, source, slide_provider, work_dir, **kwargs):
        async with self.lock:
            self.processed.append(task.task_id)


class SlowService:
    def __init__(self):
        self.concurrent = 0
        self.max_concurrent = 0

    async def run(self, task, source, slide_provider, work_dir, **kwargs):
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        await asyncio.sleep(0.05)
        self.concurrent -= 1


class SuccessfulS3Service:
    async def run(self, task, source, slide_provider, work_dir, **kwargs):
        return f"results/{task.task_id}/"


class LocalResultService:
    async def run(self, task, source, slide_provider, work_dir, **kwargs):
        return str(work_dir / "export" / "result.zip")


class FailingService:
    async def run(self, task, source, slide_provider, work_dir, **kwargs):
        raise RuntimeError("pipeline failed")


class _Task:
    def __init__(self, tid):
        self.task_id = tid


def _job(tid):
    return PipelineJob(
        task_id=tid,
        task=_Task(tid),
        source=AudioSource(path=Path("/a.mp3")),
        slide_provider=None,
        work_dir=Path("/tmp"),
    )


def _completed_job(tmp_path, tid):
    work_dir = tmp_path / tid
    work_dir.mkdir()
    (work_dir / "raw.bin").write_bytes(b"raw")
    return PipelineJob(
        task_id=tid,
        task=_Task(tid),
        source=AudioSource(path=work_dir / "raw.bin"),
        slide_provider=None,
        work_dir=work_dir,
    )


@pytest.mark.asyncio
async def test_worker_processes_all_enqueued_jobs():
    service = RecordingService()
    worker = PipelineWorker(service=service, concurrency=2)
    await worker.start()
    for i in range(5):
        await worker.enqueue(_job(f"t{i}"))
    await worker.stop()  # graceful: дождётся обработки всех
    assert sorted(service.processed) == [f"t{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_worker_respects_concurrency_limit():
    service = SlowService()
    worker = PipelineWorker(service=service, concurrency=2)
    await worker.start()
    for i in range(6):
        await worker.enqueue(_job(f"t{i}"))
    await worker.stop()
    assert service.max_concurrent <= 2  # не более 2 лекций одновременно


@pytest.mark.asyncio
async def test_worker_removes_workspace_after_s3_result_is_persisted(tmp_path):
    task_id = "a" * 32
    job = _completed_job(tmp_path, task_id)
    worker = PipelineWorker(service=SuccessfulS3Service(), concurrency=1)

    await worker.start()
    await worker.enqueue(job)
    await worker.stop()

    assert not job.work_dir.exists()


@pytest.mark.asyncio
async def test_worker_keeps_workspace_for_local_result(tmp_path):
    task_id = "b" * 32
    job = _completed_job(tmp_path, task_id)
    worker = PipelineWorker(service=LocalResultService(), concurrency=1)

    await worker.start()
    await worker.enqueue(job)
    await worker.stop()

    assert (job.work_dir / "raw.bin").exists()


@pytest.mark.asyncio
async def test_worker_keeps_workspace_when_pipeline_fails(tmp_path):
    task_id = "c" * 32
    job = _completed_job(tmp_path, task_id)
    worker = PipelineWorker(service=FailingService(), concurrency=1)

    await worker.start()
    await worker.enqueue(job)
    await worker.stop()

    assert (job.work_dir / "raw.bin").exists()


@pytest.mark.asyncio
async def test_worker_refuses_to_remove_workspace_with_unexpected_name(tmp_path):
    task_id = "d" * 32
    work_dir = tmp_path / "not-a-task-id"
    work_dir.mkdir()
    (work_dir / "raw.bin").write_bytes(b"raw")
    job = PipelineJob(
        task_id=task_id,
        task=_Task(task_id),
        source=AudioSource(path=work_dir / "raw.bin"),
        slide_provider=None,
        work_dir=work_dir,
    )
    worker = PipelineWorker(service=SuccessfulS3Service(), concurrency=1)

    await worker.start()
    await worker.enqueue(job)
    await worker.stop()

    assert (work_dir / "raw.bin").exists()


# --- TTL-очистка workspace упавших задач ---------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from lecturelog.application.worker import WorkDirSweeper  # noqa: E402
from lecturelog.domain.enums import TaskStatus  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class _Repo:
    def __init__(self, statuses):
        self._s = statuses

    async def get(self, task_id):
        st = self._s.get(task_id)
        if st is None:
            return None
        t = _Task(task_id)
        t.status = st
        return t


A, B, C, D = ("a" * 32, "b" * 32, "c" * 32, "d" * 32)


async def _fail_job(tmp_path, tid, clock):
    job = _completed_job(tmp_path, tid)
    worker = PipelineWorker(service=FailingService(), concurrency=1, clock=clock)
    await worker.start()
    await worker.enqueue(job)
    await worker.stop()


@pytest.mark.asyncio
async def test_failed_workspace_deleted_only_after_ttl(tmp_path):
    clock = FakeClock()
    await _fail_job(tmp_path, A, clock)
    repo = _Repo({A: TaskStatus.FAILED})
    sweeper = WorkDirSweeper(repo, tmp_path, timedelta(hours=24), clock)

    clock.advance(hours=23, minutes=59)
    assert (await sweeper.sweep()).deleted == 0
    assert (tmp_path / A).exists()

    clock.advance(minutes=2)
    assert (await sweeper.sweep()).deleted == 1
    assert not (tmp_path / A).exists()


@pytest.mark.asyncio
async def test_sweeper_keeps_active_done_unknown_and_reserved_dirs(tmp_path):
    clock = FakeClock()
    repo = _Repo({A: TaskStatus.PROCESSING, B: TaskStatus.PENDING, C: TaskStatus.DONE})
    names = (A, B, C, D, "results_tmp", "transcript_cache", "not-a-task")
    for name in names:
        (tmp_path / name).mkdir()
        (tmp_path / name / "x").write_bytes(b"x")
    sweeper = WorkDirSweeper(repo, tmp_path, timedelta(hours=24), clock)

    clock.advance(days=365)
    assert (await sweeper.sweep()).deleted == 0
    for name in names:
        assert (tmp_path / name).exists()


@pytest.mark.asyncio
async def test_transcript_cache_outlives_failed_workspace(tmp_path):
    # Кеш транскриптов - сосед workspace: удаление упавшей задачи его не задевает.
    clock = FakeClock()
    await _fail_job(tmp_path, A, clock)
    entry = tmp_path / "transcript_cache" / ("f" * 64)
    entry.mkdir(parents=True)
    (entry / "transcript.srt").write_text("1\n")
    sweeper = WorkDirSweeper(_Repo({A: TaskStatus.FAILED}), tmp_path, timedelta(hours=24), clock)

    clock.advance(hours=25)
    assert (await sweeper.sweep()).deleted == 1
    assert (entry / "transcript.srt").exists()


@pytest.mark.asyncio
async def test_sweeper_skips_symlink_and_continues(tmp_path):
    clock = FakeClock()
    await _fail_job(tmp_path, B, clock)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / A).symlink_to(outside, target_is_directory=True)
    repo = _Repo({A: TaskStatus.FAILED, B: TaskStatus.FAILED})
    sweeper = WorkDirSweeper(repo, tmp_path, timedelta(hours=1), clock)

    clock.advance(hours=2)
    assert (await sweeper.sweep()).deleted == 1
    assert outside.exists() and (tmp_path / A).is_symlink()
    assert not (tmp_path / B).exists()
