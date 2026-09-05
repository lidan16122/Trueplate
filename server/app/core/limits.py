"""Per-user limits on the endpoints that spend money, as route dependencies.

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
from app.core.deps import CurrentUser, DbSession, RateLimiterDep
from app.services import prompt_limits
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


async def require_prompt_allowance(user: CurrentUser, db: DbSession) -> None:
    """Refuse a detection once the account's lifetime prompt cap is spent.

    A dependency beside the limiter above, for the same reason and at the same
    point: it resolves after auth, so it can key on the user, and it runs before
    the handler, so a request over the cap never reaches a paid model call.

    The add-food screen greys its photo and text inputs out from the same count,
    but that is a courtesy to the user, not the enforcement — a cap the client
    alone honours is one devtools away from not being a cap.

    403 rather than 429: the limiter's 429 says "try again shortly", and this is
    the opposite — no amount of waiting returns the allowance.
    """
    usage = await prompt_limits.read_usage(db, user.id, user.max_prompts)
    if not usage.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"You have used all {usage.limit} AI detections on this account. "
                "Barcode lookups still work."
            ),
        )
