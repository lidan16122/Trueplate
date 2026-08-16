"""Helpers shared across test modules.

A plain module rather than a conftest: conftest is where pytest looks for
fixtures, and importing a function out of one works but reads as a trick. This
exists so `test_auth_routes` does not have to import from `test_refresh_tokens`
— a dependency between two test files that makes running either alone a
gamble.
"""

from datetime import UTC, datetime

from app.stores import keys
from app.stores.refresh_tokens import hash_token


async def age_tombstone(redis, raw_token: str, seconds: float = 3600) -> None:
    """Backdate a rotated token's tombstone past the reuse grace window.

    Replays inside the window are deliberately forgiven, so exercising genuine
    theft detection means making the rotation look old.
    """
    await redis.hset(
        keys.refresh_used_key(hash_token(raw_token)),
        "rotated_at",
        str(datetime.now(UTC).timestamp() - seconds),
    )
