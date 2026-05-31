from __future__ import annotations

from lecturelog.infrastructure.srt import parse_srt_time


def ffmpeg_timestamp(value: str) -> str:
    """SRT-таймкод (HH:MM:SS,mmm) → формат ffmpeg (HH:MM:SS.mmm)."""
    total_ms = max(0, int(round(parse_srt_time(value) * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
