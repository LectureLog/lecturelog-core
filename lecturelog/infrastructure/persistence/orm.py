from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.models import Task


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(32))
    # Ключ исходника в MinIO для последующей чистки при DELETE; NULL для не-s3 источников.
    source_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    result_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # Портативный JSON (а не JSONB) — guard-тест строит схему на SQLite.
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def task_to_row(task: Task) -> TaskRow:
    return TaskRow(
        task_id=task.task_id,
        source_kind=task.source_kind,
        source_key=task.source_key,
        status=task.status.value,
        stage=task.stage.value if task.stage else None,
        progress_pct=task.progress_pct,
        error=task.error,
        result_path=task.result_path,
        usage=task.usage,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def row_to_task(row: TaskRow) -> Task:
    return Task(
        task_id=row.task_id,
        source_kind=row.source_kind,
        source_key=row.source_key,
        status=TaskStatus(row.status),
        stage=PipelineStage(row.stage) if row.stage else None,
        progress_pct=row.progress_pct,
        error=row.error,
        result_path=row.result_path,
        usage=row.usage or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
