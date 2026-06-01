from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Callable

from lecturelog.application.factories import cutter_factory
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.media_source import MediaSource, is_video_source
from lecturelog.domain.models import Task
from lecturelog.domain.ports import (
    Exporter, MediaCutter, MediaIngestor, SlideProvider, Structurizer, TaskRepository,
    Transcriber,
)

logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(self, repository: TaskRepository, transcriber: Transcriber,
                 structurizer: Structurizer, audio_cutter: MediaCutter, exporter: Exporter,
                 progress_plan_factory: Callable[[], ProgressPlan],
                 video_cutter: MediaCutter | None = None,
                 ingestor: MediaIngestor | None = None):
        self._repo = repository
        self._transcriber = transcriber
        self._structurizer = structurizer
        self._audio_cutter = audio_cutter
        self._video_cutter = video_cutter
        self._ingestor = ingestor
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
                  slide_provider: SlideProvider | None, work_dir: Path,
                  video_slide_provider_factory: Callable[[Path], SlideProvider] | None = None
                  ) -> Path:
        is_video = is_video_source(source)
        plan = ProgressPlan.for_video() if is_video else self._plan_factory()
        try:
            # Видео: источник аудио для транскрибации — извлечённая дорожка,
            # источник для нарезки — скачанное/локальное видео. Для аудио оба = source.path.
            if is_video:
                await self._set(task, status=TaskStatus.PROCESSING,
                                stage=PipelineStage.VIDEO_INGEST, progress=0, error=None)
                local_video = await self._ingestor.ingest(
                    source, output_dir=work_dir / "video_src")

                # Отложенное создание видео-провайдера: документ приоритетнее,
                # иначе авто-извлечение из только что полученного видеофайла.
                if slide_provider is None and video_slide_provider_factory is not None:
                    slide_provider = video_slide_provider_factory(local_video)

                await self._set(task, stage=PipelineStage.AUDIO_EXTRACT,
                                progress=plan.stage_start(PipelineStage.AUDIO_EXTRACT))
                audio_for_transcribe = await self._ingestor.extract_audio(
                    local_video, output_dir=work_dir / "extracted_audio")
                cut_source = local_video
                cut_stage = PipelineStage.VIDEO_CUT
            else:
                await self._set(task, status=TaskStatus.PROCESSING,
                                stage=PipelineStage.TRANSCRIBE, progress=0, error=None)
                audio_for_transcribe = source.path
                cut_source = source.path
                cut_stage = PipelineStage.AUDIO_CUT

            await self._set(task, stage=PipelineStage.TRANSCRIBE,
                            progress=plan.stage_start(PipelineStage.TRANSCRIBE))

            async def transcribe_progress(pct: int):
                await self._set(task, stage=PipelineStage.TRANSCRIBE,
                                progress=plan.scale(PipelineStage.TRANSCRIBE, pct))

            srt_path = await self._transcriber.transcribe(
                audio_path=audio_for_transcribe, output_dir=work_dir / "transcribe",
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
            cutter = cutter_factory(
                source, audio_cutter=self._audio_cutter, video_cutter=self._video_cutter)
            await self._set(task, stage=cut_stage, progress=plan.stage_start(cut_stage))
            fragments = await cutter.cut(
                source_path=cut_source, sections=sections,
                output_dir=work_dir / ("video" if is_video else "audio"))

            await self._set(task, stage=PipelineStage.EXPORT,
                            progress=plan.stage_start(PipelineStage.EXPORT))
            zip_path = await self._exporter.export(
                topics=topics, media_fragments=fragments, slide_images=slide_images,
                output_dir=work_dir / "export", media_kind="video" if is_video else "audio")

            await self._set(task, status=TaskStatus.DONE, stage=PipelineStage.EXPORT,
                            progress=100, result_path=str(zip_path), error=None)
            return zip_path
        except Exception as exc:
            logger.warning("Пайплайн упал для task=%s: %s", task.task_id, exc)
            await self._set(task, status=TaskStatus.FAILED,
                            error=f"{exc}\n{traceback.format_exc()}")
            raise
