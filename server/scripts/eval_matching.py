"""Score which FDC row a search term resolves to, against recorded answers.

``probe_resolver`` says *whether* a term resolved. This says whether it resolved
to the **right thing**, which is a different and much harder question — and one
that was being answered by eye until a ranking change that fixed "curry sauce"
was caught regressing "potato cooked in curry" to *Sweet potato leaves*.

Two modes, and keeping them apart is the point:

    uv run --directory server python -m scripts.eval_matching --refresh
    uv run --directory server python -m scripts.eval_matching

``--refresh`` is the only part that touches the network: it fetches the raw
``/foods/search`` payload for every case and writes ``tests/fixtures``. A normal
run scores ``rank_foods`` over that fixture — instant, free and deterministic.
FDC answers roughly one request in six with a spurious 400 or 404, so an eval
that re-fetched would be measuring their edge instead of our ranking.

Expectations are written to survive an upstream revision: substrings that must
and must not appear in the description, plus a kcal band wide enough that a
recipe tweak does not fail the case. They pin *which food*, never which row.
"""

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.db.loop import psycopg_loop_factory
from app.services.nutrition import UsdaClient, close_http_client, get_http_client
from app.services.nutrition.usda import rank_foods

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "usda_search.json"

# The nutrient ids `_to_match` reads. Everything else in an FDC food is dropped
# before the fixture is written, which is the difference between a file someone
# will open and a megabyte of vitamin rows.
_KEPT_NUTRIENTS = frozenset({1008, 1003, 1004, 1005})


@dataclass(frozen=True)
class Case:
    """One search term and what a correct answer looks like."""

    term: str
    # Every one of these must appear in the matched description.
    include: tuple[str, ...] = ()
    # None of these may. This is where most of the value is: the failures are
    # confident wrong foods — a bratwurst for shredded chicken, curry *powder*
    # for a curry sauce — not near-misses within the right food.
    exclude: tuple[str, ...] = ()
    kcal: tuple[float, float] | None = None
    # Set when the honest answer is nothing at all, so the resolver widens to a
    # broader term instead of believing a confident stranger.
    expect_nothing: bool = False
    note: str = field(default="")


CASES: list[Case] = [
    # ---- the observed failures ----
    Case(
        "curry sauce",
        include=("curry",),
        exclude=("powder", "spice"),
        kcal=(30, 220),
        note="matched Spices, curry powder at 325",
    ),
    Case(
        "shredded cooked chicken",
        include=("chicken",),
        exclude=("bratwurst", "giblet", "gizzard", "patty", "sausage", "frankfurter"),
        kcal=(80, 260),
        note="matched Bratwurst, chicken, cooked",
    ),
    Case(
        "chicken drumstick cooked",
        include=("chicken", "drumstick"),
        exclude=("ostrich", "turkey"),
        kcal=(100, 260),
        note="a sibling term matched Ostrich, inside leg",
    ),
    # ---- currently correct: these must not regress ----
    Case("chicken leg roasted with skin", ("chicken", "leg"), ("turkey", "ostrich"), (140, 270)),
    Case("chicken drumstick curry cooked", ("chicken",), ("ostrich", "turkey"), (100, 260)),
    Case(
        "potato cooked in curry",
        ("potato",),
        ("sweet", "leaves", "chip", "crisp"),
        (50, 160),
        note="the token-overlap ranker regressed this to Sweet potato leaves",
    ),
    Case("scrambled eggs", ("egg", "scrambled"), ("frozen", "substitute"), (110, 230)),
    Case("boiled potato", ("potato",), ("sweet", "leaves", "chip"), (50, 140)),
    # ---- the ladder's broad rungs, where a wrong row does the most damage ----
    Case(
        "rice",
        include=("rice",),
        exclude=("cracker", "noodle", "cake", "chip", "drink"),
        kcal=(90, 400),
        note="cached as Rice crackers at 416 until it was deleted by hand",
    ),
    Case("white rice cooked", ("rice",), ("cracker", "noodle", "cake"), (90, 200)),
    Case("basmati rice steamed", ("rice",), ("cracker", "noodle", "cake"), (90, 220)),
    Case(
        "chicken",
        ("chicken",),
        # "meatless" seen live: a soy analogue is not the food someone
        # photographed, however well its name matches.
        ("bratwurst", "gizzard", "giblet", "meatless"),
        (80, 300),
    ),
    Case("potato", ("potato",), ("sweet", "chip", "crisp", "leaves"), (50, 200)),
    Case(
        "sauce",
        ("sauce",),
        # Same principle that started this round: a dry powder is not a
        # sauce. Kept as a visible known-miss rather than deleted — FDC has
        # no generic wet sauce, so every candidate here is a compromise, and
        # hiding that would make the score say more than it knows.
        ("powder", "mix", "dry"),
        (20, 400),
    ),
    # ---- the wider probe list, as a regression net ----
    Case("grilled chicken breast", ("chicken", "breast"), ("nugget", "patty"), (100, 260)),
    Case("roasted broccoli", ("broccoli",), (), (15, 130)),
    Case("greek yogurt plain", ("yogurt",), ("bar", "drink", "smoothie"), (35, 140)),
    Case(
        "ground beef cooked",
        ("beef",),
        # A rice dish containing beef is not ground beef. Added after a
        # ranking change scored "correct" while returning "Spanish rice with
        # ground beef" — the expectation was loose enough to miss it.
        ("rice", "spanish", "soup", "stew"),
        (140, 360),
    ),
    Case("extra virgin olive oil", ("oil",), (), (700, 950)),
    Case("whole milk", ("milk",), ("chocolate", "powder", "dry"), (30, 95)),
    Case("cheddar cheese", ("cheddar",), (), (280, 460)),
    Case("hummus", ("hummus",), (), (140, 360)),
    Case("avocado raw", ("avocado",), (), (110, 230)),
    Case("banana raw", ("banana",), ("chip", "bread", "pudding"), (60, 130)),
    Case("spaghetti cooked", ("spaghetti",), (), (90, 210)),
    Case("sweet potato baked", ("sweet potato",), ("leaves", "chip"), (60, 160)),
    Case("almonds raw", ("almond",), ("milk", "butter"), (490, 660)),
    Case("tomato pasta sauce", ("sauce",), ("powder", "spice"), (20, 180)),
    Case("black beans cooked", ("bean",), (), (50, 220)),
    Case("rolled oats dry", ("oat",), (), (300, 420)),
    Case("salmon fillet cooked", ("salmon",), (), (110, 280)),
]


