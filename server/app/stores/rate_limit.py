"""Per-user rate limiting for endpoints that cost real money.

A sliding window over a sorted set, not a fixed window. A fixed window admits up
to 2x the limit across a window edge — twenty vision calls at 10:59 and twenty
more at 11:00 — and "these requests cost real money per call" is exactly the
reason not to accept that. The cost is one sorted set per subject instead of one
integer, bounded by the limit itself because entries outside the window are
trimmed on every hit.

The whole operation is one Lua script. As separate calls, a crash between the
add and the expiry leaves a key with no TTL, which never resets and locks the
user out permanently.
"""

import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.stores import keys

# KEYS[1] sorted set
# ARGV[1] now (ms)   ARGV[2] window (ms)   ARGV[3] limit   ARGV[4] member id
# Returns {allowed (1/0), count_in_window, retry_after_ms}
_SLIDING_LUA = """
local now      = tonumber(ARGV[1])
local window   = tonumber(ARGV[2])
local limit    = tonumber(ARGV[3])
local cutoff   = now - window

-- Drop everything older than the window before counting, so the set never
-- grows past the limit and the count is always current.
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)

local count = redis.call('ZCARD', KEYS[1])
local allowed = 0
local retry_after = 0

if count < limit then
  redis.call('ZADD', KEYS[1], now, ARGV[4])
  count = count + 1
  allowed = 1
else
  -- At the limit: report when the oldest hit falls out of the window, which is
  -- the soonest another request could succeed. The rejected request is
  -- deliberately not recorded — otherwise a client that keeps retrying would
  -- push its own window forward and never recover.
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  if oldest[2] then
    retry_after = (tonumber(oldest[2]) + window) - now
  else
    retry_after = window
  end
end

-- Always re-armed, so an idle subject's key expires instead of lingering.
redis.call('PEXPIRE', KEYS[1], window)

return {allowed, count, math.ceil(retry_after)}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """What the limiter decided. Deliberately carries no HTTP shape.

    Turning this into `X-RateLimit-*` headers is the route layer's job; a store
    that knows about response headers is a store that has to change when the
    transport does.
    """

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._hit = redis.register_script(_SLIDING_LUA)

    async def hit(
        self, *, scope: str, subject: str, limit: int, window_seconds: int, now: float
    ) -> RateLimitResult:
        """Record one request and report whether it is permitted.

        ``now`` is injected rather than read here so tests can advance the clock
        without sleeping.
        """
        key = keys.rate_limit_key(scope, subject)
        now_ms = int(now * 1000)
        window_ms = window_seconds * 1000
        # Two requests can share a millisecond, and a sorted set dedupes by
        # member — so a bare timestamp would silently collapse them into one
        # and undercount. A random suffix keeps each hit its own entry without
        # a second round trip to Redis for a counter.
        member = f"{now_ms}-{uuid.uuid4().hex[:12]}"

        allowed, count, retry_after_ms = await self._hit(
            keys=[key], args=[now_ms, window_ms, limit, member]
        )

        return RateLimitResult(
            allowed=bool(allowed),
            limit=limit,
            remaining=max(0, limit - int(count)),
            # Ceil to whole seconds: a Retry-After that rounds down tells the
            # client to come back while it would still be refused.
            retry_after_seconds=max(1, -(-int(retry_after_ms) // 1000)),
        )

    async def reset(self, *, scope: str, subject: str) -> None:
        await self._redis.delete(keys.rate_limit_key(scope, subject))
