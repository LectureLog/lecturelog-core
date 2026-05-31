# LectureLog

HTTP-сервис обработки лекций: на вход — аудиозапись лекции (опционально + слайды PDF/PPTX),
на выходе — структурированный конспект в формате Obsidian (Markdown + нарезанные
аудиофрагменты + слайды), упакованный в ZIP.

Проект построен по принципам чистой архитектуры: доменный слой не зависит от инфраструктуры,
внешние сервисы (Groq, Gemini, ffmpeg, Postgres) подключаются через порты.

> **Статус:** текущая версия реализует **аудиорежим**. Видеорежим (загрузка видеофайла
> или ссылки) — в разработке (PR #2).

## Что умеет

1. **Транскрибация** аудио в SRT через Groq Whisper (нарезка на чанки, ротация ключей при rate limit).
2. **Структуризация** транскрипта на темы и подтемы через Gemini, с привязкой слайдов.
3. **Конвертация слайдов** PDF/PPTX → PNG (pymupdf + LibreOffice).
4. **Нарезка аудио** по секциям конспекта через ffmpeg.
5. **Экспорт** в ZIP: `конспект.md` (с виджетом аудиоплеера Obsidian) + аудиофрагменты + слайды.

Состояние задач хранится в Postgres и переживает рестарт сервиса. Зависшие после рестарта
задачи автоматически помечаются как `interrupted`. Несколько лекций обрабатываются параллельно
(лимит — `MAX_CONCURRENT_TASKS`), остальные ждут в очереди.

## Запуск

### Через Docker Compose (рекомендуется)

```bash
cp .env.example .env          # впишите реальные GROQ_API_KEYS и GEMINI_API_KEYS
docker compose up --build
```

Поднимутся два сервиса: `db` (Postgres 16) и `api`. Миграции применяются автоматически
на старте контейнера. API доступен на `http://localhost:8000`.

Проверка:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok"}
```

### Локально (для разработки)

Нужны системные пакеты: `ffmpeg`, `libreoffice`, `poppler-utils`.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# поднимите Postgres и пропишите DATABASE_URL в окружении
alembic upgrade head
uvicorn lecturelog.api.app:create_app --factory --reload
```

## API

Базовый префикс — `/api/v1`.

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/tasks` | Создать задачу. multipart: ровно один из `audio` (file) / `video` / `video_url`; опционально `slides` (file). Возвращает `{"task_id": "<hex>"}`. |
| `GET` | `/tasks/{id}` | Статус задачи: `{task_id, stage, progress_pct, error, result_path}`. |
| `GET` | `/tasks/{id}/transcript?format=srt\|txt` | Транскрипт (SRT или plain text). |
| `GET` | `/tasks/{id}/result` | Готовый ZIP (`application/zip`). |
| `GET` | `/health` | Healthcheck. |

### Коды ответов

- `POST /tasks`: `200` — успех; `400` — не ровно один источник, либо передан видеоисточник (в текущей версии).
- `GET /tasks/{id}`: `200` — статус; `404` — задача не найдена.
- `GET /tasks/{id}/transcript`:
  - `400` — `format` не `srt`/`txt`: `{"error":"invalid_format","allowed":["srt","txt"]}`
  - `404` — задачи нет: `{"error":"task_not_found"}`
  - `409` — упало на транскрибации: `{"error":"transcribe_failed","detail":"..."}`
  - `202` — ещё не готово: `{"status":"in_progress","stage":...,"progress":...}`
  - `200` — готово (SRT-файл или plain text).
- `GET /tasks/{id}/result`: `200` — ZIP; `404` — результат не готов / файл не найден / задачи нет.

### Пример

```bash
# создать задачу (аудио + слайды)
curl -F "audio=@lecture.mp3" -F "slides=@slides.pdf" \
     http://localhost:8000/api/v1/tasks
# {"task_id":"a1b2c3..."}

# опросить статус
curl http://localhost:8000/api/v1/tasks/a1b2c3...

# забрать результат, когда status=done
curl -OJ http://localhost:8000/api/v1/tasks/a1b2c3.../result
```

## Конфигурация

Переменные окружения (см. `.env.example`):

| Переменная | Назначение |
|---|---|
| `GROQ_API_KEYS` | Ключи Groq (через запятую), для транскрибации. |
| `GEMINI_API_KEYS` | Ключи Gemini (через запятую), для структуризации. |
| `GEMINI_MODELS_*` | Приоритетные списки моделей по этапам (fallback при 429). |
| `GEMINI_CONCURRENCY_*` | Параллельность вызовов Gemini по этапам. |
| `DATABASE_URL` | Async-URL Postgres (`postgresql+asyncpg://...`). |
| `UPLOAD_DIR` | Каталог для загрузок и артефактов. |
| `MAX_CONCURRENT_TASKS` | Сколько лекций обрабатывать одновременно. |

## Тесты

```bash
pytest
```

Юнит-тесты гоняют репозиторий на SQLite in-memory, а инфраструктурные зависимости
(Groq/Gemini/ffmpeg) мокаются — реальные ключи и внешние сервисы для тестов не нужны.

## Архитектура

```
lecturelog/
  domain/          модели, enums, порты, исключения — без зависимостей от инфраструктуры
  application/     ProgressPlan, PipelineService (оркестрация), use-cases, PipelineWorker
  infrastructure/  реализации портов: transcribe, structurize, slides, media, export, persistence, llm
  api/             FastAPI: роуты, DTO, обработчики исключений, lifespan (composition root)
  config/          настройки через pydantic-settings
migrations/        Alembic
```

Поток обработки (аудио): `transcribe → slides → structurize → audio_cut → export`.
Прогресс по стадиям инкапсулирован в `ProgressPlan`; статус персистится в Postgres после
каждого шага.
