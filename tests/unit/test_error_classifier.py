import json
from pathlib import Path

import httpx
import pytest

from lecturelog.application.error_classifier import classify_error
from lecturelog.domain.enums import ErrorCode


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.groq.com/x")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError("boom", request=req, response=resp)


@pytest.mark.parametrize("code", [429, 503])
def test_groq_http_status_is_rate_limit(code):
    assert classify_error(_http_status_error(code)) is ErrorCode.RATE_LIMIT


def test_http_status_500_is_internal():
    assert classify_error(_http_status_error(500)) is ErrorCode.INTERNAL


@pytest.mark.parametrize(
    "text",
    [
        "Gemini не дал ответ за 5 попыток: 429 Too Many Requests",
        "RESOURCE_EXHAUSTED quota",
        "503 Service Unavailable",
        "model UNAVAILABLE",
    ],
)
def test_text_signal_is_rate_limit(text):
    assert classify_error(RuntimeError(text)) is ErrorCode.RATE_LIMIT


def test_llm_client_retries_exhausted_is_rate_limit():
    # Регресс: точный текст, который LlmClient (infrastructure/llm/llm_client.py)
    # генерит при исчерпании ретраев (см. `raise RuntimeError(f"OpenRouter не дал
    # ответ за {retries} попыток (429/RESOURCE_EXHAUSTED): {last_error}")`).
    exc = RuntimeError(
        "OpenRouter не дал ответ за 5 попыток (429/RESOURCE_EXHAUSTED): "
        "Error code: 429 - {'error': {'message': 'rate limit exceeded'}}"
    )
    assert classify_error(exc) is ErrorCode.RATE_LIMIT


def test_file_not_found_is_bad_input():
    assert classify_error(FileNotFoundError("Видеофайл не найден: x")) is ErrorCode.BAD_INPUT


def test_value_error_is_bad_input():
    assert (
        classify_error(ValueError("Неподдерживаемый формат слайдов: .xyz")) is ErrorCode.BAD_INPUT
    )


def test_generic_runtime_is_internal():
    assert classify_error(RuntimeError("ffmpeg завершился с ошибкой: ...")) is ErrorCode.INTERNAL


# Реальные тексты ошибок с прода (tasks.error, user_id вымаран).
_PROVIDER_ERRORS = Path(__file__).parent.parent / "fixtures" / "provider_errors"
_PROD_401 = (_PROVIDER_ERRORS / "openrouter_401_with_previous_429.txt").read_text(encoding="utf-8")
_PROD_503 = (_PROVIDER_ERRORS / "openrouter_503_high_demand.txt").read_text(encoding="utf-8")


def test_prod_401_with_previous_429_is_not_rate_limit():
    # Подстроки 429/RESOURCE_EXHAUSTED приносит metadata.previous_errors —
    # история ретраев самого OpenRouter, а настоящая причина — отозванный ключ.
    assert "429" in _PROD_401
    assert classify_error(RuntimeError(_PROD_401)) is ErrorCode.INTERNAL


def test_llm_client_wrapper_over_prod_401_is_not_rate_limit():
    exc = RuntimeError(
        f"OpenRouter не дал ответ за 5 попыток (401: BYOK-ключ отклонён): {_PROD_401}"
    )
    assert classify_error(exc) is not ErrorCode.RATE_LIMIT


def test_prod_503_high_demand_is_rate_limit():
    assert classify_error(RuntimeError(_PROD_503)) is ErrorCode.RATE_LIMIT


def test_llm_client_wrapper_over_prod_503_is_rate_limit():
    exc = RuntimeError(f"OpenRouter не дал ответ за 5 попыток (HTTP 503 апстрима): {_PROD_503}")
    assert classify_error(exc) is ErrorCode.RATE_LIMIT


def test_truncated_llm_json_is_not_bad_input():
    # Прод: «Unterminated string starting at: line 20 column 12» из разбора ответа
    # split_topics. Вход пользователя тут ни при чём.
    with pytest.raises(json.JSONDecodeError) as exc_info:
        json.loads('[{"title": "Тема 1", "start": "00:00:00", "end": "00:0')
    assert "Unterminated string" in str(exc_info.value)
    assert classify_error(exc_info.value) is ErrorCode.INTERNAL


@pytest.mark.parametrize(
    "text",
    [
        "Error code: 500 - {'error': {'message': 'model UNAVAILABLE'}}",
        "Error code: 504 - {'error': {'status': 'UNAVAILABLE'}}",
    ],
)
def test_upstream_5xx_with_unavailable_stays_rate_limit(text):
    # Gemini отдаёт перегрузку и как 500/504 — статус не должен её перебивать.
    assert classify_error(RuntimeError(text)) is ErrorCode.RATE_LIMIT


def test_provider_4xx_beats_rate_limit_tokens_in_body():
    exc = RuntimeError("Error code: 403 - {'previous_errors': [{'code': 429}]}")
    assert classify_error(exc) is ErrorCode.INTERNAL
