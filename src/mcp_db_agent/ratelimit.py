"""Client-side request pacing.

Retrying a 429 recovers from a rate limit; it does not avoid one. Google's
free tier allows a handful of requests per minute and a single ReAct loop
spends several, so bursts are the normal case rather than an edge case --
five concurrent sessions will exhaust the quota before any of them finishes.

This module keeps requests under the limit in the first place with a sliding
window: a request waits until the oldest timestamp in the window expires. The
limiter is shared per model across the whole process, so every agent in the
FastAPI server draws from one budget rather than each assuming it has the
quota to itself. Quotas are enforced per model, hence one limiter per model.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable


class AsyncRateLimiter:
    """Sliding-window limiter: at most `max_requests` per `per_seconds`.

    A sliding window is used rather than a fixed one because a fixed window
    permits a double-rate burst across its boundary -- exactly the pattern that
    trips Google's limiter.
    """

    def __init__(self, max_requests: int, per_seconds: float = 60.0):
        self.max_requests = max(1, int(max_requests))
        self.per_seconds = float(per_seconds)
        self._hits: deque = deque()
        # Serialises the check-and-reserve so two coroutines cannot both see
        # the last free slot and take it.
        self._lock = asyncio.Lock()

    def _evict(self, now: float) -> None:
        cutoff = now - self.per_seconds
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()

    async def acquire(self, on_wait: Callable | None = None) -> float:
        """Reserve a slot, waiting if the window is full. Returns seconds waited."""
        waited = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                self._evict(now)
                if len(self._hits) < self.max_requests:
                    self._hits.append(now)
                    return waited
                # Wait for the oldest request to age out of the window.
                delay = self._hits[0] + self.per_seconds - now

            delay = max(delay, 0.05)
            if on_wait and waited == 0.0:
                on_wait(delay)
            waited += delay
            # Slept outside the lock so other coroutines can queue behind us.
            await asyncio.sleep(delay)

    @property
    def in_window(self) -> int:
        self._evict(time.monotonic())
        return len(self._hits)


# Free-tier requests-per-minute by model family, from the AI Studio quota page.
# The Lite models allow three times the rate and twenty-five times the daily
# budget, so pacing them at the Flash rate would throw away most of their
# throughput.
FLASH_RPM = 5
FLASH_LITE_RPM = 15


def default_rpm(model: str) -> int:
    return FLASH_LITE_RPM if "lite" in model.lower() else FLASH_RPM


_limiters: dict = {}


def limiter_for(model: str, max_requests: int, per_seconds: float = 60.0) -> AsyncRateLimiter:
    """Return the process-wide limiter for `model`, creating it on first use."""
    key = (model, max_requests, per_seconds)
    if key not in _limiters:
        _limiters[key] = AsyncRateLimiter(max_requests, per_seconds)
    return _limiters[key]


def reset() -> None:
    """Drop every limiter. Used by tests to isolate cases."""
    _limiters.clear()
