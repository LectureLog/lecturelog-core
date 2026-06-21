from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from lecturelog.api.dependencies import (
    get_gemini,
    get_presign_expiry,
    get_repository,
    get_storage,
    get_video_slides_config,
    get_work_dir,
    get_worker,
)
from lecturelog.api.schemas import (
    CreateTaskResponse,
    TaskStatusResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from lecturelog.application.use_cases.create_task import CreateTaskUseCase
from lecturelog.application.use_cases.get_result import GetResultUseCase
from lecturelog.application.use_cases.get_status import GetStatusUseCase
from lecturelog.application.use_cases.get_transcript import GetTranscriptUseCase
from lecturelog.application.worker import PipelineJob
from lecturelog.domain.exceptions import TranscribeFailed
from lecturelog.domain.media_source import (
    AudioSource,
    S3ObjectSource,
    VideoFileSource,
    VideoUrlSource,
)
from lecturelog.infrastructure.media.url_utils import is_url
from lecturelog.infrastructure.slides.document_provider import DocumentSlideProvider
from lecturelog.infrastructure.slides.video_provider import VideoSlideProvider
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


def _transcript_srt_path(work_dir: Path, task_id: str) -> Path:
    return work_dir / task_id / "transcribe" / "transcript.srt"


def _safe_filename(filename: str) -> str:
    # Берём только basename и режем потенциально опасные сепараторы,
    # чтобы клиент не задал ключ вне своего uploads/<uuid>/ префикса.
    name = Path(filename).name.replace("\\", "_")
    return name or "upload.bin"


@router.post("/tasks", response_model=CreateTaskResponse)
async def create_task(
    request: Request,
    audio: Annotated[UploadFile | None, File()] = None,
    video: Annotated[UploadFile | None, File()] = None,
    video_url: Annotated[str | None, Form()] = None,
    s3_key: Annotated[str | None, Form()] = None,
    media: Annotated[str | None, Form()] = None,
    slides: Annotated[UploadFile | None, File()] = None,
    no_slides: Annotated[bool, Form()] = False,
    repository=Depends(get_repository),
    worker=Depends(get_worker),
    work_dir: Path = Depends(get_work_dir),
    gemini=Depends(get_gemini),
    video_slides_config: dict = Depends(get_video_slides_config),
):
    sources_count = sum(x is not None for x in (audio, video, video_url, s3_key))
    if sources_count != 1:
        return JSONResponse(
            status_code=400,
            content={"detail": "Specify exactly one of: audio, video, video_url, s3_key"},
        )
    if video_url is not None and not is_url(video_url):
        return JSONResponse(
            status_code=400,
            content={"detail": "video_url должен быть http/https URL"},
        )
    if s3_key is not None and (media or "audio") not in ("audio", "video"):
        return JSONResponse(
            status_code=400,
            content={"detail": "media должен быть audio или video"},
        )

    media_upload = audio if audio is not None else video

    async def enqueue(task_id: str) -> None:
        task_dir = work_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Источник: сохраняем загруженный файл (audio/video) на диск; для video_url
        # файла нет — его скачает ingestor внутри pipeline; для s3_key исходник уже
        # в MinIO (uploads/) — его скачает pipeline по ключу.
        if s3_key is not None:
            source = S3ObjectSource(key=s3_key, media=media or "audio")
        elif video_url is not None:
            source = VideoUrlSource(url=video_url)
        else:
            media_path = task_dir / (media_upload.filename or "media.bin")
            await _save_upload(media_upload, media_path)
            source = (
                VideoFileSource(path=media_path)
                if video is not None
                else AudioSource(path=media_path)
            )

        # Документ-провайдер можно собрать сразу (файл приложен).
        document_provider = None
        if slides is not None:
            slides_path = task_dir / (slides.filename or "slides.bin")
            await _save_upload(slides, slides_path)
            document_provider = DocumentSlideProvider(slides_path=slides_path)

        # Видео-провайдер отложен: video_path появится только после ingest/скачивания.
        is_video_request = (
            video is not None or video_url is not None or (s3_key is not None and media == "video")
        )
        video_slide_provider_factory = None
        if is_video_request:

            def video_slide_provider_factory(local_video: Path):
                return VideoSlideProvider(
                    gemini_client=gemini,
                    video_path=local_video,
                    models=video_slides_config["models"],
                    concurrency=video_slides_config["concurrency"],
                    prompts_dir=video_slides_config["prompts_dir"],
                )

        # Три режима слайдов: no_slides гасит оба провайдера; документ приоритетнее
        # видео; отложенный видео-провайдер строит pipeline после ingest.
        if no_slides:
            document_provider = None
            video_slide_provider_factory = None

        task = await repository.get(task_id)
        await worker.enqueue(
            PipelineJob(
                task_id=task_id,
                task=task,
                source=source,
                slide_provider=document_provider,
                work_dir=task_dir,
                video_slide_provider_factory=video_slide_provider_factory,
            )
        )

    # Источник для use-case нужен только ради source.kind (Task.source_kind);
    # реальные пути собираются в enqueue, когда известен task_id.
    if s3_key is not None:
        kind_source = S3ObjectSource(key=s3_key, media=media or "audio")
    elif video_url is not None:
        kind_source = VideoUrlSource(url=video_url)
    elif video is not None:
        kind_source = VideoFileSource(path=Path("placeholder.bin"))
    else:
        kind_source = AudioSource(path=Path("placeholder.bin"))

    use_case = CreateTaskUseCase(repository=repository, enqueue=enqueue)
    task_id = await use_case.execute(source=kind_source, slides_path=None)
    return CreateTaskResponse(task_id=task_id)


@router.post("/uploads", response_model=UploadUrlResponse)
async def create_upload_url(
    body: UploadUrlRequest,
    storage=Depends(get_storage),
    expires_in: int = Depends(get_presign_expiry),
):
    # Презентуем платформе presigned PUT в uploads/<uuid>/<safe-filename>.
    key = f"uploads/{uuid4().hex}/{_safe_filename(body.filename)}"
    url = await storage.presigned_put(key, expires_in=expires_in)
    if url is None:
        return JSONResponse(
            status_code=409,
            content={"detail": "presigned upload недоступен: S3_PUBLIC_ENDPOINT не задан"},
        )
    return UploadUrlResponse(key=key, url=url, expires_in=expires_in)


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
    work_dir: Path = Depends(get_work_dir),
):
    # Валидация формата заранее, до проверки статуса задачи.
    if format not in ("srt", "txt"):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_format", "allowed": ["srt", "txt"]},
        )

    use_case = GetTranscriptUseCase(
        repository=repository,
        srt_path_for=lambda tid: _transcript_srt_path(work_dir, tid),
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
            path=result.path,
            filename="transcript.srt",
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
