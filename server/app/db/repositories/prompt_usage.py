"""Owner-scoped detection counts; the service applies the account's allowance."""

import uuid

from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyLog, FoodEntry
from app.models.enums import DetectionMethod


def _owned_entries(user_id: uuid.UUID, counter: object) -> Select:
    """Count something over one user's entries.

    ``food_entries`` carries no ``user_id`` — ownership is reachable only
    through ``daily_logs`` — so the join is not a convenience, it is the only
    way to scope the count to this user at all.
    """
    return (
        select(counter)
        .join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id)
    )


async def count_used(db: AsyncSession, user_id: uuid.UUID) -> int:
    # COUNT(DISTINCT ...) ignores nulls, so a photo entry that somehow reached
    # the table without a hash contributes nothing. Under-counting is the right
    # way to be wrong here — a bookkeeping slip should not cost a user a prompt.
    photos = await db.scalar(
        _owned_entries(user_id, func.count(distinct(FoodEntry.image_hash))).where(
            FoodEntry.detection_method == DetectionMethod.PHOTO
        )
    )
    texts = await db.scalar(
        _owned_entries(user_id, func.count(FoodEntry.id)).where(
            FoodEntry.detection_method == DetectionMethod.TEXT
        )
    )

    return (photos or 0) + (texts or 0)
