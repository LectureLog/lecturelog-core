from pathlib import Path

from lecturelog.infrastructure.media.url_utils import is_url


def test_http_url_is_url():
    assert is_url("http://example.com/v") is True


def test_https_url_is_url():
    assert is_url("https://youtu.be/abc") is True


def test_plain_path_is_not_url():
    assert is_url("/tmp/lecture.mp4") is False
    assert is_url("lecture.mp4") is False


def test_scheme_without_netloc_is_not_url():
    # "youtube.com/watch?v=..." без схемы — не URL (паритет с PoC)
    assert is_url("youtube.com/watch?v=x") is False


def test_path_object_is_not_url():
    assert is_url(Path("/tmp/v.mp4")) is False
