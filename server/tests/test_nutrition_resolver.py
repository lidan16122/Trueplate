"""The resolution ladder.

The tests that matter most here are the negative ones: what the resolver
*refuses* to write back is what keeps the shared ``foods`` table trustworthy.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.food import Food
from app.schemas.detection import DetectedFood
from app.services.nutrition import NutritionResolver, OpenFoodFactsClient, UsdaClient
from app.services.nutrition.open_food_facts import _is_relevant
from tests.fakes import nutrition_transport, usda_food


@pytest.fixture(autouse=True)
def usda_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "usda_fdc_api_key", "test-key-000000000000000000")


def _resolver(db: AsyncSession, transport: httpx.MockTransport) -> NutritionResolver:
    http = httpx.AsyncClient(transport=transport)
    return NutritionResolver(db, UsdaClient(http), OpenFoodFactsClient(http))


def _detected(label: str, terms: list[str], grams: float = 100.0, confidence: float = 0.9):
    return DetectedFood(
        label=label, estimated_grams=grams, confidence=confidence, search_terms=terms
    )


def _off_products(name: str, kcal: float) -> dict:
    return {
        "products": [
            {
                "code": "111",
                "product_name": name,
                "nutriments": {
                    "energy-kcal_100g": kcal,
                    "proteins_100g": 1.0,
                    "carbohydrates_100g": 20.0,
                    "fat_100g": 1.0,
                },
            }
        ]
    }


async def test_a_seeded_row_is_used_without_any_network_call(db_session: AsyncSession) -> None:
    db_session.add(Food(name="rolled oats", source="seed", kcal_per_100g=379.0))
    await db_session.flush()

    # Every route on this transport 404s or returns empty; a hit proves it never ran.
    resolver = _resolver(db_session, nutrition_transport())
    item = await resolver.resolve(_detected("oats", ["rolled oats"]))

    assert item.matched is not None
    assert item.matched.kcal_per_100g == 379.0
    assert item.is_rough is False


async def test_a_usda_match_is_written_back_for_next_time(db_session: AsyncSession) -> None:
    transport = nutrition_transport(usda=usda_food("Oats, rolled, dry", 371.0, fdc_id=172989))
    resolver = _resolver(db_session, transport)

    item = await resolver.resolve(_detected("oats", ["rolled oats dry"]))
    assert item.matched is not None
    assert item.is_rough is False

    stored = await db_session.scalar(select(Food).where(Food.name == "rolled oats dry"))
    assert stored is not None
    assert stored.source == "usda_fdc"
    assert stored.source_ref == "172989"
    assert stored.fetched_at is not None


async def test_an_open_food_facts_match_is_never_written_back(db_session: AsyncSession) -> None:
    """The regression this exists for: OFF ranks branded goods by loose text
    relevance, so "banana" can return banana chips at 360 kcal instead of the
    fruit at 89. A row like that, once cached, is served to everyone."""
    transport = nutrition_transport(
        usda={"foods": []}, off_search=_off_products("Banana Chips", 360.0)
    )
    resolver = _resolver(db_session, transport)

    item = await resolver.resolve(_detected("banana", ["banana"]))

    assert item.matched is not None
    assert item.matched.kcal_per_100g == 360.0
    # Shown, but visibly uncertain and correctable...
    assert item.is_rough is True
    assert item.confidence_label == "Rough guess"
    # ...and never frozen into the shared table.
    assert await db_session.scalar(select(func.count()).select_from(Food)) == 0


async def test_a_broader_term_resolves_but_is_flagged_as_approximate(
    db_session: AsyncSession,
) -> None:
    """Falling back down the ladder beats failing, provided the user can see it."""
    db_session.add(Food(name="rice", source="seed", kcal_per_100g=130.0))
    await db_session.flush()

    resolver = _resolver(db_session, nutrition_transport())
    item = await resolver.resolve(
        _detected("nonna's rice", ["nonna's special rice", "jasmine rice steamed", "rice"])
    )

    assert item.matched is not None
    assert item.matched.kcal_per_100g == 130.0
    assert item.is_rough is True


async def test_a_blocked_usda_key_degrades_instead_of_failing(db_session: AsyncSession) -> None:
    """USDA rate-limits per IP and blocks for an hour. Logging must not break."""
    transport = nutrition_transport(usda_status=429, off_search=_off_products("Oat Bar", 400.0))
    resolver = _resolver(db_session, transport)

    item = await resolver.resolve(_detected("oats", ["oats"]))

    assert item.matched is not None
    assert item.matched.source == "open_food_facts"


async def test_an_unresolvable_food_is_still_returned_for_manual_correction(
    db_session: AsyncSession,
) -> None:
    """Losing the whole meal because one sauce was unrecognisable is worse."""
    resolver = _resolver(db_session, nutrition_transport())
    item = await resolver.resolve(_detected("mystery sauce", ["mystery sauce"]))

    assert item.matched is None
    assert item.nutrition.calories == 0.0
    assert item.is_rough is True


async def test_low_model_confidence_keeps_a_match_out_of_the_cache(
    db_session: AsyncSession,
) -> None:
    transport = nutrition_transport(usda=usda_food("Oats, rolled", 371.0))
    resolver = _resolver(db_session, transport)

    await resolver.resolve(_detected("maybe oats", ["rolled oats"], confidence=0.4))

    assert await db_session.scalar(select(func.count()).select_from(Food)) == 0


async def test_variant_spellings_converge_on_one_row(db_session: AsyncSession) -> None:
    """Otherwise write-back accumulates near-duplicates and matching gets worse."""
    transport = nutrition_transport(usda=usda_food("Oats", 371.0))
    resolver = _resolver(db_session, transport)

    await resolver.resolve(_detected("oats", ["Rolled  Oats"]))
    await resolver.resolve(_detected("oats", ["rolled oats"]))

    rows = (await db_session.scalars(select(Food))).all()
    assert len(rows) == 1
    assert rows[0].name == "rolled oats"


async def test_a_stale_row_is_refetched_rather_than_trusted(db_session: AsyncSession) -> None:
    db_session.add(
        Food(
            name="rolled oats",
            source="usda_fdc",
            kcal_per_100g=1.0,
            fetched_at=datetime.now(UTC) - timedelta(days=settings.foods_ttl_days + 1),
        )
    )
    await db_session.flush()

    transport = nutrition_transport(usda=usda_food("Oats, rolled", 371.0))
    resolver = _resolver(db_session, transport)
    item = await resolver.resolve(_detected("oats", ["rolled oats"]))

    assert item.matched is not None
    assert item.matched.kcal_per_100g == 371.0


async def test_seeded_rows_never_expire(db_session: AsyncSession) -> None:
    """They are curated by hand and have no upstream to re-check."""
    db_session.add(Food(name="honey", source="seed", kcal_per_100g=304.0, fetched_at=None))
    await db_session.flush()

    resolver = _resolver(db_session, nutrition_transport())
    item = await resolver.resolve(_detected("honey", ["honey"]))

    assert item.matched is not None
    assert item.matched.kcal_per_100g == 304.0


@pytest.mark.parametrize(
    ("term", "name", "relevant"),
    [
        ("scrambled eggs", "Mayonnaise Classique", False),
        ("whole milk", "Perly", False),
        ("flat white coffee", "Fiocchi di latte", False),
        ("scrambled eggs", "Scrambled Egg Breakfast Wrap", True),
        ("black beans cooked", "Black Beans", True),
        ("greek yogurt plain", "Greek Style Yogurt", True),
    ],
)
def test_open_food_facts_answers_about_a_different_food_are_rejected(
    term: str, name: str, relevant: bool
) -> None:
    assert _is_relevant(term, name) is relevant


async def test_a_lost_write_back_race_does_not_discard_earlier_work(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The session is shared by the whole request and committed once at the end.

    A decomposed dish resolves several foods through `_write_back` in a loop, so
    rolling back the *transaction* to skip one duplicate would silently discard
    the write-backs for every food before it. Only the SAVEPOINT may unwind.
    """
    db_session.add(Food(name="already resolved", source="usda_fdc", kcal_per_100g=111.0))
    await db_session.flush()

    def explode(*_args, **_kwargs):
        raise IntegrityError("INSERT INTO foods", {}, Exception("duplicate key"))

    monkeypatch.setattr(db_session, "begin_nested", explode)

    transport = nutrition_transport(usda=usda_food("Oats, rolled", 371.0))
    item = await _resolver(db_session, transport).resolve(_detected("oats", ["rolled oats"]))

    # The losing insert still yields a usable match for this request...
    assert item.matched is not None
    # ...and the row written before it is untouched.
    survivor = await db_session.scalar(select(Food).where(Food.name == "already resolved"))
    assert survivor is not None, "an earlier write-back was rolled back by a later conflict"
    assert survivor.kcal_per_100g == 111.0


