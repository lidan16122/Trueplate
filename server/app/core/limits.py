"""Per-user rate limiting, as a route dependency.

A dependency rather than middleware, deliberately. Middleware runs before
dependency resolution, so it has no authenticated user to key on — it would be
limited to IP, which puts an office behind one NAT into a single bucket and lets
one signed-in user rotate addresses. It also cannot be applied per route, and
these limits exist specifically to protect the two endpoints that spend money on
vision calls.
"""

from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.config import settings
from app.core.deps import CurrentUser, RateLimiterDep
from app.stores.rate_limit import RateLimitResult

# The scope name the AI detection endpoints share. Named here rather than
# spelled at each route, so the limit and the key cannot disagree.
AI_DETECT_SCOPE = "ai_detect"


def _rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    """Turn a limiter decision into response headers.

    Shaping HTTP is the route layer's job — the store returns a decision and
    stays unaware that a transport exists.
    """
    headers = {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
    }
    if not result.allowed:
        headers["Retry-After"] = str(result.retry_after_seconds)
    return headers


class RateLimit:
    """Usage: ``dependencies=[Depends(RateLimit(AI_DETECT_SCOPE))]``."""

    def __init__(
        self, scope: str, limit: int | None = None, window_seconds: int | None = None
    ) -> None:
        self.scope = scope
        # Default to the configured policy, so the deployed limit is an env var
        # rather than a number repeated at every call site.
        self.limit = limit if limit is not None else settings.ai_detect_rate_limit
        self.window_seconds = (
            window_seconds if window_seconds is not None else settings.ai_detect_rate_window_seconds
        )

    async def __call__(self, user: CurrentUser, limiter: RateLimiterDep) -> None:
        result = await limiter.hit(
            scope=self.scope,
            subject=str(user.id),
            limit=self.limit,
            window_seconds=self.window_seconds,
            now=datetime.now(UTC).timestamp(),
        )

        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit reached: {self.limit} requests per "
                    f"{self.window_seconds // 60} minutes. Try again shortly."
                ),
                # Retry-After and X-RateLimit-* so a client can back off
                # intelligently instead of hammering.
                headers=_rate_limit_headers(result),
            )
