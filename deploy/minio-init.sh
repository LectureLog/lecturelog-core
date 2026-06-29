#!/bin/sh
# Инициализация бакета LectureLog и применение правил жизненного цикла (ILM).
# Запускается в контейнере minio/mc как идемпотентный init-step.
set -eu

: "${S3_BUCKET:?S3_BUCKET is required}"
: "${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY is required}"

mc alias set local http://lecturelog-core-minio:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY"

mc mb --ignore-existing "local/$S3_BUCKET"

# rule import целиком перезаписывает набор правил, поэтому повторный запуск безопасен.
# uploads/ живёт 7 дней, results-tmp/ живёт 1 день, постоянный results/ правил не имеет.
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

echo "minio-init: бакет $S3_BUCKET готов, ILM-правила применены."
