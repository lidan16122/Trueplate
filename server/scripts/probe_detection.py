"""Run the photo path against a local image and print what came back.

``probe_resolver`` answers "does a list of search terms resolve to nutrition".
This answers the question one step upstream, and the harder one: **given this
photo, does the model find every component and weigh it sensibly.**

That question had no cheap way to be asked. Judging a prompt change meant
starting the server, signing in, and clicking through two screens, which is slow
enough that nobody does it more than once — so every prompt edit here has been
argued rather than measured. This makes it one command:

    uv run --directory server python -m scripts.probe_detection path/to/meal.jpg
    uv run --directory server python -m scripts.probe_detection meal.jpg "no oil"

It deliberately bypasses the route, so there is no auth, no rate limit, and
**no detection cache** — every run is a fresh reading, which is the point when
you are comparing two prompts against one photo.

Unlike ``probe_resolver`` this one calls the model: roughly $0.065 a run at
current Opus 5 rates. Run it against the same photo three times before believing
any single result — the failure this exists to catch is intermittent.
"""

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.db.loop import psycopg_loop_factory
from app.db.session import engine
from app.services import imaging
from app.services.detection import PROMPT_FINGERPRINT, DetectionError, DetectionService
from app.services.nutrition import (
    NutritionResolver,
    OpenFoodFactsClient,
    UsdaClient,
    close_http_client,
    get_http_client,
)


def _household(item) -> str:  # noqa: ANN001 - ResolvedFoodItem, kept loose for a script
    quantity = item.detected.household_quantity
    unit = item.detected.household_unit
    if quantity is None or unit is None:
        return "—"
    return f"{quantity:g} {unit}"


async def _probe(path: Path, note: str | None) -> int:
    raw = path.read_bytes()
    # The same preparation the route applies, so the model sees the pixels it
    # would see in production rather than the original phone capture.
    prepared = imaging.prepare_image(raw)

    print(f"image   {path.name}  {len(raw) / 1024:.0f} kB -> {len(prepared) / 1024:.0f} kB")
    print(f"model   {settings.anthropic_model}  effort={settings.anthropic_effort}")
    print(f"prompt  {PROMPT_FINGERPRINT}")
    if note:
        print(f"note    {note}")
    print()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    http = get_http_client()
    resolver_deps = (UsdaClient(http), OpenFoodFactsClient(http))

    try:
        async with session_factory() as db:
            service = DetectionService(NutritionResolver(db, *resolver_deps))
            try:
                response = await service.detect_photo(prepared, note=note)
            except DetectionError as exc:
                print(f"FAILED  {type(exc).__name__}: {exc}")
                return 1
            finally:
                # Commits whatever the resolver wrote back to `foods` even on a
                # failure part-way down the item list.
                await db.commit()
    finally:
        await close_http_client()
        await engine.dispose()

    # The model's own inventory, above the list it produced from it — the same
    # comparison the confirm screen now shows, and the fastest way to tell an
    # under-read plate from a genuinely simple one.
    print(f"saw     {response.meal_description}")
    if response.is_provisional:
        print("        PROVISIONAL — this reading would not be cached; resubmitting retries")
    print()
    print(f"{'#':<3} {'label':<32} {'grams':>6}  {'household':<12} {'kcal':>6}  source")
    print("-" * 104)
    for index, item in enumerate(response.items, start=1):
        matched = item.matched
        source = (
            f"{matched.source}: {matched.name[:38]}"
            if matched
            else "NO MATCH — dropped on save"
        )
        print(
            f"{index:<3} {item.detected.label[:32]:<32} "
            f"{item.detected.estimated_grams:>6.0f}  {_household(item):<12} "
            f"{item.nutrition.calories:>6.0f}  {source}"
        )
        # The terms are the whole input to the resolution ladder, so a bad match
        # is only diagnosable with them in front of you — printing the outcome
        # alone tells you something went wrong and nothing about where.
        print(f"{'':<3} └ terms: {' > '.join(item.detected.search_terms)}")
        if item.detected.portion_reasoning:
            print(f"{'':<3}   {item.detected.portion_reasoning[:92]}")

    grams = sum(i.detected.estimated_grams for i in response.items)
    print("-" * 104)
    print(
        f"{len(response.items)} item(s)   {grams:.0f} g total   "
        f"{response.totals.calories:.0f} kcal   "
        f"P{response.totals.protein_g:.0f} C{response.totals.carbs_g:.0f} "
        f"F{response.totals.fat_g:.0f}"
    )
    unresolved = sum(1 for i in response.items if i.matched is None)
    if unresolved:
        print(f"WARNING {unresolved} item(s) matched nothing and would not be saved")
    if response.notes:
        print(f"notes   {response.notes}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    # The service's own INFO line carries turn count, stop reason, token split
    # and cost — the numbers that say *why* a reading came back short. Silencing
    # them here would leave this script reporting the symptom and hiding the
    # cause it exists to expose.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "anthropic", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"No such image: {path}")
        return 2
    note = sys.argv[2] if len(sys.argv) > 2 else None
    return asyncio.run(_probe(path, note), loop_factory=psycopg_loop_factory())


if __name__ == "__main__":
    sys.exit(main())
