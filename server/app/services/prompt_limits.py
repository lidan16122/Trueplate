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

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.prompt_usage import count_used


@dataclass(frozen=True)
class PromptUsage:
    """What the two counters below add up to, and what the account is allowed."""

    used: int
    limit: int | None

    @property
    def allowed(self) -> bool:
        return self.limit is None or self.used < self.limit


async def read_usage(db: AsyncSession, user_id: uuid.UUID, max_prompts: int | None) -> PromptUsage:
    """Detections spent by this user, against their cap.

    ``max_prompts`` is passed in rather than re-queried: ``CurrentUser`` is the
    live ORM row, so every caller already holds it.
    """
    used = await count_used(db, user_id)

    return PromptUsage(used=used, limit=max_prompts)
