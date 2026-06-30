import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lecturelog.infrastructure.persistence.orm import Base
from lecturelog.infrastructure.youtube.pg_cookie_store import PgCookieStore


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_then_get_and_status(session_factory):
    store = PgCookieStore(session_factory=session_factory)
    assert await store.get() is None
    st = await store.status()
    assert st.exists is False

    await store.save(b"cookie-bytes")
    assert await store.get() == b"cookie-bytes"
    st = await store.status()
    assert st.exists is True
    assert st.size == len(b"cookie-bytes")
    assert st.updated_at is not None


@pytest.mark.asyncio
async def test_save_is_singleton_overwrite(session_factory):
    store = PgCookieStore(session_factory=session_factory)
    await store.save(b"first")
    await store.save(b"second")
    assert await store.get() == b"second"


@pytest.mark.asyncio
async def test_delete_is_idempotent(session_factory):
    store = PgCookieStore(session_factory=session_factory)
    await store.delete()  # на пустом — не падает
    await store.save(b"x")
    await store.delete()
    assert await store.get() is None
