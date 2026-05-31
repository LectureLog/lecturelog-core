from __future__ import annotations

# Факты о моделях (не конфиг): лимиты free tier на ОДИН ключ.
# (rpm, rpd) — запросов в минуту и в сутки.
MODEL_LIMITS: dict[str, tuple[int, int]] = {
    "gemini-3.5-flash": (5, 20),
    "gemini-3-flash-preview": (5, 20),
    "gemini-3.1-flash-lite": (15, 500),
}

# Консервативный дефолт для незнакомой модели.
DEFAULT_LIMIT: tuple[int, int] = (5, 20)


def limits_for(model: str) -> tuple[int, int]:
    """Лимиты (rpm, rpd) на один ключ для модели."""
    return MODEL_LIMITS.get(model, DEFAULT_LIMIT)
