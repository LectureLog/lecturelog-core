from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

from lecturelog.domain.media_source import MediaSource
from lecturelog.domain.models import Task
from lecturelog.domain.ports import TaskRepository


class CreateTaskUseCase:
    def __init__(self, repository: TaskRepository, enqueue: Callable[[str], Awaitable[None]]):
        self._repo = repository
        self._enqueue = enqueue

    async def execute(
        self, source: MediaSource, slides_path: Path | None, source_key: str | None = None
    ) -> str:
        task_id = uuid4().hex
        # source_key хранится только для s3_object-источника (uploads/...), чтобы
        # позже DELETE мог удалить исходник из MinIO. Для остальных kind — None.
        task = Task(task_id=task_id, source_kind=source.kind, source_key=source_key)
        await self._repo.create(task)
        await self._enqueue(task_id)
        return task_id
