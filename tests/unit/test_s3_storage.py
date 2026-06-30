from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

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


def _storage(public_endpoint=None, client=None, presign_client=None):
    # client — стаб для сетевых операций (internal endpoint);
    # presign_client — стаб для presigned-ссылок (public endpoint). Если presign_client
    # не задан, presigned-методы переиспользуют client (как было до разделения фабрик).
    presign = presign_client if presign_client is not None else client
    return S3Storage(
        internal_endpoint="http://minio:9000",
        public_endpoint=public_endpoint,
        bucket="b",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
        default_expiry=3600,
        client_factory=_ctx(client) if client is not None else None,
        presign_client_factory=_ctx(presign) if presign is not None else None,
    )


def test_presigned_get_without_public_endpoint_returns_none():
    # Без публичного endpoint presigned наружу не выдаётся.
    s = _storage(public_endpoint=None, client=StubClient())
    assert asyncio.run(s.presigned_get("results/x.zip")) is None


def test_presigned_get_overrides_and_public_host():
    # presign-клиент подписывает сразу под public endpoint — хост в URL уже публичный,
    # пост-подмены нет (она ломала бы SigV4-подпись).
    client = StubClient(url="https://files.example/b/results/x.zip?sig=1")
    s = _storage(public_endpoint="https://files.example", presign_client=client)
    url = asyncio.run(
        s.presigned_get("results/x.zip", download_filename="Лекция", content_type="application/zip")
    )
    assert url.startswith("https://files.example/")  # подписано под публичный хост
    assert "minio:9000" not in url
    assert url == "https://files.example/b/results/x.zip?sig=1"  # URL отдаётся как есть
    assert client.captured["op"] == "get_object"
    assert client.captured["Params"]["Bucket"] == "b"
    assert client.captured["Params"]["Key"] == "results/x.zip"
    assert (
        client.captured["Params"]["ResponseContentDisposition"]
        == 'attachment; filename="Лекция.zip"'
    )
    assert client.captured["Params"]["ResponseContentType"] == "application/zip"


def test_presigned_put_uses_public_host():
    # presign-клиент подписывает под public endpoint — URL уже с публичным хостом.
    client = StubClient(url="https://files.example/b/uploads/abc/lecture.mp3?sig=2")
    s = _storage(public_endpoint="https://files.example", presign_client=client)
    url = asyncio.run(s.presigned_put("uploads/abc/lecture.mp3"))
    assert url == "https://files.example/b/uploads/abc/lecture.mp3?sig=2"
    assert "minio:9000" not in url
    assert client.captured["op"] == "put_object"
    assert client.captured["Params"]["Bucket"] == "b"
    assert client.captured["Params"]["Key"] == "uploads/abc/lecture.mp3"


def test_presigned_put_without_public_endpoint_returns_none():
    s = _storage(public_endpoint=None, client=StubClient())
    assert asyncio.run(s.presigned_put("uploads/abc/lecture.mp3")) is None


def test_presigned_get_with_empty_public_endpoint_returns_none():
    # Пустая строка (S3_PUBLIC_ENDPOINT=) — это «не задан», а не валидный хост.
    s = _storage(public_endpoint="", client=StubClient())
    assert asyncio.run(s.presigned_get("results/x.zip")) is None


def test_presigned_put_with_empty_public_endpoint_returns_none():
    s = _storage(public_endpoint="", client=StubClient())
    assert asyncio.run(s.presigned_put("uploads/abc/lecture.mp3")) is None


def test_presigned_url_is_sigv4_and_public_host():
    # Без DI-фабрики используется реальный aioboto3-клиент: проверяем, что presigned URL
    # подписан по SigV4 (AWS4-HMAC-SHA256) под публичным хостом, а не legacy SigV2.
    s = S3Storage(
        internal_endpoint="http://lecturelog-core-minio:9000",
        public_endpoint="https://s3.lecturelog.sarvizza.com",
        bucket="lectures",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
        default_expiry=900,
    )
    url = asyncio.run(s.presigned_put("uploads/abc/lecture.mp3"))
    # SigV4-маркеры присутствуют.
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
    assert "X-Amz-Credential=" in url
    assert "X-Amz-Signature=" in url
    # Legacy SigV2-параметры отсутствуют.
    assert "AWSAccessKeyId=" not in url
    # Хост публичный, internal не светится; path-style (bucket в пути).
    assert url.startswith("https://s3.lecturelog.sarvizza.com/lectures/uploads/abc/lecture.mp3")
    assert "lecturelog-core-minio" not in url
    # expires_in прокидывается в подпись (default_expiry=900).
    assert "X-Amz-Expires=900" in url


def test_default_presign_factory_without_public_endpoint_raises():
    # Прямой вызов presign-фабрики без public_endpoint должен явно падать ValueError,
    # а не отдавать тёмную ошибку botocore про endpoint_url=None.
    s = _storage(public_endpoint=None)
    with pytest.raises(ValueError):
        s._default_presign_factory()


