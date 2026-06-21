import hashlib
import hmac
import json

import httpx
import pytest

from lecturelog.domain.enums import TaskStatus
from lecturelog.infrastructure.webhook.http_notifier import (
    HttpWebhookNotifier,
    build_signed_request,
)

_URL = "https://platform.example/cb"
_SECRET = "shared-secret"


def test_hmac_signature_is_deterministic():
    # Известный secret + тело -> известная подпись, вычисленная независимо.
    body_bytes, sig = build_signed_request(_URL, _SECRET, "t1", TaskStatus.DONE, None)
    expected = hmac.new(_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
    assert sig == expected
    # И воспроизводимость: повторный вызов даёт те же байты и ту же подпись.
    body_bytes2, sig2 = build_signed_request(_URL, _SECRET, "t1", TaskStatus.DONE, None)
    assert body_bytes2 == body_bytes
    assert sig2 == sig


def test_body_is_thin_done():
    body_bytes, _ = build_signed_request(_URL, _SECRET, "t1", TaskStatus.DONE, None)
    parsed = json.loads(body_bytes)
    assert parsed == {"task_id": "t1", "status": "done", "error": None}
    # Никаких лишних полей (usage/result_path).
    assert set(parsed.keys()) == {"task_id", "status", "error"}


def test_body_includes_error_on_failed():
    body_bytes, _ = build_signed_request(_URL, _SECRET, "t1", TaskStatus.FAILED, "boom")
    parsed = json.loads(body_bytes)
    assert parsed["status"] == "failed"
    assert parsed["error"] == "boom"


@pytest.mark.asyncio
async def test_post_sends_signature_header_and_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = HttpWebhookNotifier(callback_url=_URL, secret=_SECRET, client=client)
        await notifier.notify("t1", TaskStatus.DONE)

    req = captured["request"]
    assert req.method == "POST"
    assert str(req.url) == _URL
    # Тело запроса == тому, что подписали; заголовок == подпись от этого тела.
    body_bytes, sig = build_signed_request(_URL, _SECRET, "t1", TaskStatus.DONE, None)
    assert req.content == body_bytes
    assert req.headers["X-Webhook-Signature"] == sig
    assert req.headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_notifier_swallows_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = HttpWebhookNotifier(callback_url=_URL, secret=_SECRET, client=client)
        # Не должно бросать даже на 500 (best-effort).
        await notifier.notify("t1", TaskStatus.DONE)


@pytest.mark.asyncio
async def test_notifier_swallows_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = HttpWebhookNotifier(callback_url=_URL, secret=_SECRET, client=client)
        await notifier.notify("t1", TaskStatus.DONE)


@pytest.mark.asyncio
async def test_notifier_respects_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        notifier = HttpWebhookNotifier(callback_url=_URL, secret=_SECRET, client=client)
        # Таймаут не должен ронять notify.
        await notifier.notify("t1", TaskStatus.DONE)
