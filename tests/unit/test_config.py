import pytest
from lecturelog.config.settings import AppConfig


def _env(**overrides):
    base = {
        "GROQ_API_KEYS": "g1,g2",
        "GEMINI_API_KEYS": "k1, k2 ,k3",
        "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/lecturelog",
    }
    base.update(overrides)
    return base


def test_groq_keys_parsed_and_trimmed(monkeypatch):
    for k, v in _env().items():
        monkeypatch.setenv(k, v)
    cfg = AppConfig()
    assert cfg.groq.keys == ["g1", "g2"]


def test_gemini_keys_trimmed_and_empty_dropped(monkeypatch):
    for k, v in _env(GEMINI_API_KEYS="k1, , k2 ,").items():
        monkeypatch.setenv(k, v)
    cfg = AppConfig()
    assert cfg.gemini.keys == ["k1", "k2"]


def test_gemini_models_split_into_lists(monkeypatch):
    for k, v in _env(GEMINI_MODELS_RENDER="a, b ,c").items():
        monkeypatch.setenv(k, v)
    cfg = AppConfig()
    assert cfg.gemini.render_models == ["a", "b", "c"]


def test_worker_default_concurrency(monkeypatch):
    for k, v in _env().items():
        monkeypatch.setenv(k, v)
    cfg = AppConfig()
    assert cfg.worker.max_concurrent_tasks == 2


def test_missing_required_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS", "k1")
    monkeypatch.setenv("DATABASE_URL", "x")
    with pytest.raises(Exception):
        AppConfig()
