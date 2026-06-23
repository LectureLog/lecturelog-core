from __future__ import annotations

import pytest

from lecturelog.domain.ports import Storage
from tests.support.fake_storage import FakeStorage


def test_fake_storage_is_storage():
    assert isinstance(FakeStorage(), Storage)


@pytest.mark.asyncio
async def test_upload_download_roundtrip(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"payload")
    s = FakeStorage()
    await s.upload_file(src, "results/t/result.zip")
    assert s.objects["results/t/result.zip"] == b"payload"

    dst = tmp_path / "nested" / "out.bin"
    await s.download_file("results/t/result.zip", dst)
    assert dst.read_bytes() == b"payload"


@pytest.mark.asyncio
async def test_presigned_none_without_public():
    s = FakeStorage(public=False)
    assert await s.presigned_put("uploads/a/x.mp3") is None
    assert await s.presigned_get("results/t/result.zip") is None


@pytest.mark.asyncio
async def test_presigned_contains_key_and_filename():
    s = FakeStorage(public=True)
    put = await s.presigned_put("uploads/a/x.mp3")
    assert put is not None and "uploads/a/x.mp3" in put

    get = await s.presigned_get("results/t/result.zip", download_filename="Лекция")
    assert get is not None and "results/t/result.zip" in get
    assert "Лекция" in get


@pytest.mark.asyncio
async def test_delete_prefix_removes_matching_and_is_idempotent(tmp_path):
    s = FakeStorage()
    src = tmp_path / "x.bin"
    src.write_bytes(b"d")
    await s.upload_file(src, "results/t/result.zip")
    await s.upload_file(src, "results/t/extra.png")
    await s.upload_file(src, "uploads/u/lecture.mp3")

    await s.delete_prefix("results/t/")
    assert "results/t/result.zip" not in s.objects
    assert "results/t/extra.png" not in s.objects
    assert "uploads/u/lecture.mp3" in s.objects  # чужой префикс не тронут

    # Идемпотентность: повтор по уже пустому префиксу не падает.
    await s.delete_prefix("results/t/")
    await s.delete_prefix("nothing/here/")


@pytest.mark.asyncio
async def test_list_keys_returns_matching_sorted_and_idempotent(tmp_path):
    s = FakeStorage()
    src = tmp_path / "x.bin"
    src.write_bytes(b"d")
    await s.upload_file(src, "results/t/output/b.txt")
    await s.upload_file(src, "results/t/output/a.txt")
    await s.upload_file(src, "uploads/u/lecture.mp3")

    keys = await s.list_keys("results/t/")
    # Только ключи с искомым префиксом, отсортированы; чужой префикс не попадает.
    assert keys == ["results/t/output/a.txt", "results/t/output/b.txt"]

    # Пустой результат -> [].
    assert await s.list_keys("nothing/here/") == []
