from lecturelog.api.schemas import CreateTaskResponse, TaskStatusResponse
from lecturelog.domain.enums import ErrorCode, PipelineStage, TaskStatus
from lecturelog.domain.models import Task


def test_status_response_exposes_error_code():
    task = Task(
        task_id="e",
        source_kind="audio",
        status=TaskStatus.FAILED,
        error="boom",
        error_code=ErrorCode.BAD_INPUT,
    )
    dto = TaskStatusResponse.from_task(task)
    assert dto.error_code == "bad_input"


def test_status_response_error_code_none():
    dto = TaskStatusResponse.from_task(Task(task_id="e", source_kind="audio"))
    assert dto.error_code is None


def test_wire_body_includes_error_code():
    task = Task(
        task_id="e",
        source_kind="audio",
        status=TaskStatus.FAILED,
        error="boom",
        error_code=ErrorCode.BAD_INPUT,
    )
    assert TaskStatusResponse.wire_body(task)["error_code"] == "bad_input"


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
    # Пустой usage отражается как Usage() со всеми None-полями.
    assert dto.usage.model_dump(exclude_none=True) == {}


def test_status_response_exposes_usage():
    task = Task(
        task_id="u",
        source_kind="audio",
        usage={"transcribe": {"audio_seconds": 120, "provider": "groq", "raw": {}}},
    )
    dto = TaskStatusResponse.from_task(task)
    # usage без ключа model валиден (поле опционально).
    assert dto.usage.model_dump(exclude_none=True) == {
        "transcribe": {"audio_seconds": 120, "provider": "groq", "raw": {}}
    }


def test_usage_full_shape_round_trips():
    raw = {
        "transcribe": {"audio_seconds": 12, "provider": "groq", "model": "w", "raw": {}},
        "structurize": {
            "provider": "gemini",
            "by_model": {"g": {"prompt": 1, "output": 2, "calls": 3}},
            "raw": {},
        },
        "total": {
            "audio_seconds": 12,
            "gemini_prompt": 1,
            "gemini_output": 2,
            "source": "audio",
            "slides_origin": "document",
        },
    }
    task = Task(task_id="x", source_kind="audio", usage=raw)
    dto = TaskStatusResponse.from_task(task)
    assert dto.usage.model_dump(exclude_none=True) == raw
    assert dto.usage.video_slides is None


def test_create_response_holds_task_id():
    assert CreateTaskResponse(task_id="xyz").task_id == "xyz"
