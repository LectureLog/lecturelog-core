from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import aioboto3
from aiobotocore.config import AioConfig

from lecturelog.domain.ports import Storage

# Тип фабрики boto-клиента: вызывается без аргументов, возвращает async-контекст-менеджер.
ClientFactory = Callable[[], AbstractAsyncContextManager]

# Конфиг подписи для свежих MinIO/S3: SigV4 (AWS4-HMAC-SHA256) вместо legacy SigV2
# и path-style адресация (MinIO не отдаёт virtual-hosted-стиль). AioConfig — подкласс
# botocore Config, нужный aiobotocore.
_S3V4_CONFIG = AioConfig(signature_version="s3v4", s3={"addressing_style": "path"})


class S3Storage(Storage):
    """Инфра-адаптер хранилища лекций на aioboto3.

    Сетевые операции (upload/download/list/delete) идут на INTERNAL endpoint —
    внутри docker-сети. Presigned-ссылки подписываются СРАЗУ под PUBLIC endpoint:
    в SigV4 Host входит в canonical request, поэтому пост-подмену хоста делать
    нельзя — она ломает подпись. generate_presigned_url считает подпись локально,
    без сетевых запросов, так что доступность public-хоста из контейнера не нужна.
    Без public_endpoint presigned не выдаётся (None) — безопасный дефолт автономии:
    наружу ходит только стрим GET /result.
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
        presign_client_factory: ClientFactory | None = None,
    ):
        self._internal_endpoint = internal_endpoint
        self._public_endpoint = public_endpoint
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._default_expiry = default_expiry
        # DI для тестов: по умолчанию строим реальный aioboto3-клиент на internal endpoint.
        self._client_factory = client_factory or self._default_client_factory
        # Отдельная фабрика для presigned: клиент на PUBLIC endpoint (подпись под публичный
        # хост). Переопределяется в тестах; в проде строится из _default_presign_factory.
        self._presign_client_factory = presign_client_factory or self._default_presign_factory

    def _build_factory(self, endpoint: str) -> AbstractAsyncContextManager:
        # Реальный клиент на заданном endpoint с SigV4 + path-style.
        session = aioboto3.Session()

        @asynccontextmanager
        async def factory():
            async with session.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
                config=_S3V4_CONFIG,
            ) as client:
                yield client

        return factory()

    def _default_client_factory(self) -> AbstractAsyncContextManager:
        # Клиент для сетевых операций — internal endpoint (внутри docker-сети).
        return self._build_factory(self._internal_endpoint)

    def _default_presign_factory(self) -> AbstractAsyncContextManager:
        # Клиент для presigned — public endpoint (подпись сразу под публичный хост).
        return self._build_factory(self._public_endpoint)

    async def upload_file(self, local_path: Path, key: str) -> None:
        async with self._client_factory() as client:
            await client.upload_file(Filename=str(local_path), Bucket=self._bucket, Key=key)

    async def download_file(self, key: str, local_path: Path) -> None:
        # Гарантируем существование родительских каталогов для целевого файла.
        local_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._client_factory() as client:
            await client.download_file(Bucket=self._bucket, Key=key, Filename=str(local_path))

    async def presigned_put(self, key: str, expires_in: int | None = None) -> str | None:
        # Falsy-проверка: пустая строка (S3_PUBLIC_ENDPOINT=) тоже означает «не задан».
        # Без public_endpoint presign-клиент не строим — наружу ничего не выдаём.
        if not self._public_endpoint:
            return None
        params = {"Bucket": self._bucket, "Key": key}
        # Подпись считается под public endpoint (presign-фабрика), хост уже публичный.
        async with self._presign_client_factory() as client:
            url = await client.generate_presigned_url(
                "put_object",
                Params=params,
                ExpiresIn=expires_in or self._default_expiry,
            )
        return url

    async def presigned_get(
        self,
        key: str,
        expires_in: int | None = None,
        download_filename: str | None = None,
        content_type: str | None = None,
    ) -> str | None:
        # Falsy-проверка: пустая строка (S3_PUBLIC_ENDPOINT=) тоже означает «не задан».
        # Без public_endpoint presign-клиент не строим — наружу ничего не выдаём.
        if not self._public_endpoint:
            return None
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        # Override-заголовки ответа: заставляем браузер скачать как attachment с
        # человекочитаемым именем .zip и правильным content-type.
        if download_filename is not None:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_filename}.zip"'
        if content_type is not None:
            params["ResponseContentType"] = content_type
        # Подпись считается под public endpoint (presign-фабрика), хост уже публичный.
        async with self._presign_client_factory() as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in or self._default_expiry,
            )
        return url

    async def delete_prefix(self, prefix: str) -> None:
        # Идемпотентная чистка: листаем все объекты под префиксом (с пагинацией)
        # и батч-удаляем. Пустой префикс -> delete_objects не вызываем (no-op).
        # В aiobotocore get_paginator синхронный (не awaitable), paginate() даёт
        # async-итератор по страницам.
        async with self._client_factory() as client:
            paginator = client.get_paginator("list_objects_v2")
            keys: list[dict[str, str]] = []
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append({"Key": obj["Key"]})
                    # S3 delete_objects ограничен 1000 ключами на запрос.
                    if len(keys) == 1000:
                        await client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})
                        keys = []
            if keys:
                await client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})

    async def list_keys(self, prefix: str) -> list[str]:
        # Листинг с пагинацией: собираем obj["Key"] со всех страниц.
        # Страница без Contents (пустой префикс) не должна падать — отсюда get("Contents", []).
        async with self._client_factory() as client:
            paginator = client.get_paginator("list_objects_v2")
            keys: list[str] = []
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
            return keys
