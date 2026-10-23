from collections.abc import AsyncIterator

import pytest
from fakeredis import FakeAsyncRedis
from structlog.testing import capture_logs

from homehelper.ratelimit import ConversationLock, SlidingWindowLimiter, SpendLedger, Window


class Clock:
    def __init__(self, now: float = 1_761_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_sliding_window_allows_up_to_the_limit(redis: FakeAsyncRedis) -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(redis, [Window(limit=3, seconds=60)], clock=clock)
    for _ in range(3):
        assert (await limiter.hit("rl:ip:1.2.3.4")).allowed
        clock.now += 10
    denied = await limiter.hit("rl:ip:1.2.3.4")
    # The first hit (30 s ago) leaves the window 30 s from now.
    assert (denied.allowed, denied.retry_after_s) == (False, 30)
    assert (await limiter.hit("rl:ip:5.6.7.8")).allowed  # other subjects are independent

    clock.now += 30.001
    assert (await limiter.hit("rl:ip:1.2.3.4")).allowed


async def test_denied_hits_are_not_counted(redis: FakeAsyncRedis) -> None:
    clock = Clock()
    limiter = SlidingWindowLimiter(redis, [Window(limit=1, seconds=60)], clock=clock)
    assert (await limiter.hit("k")).allowed
    for _ in range(5):
        clock.now += 5
        assert not (await limiter.hit("k")).allowed
    clock.now += 35.001  # 60 s after the only counted hit
    assert (await limiter.hit("k")).allowed


async def test_every_window_is_enforced(redis: FakeAsyncRedis) -> None:
    clock = Clock()
    windows = [Window(limit=2, seconds=3600), Window(limit=3, seconds=86400)]
    limiter = SlidingWindowLimiter(redis, windows, clock=clock)
    assert (await limiter.hit("k")).allowed
    assert (await limiter.hit("k")).allowed
    hourly = await limiter.hit("k")
    assert not hourly.allowed and hourly.retry_after_s == 3600

    clock.now += 3601
    assert (await limiter.hit("k")).allowed
    daily = await limiter.hit("k")
    assert not daily.allowed
    assert daily.retry_after_s == 86400 - 3601
    assert await redis.ttl("k") > 0


async def test_spend_cap_switches_to_maintenance(redis: FakeAsyncRedis) -> None:
    clock = Clock(1_761_004_800.0)  # 2025-10-21 00:00 UTC
    ledger = SpendLedger(redis, cap_usd=0.05, clock=clock)
    assert ledger.key() == "spend:20251021"
    await ledger.add(0.03)
    await ledger.add(0)
    assert not await ledger.over_cap()
    await ledger.add(0.02)
    assert await ledger.spent_today() == pytest.approx(0.05)
    assert await ledger.over_cap()
    assert 0 < await redis.ttl("spend:20251021") <= SpendLedger.TTL_S

    clock.now += 86400  # a new day starts from zero
    assert not await ledger.over_cap()
    assert not await SpendLedger(redis, cap_usd=0, clock=clock).over_cap()  # 0 = disabled


async def test_conversation_lock_is_exclusive_and_owned(redis: FakeAsyncRedis) -> None:
    lock = ConversationLock(redis)
    token = await lock.acquire("conv_1")
    assert token is not None
    assert await lock.acquire("conv_1") is None
    assert await lock.acquire("conv_2") is not None
    assert 0 < await redis.ttl("conv:lock:conv_1") <= ConversationLock.TTL_S

    await lock.release("conv_1", "someone-else")
    assert await lock.acquire("conv_1") is None
    await lock.release("conv_1", token)
    assert await lock.acquire("conv_1") is not None


async def test_spend_logs_once_when_it_nears_and_reaches_the_cap(redis: FakeAsyncRedis) -> None:
    """The cloud spend alert counts these lines (M8-03): one warning per threshold per day."""
    ledger = SpendLedger(redis, cap_usd=1.0, clock=Clock(1_761_004_800.0))
    with capture_logs() as logs:
        for cost in (0.5, 0.25, 0.1, 0.1, 0.1, 0.5):
            await ledger.add(cost)
    crossed = [(e["event"], e["threshold"]) for e in logs if e["event"].startswith("spend.")]
    assert crossed == [("spend.threshold_crossed", 0.8), ("spend.threshold_crossed", 1.0)]
    assert all(e["log_level"] == "warning" for e in logs if e["event"].startswith("spend."))
