import pytest
from fastapi.testclient import TestClient

from lecturelog.api import dependencies as deps
from lecturelog.api.app import create_app
from lecturelog.application.usage_accumulator import UsageAccumulator
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.models import Task
from tests.support.fake_storage import FakeStorage


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


def _build_client(repo, tmp_path, storage):
    # Собираем приложение без реального lifespan: вешаем зависимости
    # через dependency_overrides, чтобы тест проверял HTTP-контракт,
    # а не реальную обработку (Groq/Gemini/Postgres).
    app = create_app()
    worker = NoopWorker()
    app.dependency_overrides[deps.get_repository] = lambda: repo
    app.dependency_overrides[deps.get_worker] = lambda: worker
    app.dependency_overrides[deps.get_work_dir] = lambda: tmp_path
    app.dependency_overrides[deps.get_storage] = lambda: storage
    app.state.repository = repo
    app.state.worker = worker
    app.state.work_dir = tmp_path
    app.state.storage = storage
    app.state.gemini = object()
    app.state.video_slides_models = ["m"]
    app.state.concurrency_video = 1
    app.state.prompts_dir = tmp_path
    client = TestClient(app)
    client._worker = worker
    client._storage = storage
    return client


@pytest.fixture
def client(repo, tmp_path):
    # Дефолт автономии: public=False (presigned наружу выключен).
    return _build_client(repo, tmp_path, FakeStorage(public=False))


@pytest.fixture
def client_public(repo, tmp_path):
    # Платформенный режим: public=True (presigned PUT/GET доступны).
    return _build_client(repo, tmp_path, FakeStorage(public=True))


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


def test_create_with_s3_key_creates_s3_object_source(client):
    r = client.post(
        "/api/v1/tasks",
        data={"s3_key": "uploads/abc/lecture.mp3", "media": "audio"},
    )
    assert r.status_code == 200
    job = client._worker.jobs[-1]
    assert job.source.kind == "s3_object"
    assert job.source.key == "uploads/abc/lecture.mp3"
    assert job.source.media == "audio"


def test_create_with_s3_key_persists_source_key(client, repo):
    r = client.post(
        "/api/v1/tasks",
        data={"s3_key": "uploads/abc/lecture.mp3", "media": "audio"},
    )
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    assert repo.tasks[task_id].source_key == "uploads/abc/lecture.mp3"


def test_create_audio_has_no_source_key(client, repo):
    r = client.post("/api/v1/tasks", files={"audio": ("a.mp3", b"d", "audio/mpeg")})
    task_id = r.json()["task_id"]
    assert repo.tasks[task_id].source_key is None


def test_create_with_s3_key_video(client):
    r = client.post(
        "/api/v1/tasks",
        data={"s3_key": "uploads/abc/lec.mp4", "media": "video"},
    )
    assert r.status_code == 200
    job = client._worker.jobs[-1]
    assert job.source.kind == "s3_object"
    assert job.source.media == "video"


def test_s3_key_and_file_together_is_400(client):
    r = client.post(
        "/api/v1/tasks",
        data={"s3_key": "uploads/abc/lecture.mp3", "media": "audio"},
        files={"audio": ("a.mp3", b"d", "audio/mpeg")},
    )
    assert r.status_code == 400


def test_s3_key_invalid_media_is_400(client):
    r = client.post(
        "/api/v1/tasks",
        data={"s3_key": "uploads/abc/lecture.mp3", "media": "doc"},
    )
    assert r.status_code == 400


def test_s3_key_outside_uploads_is_400(client):
    # IDOR: чужой результат вне uploads/ нельзя протащить в источник.
    r = client.post(
        "/api/v1/tasks",
        data={"s3_key": "results/other/result.zip", "media": "audio"},
    )
    assert r.status_code == 400
    assert "uploads/" in r.json()["detail"]
    assert client._worker.jobs == []


def test_s3_key_with_traversal_is_400(client):
    # Path traversal: сегмент .. позволяет выйти за пределы uploads/.
    r = client.post(
        "/api/v1/tasks",
        data={"s3_key": "uploads/../results/x", "media": "audio"},
    )
    assert r.status_code == 400
    assert "uploads/" in r.json()["detail"]
    assert client._worker.jobs == []


def test_uploads_returns_presigned_put(client_public):
    r = client_public.post("/api/v1/uploads", json={"filename": "lecture.mp3"})
    assert r.status_code == 200
    body = r.json()
    assert body["key"].startswith("uploads/")
    assert body["key"].endswith("/lecture.mp3")
    assert body["url"].startswith("https://fake/")
    assert body["key"] in body["url"]
    assert "expires_in" in body


