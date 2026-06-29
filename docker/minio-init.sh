#!/bin/sh
# Инициализация бакета lectures и применение правил жизненного цикла (ILM).
# Запускается в контейнере minio/mc как инит-шаг (после minio healthy),
# затем завершается. Идемпотентен: повторный старт безопасен.
set -eu

: "${S3_BUCKET:?S3_BUCKET is required}"
: "${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY is required}"

# Подключаемся к локальному MinIO внутри docker-сети.
mc alias set local http://minio:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY"

# Бакет создаём идемпотентно.
mc mb --ignore-existing "local/$S3_BUCKET"

# Применяем lifecycle через rule import: JSON ЦЕЛИКОМ перезаписывает набор правил
# бакета → повторный запуск не дублирует и не падает (идемпотентно).
#   expire-uploads      uploads/      Expiration 7д   — сырые исходники живут недолго.
#   expire-results-tmp  results-tmp/  Expiration 1д   — временные zip от /result-url.
# ВАЖНО: results/ (постоянные лекции, ∞ до DELETE) БЕЗ правил. Префикс results-tmp/
# строго со слешом — НЕ задевает results/ (8-я позиция '-' против '/'), критичный инвариант.
# ЗАМЕТКА: orphan-части оборванных multipart-заливок чистит САМ MinIO (серверная
# настройка MINIO_API_STALE_UPLOADS_EXPIRY в docker-compose.yml), а НЕ ILM-правило —
# действие AbortIncompleteMultipartUpload через lifecycle MinIO не применяет
# (апстрим закрыл как working-as-intended, minio/minio#19115, #16120).
mc ilm rule import "local/$S3_BUCKET" <<'JSON'
{
  "Rules": [
    {
      "ID": "expire-uploads",
      "Status": "Enabled",
      "Filter": { "Prefix": "uploads/" },
      "Expiration": { "Days": 7 }
    },
    {
      "ID": "expire-results-tmp",
      "Status": "Enabled",
      "Filter": { "Prefix": "results-tmp/" },
      "Expiration": { "Days": 1 }
    }
  ]
}
JSON

echo "minio-init: бакет $S3_BUCKET готов, ILM-правила применены (2 правила)."
