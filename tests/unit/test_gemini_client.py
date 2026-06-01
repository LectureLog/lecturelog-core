import pytest

from lecturelog.infrastructure.llm.gemini_client import GeminiClient


class FakePool:
    def __init__(self, client):
        self._client = client
        self.rate_limited = []

    async def acquire(self, models):
        return self._client, 0, models[0]

    async def mark_rate_limited(self, idx, model):
        self.rate_limited.append((idx, model))


class FakeModels:
    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = 0

    def generate_content(self, model, contents, config=None):
        b = self._behaviors[self.calls]
        self.calls += 1
        if isinstance(b, Exception):
            raise b

        class R:
            text = b

        return R()


class FakeClient:
    def __init__(self, behaviors):
        self.models = FakeModels(behaviors)


@pytest.mark.asyncio
async def test_returns_text_on_success():
    client = FakeClient(["ответ модели"])
    gc = GeminiClient(pool=FakePool(client))
    out = await gc.call(prompt="привет", models=["gemini-3.5-flash"])
    assert out == "ответ модели"


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds():
    client = FakeClient([RuntimeError("429 RESOURCE_EXHAUSTED"), "успех"])
    pool = FakePool(client)
    gc = GeminiClient(pool=pool)
    out = await gc.call(prompt="x", models=["gemini-3.5-flash"])
    assert out == "успех"
    assert len(pool.rate_limited) == 1  # пара была заблокирована перед ретраем


@pytest.mark.asyncio
async def test_non_rate_limit_error_propagates():
    client = FakeClient([ValueError("плохой запрос")])
    gc = GeminiClient(pool=FakePool(client))
    with pytest.raises(ValueError):
        await gc.call(prompt="x", models=["gemini-3.5-flash"])
