"""Profile and weight queries shared by onboarding and account use cases."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserProfile, WeightEntry


async def read_profile(db: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    return await db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))


async def profile_id(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(select(UserProfile.id).where(UserProfile.user_id == user_id))


async def add_profile(db: AsyncSession, profile: UserProfile) -> None:
    db.add(profile)


async def weight_on(db: AsyncSession, user_id: uuid.UUID, day: date) -> WeightEntry | None:
    return await db.scalar(
        select(WeightEntry).where(WeightEntry.user_id == user_id, WeightEntry.recorded_on == day)
    )


async def add_weight(db: AsyncSession, entry: WeightEntry) -> None:
    db.add(entry)


async def latest_weight_kg(session: AsyncSession, user_id: uuid.UUID) -> float | None:
    return await session.scalar(
        select(WeightEntry.weight_kg)
        .where(WeightEntry.user_id == user_id)
        .order_by(WeightEntry.recorded_on.desc())
        .limit(1)
    )
