from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from lecturelog.infrastructure.llm.key_pool import KeyPool

logger = logging.getLogger(__name__)


def _is_rate_limit_error(error: Exception) -> bool:
    message = str(error).upper()
    return "429" in message or "RESOURCE_EXHAUSTED" in message


def _is_overload_error(error: Exception) -> bool:
    message = str(error).upper()
    return "503" in message or "UNAVAILABLE" in message


class GeminiClient:
    """Обёртка вызовов Gemini поверх пула ключей.

    Выбирает пару (ключ × модель) через pool.acquire, строит contents,
    вызывает generate_content. При 429/503 блокирует пару и идёт на
    следующую попытку (другая модель/ключ).
    """

    def __init__(self, pool: KeyPool) -> None:
        self._pool = pool

    async def generate(
        self,
        models: list[str],
        prepare: Callable[[Any, int], Any],
        *,
        response_json: bool = False,
        retries: int = 5,
        label: str = "gemini",
    ) -> str:
        """Выбрать пару через pool.acquire(models), построить contents через
        prepare(client, idx), вызвать generate_content. При 429/503 — блокируем
        пару и идём на следующую попытку (другая модель/ключ).

        label — метка стадии для логов (видно, какая модель отработала вызов)."""
        last_error: Exception | None = None

        for _ in range(retries):
            client, idx, model = await self._pool.acquire(models)
            contents = prepare(client, idx)
            if inspect.isawaitable(contents):
                contents = await contents
            try:
                config = None
                if response_json:
                    from google.genai.types import GenerateContentConfig

                    config = GenerateContentConfig(response_mime_type="application/json")

                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=contents,
                    config=config,
                )
                text = getattr(response, "text", None)
                if not text:
                    raise RuntimeError("Gemini вернул пустой ответ")
                logger.info("%s: модель=%s, ключ#%d", label, model, idx)
                return text
            except Exception as error:
                last_error = error
                if _is_rate_limit_error(error) or _is_overload_error(error):
                    await self._pool.mark_rate_limited(idx, model)
                    continue
                raise

        raise RuntimeError(f"Gemini не дал ответ за {retries} попыток: {last_error}")

    async def call(
        self,
        prompt: str,
        models: list[str],
        images: list[bytes] | None = None,
        retries: int = 5,
    ) -> str:
        """Тонкая обёртка над generate для текстовых и inline-картиночных вызовов."""

        def prepare(client: Any, idx: int) -> Any:
            if images:
                from google.genai import types  # type: ignore[import-not-found]

                return [
                    *[types.Part.from_bytes(data=image, mime_type="image/png") for image in images],
                    prompt,
                ]
            return prompt

        return await self.generate(models, prepare, retries=retries)
