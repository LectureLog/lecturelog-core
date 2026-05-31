from __future__ import annotations

from functools import cached_property, lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


class GroqConfig(BaseSettings):
    model_config = _BASE
    api_keys_raw: str = Field(alias="GROQ_API_KEYS")

    @property
    def keys(self) -> list[str]:
        return _split_csv(self.api_keys_raw)


class GeminiConfig(BaseSettings):
    model_config = _BASE
    api_keys_raw: str = Field(alias="GEMINI_API_KEYS")
    models_split: str = Field("gemini-3.5-flash,gemini-3-flash-preview", alias="GEMINI_MODELS_SPLIT")
    models_subsplit: str = Field("gemini-3.5-flash,gemini-3-flash-preview", alias="GEMINI_MODELS_SUBSPLIT")
    models_render: str = Field("gemini-3.1-flash-lite,gemini-3.5-flash,gemini-3-flash-preview", alias="GEMINI_MODELS_RENDER")
    models_video_slides: str = Field("gemini-3-flash-preview,gemini-3.5-flash", alias="GEMINI_MODELS_VIDEO_SLIDES")
    concurrency_subsplit: int = Field(2, alias="GEMINI_CONCURRENCY_SUBSPLIT")
    concurrency_render: int = Field(5, alias="GEMINI_CONCURRENCY_RENDER")
    concurrency_video: int = Field(5, alias="GEMINI_CONCURRENCY_VIDEO")

    @property
    def keys(self) -> list[str]:
        return _split_csv(self.api_keys_raw)

    @property
    def split_models(self) -> list[str]:
        return _split_csv(self.models_split)

    @property
    def subsplit_models(self) -> list[str]:
        return _split_csv(self.models_subsplit)

    @property
    def render_models(self) -> list[str]:
        return _split_csv(self.models_render)

    @property
    def video_slides_models(self) -> list[str]:
        return _split_csv(self.models_video_slides)


class DatabaseConfig(BaseSettings):
    model_config = _BASE
    url: str = Field(alias="DATABASE_URL")


class StorageConfig(BaseSettings):
    model_config = _BASE
    upload_dir: str = Field("/app/data", alias="UPLOAD_DIR")


class WorkerConfig(BaseSettings):
    model_config = _BASE
    max_concurrent_tasks: int = Field(2, alias="MAX_CONCURRENT_TASKS")


class AppConfig(BaseSettings):
    # Сборка под-конфигов как computed-полей: каждый блок сам читает env,
    # поэтому AppConfig не объявляет собственных env-полей и ничего не валидирует напрямую.
    model_config = _BASE

    def model_post_init(self, __context: object) -> None:
        # Форсируем создание под-конфигов сразу, чтобы required-поля
        # (GROQ_API_KEYS и т.д.) валидировались в момент построения AppConfig.
        _ = (self.groq, self.gemini, self.database, self.storage, self.worker)

    @computed_field  # type: ignore[prop-decorator]
    @cached_property
    def groq(self) -> GroqConfig:
        return GroqConfig()

    @computed_field  # type: ignore[prop-decorator]
    @cached_property
    def gemini(self) -> GeminiConfig:
        return GeminiConfig()

    @computed_field  # type: ignore[prop-decorator]
    @cached_property
    def database(self) -> DatabaseConfig:
        return DatabaseConfig()

    @computed_field  # type: ignore[prop-decorator]
    @cached_property
    def storage(self) -> StorageConfig:
        return StorageConfig()

    @computed_field  # type: ignore[prop-decorator]
    @cached_property
    def worker(self) -> WorkerConfig:
        return WorkerConfig()


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
