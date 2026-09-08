"""Idempotent persistence of development reference foods.

The command owns the session and commit so this operation is also usable against
the test database without opening a connection to a configured environment.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Food
from app.db.seed_data import SEED_FOODS
from app.models.enums import NutritionSource


async def seed_reference_foods(session: AsyncSession) -> tuple[int, int]:
    created = updated = 0
    for name, nutrition in SEED_FOODS.items():
        existing = await session.scalar(
            select(Food).where(Food.name == name, Food.source == NutritionSource.SEED)
        )
        if existing is None:
            session.add(
                Food(
                    name=name,
                    kcal_per_100g=nutrition.kcal,
                    protein_g_per_100g=nutrition.protein_g,
                    carbs_g_per_100g=nutrition.carbs_g,
                    fat_g_per_100g=nutrition.fat_g,
                    source=NutritionSource.SEED,
                )
            )
            created += 1
        else:
            existing.kcal_per_100g = nutrition.kcal
            existing.protein_g_per_100g = nutrition.protein_g
            existing.carbs_g_per_100g = nutrition.carbs_g
            existing.fat_g_per_100g = nutrition.fat_g
            updated += 1

    return created, updated
