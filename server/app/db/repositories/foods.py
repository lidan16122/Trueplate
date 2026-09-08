"""Materialized food queries and concurrent write-back persistence."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.food import Food
from app.schemas.detection import NutritionMatch


async def by_name(db: AsyncSession, name: str) -> list[Food]:
    return list((await db.scalars(select(Food).where(func.lower(Food.name) == name))).all())


async def upsert(db: AsyncSession, name: str, match: NutritionMatch, now: datetime) -> Food | None:
    existing = await db.scalar(select(Food).where(Food.name == name, Food.source == match.source))
    if existing is not None:
        existing.kcal_per_100g = match.kcal_per_100g
        existing.protein_g_per_100g = match.protein_g_per_100g
        existing.carbs_g_per_100g = match.carbs_g_per_100g
        existing.fat_g_per_100g = match.fat_g_per_100g
        existing.brand = match.brand
        existing.source_ref = match.source_ref
        existing.fetched_at = now
        await db.flush()
        return existing

    row = Food(
        name=name,
        brand=match.brand,
        source=match.source,
        source_ref=match.source_ref,
        kcal_per_100g=match.kcal_per_100g,
        protein_g_per_100g=match.protein_g_per_100g,
        carbs_g_per_100g=match.carbs_g_per_100g,
        fat_g_per_100g=match.fat_g_per_100g,
        fetched_at=now,
    )
    try:
        # A SAVEPOINT, not the whole transaction. This session is shared by
        # the entire request and committed once at the end, and a decomposed
        # dish resolves several foods through here in a loop — so a bare
        # rollback on the fourth would silently discard the write-backs for
        # the first three, and leave the route committing a dead session.
        async with db.begin_nested():
            db.add(row)
    except IntegrityError:
        # Another request resolved the same term first. The unique index is
        # the backstop that makes this a lost race rather than a duplicate
        # row; re-read and use the winner.
        winner = await db.scalar(select(Food).where(Food.name == name, Food.source == match.source))
        if winner is not None:
            return winner
        return None

    return row
