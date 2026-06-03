from lecturelog.domain.exceptions import (
    DomainError,
    InvalidFormat,
    InvalidSource,
    ResultNotReady,
    TaskNotFound,
    TranscribeFailed,
)


def test_all_inherit_domain_error():
    for exc in (TaskNotFound, ResultNotReady, TranscribeFailed, InvalidFormat, InvalidSource):
        assert issubclass(exc, DomainError)


def test_task_not_found_carries_id():
    err = TaskNotFound("abc123")
    assert "abc123" in str(err)


def test_transcribe_failed_carries_detail():
    err = TranscribeFailed("groq timeout")
    assert "groq timeout" in str(err)
