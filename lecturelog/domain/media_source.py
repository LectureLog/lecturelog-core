from __future__ import annotations

from pathlib import Path
from typing import Literal, Union

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


MediaSource = Union[AudioSource, VideoFileSource, VideoUrlSource]


def is_video_source(source: MediaSource) -> bool:
    """Видеоисточник требует доп. шагов: ingest + извлечение аудиодорожки."""
    return source.kind in ("video_file", "video_url")
