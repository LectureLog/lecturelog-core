# ruff: noqa: E501
"""Краевые случаи TTL-очистки workspace упавших задач (WorkDirSweeper, marker, _sweep_forever)."""

import asyncio
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lecturelog.api import dependencies as deps
from lecturelog.api.app import create_app
from lecturelog.api.lifespan import _sweep_forever
from lecturelog.application.worker import (
    TERMINAL_MARKER,
    PipelineJob,
    PipelineWorker,
    WorkDirSweeper,
    write_terminal_marker,
)
from lecturelog.config.settings import WorkerConfig
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.media_source import AudioSource
from lecturelog.domain.models import Task

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
RETENTION = timedelta(hours=24)
TID = "a" * 32
TID2 = "b" * 32


class Repo:
    def __init__(self, statuses=None, default=None, stage=None):
        self.statuses = dict(statuses or {})
        self.default = default
        self.stage = stage
        self.fail_for: set[str] = set()

    async def get(self, task_id):
        if task_id in self.fail_for:
            raise RuntimeError("db down")
        st = self.statuses.get(task_id, self.default)
        if st is None:
            return None
        return Task(task_id=task_id, source_kind="audio", status=st, stage=self.stage, error="boom")


def _sweeper(tmp_path, repo, retention=RETENTION, now=NOW):
    return WorkDirSweeper(repo, tmp_path, retention, clock=lambda: now)


def _ws(root: Path, tid=TID, marker_at=None, mtime_age=None, raw_marker=None):
    d = root / tid
    d.mkdir()
    (d / "raw.bin").write_bytes(b"x")
    if marker_at is not None:
        (d / TERMINAL_MARKER).write_text(json.dumps({"status": "failed", "at": marker_at}))
    if raw_marker is not None:
        (d / TERMINAL_MARKER).write_bytes(raw_marker)
    if mtime_age is not None:
        ts = (NOW - mtime_age).timestamp()
        os.utime(d, (ts, ts))
    return d


def _iso(delta):
    return (NOW - delta).isoformat()


# ---------- срок: границы ----------


async def test_marker_ровно_на_границе_срока_удаляется_потому_что_срок_истёк_включительно(tmp_path):
    d = _ws(tmp_path, marker_at=_iso(RETENTION))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert not d.exists()


async def test_marker_на_секунду_моложе_срока_сохраняется_потому_что_срок_не_истёк(tmp_path):
    d = _ws(
        tmp_path, marker_at=_iso(RETENTION - timedelta(seconds=1)), mtime_age=timedelta(days=30)
    )
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert d.exists()


async def test_marker_приоритетнее_старого_mtime_каталога_потому_что_срок_считается_от_падения(
    tmp_path,
):
    d = _ws(tmp_path, marker_at=_iso(timedelta(minutes=5)), mtime_age=timedelta(days=30))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert d.exists()


async def test_marker_без_таймзоны_трактуется_как_utc_и_свежий_не_удаляется(tmp_path):
    naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    d = _ws(tmp_path, marker_at=naive, mtime_age=timedelta(days=30))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert d.exists()


async def test_marker_с_нестандартным_смещением_сравнивается_по_абсолютному_времени(tmp_path):
    # 5 минут назад, записано в +14:00: по "голым" часам это будущее/прошлое на 14 ч.
    at = (NOW - timedelta(minutes=5)).astimezone(timezone_plus14()).isoformat()
    d = _ws(tmp_path, marker_at=at, mtime_age=timedelta(days=30))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert d.exists()


def timezone_plus14():
    from datetime import timezone

    return timezone(timedelta(hours=14))


async def test_marker_из_далёкого_будущего_не_делает_workspace_бессмертным_потому_что_диск_утечёт_навсегда(
    tmp_path,
):
    # Сбитые часы/ручная правка: at=9999 год. Срок "ещё не истёк" вечно, mtime каталога 30 дней.
    d = _ws(tmp_path, marker_at="9999-12-31T00:00:00+00:00", mtime_age=timedelta(days=30))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert not d.exists(), "marker из будущего должен считаться недостоверным и уступать mtime"


# ---------- битый marker -> откат на mtime, никогда не падение ----------

