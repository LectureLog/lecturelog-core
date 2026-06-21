from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from pathlib import Path

from lecturelog.application.factories import cutter_factory
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.application.usage_accumulator import UsageAccumulator
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.media_source import MediaSource, is_video_source
from lecturelog.domain.models import Task
from lecturelog.domain.ports import (
    Exporter,
    MediaCutter,
    MediaIngestor,
    SlideProvider,
    Structurizer,
    TaskRepository,
    Transcriber,
    WebhookNotifier,
)
from lecturelog.infrastructure.slides.video_provider import VideoSlideProvider

logger = logging.getLogger(__name__)

# Терминальные статусы: только на них шлём вебхук платформе.
_TERMINAL = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.INTERRUPTED}


class PipelineService:
    def __init__(
        self,
        repository: TaskRepository,
        transcriber: Transcriber,
        structurizer: Structurizer,
        audio_cutter: MediaCutter,
        exporter: Exporter,
        progress_plan_factory: Callable[[], ProgressPlan],
        video_cutter: MediaCutter | None = None,
        ingestor: MediaIngestor | None = None,
        webhook_notifier: WebhookNotifier | None = None,
    ):
        self._repo = repository
        self._transcriber = transcriber
        self._structurizer = structurizer
        self._audio_cutter = audio_cutter
        self._video_cutter = video_cutter
        self._ingestor = ingestor
        self._exporter = exporter
        self._plan_factory = progress_plan_factory
        # Опциональный нотификатор: None в автономном режиме (без PLATFORM_CALLBACK_URL).
        self._webhook = webhook_notifier

    async def _set(
        self, task: Task, *, status=None, stage=None, progress=None, error=None, result_path=None
    ):
        if status is not None:
            task.status = status
        if stage is not None:
            task.stage = stage
        if progress is not None:
            task.progress_pct = progress
        if error is not None:
            task.error = error
        if result_path is not None:
            task.result_path = result_path
        await self._repo.update(task)

        # Пуш платформе только на терминальных статусах и только если нотификатор задан.
        # Best-effort: ошибка/таймаут логируется и НЕ роняет/не задерживает пайплайн
        # (защита от лежащей платформы; надёжность — на fallback-поллинге платформы).
        if status in _TERMINAL and self._webhook is not None:
            try:
                await self._webhook.notify(task.task_id, status, error=task.error)
            except Exception as exc:  # noqa: BLE001 — намеренно глушим любой сбой нотификации
                logger.warning("Вебхук для task=%s не доставлен: %s", task.task_id, exc)

    async def _persist_usage(self, task: Task, acc: UsageAccumulator) -> None:
        """Гранулярность персиста = стадия: пересчитать total и сохранить usage.
        НЕ звать на каждый LLM-колбэк (иначе DB-шторм)."""
        acc.compute_total()
        task.usage = acc.usage
        await self._repo.update(task)

    async def run(
        self,
        task: Task,
        source: MediaSource,
        slide_provider: SlideProvider | None,
        work_dir: Path,
        video_slide_provider_factory: Callable[[Path], SlideProvider] | None = None,
    ) -> Path:
        is_video = is_video_source(source)
        plan = ProgressPlan.for_video() if is_video else self._plan_factory()

        # Накопитель расхода: source-ось известна сразу; slides_origin уточняется
        # после того, как определится фактически отработавший провайдер слайдов.
        acc = UsageAccumulator()
        acc.set_mode(source="video" if is_video else "audio", slides_origin="none")

        # Нейтральное зерно от провайдеров; стадию навешивают эти closure'ы.
        async def transcribe_usage(payload: dict):
            acc.record_transcribe(payload)

        async def structurize_usage(payload: dict):
            acc.record_llm("structurize", payload)

        async def video_slides_usage(payload: dict):
            acc.record_llm("video_slides", payload)

        try:
            # Видео: источник аудио для транскрибации — извлечённая дорожка,
            # источник для нарезки — скачанное/локальное видео. Для аудио оба = source.path.
            if is_video:
                await self._set(
                    task,
                    status=TaskStatus.PROCESSING,
                    stage=PipelineStage.VIDEO_INGEST,
                    progress=0,
                    error=None,
                )
                local_video = await self._ingestor.ingest(source, output_dir=work_dir / "video_src")

                # Отложенное создание видео-провайдера: документ приоритетнее,
                # иначе авто-извлечение из только что полученного видеофайла.
                if slide_provider is None and video_slide_provider_factory is not None:
                    slide_provider = video_slide_provider_factory(local_video)

                await self._set(
                    task,
                    stage=PipelineStage.AUDIO_EXTRACT,
                    progress=plan.stage_start(PipelineStage.AUDIO_EXTRACT),
                )
                audio_for_transcribe = await self._ingestor.extract_audio(
                    local_video, output_dir=work_dir / "extracted_audio"
                )
                cut_source = local_video
                cut_stage = PipelineStage.VIDEO_CUT
            else:
                await self._set(
                    task,
                    status=TaskStatus.PROCESSING,
                    stage=PipelineStage.TRANSCRIBE,
                    progress=0,
                    error=None,
                )
                audio_for_transcribe = source.path
                cut_source = source.path
                cut_stage = PipelineStage.AUDIO_CUT

            await self._set(
                task,
                stage=PipelineStage.TRANSCRIBE,
                progress=plan.stage_start(PipelineStage.TRANSCRIBE),
            )

            async def transcribe_progress(pct: int):
                await self._set(
                    task,
                    stage=PipelineStage.TRANSCRIBE,
                    progress=plan.scale(PipelineStage.TRANSCRIBE, pct),
                )

            srt_path = await self._transcriber.transcribe(
                audio_path=audio_for_transcribe,
                output_dir=work_dir / "transcribe",
                on_progress=transcribe_progress,
                on_usage=transcribe_usage,
            )
            # Инкрементальный персист: transcribe доезжает ДО появления structurize.
            await self._persist_usage(task, acc)

            slide_images: list[Path] = []
            if slide_provider is not None:
                # Ось slides_origin: video_extracted только для VideoSlideProvider,
                # иначе document. Завязка на конкретный тип держится в одном месте.
                is_video_extracted = isinstance(slide_provider, VideoSlideProvider)
                acc.set_mode(
                    source="video" if is_video else "audio",
                    slides_origin="video_extracted" if is_video_extracted else "document",
                )
                await self._set(
                    task,
                    stage=PipelineStage.SLIDES,
                    progress=plan.stage_start(PipelineStage.SLIDES),
                )
                slide_images = await slide_provider.get_slides(
                    output_dir=work_dir / "slides",
                    on_usage=video_slides_usage if is_video_extracted else None,
                )
                # Стадия video_slides существует ⟺ video_extracted.
                if is_video_extracted:
                    await self._persist_usage(task, acc)

            await self._set(
                task,
                stage=PipelineStage.STRUCTURIZE,
                progress=plan.stage_start(PipelineStage.STRUCTURIZE),
            )

            async def structurize_progress(pct: int):
                await self._set(
                    task,
                    stage=PipelineStage.STRUCTURIZE,
                    progress=plan.scale(PipelineStage.STRUCTURIZE, pct),
                )

            topics = await self._structurizer.structurize(
                srt_path=srt_path,
                slide_images=slide_images,
                output_dir=work_dir / "structurize",
                on_progress=structurize_progress,
                on_usage=structurize_usage,
            )
            await self._persist_usage(task, acc)

            sections = [s for t in topics for s in t.sections]
            cutter = cutter_factory(
                source, audio_cutter=self._audio_cutter, video_cutter=self._video_cutter
            )
            await self._set(task, stage=cut_stage, progress=plan.stage_start(cut_stage))
            fragments = await cutter.cut(
                source_path=cut_source,
                sections=sections,
                output_dir=work_dir / ("video" if is_video else "audio"),
            )

            await self._set(
                task, stage=PipelineStage.EXPORT, progress=plan.stage_start(PipelineStage.EXPORT)
            )
            zip_path = await self._exporter.export(
                topics=topics,
                media_fragments=fragments,
                slide_images=slide_images,
                output_dir=work_dir / "export",
                media_kind="video" if is_video else "audio",
            )

            await self._set(
                task,
                status=TaskStatus.DONE,
                stage=PipelineStage.EXPORT,
                progress=100,
                result_path=str(zip_path),
                error=None,
            )
            return zip_path
        except Exception as exc:
            logger.warning("Пайплайн упал для task=%s: %s", task.task_id, exc)
            # Best-effort: пересчитать total и сохранить частичный расход,
            # чтобы он доехал на FAILED/INTERRUPTED.
            acc.compute_total()
            task.usage = acc.usage
            await self._set(
                task, status=TaskStatus.FAILED, error=f"{exc}\n{traceback.format_exc()}"
            )
            raise
