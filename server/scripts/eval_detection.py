"""Check whole-dish grouping with fresh model calls and an in-memory nutrition cache.

Run ``python -m scripts.eval_detection --runs 3`` for the text cases. Add
``--photo path/to/two-slices.jpg`` to check the original pizza photo as well.
This uses the configured paid model and public nutrition APIs, never the app database.
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass
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
    for food in case.foods:
        if not any(food in label for label in labels):
            failures.append(f"missing {food}")
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
        cases.append(Case("photo", "", ("pizza",), slices=2))
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
                            if case.name == "photo" and prepared is not None
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
    if not settings.anthropic_api_key or "..." in settings.anthropic_api_key:
        parser.error("configure ANTHROPIC_API_KEY before running the live evaluation")
    if args.photo is not None and not args.photo.is_file():
        parser.error("the photo path must refer to a local image")
    return asyncio.run(evaluate(args.runs, args.case, args.photo))


if __name__ == "__main__":
    raise SystemExit(main())
