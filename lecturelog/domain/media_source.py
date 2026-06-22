from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class AudioSource(BaseModel):
    kind: Literal["audio"] = "audio"
    path: Path


class VideoFileSource(BaseModel):
    kind: Literal["video_file"] = "video_file"
    path: Path


class VideoUrlSource(BaseModel):
    kind: Literal["video_url"] = "video_url"
    url: str


class S3ObjectSource(BaseModel):
    # Источник «дай ключ — заберу сам»: объект уже лежит в MinIO движка (uploads/).
    # media различает аудио/видео-ветку пайплайна (S3 не знает контента).
    kind: Literal["s3_object"] = "s3_object"
    key: str
    media: Literal["audio", "video"]


MediaSource = AudioSource | VideoFileSource | VideoUrlSource | S3ObjectSource


def is_video_source(source: MediaSource) -> bool:
    """Видеоисточник требует доп. шагов: ingest + извлечение аудиодорожки.
    Для s3_object видео-ветка определяется полем media (S3 не знает контента)."""
    if isinstance(source, S3ObjectSource):
        return source.media == "video"
    return source.kind in ("video_file", "video_url")
