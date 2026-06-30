from lecturelog.application.error_classifier import classify_error
from lecturelog.domain.enums import ErrorCode


def test_classifies_youtube_bot_check_as_cookies_invalid():
    exc = RuntimeError(
        "yt-dlp не смог скачать видео: ERROR: [youtube] Sign in to confirm "
        "you're not a bot. Use --cookies-from-browser ..."
    )
    assert classify_error(exc) == ErrorCode.COOKIES_INVALID


def test_classifies_confirm_not_a_bot_variant():
    exc = RuntimeError("Please confirm you're not a bot")
    assert classify_error(exc) == ErrorCode.COOKIES_INVALID


def test_unrelated_error_stays_internal():
    assert classify_error(RuntimeError("disk full")) == ErrorCode.INTERNAL
