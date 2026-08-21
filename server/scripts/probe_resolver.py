"""Prove the resolution ladder against real upstreams, with no model involved.

The riskiest part of Add Food is not the vision call — it is whether a list of
search terms actually resolves to nutrition. USDA FoodData Central carries four
data types of differing completeness and mediocre search relevance, and Open
Food Facts is crowd-sourced, so coverage is an empirical question. This answers
it for the price of a few HTTP requests.

    uv run --directory server python -m scripts.probe_resolver

Prints one line per food and a hit rate at the end. Anything below roughly 90%
on this list means the ladder needs work before a prompt is worth tuning.
"""

import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.db.loop import psycopg_loop_factory
from app.db.session import engine
from app.schemas.detection import DetectedFood
from app.services.nutrition import (
    NutritionResolver,
    OpenFoodFactsClient,
    UsdaClient,
    close_http_client,
    get_http_client,
)

# Shaped the way the model is asked to emit them: most specific first, widening
# to a category the ladder can fall back to.
PROBES: list[tuple[str, list[str]]] = [
    ("grilled chicken breast", ["grilled chicken breast", "chicken breast cooked", "chicken"]),
    ("jasmine rice, cooked", ["jasmine rice steamed", "white rice cooked", "rice"]),
    ("roasted broccoli", ["roasted broccoli", "broccoli cooked", "broccoli"]),
    ("olive oil", ["extra virgin olive oil", "olive oil"]),
    ("greek yoghurt", ["greek yogurt plain", "yogurt greek", "yogurt"]),
    ("blueberries", ["blueberries raw", "blueberries"]),
    ("rolled oats", ["rolled oats dry", "oats", "oatmeal"]),
    ("honey", ["honey"]),
    ("salmon fillet", ["salmon fillet cooked", "atlantic salmon", "salmon"]),
    ("sourdough bread", ["sourdough bread", "bread white", "bread"]),
    ("avocado", ["avocado raw", "avocado"]),
    ("flat white", ["flat white coffee", "latte", "coffee with milk"]),
    ("almonds", ["almonds raw", "almonds"]),
    ("banana", ["banana raw", "banana"]),
    ("scrambled eggs", ["scrambled eggs", "eggs cooked", "egg"]),
    ("cheddar cheese", ["cheddar cheese", "cheese"]),
    ("spaghetti, cooked", ["spaghetti cooked", "pasta cooked", "pasta"]),
    ("tomato pasta sauce", ["tomato pasta sauce", "marinara sauce", "tomato sauce"]),
    ("ground beef", ["ground beef cooked", "minced beef", "beef"]),
    ("ricotta", ["ricotta cheese", "ricotta"]),
    ("hummus", ["hummus", "chickpea dip"]),
    ("sweet potato", ["sweet potato baked", "sweet potato"]),
    ("black beans", ["black beans cooked", "black beans"]),
    ("peanut butter", ["peanut butter", "peanut spread"]),
    ("whole milk", ["whole milk", "milk"]),
]


async def main() -> int:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    http = get_http_client()
    usda = UsdaClient(http)
    off = OpenFoodFactsClient(http)

    print(f"USDA key configured: {usda.configured}")
    print(f"Open Food Facts UA:  {settings.open_food_facts_user_agent}")
    print(f"{'food':<24} {'source':<18} {'kcal/100g':>9}  match")
    print("-" * 100)

    hits = 0
    async with session_factory() as db:
        resolver = NutritionResolver(db, usda, off)
        for label, terms in PROBES:
            item = await resolver.resolve(
                DetectedFood(
                    label=label,
                    estimated_grams=100,
                    confidence=0.9,
                    search_terms=terms,
                )
            )
            if item.matched is None:
                print(f"{label:<24} {'—':<18} {'—':>9}  MISS")
                continue
            hits += 1
            flag = " (rough)" if item.is_rough else ""
            print(
                f"{label:<24} {item.matched.source:<18} "
                f"{item.matched.kcal_per_100g:>9.1f}  {item.matched.name[:44]}{flag}"
            )
        await db.commit()

    await close_http_client()
    await engine.dispose()

    rate = hits / len(PROBES) * 100
    print("-" * 100)
    print(f"resolved {hits}/{len(PROBES)}  ({rate:.0f}%)")
    return 0 if rate >= 90 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(), loop_factory=psycopg_loop_factory()))
