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
    with pytest.raises(Exception):  # noqa: B017
        AppConfig()


def test_webhook_config_defaults_none(monkeypatch):
    # Без env-переменных оба поля вебхука опциональны и равны None (автономный режим).
    monkeypatch.delenv("PLATFORM_CALLBACK_URL", raising=False)
    monkeypatch.delenv("LECTURELOG_WEBHOOK_SECRET", raising=False)
    for k, v in _env().items():
        monkeypatch.setenv(k, v)
    cfg = AppConfig()
    assert cfg.webhook.callback_url is None
    assert cfg.webhook.secret is None


def test_webhook_config_reads_env(monkeypatch):
    # Заданные URL и секрет читаются из окружения.
    for k, v in _env().items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PLATFORM_CALLBACK_URL", "https://p/cb")
    monkeypatch.setenv("LECTURELOG_WEBHOOK_SECRET", "s3cr3t")
    cfg = AppConfig()
    assert cfg.webhook.callback_url == "https://p/cb"
    assert cfg.webhook.secret == "s3cr3t"
