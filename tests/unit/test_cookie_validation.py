import pytest

from lecturelog.infrastructure.youtube.cookie_validation import (
    InvalidCookieFormat,
    validate_netscape_cookies,
)

GOOD_HEADER = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tval\n"
GOOD_TABS = b".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tval\n"


def test_accepts_netscape_header():
    validate_netscape_cookies(GOOD_HEADER)  # не бросает


def test_accepts_7_field_tab_lines():
    validate_netscape_cookies(GOOD_TABS)  # не бросает


def test_rejects_html_garbage():
    with pytest.raises(InvalidCookieFormat):
        validate_netscape_cookies(b"<html>not cookies</html>")


def test_rejects_empty():
    with pytest.raises(InvalidCookieFormat):
        validate_netscape_cookies(b"")
