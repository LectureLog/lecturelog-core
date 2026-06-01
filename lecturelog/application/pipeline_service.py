from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Callable

from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.media_source import MediaSource, is_video_source
from lecturelog.domain.models import Task
from lecturelog.domain.ports import (
    Exporter, MediaCutter, SlideProvider, Structurizer, TaskRepository, Transcriber,
)

logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(self, repository: TaskRepository, transcriber: Transcriber,
                 structurizer: Structurizer, audio_cutter: MediaCutter, exporter: Exporter,
                 progress_plan_factory: Callable[[], ProgressPlan]):
        self._repo = repository
        self._transcriber = transcriber
        self._structurizer = structurizer
        self._audio_cutter = audio_cutter
        self._exporter = exporter
        self._plan_factory = progress_plan_factory

    async def _set(self, task: Task, *, status=None, stage=None, progress=None,
                   error=None, result_path=None):
        if status is not None: task.status = status
        if stage is not None: task.stage = stage
        if progress is not None: task.progress_pct = progress
        if error is not None: task.error = error
        if result_path is not None: task.result_path = result_path
        await self._repo.update(task)

    async def run(self, task: Task, source: MediaSource,
                  slide_provider: SlideProvider | None, work_dir: Path) -> Path:
        plan = self._plan_factory()
        try:
            if is_video_source(source):
                raise NotImplementedError("Видеорежим добавляется в PR #2")

            await self._set(task, status=TaskStatus.PROCESSING,
                            stage=PipelineStage.TRANSCRIBE, progress=0, error=None)

            async def transcribe_progress(pct: int):
                await self._set(task, stage=PipelineStage.TRANSCRIBE,
                                progress=plan.scale(PipelineStage.TRANSCRIBE, pct))

            srt_path = await self._transcriber.transcribe(
                audio_path=source.path, output_dir=work_dir / "transcribe",
                on_progress=transcribe_progress,
            )

            slide_images: list[Path] = []
            if slide_provider is not None:
                await self._set(task, stage=PipelineStage.SLIDES,
                                progress=plan.stage_start(PipelineStage.SLIDES))
                slide_images = await slide_provider.get_slides(output_dir=work_dir / "slides")

            await self._set(task, stage=PipelineStage.STRUCTURIZE,
                            progress=plan.stage_start(PipelineStage.STRUCTURIZE))

            async def structurize_progress(pct: int):
                await self._set(task, stage=PipelineStage.STRUCTURIZE,
                                progress=plan.scale(PipelineStage.STRUCTURIZE, pct))

            topics = await self._structurizer.structurize(
                srt_path=srt_path, slide_images=slide_images,
                output_dir=work_dir / "structurize", on_progress=structurize_progress,
            )

            sections = [s for t in topics for s in t.sections]
            await self._set(task, stage=PipelineStage.AUDIO_CUT,
                            progress=plan.stage_start(PipelineStage.AUDIO_CUT))
            fragments = await self._audio_cutter.cut(
                source_path=source.path, sections=sections, output_dir=work_dir / "audio")

            await self._set(task, stage=PipelineStage.EXPORT,
                            progress=plan.stage_start(PipelineStage.EXPORT))
            zip_path = await self._exporter.export(
                topics=topics, media_fragments=fragments, slide_images=slide_images,
                output_dir=work_dir / "export", media_kind="audio")

            await self._set(task, status=TaskStatus.DONE, stage=PipelineStage.EXPORT,
                            progress=100, result_path=str(zip_path), error=None)
            return zip_path
        except Exception as exc:
            logger.warning("Пайплайн упал для task=%s: %s", task.task_id, exc)
            await self._set(task, status=TaskStatus.FAILED,
                            error=f"{exc}\n{traceback.format_exc()}")
            raise
