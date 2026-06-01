from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from lecturelog.application.pipeline_service import PipelineService
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.application.worker import PipelineWorker
from lecturelog.config.settings import get_config
from lecturelog.infrastructure.export.obsidian_exporter import ObsidianExporter
from lecturelog.infrastructure.llm.gemini_client import GeminiClient
from lecturelog.infrastructure.llm.key_pool import KeyPool
from lecturelog.infrastructure.media.audio_cutter import FfmpegAudioCutter
from lecturelog.infrastructure.persistence.engine import make_engine, make_session_factory
from lecturelog.infrastructure.persistence.task_repository import PostgresTaskRepository
from lecturelog.infrastructure.structurize.gemini_structurizer import GeminiStructurizer
from lecturelog.infrastructure.transcribe.groq_transcriber import GroqTranscriber

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()

    engine = make_engine(cfg.database.url)
    session_factory = make_session_factory(engine)
    repo = PostgresTaskRepository(session_factory=session_factory)

    interrupted = await repo.mark_stale_as_interrupted()
    if interrupted:
        logger.warning("Помечено INTERRUPTED задач после рестарта: %d", interrupted)

    # Клиенты Gemini по каждому ключу -> KeyPool
    from google import genai  # type: ignore

    clients = [genai.Client(api_key=k) for k in cfg.gemini.keys]
    pool = KeyPool(clients=clients)
    gemini = GeminiClient(pool=pool)

    transcriber = GroqTranscriber(groq_api_keys=cfg.groq.keys)
    structurizer = GeminiStructurizer(
        gemini_client=gemini,
        split_models=cfg.gemini.split_models,
        subsplit_models=cfg.gemini.subsplit_models,
        render_models=cfg.gemini.render_models,
        concurrency_subsplit=cfg.gemini.concurrency_subsplit,
        concurrency_render=cfg.gemini.concurrency_render,
        prompts_dir=Path("prompts"),
    )
    service = PipelineService(
        repository=repo, transcriber=transcriber, structurizer=structurizer,
        audio_cutter=FfmpegAudioCutter(), exporter=ObsidianExporter(),
        progress_plan_factory=ProgressPlan.for_audio,
    )
    worker = PipelineWorker(service=service, concurrency=cfg.worker.max_concurrent_tasks)
    await worker.start()

    app.state.config = cfg
    app.state.repository = repo
    app.state.worker = worker
    app.state.upload_dir = Path(cfg.storage.upload_dir)
    try:
        yield
    finally:
        await worker.stop()
        await engine.dispose()
