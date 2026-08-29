"""Client-side pacing.

These tests run against a fake monotonic clock so a "60 second" window costs no
real time, and so the assertions are about the limiter's arithmetic rather than
about wall-clock timing that would be flaky on a loaded machine.
"""

import asyncio

import pytest

from mcp_db_agent.ratelimit import (
    AsyncRateLimiter, default_rpm, limiter_for, reset,
)


@pytest.fixture
def clock(monkeypatch):
    """A controllable clock. asyncio.sleep advances it instead of waiting."""
    from mcp_db_agent import ratelimit

    now = {"t": 1000.0}
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now["t"])

    real_sleep = asyncio.sleep

    async def _sleep(seconds):
        now["t"] += seconds
        await real_sleep(0)

    monkeypatch.setattr(ratelimit.asyncio, "sleep", _sleep)
    return now


@pytest.fixture(autouse=True)
def _isolate():
    reset()
    yield
    reset()


async def test_requests_under_the_limit_never_wait(clock):
    limiter = AsyncRateLimiter(max_requests=5, per_seconds=60)
    for _ in range(5):
        assert await limiter.acquire() == 0.0
    assert clock["t"] == 1000.0  # no time passed


async def test_the_sixth_request_waits_for_the_window_to_slide(clock):
    limiter = AsyncRateLimiter(max_requests=5, per_seconds=60)
    for _ in range(5):
        await limiter.acquire()

    waited = await limiter.acquire()
    assert waited == pytest.approx(60.0)
    assert clock["t"] == pytest.approx(1060.0)


async def test_slots_free_up_as_time_passes(clock):
    limiter = AsyncRateLimiter(max_requests=3, per_seconds=60)
    for _ in range(3):
        await limiter.acquire()

    clock["t"] += 61  # the whole window ages out
    assert await limiter.acquire() == 0.0
    assert limiter.in_window == 1


async def test_on_wait_is_notified_once_with_the_delay(clock):
    limiter = AsyncRateLimiter(max_requests=1, per_seconds=60)
    await limiter.acquire()

    notices = []
    await limiter.acquire(on_wait=notices.append)
    assert len(notices) == 1
    assert notices[0] == pytest.approx(60.0)


async def test_concurrent_callers_never_oversubscribe_any_window(clock):
    """The invariant that matters: however many coroutines race, no 60-second
    span ever contains more than max_requests admissions."""
    limiter = AsyncRateLimiter(max_requests=5, per_seconds=60)

    async def admit():
        await limiter.acquire()
        return clock["t"]  # the clock value at which this call was let through

    admitted = sorted(await asyncio.gather(*(admit() for _ in range(12))))

    assert len(admitted) == 12
    for start in admitted:
        in_window = [t for t in admitted if start <= t < start + 60]
        assert len(in_window) <= 5, f"{len(in_window)} admitted in the window at {start}"


async def test_limiter_is_shared_per_model():
    a = limiter_for("gemini-2.5-flash", 5)
    b = limiter_for("gemini-2.5-flash", 5)
    c = limiter_for("gemini-3.5-flash", 5)
    assert a is b, "agents on the same model must share one quota budget"
    assert a is not c, "quotas are enforced per model, so limiters must be too"


def test_limit_is_never_below_one():
    assert AsyncRateLimiter(max_requests=0).max_requests == 1


def test_pacing_follows_the_model_family_quota():
    """Flash allows 5 req/min, Flash-Lite 15. Pacing Lite at the Flash rate
    would discard two thirds of its throughput."""
    assert default_rpm("gemini-3.6-flash") == 5
    assert default_rpm("gemini-3.7-flash") == 5
    assert default_rpm("gemini-3.5-flash-lite") == 15
    assert default_rpm("gemini-3.1-flash-lite") == 15
    assert default_rpm("GEMINI-3.5-FLASH-LITE") == 15  # case-insensitive
