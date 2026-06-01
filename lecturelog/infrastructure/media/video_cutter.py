from __future__ import annotations

import asyncio
from pathlib import Path

from lecturelog.domain.models import Section
from lecturelog.domain.ports import MediaCutter
from lecturelog.infrastructure.media.ffmpeg_utils import ffmpeg_timestamp

# Известные видеоконтейнеры, чьё расширение наследует фрагмент.
_KNOWN_CONTAINERS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}
# Контейнеры, для которых -movflags +faststart безопасен (H.264/AAC).
_MP4_SAFE_SUFFIXES = {".mp4", ".m4v", ".mov"}


def _fragment_suffix_and_flags(video_suffix: str) -> tuple[str, list[str]]:
    """По расширению исходного видео вернуть (суффикс фрагмента, extra-флаги ffmpeg)."""
    suffix = video_suffix.lower()
    if suffix not in _KNOWN_CONTAINERS:
        suffix = ".mp4"
    extra_flags: list[str] = []
    if suffix in _MP4_SAFE_SUFFIXES:
        extra_flags = ["-movflags", "+faststart"]
    return suffix, extra_flags


class FfmpegVideoCutter(MediaCutter):
    """Реализация порта MediaCutter: нарезка видео по секциям через ffmpeg.

    Использует -c copy для скорости. Если на границе нет keyframe — фрагмент
    может начинаться чуть позже start; для нашей задачи это допустимо.

    Контейнер фрагмента наследуется от исходного видео (mp4/webm/mkv), чтобы
    избежать ошибки "codec not currently supported in container" при перепаковке
    VP9/Opus → mp4.
    """

    async def cut(
        self,
        source_path: Path,
        sections: list[Section],
        output_dir: Path,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        result: list[Path] = []

        suffix, extra_flags = _fragment_suffix_and_flags(source_path.suffix)

        for idx, section in enumerate(sections):
            target = output_dir / f"section_{idx + 1:02d}{suffix}"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-ss", ffmpeg_timestamp(section.start),
                "-to", ffmpeg_timestamp(section.end),
                "-i", str(source_path),
                "-c", "copy",
                *extra_flags,
                str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(stderr.decode("utf-8", errors="ignore"))
            result.append(target)

        return result
