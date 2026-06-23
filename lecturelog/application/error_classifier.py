from __future__ import annotations

import httpx

from lecturelog.domain.enums import ErrorCode

# Подстроки-сигналы лимита (повторяют эвристику gemini_client._is_rate_limit_error
# и _is_overload_error: ядро не зависит от типов SDK, классифицирует по тексту).
_RATE_LIMIT_TOKENS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")


def classify_error(exc: BaseException) -> ErrorCode:
    """Классифицировать исключение пайплайна в машинный код ошибки.

    rate_limit — распознаваемый лимит провайдера (HTTP 429/503 или текстовый
    сигнал RESOURCE_EXHAUSTED/UNAVAILABLE). bad_input — вход битый/не распознан
    (нет файла, неподдерживаемый формат). Остальное — internal."""
    # 1) HTTP-статус от Groq (httpx.HTTPStatusError несёт response.status_code).
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 503):
        return ErrorCode.RATE_LIMIT
    # 2) Типовые сигналы битого/нераспознанного входа.
    if isinstance(exc, (FileNotFoundError, ValueError)):
        return ErrorCode.BAD_INPUT
    # 3) Текстовый сигнал лимита (Gemini оборачивает last_error в RuntimeError).
    message = str(exc).upper()
    if any(token in message for token in _RATE_LIMIT_TOKENS):
        return ErrorCode.RATE_LIMIT
    # 4) Дефолт.
    return ErrorCode.INTERNAL
