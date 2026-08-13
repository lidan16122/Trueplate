"""Load development reference foods.

    uv run python -m scripts.seed

Idempotent: existing rows are updated in place rather than duplicated, so it is
safe to re-run after editing seed_data.py.
"""

import asyncio
import logging

from sqlalchemy import select

from app.db.models import Food
from app.db.seed_data import SEED_FOODS
from app.db.session import SessionLocal, engine
from app.enums import NutritionSource

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed")


async def seed_foods() -> None:
    created = updated = 0

    async with SessionLocal() as session:
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

        await session.commit()

    logger.info("Seeded foods: %d created, %d updated", created, updated)


async def main() -> None:
    try:
        await seed_foods()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
