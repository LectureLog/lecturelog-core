from __future__ import annotations


def timestamp_to_seconds(ts: str) -> int:
    """MM:SS или HH:MM:SS → секунды (целые)."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(parts[0])


def seconds_to_timestamp(sec: int) -> str:
    """Секунды → MM:SS (или HH:MM:SS если ≥ 1 час)."""
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
