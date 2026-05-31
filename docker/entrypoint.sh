#!/usr/bin/env bash
set -e
echo "Применяю миграции Alembic..."
alembic upgrade head
echo "Запускаю API..."
exec uvicorn lecturelog.api.app:create_app --factory --host 0.0.0.0 --port 8000
