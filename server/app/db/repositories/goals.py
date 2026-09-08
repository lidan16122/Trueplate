"""Goal history persistence; superseding a goal keeps its old target snapshot."""

import uuid
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Goal


async def active_goal(session: AsyncSession, user_id: uuid.UUID) -> Goal | None:
    return await session.scalar(select(Goal).where(Goal.user_id == user_id, Goal.ends_on.is_(None)))


async def active_goal_id(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(Goal.id).where(Goal.user_id == user_id, Goal.ends_on.is_(None))
    )


async def close_active_goal(session: AsyncSession, user_id: uuid.UUID, today: date) -> None:
    await session.execute(
        update(Goal).where(Goal.user_id == user_id, Goal.ends_on.is_(None)).values(ends_on=today)
    )


async def add_goal(session: AsyncSession, goal: Goal) -> None:
    session.add(goal)
