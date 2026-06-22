from __future__ import annotations

import asyncio
import inspect
import logging
import tempfile
from pathlib import Path
from typing import Any

from lecturelog.domain.ports import ProgressCallback, SlideProvider, UsageCallback
from lecturelog.infrastructure.llm.gemini_client import GeminiClient
from lecturelog.infrastructure.slides.video_slide_utils import (
    merge_and_dedup,
    parse_json_response,
    seconds_to_timestamp,
    timestamp_to_seconds,
)

logger = logging.getLogger(__name__)

CHUNK_DURATION_SEC = 600
CHUNK_OVERLAP_SEC = 10


async def _emit_progress(on_progress: ProgressCallback | None, value: int) -> None:
    if on_progress is None:
        return
    maybe_awaitable = on_progress(value)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


class VideoSlideProvider(SlideProvider):
    """Реализация порта SlideProvider: извлечение слайдов из видеоряда
    через Gemini Vision (чанкинг → анализ → merge+dedup → PNG-кадры ffmpeg)."""

    def __init__(
        self,
        gemini_client: GeminiClient,
        video_path: Path,
        models: list[str],
        prompts_dir: Path,
        concurrency: int = 5,
    ) -> None:
        self._gemini = gemini_client
        self._video_path = video_path
        self._models = models
        self._prompts_dir = prompts_dir
        self._concurrency = concurrency

    def _read_prompt(self, name: str) -> str:
        return (self._prompts_dir / name).read_text(encoding="utf-8")

    async def _get_video_duration(self, video_path: Path) -> int:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        return int(float(out.decode().strip()))

    async def _ffmpeg_extract_frame(
        self,
        video_path: Path,
        timestamp_sec: float,
        target: Path,
        *,
        duration: int | None = None,
    ) -> None:
        # Защита от таймкода за пределами видео: Gemini иногда возвращает
        # timestamp_finalized чуть позже конца. Берём предпоследнюю секунду.
        if duration is not None and duration > 0 and timestamp_sec >= duration:
            timestamp_sec = max(0, duration - 1)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-ss",
            str(timestamp_sec),
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-loglevel",
            "error",
            str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg ошибка при извлечении кадра: {stderr.decode('utf-8', errors='ignore')}"
            )

    async def _split_into_chunks(
        self,
        video_path: Path,
        tmp_dir: Path,
        total: int | None = None,
    ) -> list[tuple[int, int, Path]]:
        """Нарезает видео на чанки по CHUNK_DURATION_SEC секунд с перекрытием CHUNK_OVERLAP_SEC."""
        if total is None:
            total = await self._get_video_duration(video_path)
        if total <= 0:
            raise RuntimeError(f"Не удалось получить длительность видео: {video_path}")
        # Короткое видео — отдаём целиком, без перепаковки через ffmpeg
        if total <= CHUNK_DURATION_SEC:
            return [(0, total, video_path)]
        chunks: list[tuple[int, int, Path]] = []
        chunk_idx = 0
        start = 0
        while start < total:
            end = min(start + CHUNK_DURATION_SEC, total)
            chunk_path = tmp_dir / f"chunk-{chunk_idx:02d}.mp4"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-ss",
                str(start),
                "-t",
                str(end - start),
                "-i",
                str(video_path),
                "-c",
                "copy",
                "-y",
                "-loglevel",
                "error",
                str(chunk_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg ошибка при нарезке чанка {chunk_idx}: "
                    f"{stderr.decode('utf-8', errors='ignore')}"
                )
            chunks.append((start, end, chunk_path))
            chunk_idx += 1
            if end >= total:
                break
            start = end - CHUNK_OVERLAP_SEC
        return chunks

    @staticmethod
    def _build_chunk_prompt(base: str, start_sec: int, end_sec: int) -> str:
        anchor = (
            f"\nТы анализируешь ФРАГМЕНТ видеозаписи лекции.\n"
            f"Этот фрагмент соответствует отрезку с {seconds_to_timestamp(start_sec)} по "
            f"{seconds_to_timestamp(end_sec)} полного видео.\n"
            f"Все таймкоды в ответе должны быть АБСОЛЮТНЫМИ "
            f"(относительно начала полного видео, а не фрагмента).\n"
        )
        return anchor + base

    @staticmethod
    async def _upload_and_wait(client: Any, video_path: Path) -> Any:
        video_file = await asyncio.to_thread(client.files.upload, file=str(video_path))
        for _ in range(60):
            video_file = await asyncio.to_thread(client.files.get, name=video_file.name)
            state_str = str(getattr(video_file, "state", "")).upper()
            if "ACTIVE" in state_str:
                return video_file
            if "FAILED" in state_str:
                raise RuntimeError(f"Файл перешёл в FAILED: {video_file.name}")
            await asyncio.sleep(5)
        raise RuntimeError("Файл не стал ACTIVE за 5 минут")

    async def _call_gemini_video(
        self,
        prompt: str,
        video_path: Path,
        on_usage: UsageCallback | None = None,
    ) -> str:
        """Извлечь слайды одного чанка: выбор пары (ключ×модель) делает пул,
        загрузка файла мемоизируется на выбранный ключ (файл привязан к проекту
        ключа, смена ключа = повторная загрузка)."""
        from google.genai import types

        uploaded: dict[int, Any] = {}

        async def prepare(client: Any, idx: int) -> Any:
            video_file = uploaded.get(idx)
            if video_file is None:
                video_file = await self._upload_and_wait(client, video_path)
                uploaded[idx] = video_file
            return [
                types.Part.from_uri(
                    file_uri=video_file.uri,
                    mime_type=video_file.mime_type,
                ),
                types.Part.from_text(text=prompt),
            ]

        return await self._gemini.generate(
            self._models, prepare, response_json=True, label="video_slides", on_usage=on_usage
        )

    async def get_slides(
        self,
        output_dir: Path,
        on_progress: ProgressCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> list[Path]:
        """Извлекает PNG-слайды из видео через Gemini Vision.

        Возвращает отсортированный список PNG в формате output_dir/slide-NN.png.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        await _emit_progress(on_progress, 5)

        base_prompt = self._read_prompt("video_slides_v1.md")
        duration = await self._get_video_duration(self._video_path)

        with tempfile.TemporaryDirectory(prefix="lecturelog_video_chunks_") as tmp:
            tmp_dir = Path(tmp)
            chunks = await self._split_into_chunks(self._video_path, tmp_dir, total=duration)
            await _emit_progress(on_progress, 20)

            chunks_slides: list[list[dict]] = []
            failed_ranges: list[tuple[int, int, str]] = []

            semaphore = asyncio.Semaphore(max(1, self._concurrency))
            multi = len(chunks) > 1

            async def _process_chunk(
                start: int,
                end: int,
                chunk_path: Path,
            ) -> tuple[int, int, list[dict] | Exception]:
                async with semaphore:
                    prompt = (
                        self._build_chunk_prompt(base_prompt, start, end) if multi else base_prompt
                    )
                    try:
                        raw = await self._call_gemini_video(prompt, chunk_path, on_usage=on_usage)
                        data = parse_json_response(raw)
                        return start, end, list(data.get("slides", []))
                    except Exception as exc:
                        return start, end, exc

            tasks = [asyncio.create_task(_process_chunk(s, e, p)) for s, e, p in chunks]
            total = len(tasks)
            done = 0
            for task in asyncio.as_completed(tasks):
                start, end, result = await task
                if isinstance(result, Exception):
                    failed_ranges.append((start, end, str(result)))
                    chunks_slides.append([])
                else:
                    chunks_slides.append(result)
                done += 1
                await _emit_progress(on_progress, 20 + int((done / max(total, 1)) * 50))

            if failed_ranges:
                detail = ", ".join(f"{s}-{e}: {err}" for s, e, err in failed_ranges)
                logger.warning(
                    "video_slides: %d чанк(ов) не обработаны: %s",
                    len(failed_ranges),
                    detail,
                )
                # Все чанки упали — это ошибка извлечения, а не «видео без слайдов».
                if len(failed_ranges) == len(chunks):
                    raise RuntimeError(f"Не удалось обработать ни один чанк видео: {detail}")

        await _emit_progress(on_progress, 70)
        slides = merge_and_dedup(chunks_slides)

        if not slides:
            # Видео без слайдов (talking-head, музыка и т.п.) — валидный кейс.
            logger.warning("video_slides: Gemini не нашёл ни одного слайда")
            return []

        targets: list[Path] = []
        for i, slide in enumerate(slides, 1):
            ts = slide.get("timestamp_finalized", "00:00")
            try:
                sec = timestamp_to_seconds(ts)
            except ValueError:
                continue
            target = output_dir / f"slide-{i:02d}.png"
            await self._ffmpeg_extract_frame(self._video_path, sec, target, duration=duration)
            targets.append(target)
            await _emit_progress(on_progress, 75 + int((i / len(slides)) * 25))

        return targets
