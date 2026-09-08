"""The database liveness statement, shared with the bounded readiness workflow."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ping(db: AsyncSession) -> None:
    await db.execute(text("SELECT 1"))
