from lecturelog.domain.enums import PipelineStage, TaskStatus


def test_pipeline_stage_values_are_lowercase_strings():
    assert PipelineStage.TRANSCRIBE.value == "transcribe"
    assert PipelineStage.STRUCTURIZE.value == "structurize"
    assert PipelineStage.EXPORT.value == "export"


def test_task_status_lifecycle_members_exist():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.PROCESSING.value == "processing"
    assert TaskStatus.DONE.value == "done"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.INTERRUPTED.value == "interrupted"
