import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis

from homehelper.core.config import Settings

Clock = Callable[[], float]  # seconds since the epoch

# Trim hits older than the longest window, then check every window; record the hit only if all
# allow it. Returns 0 when allowed, else the milliseconds until the tightest window frees a slot.
# KEYS[1] = rl:...; ARGV = now_ms, member, then (window_ms, limit) pairs.
_SLIDING_WINDOW = """
local now = tonumber(ARGV[1])
local longest = 0
for i = 3, #ARGV, 2 do
  longest = math.max(longest, tonumber(ARGV[i]))
end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - longest)
local wait = 0
for i = 3, #ARGV, 2 do
  local window = tonumber(ARGV[i])
  local limit = tonumber(ARGV[i + 1])
  local start = '(' .. (now - window)
  local count = redis.call('ZCOUNT', KEYS[1], start, '+inf')
  if count >= limit then
    local hit = redis.call('ZRANGEBYSCORE', KEYS[1], start, '+inf', 'WITHSCORES', 'LIMIT',
      count - limit, 1)
    wait = math.max(wait, tonumber(hit[2]) + window - now)
  end
end
if wait > 0 then
  return wait
end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('PEXPIRE', KEYS[1], longest)
return 0
"""

# Delete the lock only if we still own it.
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


@dataclass(frozen=True)
class Window:
    limit: int
    seconds: int


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_s: int = 0


class SlidingWindowLimiter:
    """Exact sliding windows: one sorted set of hit timestamps per subject (`rl:ip:{ip}`,
    `rl:user:{id}`), checked against every window atomically in Lua."""

    def __init__(self, redis: Redis, windows: Sequence[Window], *, clock: Clock = time.time):
        self._script = redis.register_script(_SLIDING_WINDOW)
        self._windows = windows
        self._clock = clock

    async def hit(self, key: str) -> RateDecision:
        if not self._windows:
            return RateDecision(allowed=True)
        now_ms = int(self._clock() * 1000)
        args: list[int | str] = [now_ms, f"{now_ms}-{uuid.uuid4().hex[:8]}"]
        for window in self._windows:
            args += [window.seconds * 1000, window.limit]
        wait_ms = int(await self._script(keys=[key], args=args))
        if wait_ms <= 0:
            return RateDecision(allowed=True)
        return RateDecision(allowed=False, retry_after_s=max(1, -(-wait_ms // 1000)))


class SpendLedger:
    """Today's (UTC) LLM spend in `spend:{YYYYMMDD}`; at or over the cap = maintenance mode."""

    TTL_S = 2 * 24 * 3600

    def __init__(self, redis: Redis, cap_usd: float, *, clock: Clock = time.time) -> None:
        self._redis = redis
        self.cap_usd = cap_usd
        self._clock = clock

    def key(self) -> str:
        return f"spend:{datetime.fromtimestamp(self._clock(), UTC):%Y%m%d}"

    async def add(self, cost_usd: float) -> None:
        if cost_usd <= 0:
            return
        key = self.key()
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incrbyfloat(key, cost_usd)
            pipe.expire(key, self.TTL_S)
            await pipe.execute()

    async def spent_today(self) -> float:
        return float(await self._redis.get(self.key()) or 0)

    async def over_cap(self) -> bool:
        return self.cap_usd > 0 and await self.spent_today() >= self.cap_usd


class ConversationLock:
    """`conv:lock:{id}`: one message at a time per conversation. The TTL bounds a lock whose
    holder died; it matches the Cloud Run request timeout."""

    TTL_S = 300

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._release = redis.register_script(_RELEASE)

    @staticmethod
    def key(conversation_id: str) -> str:
        return f"conv:lock:{conversation_id}"

    async def acquire(self, conversation_id: str) -> str | None:
        """A token to release with, or None if a message is already being handled."""
        token = uuid.uuid4().hex
        acquired = await self._redis.set(self.key(conversation_id), token, nx=True, ex=self.TTL_S)
        return token if acquired else None

    async def release(self, conversation_id: str, token: str) -> None:
        await self._release(keys=[self.key(conversation_id)], args=[token])


@dataclass
class TurnGuards:
    ip_limiter: SlidingWindowLimiter
    user_limiter: SlidingWindowLimiter
    login_limiter: SlidingWindowLimiter
    spend: SpendLedger
    lock: ConversationLock

    @classmethod
    def from_settings(cls, redis: Redis, settings: Settings) -> "TurnGuards":
        windows = [
            Window(limit=settings.rate_limit_per_hour, seconds=3600),
            Window(limit=settings.rate_limit_per_day, seconds=24 * 3600),
        ]
        return cls(
            ip_limiter=SlidingWindowLimiter(redis, windows),
            user_limiter=SlidingWindowLimiter(redis, windows),
            login_limiter=SlidingWindowLimiter(
                redis, [Window(limit=settings.login_rate_limit_per_hour, seconds=3600)]
            ),
            spend=SpendLedger(redis, settings.daily_spend_cap_usd),
            lock=ConversationLock(redis),
        )
