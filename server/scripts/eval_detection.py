"""Check food grouping with fresh model calls and an in-memory nutrition cache.

Run ``python -m scripts.eval_detection --runs 3`` for the text cases. Use
``--photo path/to/meal.jpg --case topped_plate`` to check a photo against that
case's expected foods instead. Photos default to the two-slice pizza case.
This uses the configured paid model and public nutrition APIs, never the app database.
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.db.models.barcode import BarcodeProduct
from app.db.models.food import Food
from app.schemas.detection import FoodDetectionResponse
from app.services.detection import imaging
from app.services.detection.detector import PROMPT_FINGERPRINT, DetectionError, DetectionService
from app.services.nutrition import NutritionResolver, OpenFoodFactsClient, UsdaClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    foods: tuple[str, ...]
    slices: float | None = None
    grams: float | None = None


CASES = [
    Case("pizza", "Two slices of cheese pizza, 180 g total", ("pizza",), slices=2, grams=180),
    Case(
        "different_slices",
        "One cheese pizza slice and one pepperoni pizza slice",
        ("cheese", "pepperoni"),
    ),
    Case(
        "sides",
        "Cheese pizza with a separate green salad and a separate garlic dip",
        ("pizza", "salad", "dip"),
    ),
    Case(
        "rice_chicken", "Cooked rice beside a separate grilled chicken breast", ("rice", "chicken")
    ),
    Case("pasta_beef", "Cooked pasta beside a separate portion of grilled beef", ("pasta", "beef")),
    # Everyday descriptions should not need the word "separate" to preserve plate items.
    Case(
        "plate_with_sauce",
        "Rice with cooked chicken, tomato sauce and roasted potatoes",
        ("rice", "chicken", "sauce", "potato"),
    ),
    Case("chicken_rice", "Chicken with rice", ("chicken", "rice")),
    Case("chicken_sauce", "Grilled chicken breast with tomato sauce", ("chicken", "sauce")),
    Case(
        "topped_plate",
        "A plate of rice topped with cooked chicken and tomato sauce, with roasted potatoes",
        ("rice", "chicken", "sauce|gravy", "potato"),
    ),
    Case(
        "rice_bowl",
        "A chicken and rice bowl with roasted potatoes and garlic sauce",
        ("rice", "chicken", "potato", "sauce"),
    ),
    Case(
        "burger",
        "A hamburger with a bun, beef patty, cheese, lettuce and tomato",
        ("burger",),
    ),
    Case(
        "burger_sides",
        "A hamburger with fries and ketchup",
        ("burger", "fries", "ketchup"),
    ),
    Case(
        "burrito",
        "A beef burrito with rice, beans, cheese and salsa wrapped in a tortilla",
        ("burrito",),
    ),
    Case(
        "lasagna",
        "A portion of beef lasagna with pasta, ricotta, tomato sauce and cheese baked together",
        ("lasagna",),
    ),
    Case("apple", "One apple", ("apple",)),
]


def problems(case: Case, response: FoodDetectionResponse) -> list[str]:
    """Judge food grouping independently of whatever nutrition the live sources return."""
    labels = [item.detected.label.lower() for item in response.items]
    failures = []
    if len(labels) != len(case.foods):
        failures.append(f"expected {len(case.foods)} foods, got {len(labels)}")
    matched_indices = []
    for food in case.foods:
        matching = [
            index
            for index, label in enumerate(labels)
            if any(name in label for name in food.split("|"))
        ]
        if not matching:
            failures.append(f"missing {food}")
        else:
            matched_indices.append(matching[0])
    # A bundled "chicken and potatoes" label cannot satisfy two expected entries.
    if len(set(matched_indices)) != len(matched_indices):
        failures.append("bundled foods that should have separate portions")
    if response.is_provisional:
        failures.append("inconsistent inventory")
    if len(response.items) == 1:
        item = response.items[0].detected
        if case.slices is not None and (
            item.household_quantity != case.slices or item.household_unit != "slice"
        ):
            failures.append(f"expected {case.slices:g} slices")
        if case.grams is not None and item.estimated_grams != case.grams:
            failures.append("ignored the user's stated grams")
    return failures


async def evaluate(runs: int, selected: str | None, photo: Path | None) -> int:
    cases = [case for case in CASES if selected is None or case.name == selected]
    prepared = imaging.prepare_image(photo.read_bytes()) if photo is not None else None
    if prepared is not None:
        expected = next(case for case in CASES if case.name == (selected or "pizza"))
        # A text case's explicit grams say nothing about the photographed portion.
        cases = [replace(expected, name=f"photo_{expected.name}", grams=None)]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    failed, total = 0, 0
    print(
        f"model={settings.anthropic_model} effort={settings.anthropic_effort} "
        f"prompt={PROMPT_FINGERPRINT}",
        flush=True,
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all, tables=[Food.__table__, BarcodeProduct.__table__]
            )
        async with (
            async_sessionmaker(engine, expire_on_commit=False)() as db,
            httpx.AsyncClient(timeout=settings.nutrition_timeout_seconds) as http,
            AsyncAnthropic(
                api_key=settings.anthropic_api_key, timeout=settings.anthropic_timeout_seconds
            ) as client,
        ):
            resolver = NutritionResolver(db, UsdaClient(http), OpenFoodFactsClient(http))
            service = DetectionService(resolver, client=client)
            for case in cases:
                for run in range(1, runs + 1):
                    total += 1
                    try:
                        response = (
                            await service.detect_photo(prepared)
                            if prepared is not None
                            else await service.detect_text(case.text)
                        )
                    except DetectionError as error:
                        failed += 1
                        print(f"FAIL {case.name} {run}/{runs}: {type(error).__name__}", flush=True)
                        continue
                    errors = problems(case, response)
                    failed += bool(errors)
                    labels = ", ".join(item.detected.label for item in response.items)
                    verdict = "FAIL" if errors else "PASS"
                    print(
                        f"{verdict} {case.name} {run}/{runs}: {labels}; {'; '.join(errors)}",
                        flush=True,
                    )
                    for item in response.items:
                        logger.info(
                            "%s: %sg; terms=%s; matched=%s; source=%s",
                            item.detected.label,
                            item.detected.estimated_grams,
                            item.detected.search_terms,
                            item.matched.name if item.matched else None,
                            item.matched.source if item.matched else None,
                        )
    finally:
        await engine.dispose()
    print(f"{total - failed}/{total} grouping checks passed", flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--case", choices=[case.name for case in CASES])
    parser.add_argument("--photo", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    # HTTP request logs include USDA's query-string credential.
    logging.basicConfig(level=logging.WARNING)
    if args.verbose:
        logging.getLogger("app.services.detection.detector").setLevel(logging.INFO)
        logger.setLevel(logging.INFO)
    if not settings.anthropic_api_key or "..." in settings.anthropic_api_key:
        parser.error("configure ANTHROPIC_API_KEY before running the live evaluation")
    if args.photo is not None and not args.photo.is_file():
        parser.error("the photo path must refer to a local image")
    return asyncio.run(evaluate(args.runs, args.case, args.photo))


if __name__ == "__main__":
    raise SystemExit(main())
