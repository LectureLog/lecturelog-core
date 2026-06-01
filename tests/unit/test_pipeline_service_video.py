from pathlib import Path

import pytest

from lecturelog.application.pipeline_service import PipelineService
from lecturelog.application.progress_plan import ProgressPlan
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.media_source import VideoFileSource, VideoUrlSource
from lecturelog.domain.models import Section, Task, Topic


class InMemoryRepo:
    def __init__(self):
        self.tasks = {}
        self.stages = []

    async def create(self, t):
        self.tasks[t.task_id] = t

    async def get(self, tid):
        return self.tasks.get(tid)

    async def update(self, t):
        self.tasks[t.task_id] = t
        self.stages.append((t.stage, t.progress_pct))

    async def mark_stale_as_interrupted(self):
        return 0


class FakeIngestor:
    def __init__(self):
        self.ingested = None
        self.extracted_from = None

    async def ingest(self, source, output_dir):
        self.ingested = source
        return Path("/work/video.mp4")

    async def extract_audio(self, video_path, output_dir):
        self.extracted_from = video_path
        return Path("/work/extracted/audio.mp3")


class FakeTranscriber:
    def __init__(self):
        self.audio_arg = None

    async def transcribe(self, audio_path, output_dir, on_progress=None):
        self.audio_arg = audio_path
        if on_progress:
            r = on_progress(100)
            if r is not None:
                await r
        return Path("/work/t.srt")


class FakeStructurizer:
    def __init__(self, topics):
        self._t = topics

    async def structurize(self, srt_path, slide_images, output_dir, on_progress=None):
        return self._t


class RecordingCutter:
    def __init__(self, tag):
        self.tag = tag
        self.source_arg = None

    async def cut(self, source_path, sections, output_dir):
        self.source_arg = source_path
        return [Path(f"{self.tag}_{i}") for i in range(len(sections))]


class FakeExporter:
    def __init__(self, zip_path):
        self._zip = zip_path
        self.media_kind = None

    async def export(self, topics, media_fragments, slide_images, output_dir, media_kind):
        self.media_kind = media_kind
        return self._zip


def _service(repo, ingestor, transcriber, structurizer, audio_cutter, video_cutter, exporter):
    return PipelineService(
        repository=repo, transcriber=transcriber, structurizer=structurizer,
        audio_cutter=audio_cutter, video_cutter=video_cutter, ingestor=ingestor,
        exporter=exporter, progress_plan_factory=ProgressPlan.for_audio,
    )


@pytest.mark.asyncio
async def test_video_pipeline_ingests_extracts_and_completes(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="v1", source_kind="video_url")
    await repo.create(task)
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    topics = [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]
    zip_path = tmp_path / "r.zip"
    zip_path.write_bytes(b"z")

    ingestor = FakeIngestor()
    transcriber = FakeTranscriber()
    audio_cutter = RecordingCutter("audio")
    video_cutter = RecordingCutter("video")
    exporter = FakeExporter(zip_path)
    service = _service(repo, ingestor, transcriber, FakeStructurizer(topics),
                       audio_cutter, video_cutter, exporter)

    await service.run(task=task, source=VideoUrlSource(url="https://youtu.be/x"),
                      slide_provider=None, work_dir=tmp_path)

    final = await repo.get("v1")
    assert final.status == TaskStatus.DONE
    assert final.progress_pct == 100
    assert transcriber.audio_arg == Path("/work/extracted/audio.mp3")
    assert ingestor.extracted_from == Path("/work/video.mp4")
    assert video_cutter.source_arg == Path("/work/video.mp4")
    assert audio_cutter.source_arg is None
    assert exporter.media_kind == "video"


@pytest.mark.asyncio
async def test_video_stages_include_ingest_and_extract(tmp_path):
    repo = InMemoryRepo()
    task = Task(task_id="v2", source_kind="video_file")
    await repo.create(task)
    sec = Section(title="s", start="0:00", end="5:00", content="c", slide_indices=[])
    topics = [Topic(title="T", start="0:00", end="5:00", sections=[sec], slide_indices=[])]
    zip_path = tmp_path / "r.zip"
    zip_path.write_bytes(b"z")
    service = _service(repo, FakeIngestor(), FakeTranscriber(), FakeStructurizer(topics),
                       RecordingCutter("audio"), RecordingCutter("video"), FakeExporter(zip_path))
    await service.run(task=task, source=VideoFileSource(path=tmp_path / "v.mp4"),
                      slide_provider=None, work_dir=tmp_path)
    seen = [stage for stage, _ in repo.stages]
    assert PipelineStage.VIDEO_INGEST in seen
    assert PipelineStage.AUDIO_EXTRACT in seen
    assert PipelineStage.VIDEO_CUT in seen
    progress = [p for _, p in repo.stages]
    assert progress == sorted(progress)
    assert progress[-1] == 100
