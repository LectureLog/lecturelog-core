from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from lecturelog.domain.media_source import MediaSource, VideoFileSource, VideoUrlSource
from lecturelog.domain.ports import CookieStore, MediaIngestor

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}


class VideoIngestor(MediaIngestor):
    """Реализация порта MediaIngestor: yt-dlp для URL, копирование для файла."""

    def __init__(self, cookie_store: CookieStore | None = None):
        self._cookie_store = cookie_store

    async def ingest(self, source: MediaSource, output_dir: Path) -> Path:
        """Привести видеоисточник к локальному файлу output_dir/video.*"""
        output_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(source, VideoUrlSource):
            target = output_dir / "video.mp4"
            await self._download_youtube(source.url, target)
            return target

        if isinstance(source, VideoFileSource):
            src_path = source.path
            if not src_path.exists():
                raise FileNotFoundError(f"Видеофайл не найден: {src_path}")
            suffix = (
                src_path.suffix.lower() if src_path.suffix.lower() in VIDEO_EXTENSIONS else ".mp4"
            )
            target = output_dir / f"video{suffix}"
            if src_path.resolve() != target.resolve():
                shutil.copy2(src_path, target)
            return target

        raise ValueError(f"VideoIngestor не принимает источник вида {source.kind!r}")

    async def extract_audio(self, video_path: Path, output_dir: Path) -> Path:
        """Извлекает звуковую дорожку из видео в mp3 (128 kbps моно)."""
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "audio.mp3"

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-ac",
            "1",
            str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg не смог извлечь аудио: {stderr.decode('utf-8', errors='ignore')}"
            )
        return target

    @staticmethod
    def _yt_dlp_bin() -> str:
        candidate = Path(sys.executable).parent / "yt-dlp"
        if candidate.exists():
            return str(candidate)
        return "yt-dlp"

    async def _download_youtube(self, url: str, output_path: Path) -> None:
        cookies_path: Path | None = None
        cookies_dir: str | None = None
        if self._cookie_store is not None:
            content = await self._cookie_store.get()
            if content:
                # БЕЗОПАСНОСТЬ: пишем cookies в приватный temp-каталог ВНЕ output.
                # output (= export/output/) — расшаренный том, который читает web;
                # секрет туда попадать не должен даже на время загрузки.
                cookies_dir = tempfile.mkdtemp(prefix="yt-cookies-")
                cookies_path = Path(cookies_dir) / "cookies.txt"
                cookies_path.write_bytes(content)
                cookies_path.chmod(0o600)

        args = [
            self._yt_dlp_bin(),
            "-f",
            "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "--merge-output-format",
            "mp4",
            "--js-runtimes",
            "deno",
        ]
        if cookies_path is not None:
            args += ["--cookies", str(cookies_path)]
        args += ["-o", str(output_path), url]

        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "yt-dlp не найден. Установи зависимость: `pip install yt-dlp`."
                ) from exc

            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                # ВНИМАНИЕ: в текст ошибки кладём stderr yt-dlp, но НЕ содержимое cookies.
                raise RuntimeError(
                    f"yt-dlp не смог скачать видео: {stderr.decode('utf-8', errors='ignore')}"
                )

            # yt-dlp иногда возвращает 0, но кладёт файл с другим расширением.
            # cookies-файла в output больше нет (он в temp-каталоге), фильтровать не нужно.
            if not output_path.exists():
                candidates = sorted(output_path.parent.glob(f"{output_path.stem}.*"))
                if not candidates:
                    raise RuntimeError(
                        f"yt-dlp завершился без ошибки, но файл не создан: {output_path}"
                    )
                candidates[0].rename(output_path)
        finally:
            if cookies_dir is not None:
                shutil.rmtree(cookies_dir, ignore_errors=True)
