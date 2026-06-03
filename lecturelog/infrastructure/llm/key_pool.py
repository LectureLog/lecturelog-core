from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from lecturelog.infrastructure.llm.model_limits import limits_for

logger = logging.getLogger(__name__)

_PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_date(epoch: float) -> date:
    """Дата в часовом поясе America/Los_Angeles для epoch-секунд."""
    return datetime.fromtimestamp(epoch, tz=_PACIFIC).date()


def seconds_until_pacific_midnight(epoch: float) -> float:
    """Секунды до ближайшей полуночи по Pacific."""
    now = datetime.fromtimestamp(epoch, tz=_PACIFIC)
    tomorrow = (now + timedelta(days=1)).date()
    midnight = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=_PACIFIC)
    return (midnight - now).total_seconds()


class KeyPool:
    """Пул клиентов с балансировкой по парам (ключ × модель).

    Учитывает RPM (интервал между запросами) и RPD (суточный счётчик,
    сброс в полночь Pacific) на каждую пару. acquire() выбирает первую
    доступную пару в порядке приоритета моделей, при недоступности всех
    пар — ждёт минимально необходимое время.
    """

    def __init__(
        self,
        clients: list[Any],
        block_seconds: float = 60.0,
        time_func: Callable[[], float] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not clients:
            raise ValueError("Список клиентов не должен быть пустым")

        self._clients = clients
        self._lock = asyncio.Lock()
        self._block_seconds = block_seconds
        self._time = time_func or time.time
        self._sleep = sleep_func or asyncio.sleep

        # Состояние по парам (idx, model).
        self._last_request: dict[tuple[int, str], float] = defaultdict(float)
        self._day_count: dict[tuple[int, str], int] = defaultdict(int)
        self._blocked_until: dict[tuple[int, str], float] = defaultdict(float)
        # Round-robin курсор по ключам для каждой модели.
        self._cursor: dict[str, int] = defaultdict(int)
        # Текущие «квотные сутки» по Pacific.
        self._quota_day: date = pacific_date(self._time())
        # Троттлинг предупреждения о застое (раз в минуту).
        self._last_starve_warn: float = 0.0

    def _maybe_reset_day(self, now: float) -> None:
        today = pacific_date(now)
        if today != self._quota_day:
            self._day_count.clear()
            self._quota_day = today

    async def acquire(self, models: list[str]) -> tuple[Any, int, str]:
        """Вернуть (client, key_idx, model) для первой доступной пары
        в порядке приоритета models. Ждёт, если доступных пар нет."""
        n = len(self._clients)
        while True:
            best_wait = float("inf")

            async with self._lock:
                now = self._time()
                self._maybe_reset_day(now)

                for model in models:
                    rpm, rpd = limits_for(model)
                    interval = 60.0 / rpm
                    for offset in range(n):
                        idx = (self._cursor[model] + offset) % n
                        key = (idx, model)

                        # 1) реактивная блокировка (429/503)
                        blocked = self._blocked_until[key]
                        if now < blocked:
                            best_wait = min(best_wait, blocked - now)
                            continue
                        # 2) суточный лимит (RPD)
                        if self._day_count[key] >= rpd:
                            best_wait = min(best_wait, seconds_until_pacific_midnight(now))
                            continue
                        # 3) RPM-интервал
                        wait = self._last_request[key] + interval - now
                        if wait > 0:
                            best_wait = min(best_wait, wait)
                            continue
                        # доступно — резервируем слот
                        self._last_request[key] = now
                        self._day_count[key] += 1
                        self._cursor[model] = (idx + 1) % n
                        return self._clients[idx], idx, model

                # Все пары недоступны — предупреждаем о застое не чаще раза в минуту.
                if now - self._last_starve_warn >= 60.0:
                    self._last_starve_warn = now
                    logger.warning(
                        "все пары (ключ×модель) недоступны для %s, жду ~%.0fс",
                        models,
                        min(best_wait, self._block_seconds),
                    )

            delay = max(0.05, min(best_wait, self._block_seconds))
            await self._sleep(delay)

    async def mark_rate_limited(
        self, idx: int, model: str, block_seconds: float | None = None
    ) -> None:
        """Заблокировать пару (idx, model) на окно при 429/503."""
        if idx < 0 or idx >= len(self._clients):
            raise IndexError("Некорректный индекс ключа")
        window = self._block_seconds if block_seconds is None else block_seconds
        async with self._lock:
            self._blocked_until[(idx, model)] = self._time() + window
