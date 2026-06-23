#!/usr/bin/env python3
"""Минимальный клиент LectureLog: отправка задачи и опрос статуса.

Использует только стандартную библиотеку (urllib) — без внешних зависимостей.
Базовый URL берётся из переменной окружения LECTURELOG_URL или флага --base.

Примеры:
    # отправить аудио (+ опционально слайды) и получить task_id
    python scripts/submit_task.py submit --audio lecture.mp3 --slides slides.pdf

    # видео (слайды извлекаются из видеоряда автоматически)
    python scripts/submit_task.py submit --video lecture.mp4
    python scripts/submit_task.py submit --video-url "https://youtu.be/abc"

    # видео без слайдов
    python scripts/submit_task.py submit --video lecture.mp4 --no-slides

    # узнать статус (разово)
    python scripts/submit_task.py status <task_id>

    # опрашивать статус, пока задача не завершится (done/failed)
    python scripts/submit_task.py poll <task_id>

    # скачать готовый ZIP
    python scripts/submit_task.py result <task_id> -o out.zip

    # забрать транскрипт (srt|txt)
    python scripts/submit_task.py transcript <task_id> --format txt

    # удалить задачу (результаты в MinIO + запись в БД, идемпотентно)
    python scripts/submit_task.py delete <task_id>
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

DEFAULT_BASE = os.environ.get("LECTURELOG_URL", "http://localhost:8000/api/v1")

# Размер чанка при потоковом скачивании результата на диск.
_DOWNLOAD_CHUNK = 1024 * 1024


def _fail(message: str) -> None:
    """Напечатать ошибку в stderr и выйти с ненулевым кодом."""
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _request(req: urllib.request.Request) -> urllib.response.addinfourl:
    """Выполнить запрос, превратив HTTP-ошибку в читаемое сообщение.

    urllib бросает HTTPError на 4xx/5xx — без обработки это трейсбек.
    Тело ответа сервера (обычно JSON с detail/error) показываем как есть.
    """
    try:
        return urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        _fail(f"HTTP {exc.code} {exc.reason}: {body}")
    except urllib.error.URLError as exc:
        _fail(f"Не удалось подключиться к {req.full_url}: {exc.reason}")


def _get_json(url: str) -> dict[str, Any]:
    with _request(urllib.request.Request(url)) as resp:
        return json.loads(resp.read().decode())


def _build_multipart(
    files: dict[str, Path], fields: dict[str, str] | None = None
) -> tuple[bytes, str]:
    """Собрать тело multipart/form-data вручную (без requests).

    Файлы целиком читаются в память — для очень больших медиа это заметный
    расход RAM, но stdlib не даёт простого потокового multipart-аплоада.
    Текстовые поля (fields) пишутся как обычные form-part без filename.
    """
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in (fields or {}).items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode()
        out += b"\r\n"
    for name, path in files.items():
        if not path.is_file():
            _fail(f"Файл не найден: {path}")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
        ).encode()
        out += f"Content-Type: {ctype}\r\n\r\n".encode()
        out += path.read_bytes()
        out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _is_terminal(status: dict[str, Any]) -> str | None:
    """Вернуть 'done'/'failed', если задача завершилась, иначе None.

    В DTO нет явного поля статуса — завершённость выводим из result_path/error.
    """
    if status.get("error"):
        return "failed"
    if status.get("result_path"):
        return "done"
    return None


def _format_status(status: dict[str, Any]) -> str:
    return (
        f"stage={status.get('stage')} "
        f"progress={status.get('progress_pct')}% "
        f"error={status.get('error')}"
    )


def cmd_submit(args: argparse.Namespace) -> None:
    sources = sum(x is not None for x in (args.audio, args.video, args.video_url))
    if sources != 1:
        _fail("Передайте ровно один из: --audio, --video, --video-url")

    files: dict[str, Path] = {}
    fields: dict[str, str] = {}
    if args.audio:
        files["audio"] = Path(args.audio)
    elif args.video:
        files["video"] = Path(args.video)
    else:
        fields["video_url"] = args.video_url

    if args.slides:
        files["slides"] = Path(args.slides)
    if args.no_slides:
        fields["no_slides"] = "true"

    body, ctype = _build_multipart(files, fields)
    req = urllib.request.Request(
        f"{args.base}/tasks", data=body, headers={"Content-Type": ctype}, method="POST"
    )
    with _request(req) as resp:
        data = json.loads(resp.read().decode())
    print(data["task_id"])


def cmd_status(args: argparse.Namespace) -> None:
    print(json.dumps(_get_json(f"{args.base}/tasks/{args.task_id}"), ensure_ascii=False))


def cmd_poll(args: argparse.Namespace) -> None:
    while True:
        status = _get_json(f"{args.base}/tasks/{args.task_id}")
        print(_format_status(status), flush=True)
        terminal = _is_terminal(status)
        if terminal == "done":
            print(f"DONE -> {status['result_path']}")
            return
        if terminal == "failed":
            _fail(f"FAILED: {status['error']}")
        time.sleep(args.interval)


def cmd_result(args: argparse.Namespace) -> None:
    req = urllib.request.Request(f"{args.base}/tasks/{args.task_id}/result")
    with _request(req) as resp, open(args.output, "wb") as out:
        shutil.copyfileobj(resp, out, _DOWNLOAD_CHUNK)
    print(f"saved -> {args.output}")


def cmd_delete(args: argparse.Namespace) -> None:
    """Удалить задачу: чистит результаты/исходник в MinIO и запись в БД.

    Эндпоинт идемпотентен — повтор на уже удалённую/неизвестную задачу тоже
    отдаёт 204, поэтому отдельной ветки «не найдено» здесь нет.
    """
    req = urllib.request.Request(f"{args.base}/tasks/{args.task_id}", method="DELETE")
    with _request(req):
        pass
    print(f"deleted -> {args.task_id}")


def cmd_transcript(args: argparse.Namespace) -> None:
    req = urllib.request.Request(
        f"{args.base}/tasks/{args.task_id}/transcript?format={args.format}"
    )
    with _request(req) as resp:
        sys.stdout.buffer.write(resp.read())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LectureLog client")
    parser.add_argument(
        "--base", default=DEFAULT_BASE, help=f"базовый URL API (по умолчанию {DEFAULT_BASE})"
    )
    sub = parser.add_subparsers(required=True)

    s = sub.add_parser("submit", help="создать задачу")
    s.add_argument("--audio", help="путь к аудиофайлу")
    s.add_argument("--video", help="путь к видеофайлу")
    s.add_argument("--video-url", dest="video_url", help="URL видео (YouTube/HTTP)")
    s.add_argument("--slides", help="путь к PDF/PPTX со слайдами")
    s.add_argument(
        "--no-slides",
        dest="no_slides",
        action="store_true",
        help="не делать слайды (для видео — отключить авто-извлечение)",
    )
    s.set_defaults(func=cmd_submit)

    st = sub.add_parser("status", help="разовый статус")
    st.add_argument("task_id")
    st.set_defaults(func=cmd_status)

    pl = sub.add_parser("poll", help="опрашивать до завершения")
    pl.add_argument("task_id")
    pl.add_argument("--interval", type=float, default=3.0)
    pl.set_defaults(func=cmd_poll)

    r = sub.add_parser("result", help="скачать готовый ZIP")
    r.add_argument("task_id")
    r.add_argument("-o", "--output", default="result.zip")
    r.set_defaults(func=cmd_result)

    d = sub.add_parser("delete", help="удалить задачу (MinIO + БД, идемпотентно)")
    d.add_argument("task_id")
    d.set_defaults(func=cmd_delete)

    t = sub.add_parser("transcript", help="забрать транскрипт")
    t.add_argument("task_id")
    t.add_argument("--format", choices=["srt", "txt"], default="srt")
    t.set_defaults(func=cmd_transcript)

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
