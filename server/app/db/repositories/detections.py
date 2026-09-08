"""Completed detection payload storage; savepoints preserve sibling food write-backs."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.detection import Detection
from app.models.enums import DetectionMethod


async def get(db: AsyncSession, cache_key: str) -> Detection | None:
    return await db.get(Detection, cache_key)


async def delete(db: AsyncSession, row: Detection) -> None:
    await db.delete(row)


async def write_payload(
    db: AsyncSession, cache_key: str, kind: DetectionMethod, payload: dict
) -> None:
    existing = await db.get(Detection, cache_key)
    if existing is not None:
        existing.payload = payload
        return

    try:
        # A SAVEPOINT, not the request's transaction: this runs after the
        # resolver has already written foods rows on the same session, and the
        # route commits once at the end. Rolling the whole thing back to skip a
        # duplicate cache row would discard those write-backs.
        async with db.begin_nested():
            db.add(Detection(cache_key=cache_key, kind=kind, payload=payload))
    except IntegrityError:
        # Two identical photos landed at once. Whoever won stored the same
        # answer, so there is nothing to reconcile.
        pass
