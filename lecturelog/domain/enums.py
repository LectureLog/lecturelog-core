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
