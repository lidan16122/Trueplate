"""Liveness check for the Redis connection.

A one-call store, but it earns a file: the readiness route is the only place in
the app that would otherwise hold a Redis client directly, and the rule that
routes talk to a store rather than a client is worth more than the line it saves.
"""

from redis.asyncio import Redis


class HealthStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def ping(self) -> None:
        """Raise if Redis is unreachable.

        Returns nothing on success: the caller wants "did this raise", and a
        bool would just be a second thing to get wrong.
        """
        await self._redis.ping()