def test_uploads_409_without_public(client):
    r = client.post("/api/v1/uploads", json={"filename": "lecture.mp3"})
    assert r.status_code == 409


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
        usage={"transcribe": {"audio_seconds": 90, "provider": "groq", "raw": {}}},
    )
    r = client.get("/api/v1/tasks/t")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == "t"
    assert body["stage"] == "structurize"
    assert body["progress_pct"] == 55
    assert body["usage"] == {"transcribe": {"audio_seconds": 90, "provider": "groq", "raw": {}}}


def test_status_usage_wire_identical_to_accumulator(client, repo):
    # Реальный выход аккумулятора: transcribe пишет "model": None ВСЕГДА,
    # structurize по by_model, total с осями режима. GET /tasks/{id} обязан
    # отдавать usage БАЙТ-В-БАЙТ как он лежит в task.usage (как делал старый роут,
    # отдававший task.usage напрямую). В частности transcribe.model:null НЕ должен
    # пропадать из-за response_model_exclude_none.
    acc = UsageAccumulator()
    acc.set_mode("audio", "document")
    # provider/model без явного model -> payload.get("model") == None.
    acc.record_transcribe({"audio_seconds": 120, "provider": "groq"})
    acc.record_llm("structurize", {"model": "gemini-3", "prompt": 100, "output": 40})
    acc.compute_total()
    expected_usage = acc.usage
    # Инвариант реального выхода: ключ model присутствует и равен None.
    assert expected_usage["transcribe"]["model"] is None

    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.PROCESSING,
        stage=PipelineStage.STRUCTURIZE,
        usage=expected_usage,
    )
    r = client.get("/api/v1/tasks/t")
    assert r.status_code == 200
    # Тело usage идентично исходному dict аккумулятора, включая "model": null.
    assert r.json()["usage"] == expected_usage


def test_status_empty_usage_is_empty_object(client, repo):
    # Пустой usage ({}) должен сериализоваться как пустой объект (как раньше),
    # а не как Usage() со всеми None/дефолтными ключами.
    repo.tasks["t"] = Task(task_id="t", source_kind="audio", usage={})
    r = client.get("/api/v1/tasks/t")
    assert r.status_code == 200
    assert r.json()["usage"] == {}


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


def test_result_streams_zip_from_s3(client, repo):
    # result_path — S3-ключ; эндпоинт скачивает объект из storage и стримит ZIP.
    client._storage.objects["results/t/result.zip"] = b"PK\x03\x04zip"
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.DONE,
        result_path="results/t/result.zip",
    )
    r = client.get("/api/v1/tasks/t/result")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.content == b"PK\x03\x04zip"


def test_result_cleans_up_tmp_file(client, repo, tmp_path):
    # Disk leak: скачанный во work_dir ZIP должен удаляться после отдачи,
    # а не накапливаться на каждый запрос/ретрай.
    client._storage.objects["results/t/result.zip"] = b"PK\x03\x04zip"
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.DONE,
        result_path="results/t/result.zip",
    )
    results_tmp = tmp_path / "results_tmp"
    for _ in range(3):
        r = client.get("/api/v1/tasks/t/result")
        assert r.status_code == 200
        assert r.content == b"PK\x03\x04zip"
    # После всех запросов tmp-каталог не должен накапливать файлы.
    leftover = list(results_tmp.rglob("*.zip")) if results_tmp.exists() else []
    assert leftover == []


def test_result_url_with_public_returns_presigned(client_public, repo):
    client_public._storage.objects["results/t/result.zip"] = b"zip"
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.DONE,
        result_path="results/t/result.zip",
    )
    r = client_public.get("/api/v1/tasks/t/result-url?filename=Лекция")
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("https://fake/")
    assert "results/t/result.zip" in body["url"]
    assert "Лекция.zip" in body["url"]
    assert "expires_in" in body


def test_result_url_without_public_409(client, repo):
    repo.tasks["t"] = Task(
        task_id="t",
        source_kind="audio",
        status=TaskStatus.DONE,
        result_path="results/t/result.zip",
    )
    r = client.get("/api/v1/tasks/t/result-url?filename=Лекция")
    assert r.status_code == 409


def test_result_url_not_ready_404(client_public, repo):
    repo.tasks["t"] = Task(task_id="t", source_kind="audio")
    r = client_public.get("/api/v1/tasks/t/result-url?filename=X")
    assert r.status_code == 404
