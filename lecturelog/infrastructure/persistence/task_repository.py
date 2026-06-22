from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from lecturelog.domain.enums import TaskStatus
from lecturelog.domain.models import Task
from lecturelog.domain.ports import TaskRepository
from lecturelog.infrastructure.persistence.orm import TaskRow, row_to_task, task_to_row


class PostgresTaskRepository(TaskRepository):
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def create(self, task: Task) -> None:
        async with self._session_factory() as session:
            session.add(task_to_row(task))
            await session.commit()

    async def get(self, task_id: str) -> Task | None:
        async with self._session_factory() as session:
            row = await session.get(TaskRow, task_id)
            return row_to_task(row) if row else None

    async def update(self, task: Task) -> None:
        async with self._session_factory() as session:
            row = await session.get(TaskRow, task.task_id)
            if row is None:
                session.add(task_to_row(task))
            else:
                fresh = task_to_row(task)
                for col in (
                    "source_kind",
                    "status",
                    "stage",
                    "progress_pct",
                    "error",
                    "result_path",
                    "usage",
                    "created_at",
                    "updated_at",
                ):
                    setattr(row, col, getattr(fresh, col))
            await session.commit()

    async def mark_stale_as_interrupted(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                update(TaskRow)
                .where(TaskRow.status == TaskStatus.PROCESSING.value)
                .values(status=TaskStatus.INTERRUPTED.value)
            )
            await session.commit()
            return result.rowcount or 0
