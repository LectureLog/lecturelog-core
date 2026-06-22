from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from lecturelog.domain.models import Task


class CreateTaskResponse(BaseModel):
    task_id: str


class UploadUrlRequest(BaseModel):
    # Имя исходного файла; используется как хвост ключа uploads/<uuid>/<filename>.
    filename: str


class UploadUrlResponse(BaseModel):
    key: str
    url: str
    expires_in: int


class ResultUrlResponse(BaseModel):
    url: str
    expires_in: int


class TranscribeUsage(BaseModel):
    # Зерно стадии транскрибации. model опционально: ранние записи могут его не нести.
    audio_seconds: int
    provider: str
    model: str | None = None
    raw: dict = {}


class ByModelEntry(BaseModel):
    # Расход одной LLM-модели в рамках стадии.
    prompt: int
    output: int
    calls: int


class StageUsage(BaseModel):
    # LLM-стадия (structurize/video_slides) с разбивкой by_model.
    provider: str
    by_model: dict[str, ByModelEntry] = {}
    raw: dict = {}


class TotalUsage(BaseModel):
    # Свёртка движком по стадиям + две оси режима.
    audio_seconds: int
    gemini_prompt: int
    gemini_output: int
    source: Literal["audio", "video"]
    slides_origin: Literal["none", "document", "video_extracted"]


class Usage(BaseModel):
    # Контейнер usage. Все стадии опциональны: до обработки и в зависимости от
    # режима отдельные стадии могут отсутствовать.
    transcribe: TranscribeUsage | None = None
    structurize: StageUsage | None = None
    video_slides: StageUsage | None = None
    total: TotalUsage | None = None


class ErrorResponse(BaseModel):
    # Стандартная форма ошибки FastAPI/глобальных обработчиков: {"detail": "..."}.
    detail: str


class TaskStatusResponse(BaseModel):
    task_id: str
    stage: str | None
    progress_pct: int
    error: str | None
    result_path: str | None
    usage: Usage = Usage()

    @classmethod
    def from_task(cls, task: Task) -> TaskStatusResponse:
        return cls(
            task_id=task.task_id,
            stage=task.stage.value if task.stage else None,
            progress_pct=task.progress_pct,
            error=task.error,
            result_path=task.result_path,
            # Пустой usage ({}) валидируется в Usage() со всеми None-полями.
            usage=Usage.model_validate(task.usage or {}),
        )
