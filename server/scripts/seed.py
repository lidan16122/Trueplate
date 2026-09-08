"""Load development reference foods.

    uv run python -m scripts.seed

Idempotent: existing rows are updated in place rather than duplicated, so it is
safe to re-run after editing seed_data.py.
"""

import asyncio
import logging

from app.db import transaction
from app.db.loop import psycopg_loop_factory
from app.db.seeding import seed_reference_foods
from app.db.session import SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed")


async def seed_foods() -> None:
    async with SessionLocal() as session:
        created, updated = await seed_reference_foods(session)

        await transaction.commit(session)

    logger.info("Seeded foods: %d created, %d updated", created, updated)


async def main() -> None:
    try:
        await seed_foods()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    # A bare `asyncio.run` here dies on Windows before the first query — see loop.py.
    asyncio.run(main(), loop_factory=psycopg_loop_factory())
