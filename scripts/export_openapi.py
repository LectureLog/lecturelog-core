#!/usr/bin/env python3
"""Детерминированный экспорт встроенного OpenAPI в docs/openapi.json.

Работает без реальных секретов/БД/MinIO: ставит env-заглушки для required-полей
конфига ДО построения приложения. openapi.json — источник правды для генерации
типизированного клиента в platform-api.

Локальный запуск:
    python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Заглушки required-полей конфига. Ставим ДО импорта приложения: get_config()
# кэширован (@lru_cache), а валидация под-конфигов происходит при построении app.
_ENV_STUBS = {
    "GROQ_API_KEYS": "stub",
    "GEMINI_API_KEYS": "stub",
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "S3_INTERNAL_ENDPOINT": "http://stub:9000",
    "S3_BUCKET": "stub",
    "S3_ACCESS_KEY": "stub",
    "S3_SECRET_KEY": "stub",
}
for _key, _value in _ENV_STUBS.items():
    os.environ.setdefault(_key, _value)

# Импорт ПОСЛЕ установки заглушек.
from lecturelog.api.app import create_app  # noqa: E402

_OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


def build_openapi_bytes() -> bytes:
    """Построить детерминированные байты openapi.json (стабильный git diff)."""
    schema = create_app().openapi()
    text = json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def main() -> None:
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_bytes(build_openapi_bytes())
    print(f"openapi.json записан: {_OUTPUT}")


if __name__ == "__main__":
    main()
