from __future__ import annotations

import json
import re

import httpx

from lecturelog.domain.enums import ErrorCode
from lecturelog.domain.exceptions import InvalidSlidesDocument, MediaIngestError, MediaIngestReason

# Подстроки-сигналы лимита. LlmClient (infrastructure/llm/llm_client.py) при
# исчерпании ретраев оборачивает исходную ошибку провайдера в RuntimeError с
# текстом вида "OpenRouter не дал ответ за N попыток (429/RESOURCE_EXHAUSTED): ...".
# Ядро классифицирует по тексту, а не по типам SDK — это позволяет распознавать
# лимит независимо от конкретного провайдера/клиента.
_RATE_LIMIT_TOKENS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")

# Статус ответа провайдера в тексте ошибки openai SDK: «Error code: 401 - {...}».
# Берём первое вхождение: дальше в теле лежит metadata.previous_errors — история
# ретраев самого OpenRouter, где встречаются чужие 429/503. По подстрокам такой
# 401 (отозванный ключ) раньше превращался в rate_limit. Решающим статус считаем
# только для 4xx, кроме 429: это отказ по самому запросу или ключу, а не
# перегрузка. 5xx Gemini бывает и 500/504 с UNAVAILABLE в теле — их оставляем
# подстрокам.
_PROVIDER_STATUS_RE = re.compile(r"ERROR CODE: (\d{3})")

# Подстроки-сигналы протухших/непринятых YouTube-cookies (текст yt-dlp).
_COOKIES_INVALID_TOKENS = ("SIGN IN TO CONFIRM", "CONFIRM YOU'RE NOT A BOT")


def classify_error(exc: BaseException) -> ErrorCode:
    """Классифицировать исключение пайплайна в машинный код ошибки.

    rate_limit — распознаваемый лимит провайдера (HTTP 429/503 или текстовый
    сигнал RESOURCE_EXHAUSTED/UNAVAILABLE). bad_input — вход битый/не распознан
    (нет файла, неподдерживаемый формат). Остальное — internal."""
    # 1) HTTP-статус от Groq (httpx.HTTPStatusError несёт response.status_code).
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 503):
        return ErrorCode.RATE_LIMIT
    if isinstance(exc, MediaIngestError):
        if exc.reason is MediaIngestReason.RATE_LIMIT:
            return ErrorCode.RATE_LIMIT
        if exc.reason is MediaIngestReason.AUTH_REQUIRED and exc.source_kind == "youtube":
            return ErrorCode.COOKIES_INVALID
        if exc.reason in {
            MediaIngestReason.NOT_FOUND,
            MediaIngestReason.AUTH_REQUIRED,
            MediaIngestReason.EXTRACTOR,
        }:
            return ErrorCode.BAD_INPUT
        return ErrorCode.INTERNAL
    # 2) Обрыв JSON в ответе LLM — подкласс ValueError, но вход пользователя
    # тут ни при чём.
    if isinstance(exc, json.JSONDecodeError):
        return ErrorCode.INTERNAL
    # 3) Типовые сигналы битого/нераспознанного входа.
    if isinstance(exc, (FileNotFoundError, ValueError, InvalidSlidesDocument)):
        return ErrorCode.BAD_INPUT
    # 4) Текстовый сигнал лимита (LlmClient оборачивает last_error в RuntimeError).
    message = str(exc).upper()
    # Сигнал протухших cookies от yt-dlp.
    if any(token in message for token in _COOKIES_INVALID_TOKENS):
        return ErrorCode.COOKIES_INVALID
    status = _PROVIDER_STATUS_RE.search(message)
    if status is not None and 400 <= int(status.group(1)) < 500 and status.group(1) != "429":
        return ErrorCode.INTERNAL
    if any(token in message for token in _RATE_LIMIT_TOKENS):
        return ErrorCode.RATE_LIMIT
    # 5) Дефолт.
    return ErrorCode.INTERNAL
