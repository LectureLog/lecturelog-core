from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from lecturelog.domain.enums import ErrorCode, PipelineStage, TaskStatus


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


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
    # Ключ исходника в MinIO (uploads/<uuid>/<file>) для s3_object-источника.
    # Сохраняется при создании задачи, чтобы DELETE мог удалить исходник.
    # Для остальных kind (audio/video/video_url) — None.
    source_key: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    stage: PipelineStage | None = None
    progress_pct: int = 0
    error: str | None = None
    # Машинный код ошибки (классифицируется при переходе в FAILED). None — нет ошибки.
    error_code: ErrorCode | None = None
    result_path: str | None = None
    usage: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
