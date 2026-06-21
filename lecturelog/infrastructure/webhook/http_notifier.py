from __future__ import annotations

import hashlib
import hmac
import json
import logging

import httpx

from lecturelog.domain.enums import TaskStatus
from lecturelog.domain.ports import WebhookNotifier

logger = logging.getLogger(__name__)

# Заголовок с HMAC-подписью тела; платформа сверяет его своим экземпляром секрета.
SIGNATURE_HEADER = "X-Webhook-Signature"


def build_signed_request(
    callback_url: str,
    secret: str,
    task_id: str,
    status: TaskStatus,
    error: str | None,
) -> tuple[bytes, str]:
    """Собрать тонкое тело и его HMAC-SHA256 подпись.

    Тело сериализуется детерминированно (компактный JSON, отсортированные ключи),
    чтобы подпись была воспроизводима и совпадала с тем, что проверит платформа.
    Подписываются ровно те байты, что уйдут в POST.
    Возвращает (body_bytes, signature_hex).
    """
    # Ключ "error" присутствует всегда (None если статус не failed) — тело стабильно.
    payload = {"task_id": task_id, "status": status.value, "error": error}
    body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return body_bytes, signature


class HttpWebhookNotifier(WebhookNotifier):
    """Инфра-адаптер: POST с HMAC-подписью, короткий таймаут, best-effort.

    Любое исключение/таймаут логируется и проглатывается внутри — наружу не пробрасывается
    (двойная защита совместно с try/except в _set пайплайна).
    """

    def __init__(
        self,
        callback_url: str,
        secret: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 3.0,
    ):
        self._callback_url = callback_url
        self._secret = secret
        # Для тестируемости клиент можно внедрить (DI с MockTransport).
        # Если не передан — создаём свой на время каждого вызова.
        self._client = client
        self._timeout = timeout

    async def notify(self, task_id: str, status: TaskStatus, error: str | None = None) -> None:
        try:
            body_bytes, signature = build_signed_request(
                self._callback_url, self._secret, task_id, status, error
            )
            headers = {
                SIGNATURE_HEADER: signature,
                "Content-Type": "application/json",
            }
            if self._client is not None:
                await self._client.post(
                    self._callback_url,
                    content=body_bytes,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    await client.post(self._callback_url, content=body_bytes, headers=headers)
        except Exception as exc:  # noqa: BLE001 — намеренно глушим любой сбой нотификации
            logger.warning("Вебхук для task=%s не отправлен: %s", task_id, exc)