async def test_a_spurious_usda_400_is_retried_rather_than_lost(
    db_session: AsyncSession,
) -> None:
    """FDC's front end answers valid requests with a 400 about half the time.

    Without a retry the resolver degrades politely to Open Food Facts and the
    user simply gets a worse answer, with nothing anywhere saying why — so this
    pins the retry rather than the fallback.
    """
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "foods/search" not in request.url.path:
            return httpx.Response(404, json={})
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(400, text="<html>400 Bad Request</html>")
        return httpx.Response(200, json=usda_food("Avocado, raw", 160.0))

    item = await _resolver(db_session, httpx.MockTransport(handler)).resolve(
        _detected("avocado", ["avocado"])
    )

    assert attempts["n"] == 3, "should have retried past the spurious 400s"
    assert item.matched is not None
    assert item.matched.source == "usda_fdc"
    assert item.matched.kcal_per_100g == 160.0


async def test_a_real_rate_limit_is_not_retried(db_session: AsyncSession) -> None:
    """429 is per-IP and hour-long; hammering it extends the block."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "foods/search" in request.url.path:
            attempts["n"] += 1
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"products": []})

    await _resolver(db_session, httpx.MockTransport(handler)).resolve(
        _detected("avocado", ["avocado"])
    )

    assert attempts["n"] == 1, "429 must not be retried"
