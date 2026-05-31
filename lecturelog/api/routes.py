from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from lecturelog.api.dependencies import get_repository, get_upload_dir, get_worker
from lecturelog.api.schemas import CreateTaskResponse, TaskStatusResponse
from lecturelog.application.use_cases.create_task import CreateTaskUseCase
from lecturelog.application.use_cases.get_result import GetResultUseCase
from lecturelog.application.use_cases.get_status import GetStatusUseCase
from lecturelog.application.use_cases.get_transcript import GetTranscriptUseCase
from lecturelog.application.worker import PipelineJob
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.exceptions import TranscribeFailed
from lecturelog.domain.media_source import AudioSource
from lecturelog.infrastructure.slides.document_provider import DocumentSlideProvider
from lecturelog.infrastructure.srt import srt_to_plain_text

router = APIRouter(prefix="/api/v1")

# Размер чанка для стриминговой записи UploadFile на диск:
# .read() без аргумента грузит весь файл в RAM, что недопустимо на больших медиа.
_UPLOAD_CHUNK = 1024 * 1024


async def _save_upload(upload: UploadFile, target: Path) -> None:
    with target.open("wb") as f:
        while True:
            chunk = await upload.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            f.write(chunk)


def _transcript_srt_path(upload_dir: Path, task_id: str) -> Path:
    return upload_dir / task_id / "transcribe" / "transcript.srt"


@router.post("/tasks", response_model=CreateTaskResponse)
async def create_task(
    request: Request,
    audio: Annotated[Optional[UploadFile], File()] = None,
    video: Annotated[Optional[UploadFile], File()] = None,
    video_url: Annotated[Optional[str], Form()] = None,
    slides: Annotated[Optional[UploadFile], File()] = None,
    repository=Depends(get_repository),
    worker=Depends(get_worker),
    upload_dir: Path = Depends(get_upload_dir),
):
    sources_count = sum(x is not None for x in (audio, video, video_url))
    if sources_count != 1:
        return JSONResponse(
            status_code=400,
            content={"detail": "Specify exactly one of: audio, video, video_url"},
        )
    # PR #1 — только аудиорежим. Видео добавится в PR #2.
    if video is not None or video_url is not None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Видеорежим будет доступен в PR #2; используйте audio"},
        )

    # task_id генерит use-case; чтобы знать каталог заранее, сохраняем во временный
    # каталог по имени, а реальный task_id подставляем через enqueue-замыкание.
    # Проще: сначала создаём use-case с enqueue, который соберёт job уже зная task_id.
    pending: dict[str, object] = {}

    async def enqueue(task_id: str) -> None:
        task_dir = upload_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        audio_path = task_dir / (audio.filename or "audio.bin")
        await _save_upload(audio, audio_path)

        slide_provider = None
        if slides is not None:
            slides_path = task_dir / (slides.filename or "slides.bin")
            await _save_upload(slides, slides_path)
            slide_provider = DocumentSlideProvider(slides_path=slides_path)

        task = await repository.get(task_id)
        await worker.enqueue(PipelineJob(
            task_id=task_id, task=task,
            source=AudioSource(path=audio_path),
            slide_provider=slide_provider, work_dir=task_dir,
        ))

    use_case = CreateTaskUseCase(repository=repository, enqueue=enqueue)
    task_id = await use_case.execute(
        source=AudioSource(path=Path(audio.filename or "audio.bin")), slides_path=None)
    return CreateTaskResponse(task_id=task_id)


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, repository=Depends(get_repository)):
    use_case = GetStatusUseCase(repository=repository)
    task = await use_case.execute(task_id)
    return TaskStatusResponse.from_task(task)


@router.get("/tasks/{task_id}/transcript")
async def get_task_transcript(
    task_id: str,
    format: str = "srt",
    repository=Depends(get_repository),
    upload_dir: Path = Depends(get_upload_dir),
):
    # Валидация формата заранее, до проверки статуса задачи.
    if format not in ("srt", "txt"):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_format", "allowed": ["srt", "txt"]},
        )

    use_case = GetTranscriptUseCase(
        repository=repository,
        srt_path_for=lambda tid: _transcript_srt_path(upload_dir, tid),
    )
    task = await repository.get(task_id)
    if task is None:
        return JSONResponse(status_code=404, content={"error": "task_not_found"})

    try:
        result = await use_case.execute(task_id)
    except TranscribeFailed:
        return JSONResponse(
            status_code=409,
            content={"error": "transcribe_failed", "detail": task.error},
        )

    if not result.ready:
        return JSONResponse(
            status_code=202,
            content={
                "status": "in_progress",
                "stage": result.stage.value if result.stage else None,
                "progress": result.progress_pct,
                "message": "Transcript not ready yet, retry later",
            },
        )

    if format == "srt":
        return FileResponse(
            path=result.path, filename="transcript.srt",
            media_type="application/x-subrip",
        )

    plain = srt_to_plain_text(result.path.read_text(encoding="utf-8"))
    return Response(
        content=plain,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="transcript.txt"'},
    )


@router.get("/tasks/{task_id}/result")
async def get_task_result(task_id: str, repository=Depends(get_repository)):
    use_case = GetResultUseCase(repository=repository)
    path = await use_case.execute(task_id)
    if not path.exists():
        return JSONResponse(status_code=404, content={"detail": "Result file not found"})
    return FileResponse(path=path, filename=path.name, media_type="application/zip")


@router.get("/health")
async def health():
    return {"status": "ok"}
