import inspect

from lecturelog.domain.ports import CookieStatus, CookieStore


def test_cookie_store_is_abstract_with_expected_methods():
    assert inspect.isabstract(CookieStore)
    for name in ("save", "get", "status", "delete"):
        assert hasattr(CookieStore, name)


def test_cookie_status_fields():
    s = CookieStatus(exists=True, updated_at=None, size=42)
    assert s.exists is True
    assert s.size == 42
    assert s.updated_at is None
