"""Check food grouping with fresh model calls and an in-memory nutrition cache.

Run ``python -m scripts.eval_detection --runs 3`` for the text cases. Use
``--photo path/to/meal.jpg --case topped_plate`` to check a photo against that
case's expected foods instead. Photos default to the two-slice pizza case.
Use ``--image-edges 1568 1280 1024 --report comparison.json`` with a photo to
compare complete detections, including grounded explanations. ``--images-only``
compares encoded dimensions and bytes offline without any API calls.
Live runs use the configured paid model and public nutrition APIs, never the app database.
"""

import argparse
import asyncio
import json
import logging
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db.base import Base
from app.db.models.barcode import BarcodeProduct
from app.db.models.food import Food
from app.schemas.detection import FoodDetectionResponse
from app.services.detection import imaging
from app.services.detection.detector import PROMPT_FINGERPRINT, DetectionError, DetectionService
from app.services.grounding import GroundedResponseService
from app.services.model_usage import ModelUsage
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


async def _measure_run(service, grounding, case: Case, raw: bytes | None, run: int) -> dict:
    """Include failed runs and the second model pass so smaller images cannot hide extra work."""
    detection_usage, grounding_usage = ModelUsage(), ModelUsage()
    started = perf_counter()
    row = {"case": case.name, "run": run}
    try:
        response = (
            await service.detect_photo(raw, usage=detection_usage)
            if raw is not None
            else await service.detect_text(case.text, usage=detection_usage)
        )
        grounded = await grounding.generate(response, usage=grounding_usage)
        row.update(
            errors=problems(case, response),
            provisional=response.is_provisional,
            unresolved=sum(item.matched is None for item in response.items),
            grounding_status=grounded.status,
            foods=[
                {"label": item.detected.label, "grams": item.detected.estimated_grams}
                for item in response.items
            ],
        )
    except DetectionError as error:
        row["errors"] = [type(error).__name__]
    row.update(
        seconds=round(perf_counter() - started, 3),
        detection=asdict(detection_usage),
        grounding=asdict(grounding_usage),
        total_input=detection_usage.total_input + grounding_usage.total_input,
        total_output=detection_usage.output + grounding_usage.output,
    )
    verdict = "FAIL" if row["errors"] else "PASS"
    print(f"{verdict} {case.name} run={run}: {json.dumps(row)}", flush=True)
    return row


async def evaluate(
    runs: int,
    selected: str | None,
    photo: Path | None,
    *,
    edges: list[int] | None = None,
    qualities: list[int] | None = None,
    images_only: bool = False,
    report: Path | None = None,
) -> int:
    cases = [case for case in CASES if selected is None or case.name == selected]
    raw = photo.read_bytes() if photo is not None else None
    if raw is not None:
        expected = next(case for case in CASES if case.name == (selected or "pizza"))
        # A text case's explicit grams say nothing about the photographed portion.
        cases = [replace(expected, name=f"photo_{expected.name}", grams=None)]
    original_edge = settings.detect_image_max_edge_px
    original_quality = settings.detect_image_jpeg_quality
    profiles = [
        (edge, quality)
        for quality in (qualities or [original_quality])
        for edge in (edges or [original_edge])
    ]
    results = {
        "model": settings.anthropic_model,
        "effort": settings.anthropic_effort,
        "prompt": PROMPT_FINGERPRINT,
        "preprocessing": imaging.PREPROCESSING_VERSION,
        "crop_max_edge": settings.detect_image_crop_max_edge_px,
        "images_only": images_only,
        "profiles": [],
    }
    # Offline comparisons need neither an engine nor an external client.
    engine = None if images_only else create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        if engine is not None:
            async with engine.begin() as connection:
                await connection.run_sync(
                    Base.metadata.create_all, tables=[Food.__table__, BarcodeProduct.__table__]
                )
        for edge, quality in profiles:
            settings.detect_image_max_edge_px = edge
            settings.detect_image_jpeg_quality = quality
            profile = {"max_edge": edge, "jpeg_quality": quality, "runs": []}
            results["profiles"].append(profile)
            if raw is not None:
                prepared = await run_in_threadpool(imaging.prepare_image, raw)
                profile["original"] = await run_in_threadpool(imaging.image_stats, raw)
                profile["prepared"] = await run_in_threadpool(imaging.image_stats, prepared)
            print(json.dumps({key: value for key, value in profile.items() if key != "runs"}))
            if engine is None:
                continue
            async with (
                async_sessionmaker(engine, expire_on_commit=False)() as db,
                httpx.AsyncClient(timeout=settings.nutrition_timeout_seconds) as http,
                AsyncAnthropic(
                    api_key=settings.anthropic_api_key, timeout=settings.anthropic_timeout_seconds
                ) as client,
            ):
                resolver = NutritionResolver(db, UsdaClient(http), OpenFoodFactsClient(http))
                service = DetectionService(resolver, client=client)
                grounding = GroundedResponseService(client=client)
                for case in cases:
                    for run in range(1, runs + 1):
                        profile["runs"].append(
                            await _measure_run(service, grounding, case, raw, run)
                        )
    finally:
        settings.detect_image_max_edge_px = original_edge
        settings.detect_image_jpeg_quality = original_quality
        if engine is not None:
            await engine.dispose()
        if report is not None:
            report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    measured_runs = [row for profile in results["profiles"] for row in profile["runs"]]
    failed = sum(bool(row["errors"]) for row in measured_runs)
    if not images_only:
        print(
            f"{len(measured_runs) - failed}/{len(measured_runs)} grouping checks passed", flush=True
        )
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--case", choices=[case.name for case in CASES])
    parser.add_argument("--photo", type=Path)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--image-edges", type=int, nargs="+", help="Compare overview sizes serially"
    )
    parser.add_argument("--jpeg-qualities", type=int, nargs="+", help="Compare JPEG byte sizes")
    parser.add_argument(
        "--images-only", action="store_true", help="Offline resize only; no API calls"
    )
    parser.add_argument("--report", type=Path, help="Save dimensions, all runs, and usage as JSON")
    args = parser.parse_args()
    if (args.image_edges or args.jpeg_qualities or args.images_only) and args.photo is None:
        parser.error("image comparisons require --photo")
    if args.image_edges and any(not 28 <= edge <= 2576 for edge in args.image_edges):
        parser.error("image edges must be between 28 and 2576")
    if args.jpeg_qualities and any(not 1 <= quality <= 95 for quality in args.jpeg_qualities):
        parser.error("JPEG qualities must be between 1 and 95")
    # HTTP request logs include USDA's query-string credential.
    logging.basicConfig(level=logging.WARNING)
    if args.verbose:
        logging.getLogger("app.services.detection.detector").setLevel(logging.INFO)
        logger.setLevel(logging.INFO)
    if not args.images_only and (
        not settings.anthropic_api_key or "..." in settings.anthropic_api_key
    ):
        parser.error("configure ANTHROPIC_API_KEY before running the live evaluation")
    if args.photo is not None and not args.photo.is_file():
        parser.error("the photo path must refer to a local image")
    return asyncio.run(
        evaluate(
            args.runs,
            args.case,
            args.photo,
            edges=args.image_edges,
            qualities=args.jpeg_qualities,
            images_only=args.images_only,
            report=args.report,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
