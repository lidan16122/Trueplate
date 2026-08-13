from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fakeredis import aioredis

from app.stores.refresh_tokens import RefreshTokenStore


@pytest_asyncio.fixture
async def redis() -> AsyncGenerator[aioredis.FakeRedis]:
    """An in-process Redis that executes real Lua via lupa.

    Not a mock of our own code: the rotation script is genuinely evaluated, so
    the check-and-swap semantics these tests depend on are actually exercised.
    """
    client = aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest.fixture
def store(redis: aioredis.FakeRedis) -> RefreshTokenStore:
    return RefreshTokenStore(redis)
