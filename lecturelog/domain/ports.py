from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path

from lecturelog.domain.media_source import MediaSource
from lecturelog.domain.models import Section, Task, Topic

ProgressCallback = Callable[[int], Awaitable[None] | None]
# Нейтральное зерно расхода ресурсов (audio_seconds / tokens). Стадию навешивает оркестратор.
UsageCallback = Callable[[dict], Awaitable[None] | None]


class Transcriber(ABC):
    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        on_progress: ProgressCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> Path:
        """Аудио -> путь к SRT-файлу."""


class SlideProvider(ABC):
    @abstractmethod
    async def get_slides(
        self,
        output_dir: Path,
        on_progress: ProgressCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> list[Path]:
        """Вернуть список путей к PNG слайдов. Реализация знает источник (PDF/PPTX или видео)."""


class Structurizer(ABC):
    @abstractmethod
    async def structurize(
        self,
        srt_path: Path,
        slide_images: list[Path],
        output_dir: Path,
        on_progress: ProgressCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> list[Topic]:
        """SRT + слайды -> структура тем/подтем с привязкой слайдов."""


class MediaCutter(ABC):
    @abstractmethod
    async def cut(self, source_path: Path, sections: list[Section], output_dir: Path) -> list[Path]:
        """Нарезать медиа по секциям -> список путей фрагментов (по одному на секцию)."""


class MediaIngestor(ABC):
    @abstractmethod
    async def ingest(self, source: MediaSource, output_dir: Path) -> Path:
        """Привести видеоисточник к локальному файлу (скачать URL / принять файл)."""

    @abstractmethod
    async def extract_audio(self, video_path: Path, output_dir: Path) -> Path:
        """Извлечь аудиодорожку из видео."""


class Exporter(ABC):
    @abstractmethod
    async def export(
        self,
        topics: list[Topic],
        media_fragments: list[Path],
        slide_images: list[Path],
        output_dir: Path,
        media_kind: str,
    ) -> Path:
        """Собрать конспект.md + медиа + слайды в ZIP, вернуть путь к ZIP."""


class TaskRepository(ABC):
    @abstractmethod
    async def create(self, task: Task) -> None: ...

    @abstractmethod
    async def get(self, task_id: str) -> Task | None: ...

    @abstractmethod
    async def update(self, task: Task) -> None: ...

    @abstractmethod
    async def mark_stale_as_interrupted(self) -> int:
        """Пометить все PROCESSING-задачи как INTERRUPTED (при старте). Вернуть кол-во."""