# ----------------------------------------------------------------------
# Fixture
# ----------------------------------------------------------------------


def _slim(food: dict[str, Any]) -> dict[str, Any]:
    return {
        "fdcId": food.get("fdcId"),
        "description": food.get("description"),
        "dataType": food.get("dataType"),
        "brandName": food.get("brandName") or food.get("brandOwner"),
        "foodNutrients": [
            {"nutrientId": n.get("nutrientId"), "value": n.get("value")}
            for n in food.get("foodNutrients") or []
            if isinstance(n, dict) and n.get("nutrientId") in _KEPT_NUTRIENTS
        ],
    }


async def refresh() -> int:
    """Re-record every case's raw FDC response."""
    client = UsdaClient(get_http_client())
    if not client.configured:
        print("USDA_FDC_API_KEY is not set; nothing to record.")
        return 2

    recorded: dict[str, list[dict[str, Any]]] = {}
    if FIXTURE.exists():
        recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))

    failed = []
    for case in CASES:
        # Reaches past `search` on purpose: the fixture must hold what FDC sent,
        # not what today's ranking made of it, or refreshing would bake the
        # current ordering into the thing meant to judge it.
        response = await client._retrying_get(case.term)  # noqa: SLF001
        if response.status_code != 200:
            failed.append(f"{case.term} (HTTP {response.status_code})")
            continue
        foods = response.json().get("foods") or []
        recorded[case.term] = [_slim(f) for f in foods if isinstance(f, dict)]
        print(f"  recorded {len(recorded[case.term]):>2} results for {case.term!r}")

    await close_http_client()

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(recorded, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {FIXTURE} ({FIXTURE.stat().st_size / 1024:.0f} kB)")
    if failed:
        # Kept rather than blanked: a term FDC would not answer this minute is
        # still correctly recorded from last time.
        print(f"{len(failed)} term(s) failed and kept their previous recording:")
        for line in failed:
            print(f"  {line}")
    return 0


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------


def _kcal(food: dict[str, Any]) -> float | None:
    for nutrient in food.get("foodNutrients") or []:
        if nutrient.get("nutrientId") == 1008:
            value = nutrient.get("value")
            return float(value) if value is not None else None
    return None


def judge(case: Case, top: dict[str, Any] | None) -> str | None:
    """None when the case passes, else why it failed."""
    if top is None:
        return None if case.expect_nothing else "nothing matched"
    if case.expect_nothing:
        return f"expected nothing, got {top.get('description')!r}"

    name = (top.get("description") or "").lower()
    missing = [word for word in case.include if word not in name]
    if missing:
        return f"missing {missing}"
    present = [word for word in case.exclude if word in name]
    if present:
        return f"contains {present}"

    kcal = _kcal(top)
    if case.kcal is not None:
        if kcal is None:
            return "no energy value"
        low, high = case.kcal
        if not low <= kcal <= high:
            return f"{kcal:.0f} kcal outside {low:.0f}-{high:.0f}"
    return None


def score() -> int:
    if not FIXTURE.exists():
        print(f"No fixture at {FIXTURE}. Run with --refresh first.")
        return 2
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))

    passed, failures, unrecorded = 0, [], 0
    for case in CASES:
        foods = recorded.get(case.term)
        if foods is None:
            unrecorded += 1
            print(f"  ?  {case.term:<32} not in the fixture")
            continue

        ranked = rank_foods(case.term, foods)
        # Mirrors the resolver, which takes the first match carrying energy and
        # offers the rest as alternatives.
        top = next((f for f in ranked if _kcal(f) is not None), None)
        problem = judge(case, top)
        if problem is None:
            passed += 1
            name = (top or {}).get("description", "nothing")
            print(f"  ok {case.term:<32} {name[:44]}")
        else:
            name = (top or {}).get("description", "—")
            failures.append(case)
            print(f"  XX {case.term:<32} {name[:44]}")
            print(f"     {problem}" + (f"  [{case.note}]" if case.note else ""))

    total = len(CASES) - unrecorded
    print("-" * 88)
    print(f"{passed}/{total} correct" + (f"  ({unrecorded} unrecorded)" if unrecorded else ""))
    return 0 if not failures else 1


def main() -> int:
    if "--refresh" in sys.argv:
        return asyncio.run(refresh(), loop_factory=psycopg_loop_factory())
    return score()


if __name__ == "__main__":
    sys.exit(main())
