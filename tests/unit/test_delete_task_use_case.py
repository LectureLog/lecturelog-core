from __future__ import annotations

import pytest

from lecturelog.application.use_cases.delete_task import DeleteTaskUseCase
from lecturelog.domain.models import Task
from tests.support.fake_storage import FakeStorage


class _Repo:
    def __init__(self):
        self.tasks: dict[str, Task] = {}

    async def get(self, tid):
        return self.tasks.get(tid)

    async def delete(self, tid):
        self.tasks.pop(tid, None)


def _put(storage: FakeStorage, key: str) -> None:
    storage.objects[key] = b"x"


@pytest.mark.asyncio
async def test_deletes_results_uploads_and_row():
    repo = _Repo()
    storage = FakeStorage()
    repo.tasks["t"] = Task(task_id="t", source_kind="s3_object", source_key="uploads/u/lec.mp3")
    _put(storage, "results/t/output/конспект.md")
    _put(storage, "results/t/output/audio/0.mp3")
    _put(storage, "uploads/u/lec.mp3")

    await DeleteTaskUseCase(repository=repo, storage=storage).execute("t")

    assert storage.objects == {}  # оба префикса вычищены
    assert await repo.get("t") is None


@pytest.mark.asyncio
async def test_clears_results_tmp_prefix():
    # /result-url заливает временный zip в results-tmp/<id>/ — DELETE должен его чистить.
    repo = _Repo()
    storage = FakeStorage()
    repo.tasks["t"] = Task(task_id="t", source_kind="audio")
    _put(storage, "results/t/output/конспект.md")
    _put(storage, "results-tmp/t/abc.zip")
    _put(storage, "results-tmp/other/keep.zip")

    await DeleteTaskUseCase(repository=repo, storage=storage).execute("t")

    assert "results/t/output/конспект.md" not in storage.objects
    assert "results-tmp/t/abc.zip" not in storage.objects
    assert "results-tmp/other/keep.zip" in storage.objects  # чужой tmp не тронут


@pytest.mark.asyncio
async def test_idempotent_with_tmp():
    # Повтор DELETE при наличии results-tmp не падает.
    repo = _Repo()
    storage = FakeStorage()
    repo.tasks["t"] = Task(task_id="t", source_kind="audio")
    _put(storage, "results-tmp/t/abc.zip")
    uc = DeleteTaskUseCase(repository=repo, storage=storage)
    await uc.execute("t")
    await uc.execute("t")


@pytest.mark.asyncio
async def test_idempotent_on_unknown_task():
    repo = _Repo()
    storage = FakeStorage()
    # Несуществующая задача -> чистим results/<id>/ по префиксу, строки нет, не падаем.
    await DeleteTaskUseCase(repository=repo, storage=storage).execute("ghost")
    assert await repo.get("ghost") is None


@pytest.mark.asyncio
async def test_no_source_key_skips_uploads():
    repo = _Repo()
    storage = FakeStorage()
    repo.tasks["t"] = Task(task_id="t", source_kind="audio")  # source_key None
    _put(storage, "results/t/output/конспект.md")
    _put(storage, "uploads/other/keep.mp3")

    await DeleteTaskUseCase(repository=repo, storage=storage).execute("t")

    assert "results/t/output/конспект.md" not in storage.objects
    assert "uploads/other/keep.mp3" in storage.objects  # чужой upload не тронут


@pytest.mark.asyncio
async def test_repeat_delete_does_not_raise():
    repo = _Repo()
    storage = FakeStorage()
    repo.tasks["t"] = Task(task_id="t", source_kind="s3_object", source_key="uploads/u/lec.mp3")
    _put(storage, "results/t/output/конспект.md")
    _put(storage, "uploads/u/lec.mp3")

    uc = DeleteTaskUseCase(repository=repo, storage=storage)
    await uc.execute("t")
    await uc.execute("t")  # повтор -> no-op, без исключений
