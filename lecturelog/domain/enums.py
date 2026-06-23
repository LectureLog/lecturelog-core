from __future__ import annotations

from enum import StrEnum


class PipelineStage(StrEnum):
    VIDEO_INGEST = "video_ingest"
    AUDIO_EXTRACT = "audio_extract"
    TRANSCRIBE = "transcribe"
    SLIDES = "slides"
    VIDEO_SLIDES = "video_slides"
    STRUCTURIZE = "structurize"
    AUDIO_CUT = "audio_cut"
    VIDEO_CUT = "video_cut"
    EXPORT = "export"


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ErrorCode(StrEnum):
    # Повторяемая ошибка: лимит Gemini/Groq (429 / RESOURCE_EXHAUSTED / 503 / UNAVAILABLE).
    RATE_LIMIT = "rate_limit"
    # Вход битый/не распознан: retry бесполезен (нет файла, неподдерживаемый формат).
    BAD_INPUT = "bad_input"
    # Всё прочее (дефолт): неклассифицированный внутренний сбой ядра.
    INTERNAL = "internal"
