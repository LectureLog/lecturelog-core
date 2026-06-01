from lecturelog.domain.models import Task
from lecturelog.domain.enums import TaskStatus, PipelineStage
from lecturelog.infrastructure.persistence.orm import task_to_row, row_to_task


def test_domain_to_row_and_back_preserves_fields():
    task = Task(task_id="abc", source_kind="audio", status=TaskStatus.PROCESSING,
                stage=PipelineStage.TRANSCRIBE, progress_pct=15, error=None, result_path=None)
    row = task_to_row(task)
    restored = row_to_task(row)
    assert restored.task_id == "abc"
    assert restored.status == TaskStatus.PROCESSING
    assert restored.stage == PipelineStage.TRANSCRIBE
    assert restored.progress_pct == 15


def test_round_trip_preserves_error_and_result():
    task = Task(task_id="x", source_kind="video_file", status=TaskStatus.FAILED,
                stage=None, progress_pct=42, error="boom", result_path="/r.zip")
    restored = row_to_task(task_to_row(task))
    assert restored.error == "boom"
    assert restored.result_path == "/r.zip"
    assert restored.stage is None
