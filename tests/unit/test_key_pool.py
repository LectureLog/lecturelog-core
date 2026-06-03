import pytest

from lecturelog.infrastructure.llm.key_pool import KeyPool


class FakeClock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


async def _noop_sleep(_):
    pass


@pytest.mark.asyncio
async def test_acquire_returns_client_idx_model():
    clock = FakeClock()
    pool = KeyPool(clients=["c0", "c1"], time_func=clock, sleep_func=_noop_sleep)
    client, idx, model = await pool.acquire(["gemini-3.5-flash"])
    assert client in ("c0", "c1")
    assert model == "gemini-3.5-flash"


@pytest.mark.asyncio
async def test_round_robin_alternates_keys():
    clock = FakeClock()
    pool = KeyPool(clients=["c0", "c1"], time_func=clock, sleep_func=_noop_sleep)
    _, idx1, _ = await pool.acquire(["gemini-3.5-flash"])
    _, idx2, _ = await pool.acquire(["gemini-3.5-flash"])
    assert idx1 != idx2  # курсор сдвинулся на другой ключ


@pytest.mark.asyncio
async def test_rate_limited_pair_is_skipped():
    clock = FakeClock()
    pool = KeyPool(
        clients=["c0", "c1"], block_seconds=60.0, time_func=clock, sleep_func=_noop_sleep
    )
    _, idx, model = await pool.acquire(["gemini-3.5-flash"])
    await pool.mark_rate_limited(idx, model)
    # следующий acquire должен выдать другой ключ (заблокированный пропущен)
    _, idx2, _ = await pool.acquire(["gemini-3.5-flash"])
    assert idx2 != idx
