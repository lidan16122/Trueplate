"""Sliding-window limiter for the endpoints that cost money per call.

`now` is injected throughout so the window can be advanced without sleeping.
"""

import pytest

from app.stores import keys
from app.stores.rate_limit import RateLimiter

SCOPE = "ai_detect"
USER = "user-1"
T0 = 1000.0


@pytest.fixture
def limiter(redis) -> RateLimiter:
    return RateLimiter(redis)


async def test_requests_under_the_limit_are_allowed(limiter: RateLimiter):
    for _ in range(3):
        result = await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)
        assert result.allowed is True


async def test_the_request_past_the_limit_is_rejected(limiter: RateLimiter):
    for _ in range(3):
        await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)

    result = await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)
    assert result.allowed is False


async def test_remaining_counts_down_and_floors_at_zero(limiter: RateLimiter):
    seen = [
        (await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0)).remaining
        for _ in range(4)
    ]
    assert seen == [1, 0, 0, 0]


async def test_a_ttl_is_always_set(limiter: RateLimiter, redis):
    """The key must never be left immortal — that would lock a user out for good."""
    await limiter.hit(scope=SCOPE, subject=USER, limit=5, window_seconds=60, now=T0)

    assert 0 < await redis.ttl(keys.rate_limit_key(SCOPE, USER)) <= 60


async def test_the_window_slides_rather_than_resetting_on_a_boundary(limiter: RateLimiter):
    """The reason this is not a fixed window.

    A fixed window lets a client spend its whole allowance just before an edge
    and the whole next allowance just after — 2x the limit in a moment, on the
    endpoints whose cost is the entire point of limiting them.
    """
    for _ in range(3):
        await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)

    # A fixed 60s window keyed on now//60 would roll over here and allow 3 more.
    just_past_the_edge = await limiter.hit(
        scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0 + 1
    )
    assert just_past_the_edge.allowed is False


async def test_capacity_returns_as_individual_hits_age_out(limiter: RateLimiter):
    await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0)
    await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0 + 30)

    assert not (
        await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0 + 40)
    ).allowed

    # The first hit is now outside the window; exactly one slot frees up.
    assert (
        await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0 + 61)
    ).allowed
    assert not (
        await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0 + 61)
    ).allowed


async def test_a_rejected_request_does_not_extend_its_own_lockout(limiter: RateLimiter):
    """A client that keeps retrying must still recover.

    If a refused hit were recorded, every retry would push the window forward
    and the user could never get back in.
    """
    await limiter.hit(scope=SCOPE, subject=USER, limit=1, window_seconds=60, now=T0)
    for offset in range(1, 30):
        await limiter.hit(scope=SCOPE, subject=USER, limit=1, window_seconds=60, now=T0 + offset)

    assert (
        await limiter.hit(scope=SCOPE, subject=USER, limit=1, window_seconds=60, now=T0 + 61)
    ).allowed


async def test_users_are_limited_independently(limiter: RateLimiter):
    for _ in range(3):
        await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)

    other = await limiter.hit(scope=SCOPE, subject="user-2", limit=3, window_seconds=60, now=T0)
    assert other.allowed is True


async def test_scopes_are_limited_independently(limiter: RateLimiter):
    for _ in range(3):
        await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)

    other = await limiter.hit(scope="ai_text", subject=USER, limit=3, window_seconds=60, now=T0)
    assert other.allowed is True


async def test_rejection_reports_when_to_come_back(limiter: RateLimiter):
    await limiter.hit(scope=SCOPE, subject=USER, limit=1, window_seconds=60, now=T0)

    result = await limiter.hit(scope=SCOPE, subject=USER, limit=1, window_seconds=60, now=T0 + 10)

    assert result.allowed is False
    assert result.limit == 1
    assert result.remaining == 0
    # The first hit ages out 50s from now; never report 0, which invites an
    # immediate retry that would just be refused again.
    assert 0 < result.retry_after_seconds <= 60


async def test_hits_in_the_same_millisecond_are_counted_separately(limiter: RateLimiter):
    """Sorted sets dedupe by member, so a bare timestamp would undercount."""
    for _ in range(2):
        await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0)

    result = await limiter.hit(scope=SCOPE, subject=USER, limit=2, window_seconds=60, now=T0)
    assert result.allowed is False


async def test_reset_clears_the_window(limiter: RateLimiter):
    for _ in range(3):
        await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)

    await limiter.reset(scope=SCOPE, subject=USER)

    result = await limiter.hit(scope=SCOPE, subject=USER, limit=3, window_seconds=60, now=T0)
    assert result.allowed is True
    assert result.remaining == 2
