from __future__ import annotations

from pathlib import Path

from lecturelog.domain.exceptions import ResultNotReady, TaskNotFound
from lecturelog.domain.ports import TaskRepository


class GetResultUseCase:
    def __init__(self, repository: TaskRepository):
        self._repo = repository

    async def execute(self, task_id: str) -> Path:
        task = await self._repo.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        if not task.result_path:
            raise ResultNotReady(task_id)
        return Path(task.result_path)
