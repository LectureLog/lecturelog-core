from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from lecturelog.domain.media_source import MediaSource
from lecturelog.domain.models import Task
from lecturelog.domain.ports import TaskRepository


class CreateTaskUseCase:
    def __init__(self, repository: TaskRepository,
                 enqueue: Callable[[str], Awaitable[None]]):
        self._repo = repository
        self._enqueue = enqueue

    async def execute(self, source: MediaSource, slides_path: Path | None) -> str:
        task_id = uuid4().hex
        task = Task(task_id=task_id, source_kind=source.kind)
        await self._repo.create(task)
        await self._enqueue(task_id)
        return task_id
