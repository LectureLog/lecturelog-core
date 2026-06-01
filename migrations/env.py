import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

from lecturelog.infrastructure.persistence.orm import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    return os.environ["DATABASE_URL"]


def _is_async(url: str) -> bool:
    # Async-драйверы содержат "+aiosqlite" / "+asyncpg" и т.п. в схеме URL.
    scheme = url.split("://", 1)[0]
    return "+" in scheme and any(
        drv in scheme for drv in ("asyncpg", "aiosqlite", "aiomysql", "asyncmy")
    )


def run_migrations_offline() -> None:
    context.configure(url=_db_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync() -> None:
    engine = create_engine(_db_url())
    with engine.connect() as conn:
        _do_run(conn)
    engine.dispose()


async def _run_async() -> None:
    engine = create_async_engine(_db_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


def run_migrations_online() -> None:
    if _is_async(_db_url()):
        asyncio.run(_run_async())
    else:
        _run_sync()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
