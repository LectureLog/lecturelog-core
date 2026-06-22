from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from fastapi import FastAPI

from lecturelog.api.error_handlers import register_error_handlers
from lecturelog.api.lifespan import lifespan
from lecturelog.api.routes import router

# Описание продукта для секции info OpenAPI (источник правды для генерации клиента).
_DESCRIPTION = "Сервис обработки лекций: медиа + слайды -> структурированный конспект"


def _app_version() -> str:
    # Версия берётся из метаданных установленного пакета; фоллбэк — на случай,
    # если пакет не установлен (например, запуск из исходников без editable install).
    try:
        return _pkg_version("lecturelog")
    except PackageNotFoundError:
        return "1.0.0"


def create_app() -> FastAPI:
    app = FastAPI(
        title="LectureLog",
        version=_app_version(),
        description=_DESCRIPTION,
        lifespan=lifespan,
    )
    app.include_router(router)
    register_error_handlers(app)
    return app
