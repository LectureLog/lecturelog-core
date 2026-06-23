#!/bin/sh
# Инициализация бакета lectures и применение правил жизненного цикла (ILM).
# Запускается в контейнере minio/mc как инит-шаг (после minio healthy),
# затем завершается. Идемпотентен: повторный старт безопасен.
set -eu

# Подключаемся к локальному MinIO внутри docker-сети.
mc alias set local http://minio:9000 minioadmin minioadmin

# Бакет создаём идемпотентно.
mc mb --ignore-existing local/lectures

# Применяем lifecycle через rule import: JSON ЦЕЛИКОМ перезаписывает набор правил
# бакета → повторный запуск не дублирует и не падает (идемпотентно).
#   expire-uploads      uploads/      Expiration 7д   — сырые исходники живут недолго.
#   abort-mpu-uploads   uploads/      AbortMPU 1д     — чистка orphan-parts от
#                                                       оборванных presigned-PUT заливок.
#   expire-results-tmp  results-tmp/  Expiration 1д   — временные zip от /result-url.
# ВАЖНО: results/ (постоянные лекции, ∞ до DELETE) БЕЗ правил. Префикс results-tmp/
# строго со слешом — НЕ задевает results/ (8-я позиция '-' против '/'), критичный инвариант.
mc ilm rule import local/lectures <<'JSON'
{
  "Rules": [
    {
      "ID": "expire-uploads",
      "Status": "Enabled",
      "Filter": { "Prefix": "uploads/" },
      "Expiration": { "Days": 7 }
    },
    {
      "ID": "abort-mpu-uploads",
      "Status": "Enabled",
      "Filter": { "Prefix": "uploads/" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
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

echo "minio-init: бакет lectures готов, ILM-правила применены (3 правила)."
