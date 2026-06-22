import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def test_export_is_deterministic():
    import export_openapi

    first = export_openapi.build_openapi_bytes()
    second = export_openapi.build_openapi_bytes()
    assert first == second  # повторный вызов даёт байт-в-байт идентичный результат


def test_export_matches_committed_file():
    import export_openapi

    committed = (ROOT / "docs" / "openapi.json").read_bytes()
    assert export_openapi.build_openapi_bytes() == committed