BAD_MARKERS = [
    b"",
    b"{",
    b"[]",
    b"null",
    b'"2026-01-01"',
    b'{"status": "failed"}',
    b'{"at": 12345}',
    b'{"at": null}',
    b'{"at": ""}',
    '{"at": "вчера"}'.encode(),
    b"\xff\xfe\x00garbage",
]


@pytest.mark.parametrize("raw", BAD_MARKERS)
async def test_битый_marker_не_роняет_проход_и_старый_workspace_удаляется_по_mtime(tmp_path, raw):
    d = _ws(tmp_path, raw_marker=raw, mtime_age=timedelta(days=3))
    res = await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert res.deleted == 1 and not d.exists()


@pytest.mark.parametrize("raw", BAD_MARKERS)
async def test_битый_marker_у_свежего_workspace_не_приводит_к_удалению(tmp_path, raw):
    d = _ws(tmp_path, raw_marker=raw, mtime_age=timedelta(minutes=1))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert d.exists()


async def test_marker_являющийся_каталогом_не_роняет_проход(tmp_path):
    d = _ws(tmp_path, mtime_age=timedelta(minutes=1))
    (d / TERMINAL_MARKER).mkdir()
    res = await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert d.exists() and res.deleted == 0


# ---------- статус в БД решает, marker — нет ----------


@pytest.mark.parametrize(
    "status", [TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.DONE, TaskStatus.INTERRUPTED]
)
async def test_старый_marker_не_удаляет_workspace_задачи_не_в_FAILED_потому_что_решает_статус_в_БД(
    tmp_path, status
):
    d = _ws(tmp_path, marker_at=_iso(timedelta(days=10)), mtime_age=timedelta(days=10))
    await _sweeper(tmp_path, Repo({TID: status})).sweep()
    assert (d / "raw.bin").exists()


async def test_каталог_без_строки_в_БД_не_удаляется_потому_что_это_может_быть_создание_задачи(
    tmp_path,
):
    d = _ws(tmp_path, marker_at=_iso(timedelta(days=10)), mtime_age=timedelta(days=10))
    await _sweeper(tmp_path, Repo()).sweep()
    assert d.exists()


async def test_marker_со_статусом_failed_не_заменяет_проверку_БД_когда_БД_говорит_processing(
    tmp_path,
):
    d = _ws(tmp_path, marker_at=_iso(timedelta(days=10)))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.PROCESSING})).sweep()
    assert d.exists()


# ---------- имена, зарезервированные каталоги, симлинки ----------


async def test_зарезервированные_каталоги_и_кеш_не_удаляются_даже_если_БД_ответит_FAILED_на_любой_id(
    tmp_path,
):
    keep = []
    for name in (
        "results_tmp",
        "transcript_cache",
        "f" * 64,
        "A" * 32,
        "a" * 31,
        "a" * 33,
        "not-task",
        ".hidden",
    ):
        p = tmp_path / name
        p.mkdir()
        (p / "x").write_text("x")
        os.utime(p, (0, 0))
        keep.append(p)
    await _sweeper(tmp_path, Repo(default=TaskStatus.FAILED)).sweep()
    assert all(p.exists() for p in keep)


async def test_symlink_с_именем_задачи_не_ведёт_к_удалению_цели_потому_что_rmtree_не_должен_выходить_из_work_dir(
    tmp_path,
):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "precious").write_text("data")
    (tmp_path / TID).symlink_to(outside, target_is_directory=True)
    await _sweeper(tmp_path, Repo(default=TaskStatus.FAILED)).sweep()
    assert (outside / "precious").exists()
    shutil.rmtree(outside)


