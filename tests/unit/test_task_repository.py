import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from lecturelog.domain.models import Task
from lecturelog.domain.enums import TaskStatus, PipelineStage
from lecturelog.infrastructure.persistence.orm import Base
from lecturelog.infrastructure.persistence.task_repository import PostgresTaskRepository


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield PostgresTaskRepository(session_factory=factory)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_then_get_returns_same_task(repo):
    task = Task(task_id="t1", source_kind="audio")
    await repo.create(task)
    fetched = await repo.get("t1")
    assert fetched is not None
    assert fetched.task_id == "t1"
    assert fetched.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_get_missing_returns_none(repo):
    assert await repo.get("nope") is None


@pytest.mark.asyncio
async def test_update_persists_new_state(repo):
    task = Task(task_id="t2", source_kind="audio")
    await repo.create(task)
    task.status = TaskStatus.PROCESSING
    task.stage = PipelineStage.STRUCTURIZE
    task.progress_pct = 55
    await repo.update(task)
    fetched = await repo.get("t2")
    assert fetched.status == TaskStatus.PROCESSING
    assert fetched.stage == PipelineStage.STRUCTURIZE
    assert fetched.progress_pct == 55


@pytest.mark.asyncio
async def test_mark_stale_as_interrupted_only_affects_processing(repo):
    t_proc = Task(task_id="p", source_kind="audio", status=TaskStatus.PROCESSING)
    t_done = Task(task_id="d", source_kind="audio", status=TaskStatus.DONE)
    await repo.create(t_proc)
    await repo.create(t_done)
    count = await repo.mark_stale_as_interrupted()
    assert count == 1
    assert (await repo.get("p")).status == TaskStatus.INTERRUPTED
    assert (await repo.get("d")).status == TaskStatus.DONE
