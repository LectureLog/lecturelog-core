from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from lecturelog.domain.ports import ProgressCallback, Transcriber, UsageCallback
from lecturelog.infrastructure.transcribe.common import emit_progress

logger = logging.getLogger(__name__)

# Версия формата записи и постобработки SRT: поднять, если меняется то, как из ответа
# провайдера получается транскрипт (старые записи тогда перестанут находиться).
CACHE_FORMAT_VERSION = 1
_CHUNK = 1024 * 1024


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class CachingTranscriber(Transcriber):
    """Переиспользует транскрипт по ключу «содержимое аудио + настройки транскрипции».

    Запись кладётся в `cache_dir/<ключ>/transcript.srt` сразу после успешной
    транскрипции, то есть до всех следующих стадий: падение задачи дальше не
    теряет транскрипт. Каталог кеша живёт вне workspace задачи и не удаляется
    вместе с ним. Любой сбой кеша (чтение, запись) — это промах, а не ошибка задачи.

    При попадании usage не эмитится: оплаченная транскрипция второй раз
    в учёт расходов не попадает.
    """

    def __init__(self, inner: Transcriber, *, cache_dir: Path, settings: dict[str, Any]) -> None:
        self._inner = inner
        self._cache_dir = cache_dir
        self._settings = settings

    def _entry(self, audio_hash: str) -> Path:
        # Ключ — хеш аудио вместе с канонической записью настроек: смена любой
        # настройки даёт другой каталог.
        payload = json.dumps(
            {"v": CACHE_FORMAT_VERSION, "audio": audio_hash, "settings": self._settings},
            sort_keys=True,
            ensure_ascii=False,
        )
        return self._cache_dir / hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _lookup(self, entry: Path) -> str | None:
        try:
            text = (entry / "transcript.srt").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        if not text.strip():
            return None
        with contextlib.suppress(OSError):
            os.utime(entry)  # свежесть записи для будущей чистки по сроку
        return text

    def _store(self, entry: Path, srt_path: Path) -> None:
        try:
            text = srt_path.read_text(encoding="utf-8")
            if not text.strip():
                return
            entry.mkdir(parents=True, exist_ok=True)
            tmp = entry / ".transcript.srt.tmp"
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(entry / "transcript.srt")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Кеш транскриптов: запись %s не сохранена: %s", entry.name, exc)

    async def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        on_progress: ProgressCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> Path:
        entry: Path | None = None
        try:
            entry = self._entry(await asyncio.to_thread(_hash_file, audio_path))
        except OSError as exc:
            logger.warning("Кеш транскриптов: не удалось хешировать аудио: %s", exc)
        if entry is not None:
            cached = await asyncio.to_thread(self._lookup, entry)
            if cached is not None:
                logger.info("Кеш транскриптов: попадание %s, транскрипция пропущена", entry.name)
                output_dir.mkdir(parents=True, exist_ok=True)
                target = output_dir / "transcript.srt"
                tmp = output_dir / ".transcript.srt.tmp"
                tmp.write_text(cached, encoding="utf-8")
                tmp.replace(target)
                await emit_progress(on_progress, 100)
                return target

        srt_path = await self._inner.transcribe(
            audio_path=audio_path,
            output_dir=output_dir,
            on_progress=on_progress,
            on_usage=on_usage,
        )
        if entry is not None:
            await asyncio.to_thread(self._store, entry, srt_path)
        return srt_path
