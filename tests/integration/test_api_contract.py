import pytest
from fastapi.testclient import TestClient

from lecturelog.api import dependencies as deps
from lecturelog.api.app import create_app
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.models import Task


class InMemoryRepo:
    def __init__(self):
        self.tasks = {}

    async def create(self, t):
        self.tasks[t.task_id] = t

    async def get(self, tid):
        return self.tasks.get(tid)

    async def update(self, t):
        self.tasks[t.task_id] = t

    async def mark_stale_as_interrupted(self):
        return 0


class NoopWorker:
    def __init__(self):
        self.jobs = []

    async def enqueue(self, job):
        self.jobs.append(job)


@pytest.fixture
def repo():
    return InMemoryRepo()


@pytest.fixture
def client(repo, tmp_path):
    # Собираем приложение без реального lifespan: вешаем зависимости
    # через dependency_overrides, чтобы тест проверял HTTP-контракт,
    # а не реальную обработку (Groq/Gemini/Postgres).
    app = create_app()
    worker = NoopWorker()
    app.dependency_overrides[deps.get_repository] = lambda: repo
    app.dependency_overrides[deps.get_worker] = lambda: worker
    app.dependency_overrides[deps.get_upload_dir] = lambda: tmp_path
    app.state.repository = repo
    app.state.worker = worker
    app.state.upload_dir = tmp_path
    app.state.gemini = object()
    app.state.video_slides_models = ["m"]
    app.state.concurrency_video = 1
    app.state.prompts_dir = tmp_path
    return TestClient(app)


def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_create_requires_exactly_one_source(client):
    r = client.post("/api/v1/tasks")  # ни одного источника
    assert r.status_code == 400


def test_create_audio_returns_task_id(client):
    r = client.post("/api/v1/tasks", files={"audio": ("a.mp3", b"data", "audio/mpeg")})
    assert r.status_code == 200
    assert "task_id" in r.json()


def test_status_404_for_unknown(client):
    r = client.get("/api/v1/tasks/nonexistent")
    assert r.status_code == 404
    assert r.json()["detail"] == "Task not found"


def test_status_returns_fields(client, repo):
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.PROCESSING,
        stage=PipelineStage.STRUCTURIZE,
        progress_pct=55,
    )
    r = client.get("/api/v1/tasks/t")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == "t"
    assert body["stage"] == "structurize"
    assert body["progress_pct"] == 55


def test_transcript_invalid_format_400(client):
    r = client.get("/api/v1/tasks/whatever/transcript?format=pdf")
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_format", "allowed": ["srt", "txt"]}


def test_transcript_task_not_found_404(client):
    r = client.get("/api/v1/tasks/missing/transcript")
    assert r.status_code == 404
    assert r.json() == {"error": "task_not_found"}


def test_transcript_failed_on_transcribe_409(client, repo):
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.FAILED,
        stage=PipelineStage.TRANSCRIBE,
        error="groq down",
    )
    r = client.get("/api/v1/tasks/t/transcript")
    assert r.status_code == 409
    assert r.json()["error"] == "transcribe_failed"


def test_transcript_in_progress_202(client, repo):
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.PROCESSING,
        stage=PipelineStage.TRANSCRIBE,
        progress_pct=10,
    )
    r = client.get("/api/v1/tasks/t/transcript")
    assert r.status_code == 202
    assert r.json()["status"] == "in_progress"


def test_transcript_srt_ready(client, repo, tmp_path):
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.PROCESSING,
        stage=PipelineStage.STRUCTURIZE,
    )
    srt_dir = tmp_path / "t" / "transcribe"
    srt_dir.mkdir(parents=True)
    (srt_dir / "transcript.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
    )
    r = client.get("/api/v1/tasks/t/transcript?format=srt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-subrip")


def test_result_not_ready_404(client, repo):
    repo.tasks["t"] = Task(task_id="t", source_kind="audio")
    r = client.get("/api/v1/tasks/t/result")
    assert r.status_code == 404
    assert r.json()["detail"] == "Result is not ready"


def test_result_returns_zip(client, repo, tmp_path):
    zip_path = tmp_path / "r.zip"
    zip_path.write_bytes(b"PK\x03\x04zip")
    repo.tasks["t"] = Task(
        task_id="t", source_kind="audio", status=TaskStatus.DONE, result_path=str(zip_path)
    )
    r = client.get("/api/v1/tasks/t/result")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
