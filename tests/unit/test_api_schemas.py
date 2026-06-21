from lecturelog.api.schemas import CreateTaskResponse, TaskStatusResponse
from lecturelog.domain.enums import PipelineStage, TaskStatus
from lecturelog.domain.models import Task


def test_status_response_from_domain_task():
    task = Task(
        task_id="abc",
        source_kind="audio",
        status=TaskStatus.PROCESSING,
        stage=PipelineStage.STRUCTURIZE,
        progress_pct=55,
        error=None,
        result_path=None,
    )
    dto = TaskStatusResponse.from_task(task)
    assert dto.task_id == "abc"
    assert dto.stage == "structurize"
    assert dto.progress_pct == 55
    assert dto.error is None
    assert dto.usage == {}


def test_status_response_exposes_usage():
    task = Task(
        task_id="u",
        source_kind="audio",
        usage={"transcribe": {"audio_seconds": 120, "provider": "groq", "raw": {}}},
    )
    dto = TaskStatusResponse.from_task(task)
    assert dto.usage == {"transcribe": {"audio_seconds": 120, "provider": "groq", "raw": {}}}


def test_create_response_holds_task_id():
    assert CreateTaskResponse(task_id="xyz").task_id == "xyz"
