from collections.abc import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

from app.config import settings

# One shared pool for the process. `decode_responses=True` keeps every store in
# this package working with `str` rather than sprinkling `.decode()` around.
pool = ConnectionPool.from_url(
    settings.redis_url,
    decode_responses=True,
    max_connections=50,
    # Bounded so an unreachable Redis surfaces as an error rather than a stalled
    # request. Auth reads from Redis on every refresh; a hang there would block
    # the whole sign-in path.
    socket_connect_timeout=settings.redis_timeout_seconds,
    socket_timeout=settings.redis_timeout_seconds,
)


def get_redis_client() -> Redis:
    return Redis(connection_pool=pool)


async def get_redis() -> AsyncGenerator[Redis]:
    client = get_redis_client()
    try:
        yield client
    finally:
        # Returns the connection to the shared pool; it does not close the pool.
        await client.aclose()


async def close_redis_pool() -> None:
    await pool.aclose()