async def test_symlink_внутри_workspace_удаляется_без_удаления_цели_за_пределами_каталога(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_outside2")
    outside.mkdir()
    (outside / "precious").write_text("data")
    d = _ws(tmp_path, marker_at=_iso(timedelta(days=2)))
    (d / "link").symlink_to(outside, target_is_directory=True)
    await _sweeper(tmp_path, Repo({TID: TaskStatus.FAILED})).sweep()
    assert not d.exists() and (outside / "precious").exists()
    shutil.rmtree(outside)


async def test_обычный_файл_с_именем_задачи_не_останавливает_проход_по_остальным_каталогам(
    tmp_path,
):
    (tmp_path / ("0" * 32)).write_text("file")
    d = _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    await _sweeper(tmp_path, Repo(default=TaskStatus.FAILED)).sweep()
    assert not d.exists()


async def test_work_dir_сам_симлинк_на_реальный_каталог_не_считается_небезопасным_и_чистится(
    tmp_path,
):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    d = _ws(real, marker_at=_iso(timedelta(days=2)))
    sw = WorkDirSweeper(Repo({TID: TaskStatus.FAILED}), link, RETENTION, clock=lambda: NOW)
    await sw.sweep()
    assert not d.exists()


# ---------- отказы ----------


async def test_ошибка_БД_на_одной_задаче_не_мешает_чистке_соседней(tmp_path):
    a = _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    b = _ws(tmp_path, TID2, marker_at=_iso(timedelta(days=2)))
    repo = Repo(default=TaskStatus.FAILED)
    repo.fail_for = {TID}
    await _sweeper(tmp_path, repo).sweep()
    assert a.exists() and not b.exists()


async def test_ошибка_БД_не_приводит_к_удалению_потому_что_неизвестный_статус_не_значит_FAILED(
    tmp_path,
):
    a = _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    repo = Repo(default=TaskStatus.FAILED)
    repo.fail_for = {TID}
    await _sweeper(tmp_path, repo).sweep()
    assert a.exists()


async def test_rmtree_с_PermissionError_не_роняет_проход_и_идёт_дальше(tmp_path, monkeypatch):
    a = _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    b = _ws(tmp_path, TID2, marker_at=_iso(timedelta(days=2)))
    real = shutil.rmtree

    def flaky(p, *a_, **k):
        if Path(p).name == TID:
            raise PermissionError("ro")
        return real(p, *a_, **k)

    monkeypatch.setattr(shutil, "rmtree", flaky)
    res = await _sweeper(tmp_path, Repo(default=TaskStatus.FAILED)).sweep()
    assert a.exists() and not b.exists() and res.deleted == 1


async def test_отсутствующий_WORK_DIR_даёт_пустой_результат_без_исключения(tmp_path):
    res = await _sweeper(tmp_path / "нет", Repo(default=TaskStatus.FAILED)).sweep()
    assert res.scanned == 0 and res.deleted == 0


async def test_WORK_DIR_являющийся_файлом_даёт_пустой_результат_без_исключения(tmp_path):
    f = tmp_path / "file"
    f.write_text("x")
    res = await _sweeper(f, Repo(default=TaskStatus.FAILED)).sweep()
    assert res.deleted == 0


async def test_пустой_WORK_DIR_ничего_не_делает(tmp_path):
    res = await _sweeper(tmp_path, Repo(default=TaskStatus.FAILED)).sweep()
    assert (res.scanned, res.deleted, res.skipped) == (0, 0, 0)


async def test_нулевой_срок_хранения_удаляет_только_FAILED_а_не_всё(tmp_path):
    a = _ws(tmp_path, TID, marker_at=_iso(timedelta(0)))
    b = _ws(tmp_path, TID2, marker_at=_iso(timedelta(0)))
    await _sweeper(
        tmp_path, Repo({TID: TaskStatus.FAILED, TID2: TaskStatus.DONE}), retention=timedelta(0)
    ).sweep()
    assert not a.exists() and b.exists()


# ---------- конкуренция ----------


async def test_параллельный_второй_проход_того_же_sweeper_ничего_не_делает_пока_идёт_первый(
    tmp_path, monkeypatch
):
    _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    gate = asyncio.Event()
    started = asyncio.Event()
    repo = Repo(default=TaskStatus.FAILED)
    orig = repo.get

    async def slow_get(tid):
        started.set()
        await gate.wait()
        return await orig(tid)

    repo.get = slow_get
    sw = _sweeper(tmp_path, repo)
    first = asyncio.create_task(sw.sweep())
    await started.wait()
    second = await sw.sweep()
    gate.set()
    r1 = await first
    assert second.scanned == 0 and r1.deleted == 1


async def test_два_sweeper_на_одном_каталоге_как_два_процесса_не_падают_и_workspace_удалён(
    tmp_path,
):
    d = _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    repo = Repo(default=TaskStatus.FAILED)
    r = await asyncio.gather(_sweeper(tmp_path, repo).sweep(), _sweeper(tmp_path, repo).sweep())
    assert not d.exists() and sum(x.deleted for x in r) >= 1


async def test_отмена_прохода_во_время_ожидания_БД_пробрасывает_CancelledError_а_не_глотает_её(
    tmp_path,
):
    _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    repo = Repo(default=TaskStatus.FAILED)

    async def hang(tid):
        await asyncio.sleep(3600)

    repo.get = hang
    t = asyncio.create_task(_sweeper(tmp_path, repo).sweep())
    await asyncio.sleep(0.01)
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t


async def test_после_отмены_прохода_lock_освобождён_и_следующий_проход_работает(tmp_path):
    d = _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    repo = Repo(default=TaskStatus.FAILED)
    orig = repo.get

    async def hang(tid):
        await asyncio.sleep(3600)

    repo.get = hang
    sw = _sweeper(tmp_path, repo)
    t = asyncio.create_task(sw.sweep())
    await asyncio.sleep(0.01)
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    repo.get = orig
    await sw.sweep()
    assert not d.exists()


# ---------- _sweep_forever ----------


async def test_sweep_forever_переживает_исключение_прохода_и_делает_следующий():
    calls = []

    class S:
        async def sweep(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")

    t = asyncio.create_task(_sweep_forever(S(), 0.01))
    await asyncio.sleep(0.1)
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    assert len(calls) >= 2


async def test_sweep_forever_отменяется_во_сне_без_зависания():
    class S:
        async def sweep(self):
            return None

    t = asyncio.create_task(_sweep_forever(S(), 3600))
    await asyncio.sleep(0.01)
    t.cancel()
    res = await asyncio.wait_for(asyncio.gather(t, return_exceptions=True), 1)
    assert isinstance(res[0], asyncio.CancelledError)


# ---------- конфиг ----------


@pytest.mark.parametrize(
    "env",
    [
        {"WORK_DIR_SWEEP_INTERVAL_MINUTES": "0"},
        {"WORK_DIR_SWEEP_INTERVAL_MINUTES": "-5"},
        {"WORK_DIR_FAILED_RETENTION_HOURS": "-1"},
        {"WORK_DIR_FAILED_RETENTION_HOURS": "nan"},
    ],
)
def test_конфиг_отвергает_нулевой_отрицательный_интервал_и_отрицательный_срок_потому_что_иначе_busy_loop_или_мгновенное_удаление(
    monkeypatch, env
):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(Exception):  # noqa: B017
        WorkerConfig()


def test_конфиг_по_умолчанию_включён_24_часа_60_минут(monkeypatch):
    for k in (
        "WORK_DIR_CLEANUP_ENABLED",
        "WORK_DIR_FAILED_RETENTION_HOURS",
        "WORK_DIR_SWEEP_INTERVAL_MINUTES",
    ):
        monkeypatch.delenv(k, raising=False)
    c = WorkerConfig()
    assert (c.cleanup_enabled, c.failed_retention_hours, c.sweep_interval_minutes) == (True, 24, 60)


# ---------- marker и воркер ----------


class FailingService:
    async def run(self, task, source, slide_provider, work_dir, **kw):
        raise RuntimeError("секретный токен sk-123 в тексте ошибки")


class OkLocalService:
    async def run(self, task, source, slide_provider, work_dir, **kw):
        return str(work_dir / "export" / "result.zip")


class OkS3Service:
    async def run(self, task, source, slide_provider, work_dir, **kw):
        return f"results/{task.task_id}/"


class _T:
    def __init__(self, tid):
        self.task_id = tid


def _job(work_dir, tid=TID):
    return PipelineJob(
        task_id=tid,
        task=_T(tid),
        source=AudioSource(path=Path("/a.mp3")),
        slide_provider=None,
        work_dir=work_dir,
    )


async def _run(worker, *jobs):
    await worker.start()
    for j in jobs:
        await worker.enqueue(j)
    await worker.stop()


async def test_упавшая_задача_получает_marker_с_utc_временем_и_без_текста_ошибки(tmp_path):
    d = tmp_path / TID
    d.mkdir()
    await _run(PipelineWorker(FailingService(), 1, clock=lambda: NOW), _job(d))
    raw = (d / TERMINAL_MARKER).read_text()
    data = json.loads(raw)
    assert data["status"] == "failed" and datetime.fromisoformat(data["at"]) == NOW
    assert "sk-123" not in raw
    assert not (d / (TERMINAL_MARKER + ".tmp")).exists()


async def test_успешная_задача_не_получает_marker_потому_что_он_маркирует_только_падение(tmp_path):
    d = tmp_path / TID
    d.mkdir()
    await _run(PipelineWorker(OkLocalService(), 1, clock=lambda: NOW), _job(d))
    assert not (d / TERMINAL_MARKER).exists()


async def test_падение_с_исчезнувшим_workspace_не_создаёт_каталог_заново_и_не_роняет_воркер(
    tmp_path,
):
    d = tmp_path / TID
    await _run(PipelineWorker(FailingService(), 1, clock=lambda: NOW), _job(d))
    assert not d.exists()


async def test_падение_в_каталоге_с_нештатным_именем_не_пишет_marker(tmp_path):
    d = tmp_path / "custom"
    d.mkdir()
    await _run(PipelineWorker(FailingService(), 1, clock=lambda: NOW), _job(d))
    assert not (d / TERMINAL_MARKER).exists()


async def test_не_записанный_marker_не_убивает_consumer_и_следующая_задача_обрабатывается(tmp_path):
    bad = tmp_path / TID
    bad.mkdir()
    (bad / (TERMINAL_MARKER + ".tmp")).mkdir()  # write_text упадёт IsADirectoryError
    good = tmp_path / TID2
    good.mkdir()
    await _run(PipelineWorker(FailingService(), 1, clock=lambda: NOW), _job(bad), _job(good, TID2))
    assert (good / TERMINAL_MARKER).exists()


async def test_marker_после_ошибки_cleanup_DONE_задачи_не_делает_её_workspace_удаляемой(tmp_path):
    # DONE-задача: даже если marker оказался в каталоге, sweeper смотрит в БД.
    d = tmp_path / TID
    d.mkdir()
    write_terminal_marker(d, TaskStatus.FAILED, lambda: NOW - timedelta(days=9))
    await _sweeper(tmp_path, Repo({TID: TaskStatus.DONE})).sweep()
    assert d.exists()


def test_write_terminal_marker_в_отсутствующий_каталог_не_бросает(tmp_path):
    write_terminal_marker(tmp_path / "нет", TaskStatus.FAILED, lambda: NOW)


def test_write_terminal_marker_с_наивными_часами_не_сдвигает_время_относительно_utc(tmp_path):
    d = tmp_path / TID
    d.mkdir()
    write_terminal_marker(d, TaskStatus.FAILED, lambda: NOW.replace(tzinfo=None))
    at = datetime.fromisoformat(json.loads((d / TERMINAL_MARKER).read_text())["at"])
    assert at.tzinfo is not None


# ---------- стык со слоем чтения workspace (API) ----------


def _client(tmp_path, repo):
    app = create_app()
    app.dependency_overrides[deps.get_repository] = lambda: repo
    app.dependency_overrides[deps.get_work_dir] = lambda: tmp_path
    app.dependency_overrides[deps.get_storage] = lambda: None
    return TestClient(app)


async def test_транскрипт_FAILED_задачи_после_чистки_не_маскируется_под_идущую_обработку_202_in_progress(
    tmp_path,
):
    # Задача упала после транскрибации (STRUCTURIZE), SRT был доступен; после TTL-чистки
    # роут отвечает 202 "in_progress, retry later" вечно: клиент поллит мёртвую задачу.
    d = _ws(tmp_path, TID, marker_at=_iso(timedelta(days=2)))
    (d / "transcribe").mkdir()
    (d / "transcribe" / "transcript.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nпривет\n")
    repo = Repo({TID: TaskStatus.FAILED}, stage=PipelineStage.STRUCTURIZE)
    client = _client(tmp_path, repo)
    assert client.get(f"/api/v1/tasks/{TID}/transcript").status_code == 200  # до чистки
    await _sweeper(tmp_path, repo).sweep()
    assert not d.exists()
    resp = client.get(f"/api/v1/tasks/{TID}/transcript")
    assert not (resp.status_code == 202 and resp.json().get("status") == "in_progress")
