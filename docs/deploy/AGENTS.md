# Deploy Workflow for Agents

Этот документ — рабочий регламент для AI-агентов, которые меняют деплой, CI,
ветки и релизы LectureLog.

## Текущий режим

- Работаем в ветке `dev`.
- В `main` ничего не льём без прямой команды человека.
- `latest` — только Docker-тег, не git-ветка.
- GitHub Actions публикует `ghcr.io/lecturelog/lecturelog-core:dev` при push в `dev`.
- GitHub Actions публикует `ghcr.io/lecturelog/lecturelog-core:vX.Y.Z` и `:latest`
  только при push git tag `vX.Y.Z`.

## Модель веток

```text
node/<задача> или рабочая ветка -> dev -> main -> tag vX.Y.Z
```

Правила:

1. Для текущей разработки коммитить и пушить только в `dev`.
2. Не пушить в `main`, если человек явно не попросил stable-релиз.
3. Не создавать ветку `latest`.
4. Перед удалением старых remote-веток проверять, что `dev` уже есть на GitHub.
5. Не трогать чужие незакоммиченные изменения в основном worktree.

## Что проверять перед push

Минимальный gate для core:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
.venv/bin/python scripts/export_openapi.py
git diff --exit-code docs/openapi.json
git diff --check
```

Если `.venv` нет, создать и поставить зависимости:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Синхронизация версий и контракта

Текущая модель — lockstep product version:

- core и web в стабильном релизе получают один и тот же git tag `vX.Y.Z`;
- core и web images с тегами `:vX.Y.Z` должны быть совместимы друг с другом;
- `:latest` в обоих репозиториях должен указывать на одну стабильную пару;
- `:dev` — плавающий канал разработки, его можно обновлять часто, но после
  контрактных изменений core и web надо выкатывать парой.

Источник правды по API — `docs/openapi.json` в этом репозитории. Web хранит
vendored snapshot этого контракта в `internal/coreclient/openapi.json`.

Если менялся API core:

1. Изменить код API в core.
2. Регенерировать OpenAPI:

   ```bash
   .venv/bin/python scripts/export_openapi.py
   git diff --exit-code docs/openapi.json
   ```

   Если diff есть, его надо закоммитить вместе с изменением API.
3. В web подтянуть новый snapshot:

   ```bash
   make sync-spec
   make generate
   GOMODCACHE=/tmp/go-modcache GOCACHE=/tmp/go-build make gate
   ```

4. Обновить доменный код web под новый контракт.
5. Пушить оба репозитория в `dev` и обновлять VPS оба стека:

   ```bash
   cd /opt/lecturelog-core && docker compose pull && docker compose up -d
   cd /opt/lecturelog-web && docker compose pull && docker compose up -d
   ```

Если менялся core без изменения OpenAPI, web обновлять не обязательно. Если
менялся только UI/web без изменения контракта, core обновлять не обязательно. Но
stable-релиз всё равно выпускается парой с одним тегом `vX.Y.Z`.

## Как пушить dev

Если текущая ветка ещё называется `integration`, переименовать её локально:

```bash
git branch -m integration dev
```

Для worktree-ветки с готовыми изменениями:

```bash
git fetch origin
git checkout dev
git merge --ff-only <рабочая-ветка>
git push -u origin dev
```

Если `dev` ещё нет на remote, первый push создаст её. После проверки можно удалить
старую remote-ветку `integration`, но только когда GitHub default branch и все
активные workflow уже смотрят на `dev`:

```bash
git push origin --delete integration
```

## Как обновить VPS dev

На сервере core лежит в `/opt/lecturelog-core`.

```bash
cd /opt/lecturelog-core
docker compose pull
docker compose up -d
docker compose logs -f api
```

В `.env` должен быть dev-канал:

```env
LECTURELOG_CORE_IMAGE_TAG=dev
```

Core публикует API и MinIO только на `127.0.0.1`; наружу их должен открывать
reverse proxy. Для связки с web оба compose-стека подключаются к Docker-сети
`lecturelog-shared`, а web ходит в core по `http://lecturelog-core-api:8000`.

Webhook в `.env` должен смотреть на web:

```env
PLATFORM_CALLBACK_URL=https://app.example.com/webhooks/core
LECTURELOG_WEBHOOK_SECRET=<тот же секрет, что в web>
```

`S3_PUBLIC_ENDPOINT` должен быть публичным HTTPS endpoint MinIO без path-prefix,
например:

```env
S3_PUBLIC_ENDPOINT=https://files.example.com
```

## Как выпускать релиз

Релиз делать только после прямой команды человека. Общая последовательность:

```bash
git checkout main
git merge --ff-only dev
git tag vX.Y.Z
git push origin main vX.Y.Z
```

После push tag workflow публикует:

```text
ghcr.io/lecturelog/lecturelog-core:vX.Y.Z
ghcr.io/lecturelog/lecturelog-core:latest
```

Тот же тег `vX.Y.Z` должен быть поставлен и в `lecturelog-web`. Не выпускать
stable core с новым контрактом, если совместимый web с тем же тегом не выпущен.

Для стабильного VPS-канала заменить в `/opt/lecturelog-core/.env`:

```env
LECTURELOG_CORE_IMAGE_TAG=latest
```

Для воспроизводимого деплоя лучше использовать конкретный тег:

```env
LECTURELOG_CORE_IMAGE_TAG=vX.Y.Z
```

## Безопасность

- Не коммитить `.env`, токены, API-ключи и реальные пароли.
- Комментарии в коде писать на русском.
- Не добавлять авторство AI-ассистента в commit message, PR body или комментарии.
- Если меняется существенное поведение деплоя, обновлять `README.md` и этот документ.