def test_presigned_methods_without_public_endpoint_still_return_none():
    # Контракт fail-fast в фабрике НЕ должен сломать ранний return None:
    # presigned-методы при public_endpoint=None по-прежнему возвращают None и фабрику не дёргают.
    s = _storage(public_endpoint=None)
    assert asyncio.run(s.presigned_put("uploads/abc/lecture.mp3")) is None
    assert asyncio.run(s.presigned_get("results/x.zip")) is None


def test_default_client_factory_uses_internal_endpoint():
    # Сетевые операции идут на internal endpoint: реальный aioboto3-клиент офлайн,
    # читаем endpoint_url из client.meta (сети не требует).
    internal = "http://lecturelog-core-minio:9000"
    s = S3Storage(
        internal_endpoint=internal,
        public_endpoint="https://s3.lecturelog.sarvizza.com",
        bucket="lectures",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
    )

    async def _check():
        async with s._default_client_factory() as client:
            # botocore может нормализовать trailing slash — сравниваем без него.
            assert client.meta.endpoint_url.rstrip("/") == internal.rstrip("/")

    asyncio.run(_check())


def test_default_presign_factory_uses_public_endpoint():
    # Presigned-ссылки подписываются под public endpoint: тот же офлайн-приём с client.meta.
    public = "https://s3.lecturelog.sarvizza.com"
    s = S3Storage(
        internal_endpoint="http://lecturelog-core-minio:9000",
        public_endpoint=public,
        bucket="lectures",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
    )

    async def _check():
        async with s._default_presign_factory() as client:
            assert client.meta.endpoint_url.rstrip("/") == public.rstrip("/")

    asyncio.run(_check())


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


def test_delete_prefix_lists_and_deletes_all(tmp_path):
    # get_paginator в aiobotocore синхронный (не awaitable); paginate() -> async-итератор.
    listed = []
    deleted = []

    class _Pages:
        def __aiter__(self):
            async def gen():
                yield {
                    "Contents": [
                        {"Key": "results/t/result.zip"},
                        {"Key": "results/t/a.png"},
                    ]
                }
                yield {}  # страница без Contents — не должна падать

            return gen()

    class _Paginator:
        def paginate(self, Bucket, Prefix):
            listed.append((Bucket, Prefix))
            return _Pages()

    class DelStub:
        def get_paginator(self, op):
            assert op == "list_objects_v2"
            return _Paginator()

        async def delete_objects(self, Bucket, Delete):
            deleted.append((Bucket, [o["Key"] for o in Delete["Objects"]]))

    s = _storage(client=DelStub())
    asyncio.run(s.delete_prefix("results/t/"))
    assert listed == [("b", "results/t/")]
    assert deleted == [("b", ["results/t/result.zip", "results/t/a.png"])]


def test_delete_prefix_empty_is_noop(tmp_path):
    deleted = []

    class _EmptyPages:
        def __aiter__(self):
            async def gen():
                yield {}

            return gen()

    class _EmptyPaginator:
        def paginate(self, Bucket, Prefix):
            return _EmptyPages()

    class DelStub:
        def get_paginator(self, op):
            return _EmptyPaginator()

        async def delete_objects(self, Bucket, Delete):
            deleted.append(Delete)

    s = _storage(client=DelStub())
    asyncio.run(s.delete_prefix("results/none/"))
    assert deleted == []  # нечего удалять — delete_objects не вызывается


def test_list_keys_paginates_and_collects(tmp_path):
    # Пагинация: ключи собираются со всех страниц; страница без Contents не падает.
    listed = []

    class _Pages:
        def __aiter__(self):
            async def gen():
                yield {"Contents": [{"Key": "results/t/output/a.txt"}]}
                yield {}  # страница без Contents — не должна падать
                yield {"Contents": [{"Key": "results/t/output/b.txt"}]}

            return gen()

    class _Paginator:
        def paginate(self, Bucket, Prefix):
            listed.append((Bucket, Prefix))
            return _Pages()

    class ListStub:
        def get_paginator(self, op):
            assert op == "list_objects_v2"
            return _Paginator()

    s = _storage(client=ListStub())
    keys = asyncio.run(s.list_keys("results/t/"))
    assert listed == [("b", "results/t/")]
    assert keys == ["results/t/output/a.txt", "results/t/output/b.txt"]


def test_list_keys_empty_returns_empty_list(tmp_path):
    class _EmptyPages:
        def __aiter__(self):
            async def gen():
                yield {}

            return gen()

    class _EmptyPaginator:
        def paginate(self, Bucket, Prefix):
            return _EmptyPages()

    class ListStub:
        def get_paginator(self, op):
            return _EmptyPaginator()

    s = _storage(client=ListStub())
    assert asyncio.run(s.list_keys("results/none/")) == []
