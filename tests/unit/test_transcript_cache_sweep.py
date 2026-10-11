"""Чистка кеша транскриптов sweeper-ом: по mtime записи, с поддельными часами."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from lecturelog.application.worker import WorkDirSweeper
from lecturelog.config.settings import WorkerConfig

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
RETENTION = timedelta(days=30)
KEY_OLD = "a" * 64
KEY_FRESH = "b" * 64


class _NoTasks:
    async def get(self, task_id):
        return None


def _entry(cache_dir: Path, key: str, age: timedelta) -> Path:
    entry = cache_dir / key
    entry.mkdir(parents=True)
    (entry / "transcript.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nтекст\n")
    ts = (NOW - age).timestamp()
    os.utime(entry, (ts, ts))
    return entry


def _sweeper(work_root: Path, cache_dir: Path | None, retention: timedelta | None = RETENTION):
    return WorkDirSweeper(
        _NoTasks(),
        work_root,
        timedelta(hours=24),
        clock=lambda: NOW,
        transcript_cache_dir=cache_dir,
        cache_retention=retention,
    )


@pytest.mark.asyncio
async def test_запись_старше_срока_удаляется_а_свежая_остаётся(tmp_path):
    cache = tmp_path / "transcript_cache"
    old = _entry(cache, KEY_OLD, RETENTION + timedelta(seconds=1))
    fresh = _entry(cache, KEY_FRESH, RETENTION - timedelta(seconds=1))

    result = await _sweeper(tmp_path, cache).sweep()

    assert not old.exists()
    assert fresh.exists()
    assert result.cache_deleted == 1


@pytest.mark.asyncio
async def test_запись_ровно_на_границе_срока_удаляется(tmp_path):
    cache = tmp_path / "transcript_cache"
    entry = _entry(cache, KEY_OLD, RETENTION)

    await _sweeper(tmp_path, cache).sweep()

    assert not entry.exists()


@pytest.mark.asyncio
async def test_без_срока_кеш_не_чистится(tmp_path):
    cache = tmp_path / "transcript_cache"
    entry = _entry(cache, KEY_OLD, timedelta(days=3650))

    await _sweeper(tmp_path, cache, retention=None).sweep()

    assert entry.exists()


@pytest.mark.asyncio
async def test_посторонние_объекты_в_каталоге_кеша_не_трогаются(tmp_path):
    cache = tmp_path / "transcript_cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    cache.mkdir()
    link = cache / KEY_OLD
    link.symlink_to(outside, target_is_directory=True)
    stray_file = cache / (KEY_FRESH)
    stray_file.write_text("x")
    not_hash = cache / "not-a-hash"
    not_hash.mkdir()
    for path in (stray_file, not_hash):
        os.utime(path, (0, 0))

    await _sweeper(tmp_path, cache).sweep()

    assert (outside / "keep.txt").exists()
    assert link.is_symlink()
    assert stray_file.exists()
    assert not_hash.exists()


@pytest.mark.asyncio
async def test_кеш_вне_work_dir_тоже_чистится_а_отсутствующий_каталог_не_ошибка(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    cache = tmp_path / "elsewhere" / "cache"
    await _sweeper(work, cache).sweep()  # каталога нет - проход не падает

    entry = _entry(cache, KEY_OLD, RETENTION + timedelta(days=1))
    await _sweeper(work, cache).sweep()

    assert not entry.exists()


def test_срок_кеша_по_умолчанию_30_дней(monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_CACHE_RETENTION_DAYS", raising=False)
    assert WorkerConfig().transcript_cache_retention_days == 30


@pytest.mark.parametrize(
    "env",
    [
        {"TRANSCRIPT_CACHE_RETENTION_DAYS": "0"},
        {"TRANSCRIPT_CACHE_RETENTION_DAYS": "-1"},
        {"TRANSCRIPT_CACHE_RETENTION_DAYS": "366"},
        # Кеш не должен жить меньше workspace упавшей задачи (48 ч > 1 дня).
        {"TRANSCRIPT_CACHE_RETENTION_DAYS": "1", "WORK_DIR_FAILED_RETENTION_HOURS": "48"},
    ],
)
def test_неверный_срок_кеша_отклоняется(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        WorkerConfig()


def test_срок_кеша_равный_сроку_workspace_допустим(monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_CACHE_RETENTION_DAYS", "2")
    monkeypatch.setenv("WORK_DIR_FAILED_RETENTION_HOURS", "48")
    assert WorkerConfig().transcript_cache_retention_days == 2
