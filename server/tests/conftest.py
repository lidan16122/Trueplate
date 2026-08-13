from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fakeredis import aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AuthIdentity, Goal, User, UserProfile
from app.db.session import get_db
from app.main import app as fastapi_app
from app.stores.client import get_redis
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


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """SQLite stand-in for the tables the auth flow touches.

    ``foods`` and ``barcode_products`` are left out because their JSONB columns
    have no SQLite equivalent; nothing in the auth path reads them. ``goals``
    comes along so the post-sign-in onboarding check runs for real — its partial
    index degrades to a plain unique index here, which is harmless given the
    constraint it encodes is one active goal per user either way.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    auth_tables = [
        User.__table__,
        AuthIdentity.__table__,
        UserProfile.__table__,
        Goal.__table__,
    ]

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=auth_tables)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, redis: aioredis.FakeRedis
) -> AsyncGenerator[httpx.AsyncClient]:
    """The real app, with only its two external dependencies swapped out."""

    async def override_db():
        yield db_session

    async def override_redis():
        yield redis

    fastapi_app.dependency_overrides[get_db] = override_db
    fastapi_app.dependency_overrides[get_redis] = override_redis

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        yield c

    fastapi_app.dependency_overrides.clear()
