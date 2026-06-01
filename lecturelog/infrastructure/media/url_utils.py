from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


def is_url(source: str | Path) -> bool:
    """URL = http/https-схема + непустой netloc. Путь/Path → False."""
    if not isinstance(source, str):
        return False
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
