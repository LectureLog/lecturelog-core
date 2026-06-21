from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from lecturelog.infrastructure.storage.s3_storage import S3Storage


def _ctx(client):
    # Фабрика клиента как async-контекст-менеджер (тот же контракт, что у aioboto3).
    @asynccontextmanager
    async def factory():
        yield client

    return factory


class StubClient:
    def __init__(self, url="http://minio:9000/b/results/x.zip?sig=1"):
        self._url = url
        self.captured = {}

    async def generate_presigned_url(self, op, Params, ExpiresIn):
        self.captured["op"] = op
        self.captured["Params"] = Params
        self.captured["exp"] = ExpiresIn
        return self._url


def _storage(public_endpoint=None, client=None):
    return S3Storage(
        internal_endpoint="http://minio:9000",
        public_endpoint=public_endpoint,
        bucket="b",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
        default_expiry=3600,
        client_factory=_ctx(client) if client is not None else None,
    )


def test_presigned_get_without_public_endpoint_returns_none():
    # Без публичного endpoint presigned наружу не выдаётся.
    s = _storage(public_endpoint=None, client=StubClient())
    assert asyncio.run(s.presigned_get("results/x.zip")) is None


def test_presigned_get_overrides_and_public_host():
    client = StubClient(url="http://minio:9000/b/results/x.zip?sig=1")
    s = _storage(public_endpoint="https://files.example", client=client)
    url = asyncio.run(
        s.presigned_get("results/x.zip", download_filename="Лекция", content_type="application/zip")
    )
    assert url.startswith("https://files.example/")  # хост подменён
    assert "minio:9000" not in url
    assert url.endswith("/b/results/x.zip?sig=1")  # path+query сохранены (та же подпись)
    assert client.captured["op"] == "get_object"
    assert client.captured["Params"]["Bucket"] == "b"
    assert client.captured["Params"]["Key"] == "results/x.zip"
    assert (
        client.captured["Params"]["ResponseContentDisposition"]
        == 'attachment; filename="Лекция.zip"'
    )
    assert client.captured["Params"]["ResponseContentType"] == "application/zip"


def test_presigned_put_uses_public_host():
    client = StubClient(url="http://minio:9000/b/uploads/abc/lecture.mp3?sig=2")
    s = _storage(public_endpoint="https://files.example", client=client)
    url = asyncio.run(s.presigned_put("uploads/abc/lecture.mp3"))
    assert url.startswith("https://files.example/")
    assert "minio:9000" not in url
    assert client.captured["op"] == "put_object"
    assert client.captured["Params"]["Bucket"] == "b"
    assert client.captured["Params"]["Key"] == "uploads/abc/lecture.mp3"


def test_presigned_put_without_public_endpoint_returns_none():
    s = _storage(public_endpoint=None, client=StubClient())
    assert asyncio.run(s.presigned_put("uploads/abc/lecture.mp3")) is None


def test_upload_download_roundtrip(tmp_path):
    # upload_file/download_file проходят через client_factory; стаб хранит байты в dict.
    store: dict[str, bytes] = {}

    class IOStub:
        async def upload_file(self, Filename, Bucket, Key):
            with open(Filename, "rb") as f:
                store[Key] = f.read()

        async def download_file(self, Bucket, Key, Filename):
            with open(Filename, "wb") as f:
                f.write(store[Key])

    src = tmp_path / "src.bin"
    src.write_bytes(b"payload")
    s = _storage(client=IOStub())
    asyncio.run(s.upload_file(src, "results/t/result.zip"))
    assert store["results/t/result.zip"] == b"payload"

    dst = tmp_path / "nested" / "out.bin"
    asyncio.run(s.download_file("results/t/result.zip", dst))
    assert dst.read_bytes() == b"payload"
