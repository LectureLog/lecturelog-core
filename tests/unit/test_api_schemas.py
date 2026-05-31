from lecturelog.domain.models import Task
from lecturelog.domain.enums import TaskStatus, PipelineStage
from lecturelog.api.schemas import TaskStatusResponse, CreateTaskResponse


def test_status_response_from_domain_task():
    task = Task(task_id="abc", source_kind="audio", status=TaskStatus.PROCESSING,
                stage=PipelineStage.STRUCTURIZE, progress_pct=55, error=None, result_path=None)
    dto = TaskStatusResponse.from_task(task)
    assert dto.task_id == "abc"
    assert dto.stage == "structurize"
    assert dto.progress_pct == 55
    assert dto.error is None


def test_create_response_holds_task_id():
    assert CreateTaskResponse(task_id="xyz").task_id == "xyz"
