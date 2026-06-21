import pytest

from lecturelog.application.pipeline_service import PipelineService
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.enums import TaskStatus
from lecturelog.domain.media_source import AudioSource
from lecturelog.domain.models import Section, Task, Topic
from tests.unit.test_pipeline_service import (
    FailingTranscriber,
    FakeCutter,
    FakeExporter,
    FakeStructurizer,
    FakeTranscriber,
    InMemoryRepo,
)


class RecordingNotifier:
    """Записывает все вызовы notify как (task_id, status, error)."""

    def __init__(self):
        self.calls = []

    async def notify(self, task_id, status, error=None):
        self.calls.append((task_id, status, error))


class BoomNotifier:
    """Бросает при любой попытке отправки — проверяем, что пайплайн не падает."""

    async def notify(self, task_id, status, error=None):
        raise RuntimeError("notifier boom")


class TimeoutNotifier:
    """Имитирует таймаут нотификатора — пайплайн не должен ронять/задерживать."""

    async def notify(self, task_id, status, error=None):
        raise TimeoutError("notifier timeout")


def _service(repo, transcriber, structurizer, cutter, exporter, notifier):
    return PipelineService(
        repository=repo,
        transcriber=transcriber,
        structurizer=structurizer,
        audio_cutter=cutter,
        exporter=exporter,
        progress_plan_factory=ProgressPlan.for_audio,
        webhook_notifier=notifier,
    )


def _topics():
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    return [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]


async def _run_ok(repo, tmp_path, task, notifier):
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(_topics()),
        FakeCutter(),
        FakeExporter(zip_path),
        notifier,
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )


@pytest.mark.asyncio
async def test_webhook_fires_once_on_done(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="w1", source_kind="audio")
    await repo.create(task)
    notifier = RecordingNotifier()
    await _run_ok(repo, tmp_path, task, notifier)

    assert len(notifier.calls) == 1
    tid, status, error = notifier.calls[0]
    assert tid == "w1"
    assert status == TaskStatus.DONE
    assert error is None


@pytest.mark.asyncio
async def test_webhook_fires_on_failed_with_error(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="w2", source_kind="audio")
    await repo.create(task)
    notifier = RecordingNotifier()
    service = _service(
        repo,
        FailingTranscriber(),
        FakeStructurizer([]),
        FakeCutter(),
        FakeExporter(tmp_path / "z.zip"),
        notifier,
    )
    with pytest.raises(RuntimeError):
        await service.run(
            task=task,
            source=AudioSource(path=tmp_path / "a.mp3"),
            slide_provider=None,
            work_dir=tmp_path,
        )
    assert len(notifier.calls) == 1
    tid, status, error = notifier.calls[0]
    assert tid == "w2"
    assert status == TaskStatus.FAILED
    assert error is not None and "groq down" in error


@pytest.mark.asyncio
async def test_webhook_not_fired_on_intermediate_statuses(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="w3", source_kind="audio")
    await repo.create(task)
    notifier = RecordingNotifier()
    await _run_ok(repo, tmp_path, task, notifier)

    # Среди вызовов нет промежуточных (PROCESSING и т.п.) — только терминальный DONE.
    statuses = {c[1] for c in notifier.calls}
    assert statuses <= {TaskStatus.DONE}
    assert TaskStatus.PROCESSING not in statuses


@pytest.mark.asyncio
async def test_no_notifier_means_no_webhook_and_normal_completion(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="w4", source_kind="audio")
    await repo.create(task)
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")
    # webhook_notifier=None (автономный режим) — задача должна завершиться DONE без ошибок.
    service = PipelineService(
        repository=repo,
        transcriber=FakeTranscriber(tmp_path / "t.srt"),
        structurizer=FakeStructurizer(_topics()),
        audio_cutter=FakeCutter(),
        exporter=FakeExporter(zip_path),
        progress_plan_factory=ProgressPlan.for_audio,
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )
    final = await repo.get("w4")
    assert final.status == TaskStatus.DONE


@pytest.mark.asyncio
async def test_failing_notifier_does_not_break_pipeline(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="w5", source_kind="audio")
    await repo.create(task)
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(_topics()),
        FakeCutter(),
        FakeExporter(zip_path),
        BoomNotifier(),
    )
    # Падающий нотификатор не должен ронять run.
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )
    final = await repo.get("w5")
    assert final.status == TaskStatus.DONE


@pytest.mark.asyncio
async def test_timeouting_notifier_does_not_delay_or_break(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="w6", source_kind="audio")
    await repo.create(task)
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(_topics()),
        FakeCutter(),
        FakeExporter(zip_path),
        TimeoutNotifier(),
    )
    # TimeoutError тоже глушится в _set — run завершается DONE.
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )
    final = await repo.get("w6")
    assert final.status == TaskStatus.DONE


@pytest.mark.asyncio
async def test_usage_still_persisted_with_notifier(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="w7", source_kind="audio")
    await repo.create(task)
    zip_path = tmp_path / "result.zip"
    zip_path.write_bytes(b"zip")
    service = _service(
        repo,
        FakeTranscriber(tmp_path / "t.srt"),
        FakeStructurizer(_topics()),
        FakeCutter(),
        FakeExporter(zip_path),
        RecordingNotifier(),
    )
    await service.run(
        task=task,
        source=AudioSource(path=tmp_path / "a.mp3"),
        slide_provider=None,
        work_dir=tmp_path,
    )
    final = await repo.get("w7")
    # Узел usage не сломан: расход по-прежнему персистится.
    assert final.usage["total"]["audio_seconds"] == 120
