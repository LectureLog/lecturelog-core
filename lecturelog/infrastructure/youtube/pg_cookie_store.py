from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from lecturelog.domain.ports import CookieStatus, CookieStore
from lecturelog.infrastructure.persistence.orm import YoutubeCookieRow

# Singleton-строка всегда под этим id (см. CHECK id=1 в ORM/миграции).
_COOKIE_ID = 1


class PgCookieStore(CookieStore):
    """CookieStore поверх Postgres: одна строка youtube_cookies."""

    def __init__(self, *, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def save(self, content: bytes) -> CookieStatus:
        # Атомарный UPSERT: одна строка под фиксированным id=1. get-then-insert
        # уязвим к гонке (две параллельные save увидят None → второй упадёт на PK),
        # поэтому используем INSERT ... ON CONFLICT DO UPDATE. Диалект разный:
        # PostgreSQL в проде, SQLite в тестах — выбираем по имени диалекта.
        text = content.decode("utf-8")
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            dialect = session.bind.dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                stmt = pg_insert(YoutubeCookieRow).values(
                    id=_COOKIE_ID, content=text, updated_at=now
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[YoutubeCookieRow.id],
                    set_={"content": text, "updated_at": now},
                )
            else:
                # SQLite (тесты) — тот же ON CONFLICT через sqlite-диалект.
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                stmt = sqlite_insert(YoutubeCookieRow).values(
                    id=_COOKIE_ID, content=text, updated_at=now
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[YoutubeCookieRow.id],
                    set_={"content": text, "updated_at": now},
                )
            await session.execute(stmt)
            await session.commit()
        return CookieStatus(exists=True, updated_at=now, size=len(content))

    async def get(self) -> bytes | None:
        async with self._session_factory() as session:
            row = await session.get(YoutubeCookieRow, _COOKIE_ID)
            if row is None:
                return None
            return row.content.encode("utf-8")

    async def status(self) -> CookieStatus:
        async with self._session_factory() as session:
            row = await session.get(YoutubeCookieRow, _COOKIE_ID)
            if row is None:
                return CookieStatus(exists=False, updated_at=None, size=0)
            return CookieStatus(
                exists=True,
                updated_at=row.updated_at,
                size=len(row.content.encode("utf-8")),
            )

    async def delete(self) -> None:
        async with self._session_factory() as session:
            await session.execute(delete(YoutubeCookieRow).where(YoutubeCookieRow.id == _COOKIE_ID))
            await session.commit()
