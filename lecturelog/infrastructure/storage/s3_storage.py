from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import aioboto3

from lecturelog.domain.ports import Storage

# Тип фабрики boto-клиента: вызывается без аргументов, возвращает async-контекст-менеджер.
ClientFactory = Callable[[], AbstractAsyncContextManager]


class S3Storage(Storage):
    """Инфра-адаптер хранилища лекций на aioboto3.

    Подпись presigned-ссылок делается по INTERNAL endpoint (движок ходит внутри
    docker-сети), затем хост подменяется на PUBLIC для отдачи браузеру — путь и
    query (а значит подпись) сохраняются. Без public_endpoint presigned не выдаётся
    (None) — безопасный дефолт автономии: наружу ходит только стрим GET /result.
    """

    def __init__(
        self,
        *,
        internal_endpoint: str,
        public_endpoint: str | None,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        default_expiry: int = 3600,
        client_factory: ClientFactory | None = None,
    ):
        self._internal_endpoint = internal_endpoint
        self._public_endpoint = public_endpoint
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._default_expiry = default_expiry
        # DI для тестов: по умолчанию строим реальный aioboto3-клиент.
        self._client_factory = client_factory or self._default_client_factory

    def _default_client_factory(self) -> AbstractAsyncContextManager:
        # Реальный клиент на internal endpoint (подпись/обмен — внутри docker-сети).
        session = aioboto3.Session()

        @asynccontextmanager
        async def factory():
            async with session.client(
                "s3",
                endpoint_url=self._internal_endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
            ) as client:
                yield client

        return factory()

    def _swap_host(self, url: str) -> str:
        """Подменить scheme+netloc на публичный endpoint, сохранив path/query (и подпись)."""
        pub = urlparse(self._public_endpoint)
        parsed = urlparse(url)
        return urlunparse(
            (pub.scheme, pub.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )

    async def upload_file(self, local_path: Path, key: str) -> None:
        async with self._client_factory() as client:
            await client.upload_file(Filename=str(local_path), Bucket=self._bucket, Key=key)

    async def download_file(self, key: str, local_path: Path) -> None:
        # Гарантируем существование родительских каталогов для целевого файла.
        local_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._client_factory() as client:
            await client.download_file(Bucket=self._bucket, Key=key, Filename=str(local_path))

    async def presigned_put(self, key: str, expires_in: int | None = None) -> str | None:
        # Falsy-проверка: пустая строка (S3_PUBLIC_ENDPOINT=) тоже означает «не задан»,
        # иначе _swap_host подставит пустые scheme/netloc → сломанный URL.
        if not self._public_endpoint:
            return None
        params = {"Bucket": self._bucket, "Key": key}
        async with self._client_factory() as client:
            url = await client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expires_in or self._default_expiry,
            )
        return self._swap_host(url)

    async def presigned_get(
        self,
        key: str,
        expires_in: int | None = None,
        download_filename: str | None = None,
        content_type: str | None = None,
    ) -> str | None:
        # Falsy-проверка: пустая строка (S3_PUBLIC_ENDPOINT=) тоже означает «не задан».
        if not self._public_endpoint:
            return None
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        # Override-заголовки ответа: заставляем браузер скачать как attachment с
        # человекочитаемым именем .zip и правильным content-type.
        if download_filename is not None:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_filename}.zip"'
        if content_type is not None:
            params["ResponseContentType"] = content_type
        async with self._client_factory() as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in or self._default_expiry,
            )
        return self._swap_host(url)
