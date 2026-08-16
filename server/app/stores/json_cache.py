"""Shared body for the read-through JSON caches.

Both caches — AI detections and barcode products — are the same three
operations over a different key shape and TTL. Keeping one file per *use case*
is the rule; duplicating the body between them is not, because a fix to the
corrupt-entry path would otherwise have to be made twice and would eventually
be made once.
"""

import json
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis


class JSONCache:
    """A TTL'd JSON value addressed by some domain identifier.

    `key_for` maps that identifier to a Redis key, so callers never build key
    strings themselves and the namespace stays auditable in `stores/keys.py`.
    """

    def __init__(self, redis: Redis, key_for: Callable[[str], str], ttl_seconds: int) -> None:
        self._redis = redis
        self._key_for = key_for
        self._ttl = ttl_seconds

    async def get(self, identifier: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._key_for(identifier))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # A corrupt entry degrades to a miss, not a 500 — the caller can
            # always recompute, and a poisoned key that never expires cannot be
            # cleared by retrying.
            await self.invalidate(identifier)
            return None

    async def set(self, identifier: str, payload: dict[str, Any]) -> None:
        await self._redis.set(self._key_for(identifier), json.dumps(payload), ex=self._ttl)

    async def invalidate(self, identifier: str) -> None:
        await self._redis.delete(self._key_for(identifier))
