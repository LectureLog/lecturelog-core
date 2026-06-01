from __future__ import annotations

from lecturelog.domain.exceptions import TaskNotFound
from lecturelog.domain.models import Task
from lecturelog.domain.ports import TaskRepository


class GetStatusUseCase:
    def __init__(self, repository: TaskRepository):
        self._repo = repository

    async def execute(self, task_id: str) -> Task:
        task = await self._repo.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        return task
