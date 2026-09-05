"""How much of an account's AI-detection allowance has been spent.

``users.max_prompts`` caps *detections*, not logged foods. One photo of a plate
resolves to several ``food_entries`` rows, so counting rows would spend a cap of
1 on the first meal anyone photographs. Photos are therefore folded on
``image_hash`` — the column that already ties one photo's entries together — and
a text entry, which has no such key, counts as the one detection it came from.

That leaves the count approximate in a single direction: two foods saved from
one *text* detection still read as two, because nothing on that path groups
them. Making it exact needs a detection id on ``food_entries``.

A null ``max_prompts`` means uncapped. That is what every account created before
the column existed holds, and the migration adds no server default.

Read from Postgres on every call rather than cached: this is a single indexed
count, and caching it would buy an invalidation problem for nothing.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyLog, FoodEntry
from app.enums import DetectionMethod


@dataclass(frozen=True)
class PromptUsage:
    """What the two counters below add up to, and what the account is allowed."""

    used: int
    limit: int | None

    @property
    def allowed(self) -> bool:
        return self.limit is None or self.used < self.limit


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


async def read_usage(
    db: AsyncSession, user_id: uuid.UUID, max_prompts: int | None
) -> PromptUsage:
    """Detections spent by this user, against their cap.

    ``max_prompts`` is passed in rather than re-queried: ``CurrentUser`` is the
    live ORM row, so every caller already holds it.
    """
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

    return PromptUsage(used=(photos or 0) + (texts or 0), limit=max_prompts)
