from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lecturelog.domain.enums import TaskStatus
from lecturelog.domain.media_source import MediaSource
from lecturelog.domain.models import Task
from lecturelog.domain.ports import SlideProvider, TaskRepository

logger = logging.getLogger(__name__)

_TASK_ID_RE = re.compile(r"[0-9a-f]{32}\Z")

# Служебный marker терминального состояния внутри workspace задачи: TTL считается по нему,
# а не по mtime медиафайлов. Каталоги-соседи задач (results_tmp, кеш транскриптов) sweeper
# не трогает: кеш обязан пережить workspace упавшей задачи, иначе перезапуск заплатит за STT.
TERMINAL_MARKER = ".terminal.json"
RESERVED_DIRS = frozenset({"results_tmp", "transcript_cache"})

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_task_dir(path: Path, work_root: Path) -> bool:
    """Каталог задачи: имя - task_id, не symlink, прямой потомок work_root."""
    if not _TASK_ID_RE.fullmatch(path.name) or path.is_symlink():
        return False
    return path.resolve().parent == work_root.resolve()


def write_terminal_marker(work_dir: Path, status: TaskStatus, clock: Clock = utc_now) -> None:
    """Атомарно записать marker (статус и UTC-время). Best-effort, без текста ошибки."""
    payload = json.dumps({"status": status.value, "at": clock().astimezone(UTC).isoformat()})
    tmp = work_dir / (TERMINAL_MARKER + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, work_dir / TERMINAL_MARKER)
    except OSError as exc:
        logger.warning("Воркер: не записан marker work_dir=%s: %s", work_dir, exc)


def _read_terminal_time(work_dir: Path) -> datetime | None:
    try:
        raw = json.loads((work_dir / TERMINAL_MARKER).read_text(encoding="utf-8"))
        at = datetime.fromisoformat(raw["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


@dataclass
class SweepResult:
    scanned: int = 0
    deleted: int = 0
    skipped: int = 0


class WorkDirSweeper:
    """Страховочная TTL-очистка workspace упавших задач (расширение очистки воркера).

    Удаляет только каталоги задач в статусе FAILED, чей marker старше срока хранения.
    PENDING/PROCESSING/DONE/INTERRUPTED и каталоги без строки в БД не трогает.
    """

    def __init__(
        self,
        repository: TaskRepository,
        work_root: Path,
        failed_retention: timedelta,
        clock: Clock = utc_now,
    ):
        self._repo = repository
        self._root = work_root
        self._retention = failed_retention
        self._clock = clock
        self._lock = asyncio.Lock()

    async def sweep(self) -> SweepResult:
        result = SweepResult()
        if self._lock.locked():  # параллельные проходы запрещены
            return result
        async with self._lock:
            try:
                entries = await asyncio.to_thread(lambda: sorted(self._root.iterdir()))
            except OSError as exc:
                logger.warning("Sweeper: не прочитан WORK_DIR %s: %s", self._root, exc)
                return result
            for entry in entries:
                if entry.name in RESERVED_DIRS:
                    continue
                result.scanned += 1
                try:
                    deleted = await self._sweep_one(entry)
                except Exception as exc:  # ошибка одного каталога не останавливает проход
                    logger.warning("Sweeper: сбой на %s: %s", entry, exc)
                    deleted = False
                if deleted:
                    result.deleted += 1
                else:
                    result.skipped += 1
        logger.info(
            "Sweeper: scanned=%d deleted=%d skipped=%d",
            result.scanned,
            result.deleted,
            result.skipped,
        )
        return result

    async def _sweep_one(self, entry: Path) -> bool:
        if not _safe_task_dir(entry, self._root):
            return False
        task = await self._repo.get(entry.name)
        if task is None or task.status != TaskStatus.FAILED:
            return False
        at = _read_terminal_time(entry)
        if at is None:
            # Marker нет (каталог до внедрения marker): считаем от mtime каталога.
            at = datetime.fromtimestamp(entry.stat().st_mtime, UTC)
        if self._clock() - at < self._retention:
            return False
        await asyncio.to_thread(shutil.rmtree, entry)
        logger.info("Sweeper: удалён workspace упавшей задачи task=%s", entry.name)
        return True


@dataclass
class PipelineJob:
    task_id: str
    task: Task
    source: MediaSource
    slide_provider: SlideProvider | None
    work_dir: Path
    # Отложенный видео-провайдер: строится после transcribe из (video_path, srt_path) —
    # стадии кадров нужен транскрипт (оракул live-coding, легенда QC).
    video_slide_provider_factory: Callable[[Path, Path], SlideProvider] | None = None


class PipelineWorker:
    def __init__(self, service, concurrency: int, clock: Clock = utc_now):
        self._service = service
        self._clock = clock
        self._concurrency = concurrency
        self._queue: asyncio.Queue[PipelineJob] = asyncio.Queue()
        self._consumers: list[asyncio.Task] = []

    async def start(self) -> None:
        self._consumers = [asyncio.create_task(self._consume()) for _ in range(self._concurrency)]

    async def enqueue(self, job: PipelineJob) -> None:
        await self._queue.put(job)

    async def _cleanup_completed_work_dir(self, job: PipelineJob, result_path: str) -> None:
        """Best-effort удалить scratch только после подтверждённого S3-результата."""
        if result_path != f"results/{job.task_id}/":
            return
        if not _TASK_ID_RE.fullmatch(job.task_id) or job.work_dir.name != job.task_id:
            logger.error(
                "Воркер: небезопасный work_dir для cleanup task=%s path=%s",
                job.task_id,
                job.work_dir,
            )
            return
        if job.work_dir.is_symlink():
            logger.error("Воркер: symlink work_dir не удалён task=%s", job.task_id)
            return

        try:
            await asyncio.to_thread(shutil.rmtree, job.work_dir)
        except FileNotFoundError:
            return
        except OSError as exc:
            # Cleanup не должен менять уже сохранённую DONE-задачу на FAILED.
            logger.warning(
                "Воркер: не удалось очистить work_dir task=%s path=%s: %s",
                job.task_id,
                job.work_dir,
                exc,
            )
        else:
            logger.info("Воркер: очищен work_dir завершённой задачи task=%s", job.task_id)

    async def _consume(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                result_path = await self._service.run(
                    task=job.task,
                    source=job.source,
                    slide_provider=job.slide_provider,
                    work_dir=job.work_dir,
                    video_slide_provider_factory=job.video_slide_provider_factory,
                )
                await self._cleanup_completed_work_dir(job, result_path)
            except Exception as exc:  # задача уже помечена FAILED в repo
                logger.warning("Воркер: задача %s завершилась ошибкой: %s", job.task_id, exc)
                if job.work_dir.is_dir() and _safe_task_dir(job.work_dir, job.work_dir.parent):
                    await asyncio.to_thread(
                        write_terminal_marker, job.work_dir, TaskStatus.FAILED, self._clock
                    )
            finally:
                self._queue.task_done()

    async def stop(self) -> None:
        await self._queue.join()  # дождаться обработки всех заданий
        for c in self._consumers:
            c.cancel()
        await asyncio.gather(*self._consumers, return_exceptions=True)
        self._consumers = []
