from __future__ import annotations

import asyncio
from pathlib import Path

from lecturelog.domain.models import Section
from lecturelog.domain.ports import MediaCutter
from lecturelog.infrastructure.media.ffmpeg_utils import ffmpeg_timestamp


class FfmpegAudioCutter(MediaCutter):
    """Реализация порта MediaCutter: нарезка аудио по секциям через ffmpeg."""

    async def cut(
        self,
        source_path: Path,
        sections: list[Section],
        output_dir: Path,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        result: list[Path] = []

        for idx, section in enumerate(sections):
            target = output_dir / f"section_{idx + 1:02d}.mp3"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-ss",
                ffmpeg_timestamp(section.start),
                "-to",
                ffmpeg_timestamp(section.end),
                "-vn",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(stderr.decode("utf-8", errors="ignore"))
            result.append(target)

        return result
