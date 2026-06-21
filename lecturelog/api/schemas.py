from __future__ import annotations

from pydantic import BaseModel

from lecturelog.domain.models import Task


class CreateTaskResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    task_id: str
    stage: str | None
    progress_pct: int
    error: str | None
    result_path: str | None
    usage: dict = {}

    @classmethod
    def from_task(cls, task: Task) -> TaskStatusResponse:
        return cls(
            task_id=task.task_id,
            stage=task.stage.value if task.stage else None,
            progress_pct=task.progress_pct,
            error=task.error,
            result_path=task.result_path,
            usage=task.usage,
        )
