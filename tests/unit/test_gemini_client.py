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


class FakeModelsWithUsage:
    def __init__(self, text, prompt, output):
        self._text = text
        self._prompt = prompt
        self._output = output

    def generate_content(self, model, contents, config=None):
        meta = type(
            "Meta",
            (),
            {
                "prompt_token_count": self._prompt,
                "candidates_token_count": self._output,
            },
        )()

        return type("R", (), {"text": self._text, "usage_metadata": meta})()


class FakeClientWithUsage:
    def __init__(self, text, prompt, output):
        self.models = FakeModelsWithUsage(text, prompt, output)


@pytest.mark.asyncio
async def test_generate_emits_usage_per_call():
    client = FakeClientWithUsage("ok", prompt=100, output=40)
    gc = GeminiClient(pool=FakePool(client))
    captured = []

    async def on_usage(payload):
        captured.append(payload)

    await gc.call(prompt="x", models=["gemini-3.5-flash"], on_usage=on_usage)
    assert captured == [{"model": "gemini-3.5-flash", "prompt": 100, "output": 40}]


@pytest.mark.asyncio
async def test_generate_without_usage_metadata_defaults_to_zero():
    # существующий FakeClient не имеет usage_metadata -> getattr-дефолты, без падения
    client = FakeClient(["ответ"])
    gc = GeminiClient(pool=FakePool(client))
    captured = []

    async def on_usage(payload):
        captured.append(payload)

    out = await gc.call(prompt="x", models=["gemini-3.5-flash"], on_usage=on_usage)
    assert out == "ответ"
    assert captured == [{"model": "gemini-3.5-flash", "prompt": 0, "output": 0}]


@pytest.mark.asyncio
async def test_generate_no_usage_callback_does_not_break():
    client = FakeClientWithUsage("ok", prompt=5, output=5)
    gc = GeminiClient(pool=FakePool(client))
    out = await gc.call(prompt="x", models=["gemini-3.5-flash"])
    assert out == "ok"
