from lecturelog.domain.enums import ErrorCode, PipelineStage, TaskStatus


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


def test_error_code_values():
    assert ErrorCode.RATE_LIMIT.value == "rate_limit"
    assert ErrorCode.BAD_INPUT.value == "bad_input"
    assert ErrorCode.INTERNAL.value == "internal"
    # StrEnum: значение сравнимо со строкой.
    assert ErrorCode.INTERNAL == "internal"
    # Все значения (каталог минимален).
    assert {e.value for e in ErrorCode} == {"rate_limit", "bad_input", "internal", "cookies_invalid"}
