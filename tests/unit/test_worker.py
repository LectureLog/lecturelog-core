import asyncio
import pytest
from pathlib import Path
from lecturelog.application.worker import PipelineWorker, PipelineJob
from lecturelog.domain.media_source import AudioSource


class RecordingService:
    def __init__(self): self.processed = []; self.lock = asyncio.Lock()
    async def run(self, task, source, slide_provider, work_dir):
        async with self.lock:
            self.processed.append(task.task_id)


class SlowService:
    def __init__(self): self.concurrent = 0; self.max_concurrent = 0
    async def run(self, task, source, slide_provider, work_dir):
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        await asyncio.sleep(0.05)
        self.concurrent -= 1


class _Task:
    def __init__(self, tid): self.task_id = tid


def _job(tid):
    return PipelineJob(task_id=tid, task=_Task(tid), source=AudioSource(path=Path("/a.mp3")),
                       slide_provider=None, work_dir=Path("/tmp"))


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
