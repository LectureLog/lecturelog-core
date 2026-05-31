from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from lecturelog.domain.enums import PipelineStage, TaskStatus


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Section(BaseModel):
    title: str
    start: str
    end: str
    content: str
    slide_indices: list[int] = Field(default_factory=list)


class Topic(BaseModel):
    title: str
    start: str
    end: str
    sections: list[Section] = Field(default_factory=list)
    slide_indices: list[int] = Field(default_factory=list)


class Task(BaseModel):
    task_id: str
    source_kind: str
    status: TaskStatus = TaskStatus.PENDING
    stage: PipelineStage | None = None
    progress_pct: int = 0
    error: str | None = None
    result_path: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
