"""Session operations shared by workflows.

Services choose when a transaction ends; keeping the driver calls here makes
that boundary explicit without changing the request's session or commit order.
"""

from sqlalchemy.ext.asyncio import AsyncSession


async def commit(session: AsyncSession) -> None:
    await session.commit()


async def flush(session: AsyncSession) -> None:
    await session.flush()


async def refresh(session: AsyncSession, row: object) -> None:
    await session.refresh(row)


async def rollback(session: AsyncSession) -> None:
    await session.rollback()
