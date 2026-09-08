"""Food-log persistence. Every entry lookup includes the owning user's join."""

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import DailyLog, FoodEntry
from app.schemas.log import FoodEntryCreate


async def read_log(db: AsyncSession, user_id: uuid.UUID, log_date: date) -> DailyLog | None:
    log = await db.scalar(
        select(DailyLog)
        .where(DailyLog.user_id == user_id, DailyLog.log_date == log_date)
        .options(selectinload(DailyLog.entries))
    )
    return log


async def get_or_create_log(db: AsyncSession, user_id: uuid.UUID, log_date: date) -> DailyLog:
    log = await db.scalar(
        select(DailyLog)
        .where(DailyLog.user_id == user_id, DailyLog.log_date == log_date)
        .options(selectinload(DailyLog.entries))
    )
    if log is None:
        log = DailyLog(user_id=user_id, log_date=log_date)
        db.add(log)
        await db.flush()
        await db.refresh(log, ["entries"])
    return log


async def read_range(
    db: AsyncSession, user_id: uuid.UUID, start_date: date, end_date: date
) -> list[DailyLog]:
    return list(
        (
            await db.scalars(
                select(DailyLog)
                .where(
                    DailyLog.user_id == user_id,
                    DailyLog.log_date >= start_date,
                    DailyLog.log_date <= end_date,
                )
                .options(selectinload(DailyLog.entries))
            )
        ).all()
    )


async def add_entries(
    db: AsyncSession, log_id: uuid.UUID, entries: list[FoodEntryCreate], now: datetime
) -> None:
    for item in entries:
        db.add(
            FoodEntry(
                daily_log_id=log_id,
                meal_type=item.meal_type,
                name=item.name,
                brand=item.brand,
                quantity_g=item.quantity_g,
                serving_description=item.serving_description,
                kcal_per_100g=item.kcal_per_100g,
                protein_g_per_100g=item.protein_g_per_100g,
                carbs_g_per_100g=item.carbs_g_per_100g,
                fat_g_per_100g=item.fat_g_per_100g,
                detection_method=item.detection_method,
                nutrition_source=item.nutrition_source,
                source_ref=item.source_ref,
                detection_confidence=item.detection_confidence,
                image_hash=item.image_hash,
                logged_at=now,
            )
        )


async def owned_entry(
    db: AsyncSession, entry_id: uuid.UUID, user_id: uuid.UUID
) -> FoodEntry | None:
    """Fetch an entry, refusing to reveal whether someone else's exists.

    The join through daily_logs is the authorisation check: without it, any
    entry id would be editable by any signed-in user.
    """
    entry = await db.scalar(
        select(FoodEntry)
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(FoodEntry.id == entry_id, DailyLog.user_id == user_id)
    )
    return entry


async def delete_entry(db: AsyncSession, entry: FoodEntry) -> None:
    await db.delete(entry)
