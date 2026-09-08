"""The seed command's persistence is repeatable without requiring managed Postgres."""

from sqlalchemy import func, select

from app.db.models import Food
from app.db.seed_data import SEED_FOODS
from app.db.seeding import seed_reference_foods
from app.models.enums import NutritionSource


async def test_reseeding_updates_reference_rows_without_duplicating_them(db_session):
    created, updated = await seed_reference_foods(db_session)
    await db_session.commit()
    assert (created, updated) == (len(SEED_FOODS), 0)

    row = await db_session.scalar(select(Food).where(Food.source == NutritionSource.SEED))
    row.kcal_per_100g = 999
    await db_session.commit()

    created, updated = await seed_reference_foods(db_session)
    await db_session.commit()
    assert (created, updated) == (0, len(SEED_FOODS))
    assert await db_session.scalar(select(func.count()).select_from(Food)) == len(SEED_FOODS)
    assert row.kcal_per_100g == SEED_FOODS[row.name].kcal
