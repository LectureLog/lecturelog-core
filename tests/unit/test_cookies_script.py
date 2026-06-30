import asyncio

import pytest

from lecturelog.domain.ports import CookieStatus, CookieStore

import scripts.cookies as cookies_cli


class FakeStore(CookieStore):
    def __init__(self):
        self._c = None
    async def save(self, content):
        self._c = content
        return CookieStatus(exists=True, updated_at=None, size=len(content))
    async def get(self):
        return self._c
    async def status(self):
        return CookieStatus(exists=self._c is not None, updated_at=None,
                            size=len(self._c or b""))
    async def delete(self):
        self._c = None


def test_cmd_set_reads_validates_saves(tmp_path):
    f = tmp_path / "c.txt"
    f.write_bytes(b"# Netscape HTTP Cookie File\n")
    store = FakeStore()
    asyncio.run(cookies_cli.cmd_set(store, str(f)))
    assert asyncio.run(store.get()) == b"# Netscape HTTP Cookie File\n"


def test_cmd_set_rejects_garbage(tmp_path):
    f = tmp_path / "c.txt"
    f.write_bytes(b"<html></html>")
    store = FakeStore()
    with pytest.raises(SystemExit):
        asyncio.run(cookies_cli.cmd_set(store, str(f)))


def test_cmd_clear(tmp_path):
    store = FakeStore()
    asyncio.run(store.save(b"# Netscape HTTP Cookie File\n"))
    asyncio.run(cookies_cli.cmd_clear(store))
    assert asyncio.run(store.get()) is None
