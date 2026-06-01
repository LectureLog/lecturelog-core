from __future__ import annotations

from pathlib import Path

from fastapi import Request

from lecturelog.application.worker import PipelineWorker
from lecturelog.domain.ports import TaskRepository


def get_repository(request: Request) -> TaskRepository:
    return request.app.state.repository


def get_worker(request: Request) -> PipelineWorker:
    return request.app.state.worker


def get_upload_dir(request: Request) -> Path:
    return request.app.state.upload_dir


def get_gemini(request: Request):
    return request.app.state.gemini


def get_video_slides_config(request: Request) -> dict:
    return {
        "models": request.app.state.video_slides_models,
        "concurrency": request.app.state.concurrency_video,
        "prompts_dir": request.app.state.prompts_dir,
    }
