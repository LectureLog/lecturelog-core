"""Управление YouTube-cookies ядра из командной строки.

Запуск внутри окружения ядра (есть доступ к БД через DATABASE_URL):
    python -m scripts.cookies set ./cookies.txt
    python -m scripts.cookies status
    python -m scripts.cookies clear
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from lecturelog.config.settings import get_config
from lecturelog.domain.ports import CookieStore
from lecturelog.infrastructure.persistence.engine import (
    make_engine,
    make_session_factory,
)
from lecturelog.infrastructure.youtube.cookie_validation import (
    InvalidCookieFormat,
    validate_netscape_cookies,
)
from lecturelog.infrastructure.youtube.pg_cookie_store import PgCookieStore


async def cmd_set(store: CookieStore, path: str) -> None:
    content = Path(path).read_bytes()
    try:
        validate_netscape_cookies(content)
    except InvalidCookieFormat as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    st = await store.save(content)
    print(f"Cookies сохранены: {st.size} байт")


async def cmd_status(store: CookieStore) -> None:
    st = await store.status()
    if st.exists:
        print(f"Cookies загружены: {st.size} байт, обновлены {st.updated_at}")
    else:
        print("Cookies не загружены")


async def cmd_clear(store: CookieStore) -> None:
    await store.delete()
    print("Cookies удалены")


def _build_store() -> tuple[CookieStore, object]:
    cfg = get_config()
    engine = make_engine(cfg.database.url)
    factory = make_session_factory(engine)
    return PgCookieStore(session_factory=factory), engine


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="YouTube cookies ядра")
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set", help="загрузить cookies.txt")
    p_set.add_argument("path")
    sub.add_parser("status", help="показать статус")
    sub.add_parser("clear", help="удалить cookies")
    args = parser.parse_args(argv)

    async def run() -> None:
        store, engine = _build_store()
        try:
            if args.command == "set":
                await cmd_set(store, args.path)
            elif args.command == "status":
                await cmd_status(store)
            elif args.command == "clear":
                await cmd_clear(store)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
