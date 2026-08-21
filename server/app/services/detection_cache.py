"""Content-addressed cache for completed detections, in Postgres.

A vision call is the most expensive thing this app does. Re-submitting the same
photo — a retry after a dropped connection, the same packaged breakfast every
morning — must not pay for it twice. ``FoodDetectionResponse.cached`` exists to
tell the user when it did not.

Postgres rather than Redis: the Redis instance here is small and reserved for
refresh-token families and rate-limit counters, and this payload is large and
long-lived. ``food_entries.image_hash`` cannot serve the same purpose — it only
covers meals that were actually *logged*, and the expensive case is a detection
the user abandoned before confirming.
"""

import hashlib
import logging
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.detection import Detection
from app.enums import DetectionMethod, MealType
from app.schemas.detection import FoodDetectionResponse

logger = logging.getLogger(__name__)


def hash_image(data: bytes) -> str:
    """Content address for an image.

    Content-based rather than per-user: the same photo yields the same foods
    whoever uploaded it, and sharing the entry across users is the whole saving.
    Nothing user-identifying is stored under the key — only the detected foods.

    Deliberately depends on the bytes and nothing else, because this value is
    also ``food_entries.image_hash`` — the key that groups one photo's entries
    together. Folding the model or prompt into it would make that grouping
    change under a config edit. The *cache* key is derived separately, below.
    """
    return hashlib.sha256(data).hexdigest()


def photo_cache_key(image_hash: str) -> str:
    """Cache key for a photo detection.

    The model id and effort are folded in for the same reason they are on the
    text path: they change the answer. Keying the cache on image bytes alone
    would keep serving a pre-upgrade reading of a meal to anyone who had
    already logged it, with no way to invalidate short of emptying the table.
    """
    return _key(image_hash, settings.anthropic_model, settings.anthropic_effort)


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def hash_text(description: str, meal_type: MealType | None) -> str:
    """Content address for a typed description.

    Normalised so trivial differences in spacing or case share an entry. The
    model id and effort are folded in because a change to either changes the
    answer — without them, tuning the prompt would keep serving the old result
    until every entry aged out.
    """
    normalized = " ".join(description.lower().split())
    return _key(
        normalized,
        str(meal_type or ""),
        settings.anthropic_model,
        settings.anthropic_effort,
    )


async def read(db: AsyncSession, cache_key: str) -> FoodDetectionResponse | None:
    """The stored response, or None on a miss.

    A payload that no longer validates is treated as a miss rather than an
    error: the schema moved on, and re-detecting is always correct where
    deserialising a stale shape is not.
    """
    row = await db.get(Detection, cache_key)
    if row is None:
        return None

    # Postgres returns an aware datetime for DateTime(timezone=True); SQLite,
    # which the suite runs on, returns a naive one for the same column.
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if datetime.now(UTC) - created > timedelta(days=settings.detections_ttl_days):
        # Expired rather than wrong. Deleting it here keeps the table from
        # growing without bound, since nothing else ever prunes it.
        await db.delete(row)
        return None

    try:
        response = FoodDetectionResponse.model_validate(row.payload)
    except ValidationError:
        logger.info("Discarding unparseable cached detection %s", cache_key[:12])
        await db.delete(row)
        return None

    # Flag it, so the client can say the meal was recognised without a new call.
    return response.model_copy(update={"cached": True})


async def write(
    db: AsyncSession,
    cache_key: str,
    kind: DetectionMethod,
    response: FoodDetectionResponse,
) -> None:
    """Store a completed detection. Never raises — a cache is an optimisation."""
    existing = await db.get(Detection, cache_key)
    if existing is not None:
        existing.payload = response.model_dump(mode="json")
        return

    try:
        # A SAVEPOINT, not the request's transaction: this runs after the
        # resolver has already written foods rows on the same session, and the
        # route commits once at the end. Rolling the whole thing back to skip a
        # duplicate cache row would discard those write-backs.
        async with db.begin_nested():
            db.add(
                Detection(
                    cache_key=cache_key, kind=kind, payload=response.model_dump(mode="json")
                )
            )
    except IntegrityError:
        # Two identical photos landed at once. Whoever won stored the same
        # answer, so there is nothing to reconcile.
        pass
