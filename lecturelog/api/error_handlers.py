from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lecturelog.domain.exceptions import (
    InvalidSource, ResultNotReady, TaskNotFound,
)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TaskNotFound)
    async def _not_found(request: Request, exc: TaskNotFound):
        return JSONResponse(status_code=404, content={"detail": "Task not found"})

    @app.exception_handler(ResultNotReady)
    async def _not_ready(request: Request, exc: ResultNotReady):
        return JSONResponse(status_code=404, content={"detail": "Result is not ready"})

    @app.exception_handler(InvalidSource)
    async def _bad_source(request: Request, exc: InvalidSource):
        return JSONResponse(status_code=400, content={"detail": str(exc)})
