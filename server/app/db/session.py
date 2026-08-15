from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    # A pooled connection can be severed while idle — a database restart, or a
    # managed provider scaling to zero. Without this the next checkout hands out
    # a dead socket and the request fails on a connection it never opened.
    pool_pre_ping=True,
    connect_args={
        # Without this, connecting to an unreachable Postgres blocks on the OS
        # default (minutes). A request would hang rather than fail, and the
        # readiness probe would time out instead of reporting a clean 503.
        "connect_timeout": settings.db_connect_timeout_seconds,
        # A connect timeout only bounds the handshake. A statement that hangs
        # after connecting is unbounded, which is the same "looks like a hang,
        # not an outage" failure the connect timeout exists to prevent.
        "options": f"-c statement_timeout={settings.db_statement_timeout_seconds * 1000}",
    },
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # Attributes stay readable after commit. Without this, serialising a model
    # in a response handler re-fetches every column, one query per attribute,
    # after the session has already done its work.
    expire_on_commit=False,
    # Flush only where a write is intended. Autoflush turns an innocent read
    # into a write of whatever happens to be pending in the identity map.
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    # `async with` already rolls back and closes on an exception, so there is no
    # try/except here — one would only restate what the context manager does.
    async with SessionLocal() as session:
        yield session
