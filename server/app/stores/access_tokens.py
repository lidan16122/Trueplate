"""Optional instant revocation for access tokens.

Separate from refresh-session revocation: this optional Redis lookup rejects an
individual JWT before its normal expiry.
"""

from redis.asyncio import Redis

from app.config import settings
from app.stores import keys


class AccessTokenDenylist:
    """Off by default.

    The normal path verifies the JWT by signature alone and never touches Redis
    — a 15-minute token expiring on its own is usually enough, and a per-request
    round-trip is a real cost to pay for the remainder. This exists so "sign out
    everywhere, right now" is a config flag rather than a refactor.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Deny a specific token until it would have expired anyway.

        A no-op when the feature is off, so a caller cannot fill Redis with
        entries that `is_revoked` will never read.
        """
        if not settings.access_denylist_enabled:
            return
        # TTL matches the token's own expiry: past that it is rejected anyway,
        # so the entry has no further work to do.
        await self._redis.set(keys.access_deny_key(jti), "1", ex=ttl_seconds)

    async def is_revoked(self, jti: str) -> bool:
        if not settings.access_denylist_enabled:
            return False
        return await self._redis.exists(keys.access_deny_key(jti)) == 1
