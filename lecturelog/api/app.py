from __future__ import annotations

from fastapi import FastAPI

from lecturelog.api.error_handlers import register_error_handlers
from lecturelog.api.lifespan import lifespan
from lecturelog.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="LectureLog", lifespan=lifespan)
    app.include_router(router)
    register_error_handlers(app)
    return app
