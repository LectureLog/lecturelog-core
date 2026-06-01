from __future__ import annotations

import json
from typing import Any

DEDUP_THRESHOLD_SEC = 10


def parse_json_response(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


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


def merge_and_dedup(chunks_slides: list[list[dict]]) -> list[dict]:
    """Сплющить слайды всех чанков, отсортировать по времени, убрать дубли
    в пределах DEDUP_THRESHOLD_SEC (оставив последний), проставить index."""
    all_slides = [s for chunk in chunks_slides for s in chunk]

    def sec(s: dict) -> int:
        try:
            return timestamp_to_seconds(s.get("timestamp_finalized", "00:00"))
        except ValueError:
            return 0

    all_slides.sort(key=sec)
    result: list[dict] = []
    for slide in all_slides:
        cur = sec(slide)
        if result and abs(cur - sec(result[-1])) <= DEDUP_THRESHOLD_SEC:
            result[-1] = slide
        else:
            result.append(slide)
    for i, slide in enumerate(result, 1):
        slide["index"] = i
    return result
