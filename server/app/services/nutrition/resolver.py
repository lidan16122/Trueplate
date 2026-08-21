"""The resolution ladder: turn a detected food into a sourced nutrition row.

```
foods (cached)  ->  USDA FDC  ->  Open Food Facts  ->  unresolved
```

walked once per search term, most specific first. The model supplies
``["jasmine rice steamed", "white rice cooked", "rice"]``; the server walks down
until something hits.

The load-bearing idea is that **most foods do not need an exact match**. The
naming space of food is enormous and the nutritional space is small, so
"Nonna's Sunday gravy" resolving to "tomato pasta sauce" is a far better outcome
than failing — *provided the user can see that it was approximate and correct
it*. That is what ``is_rough`` and ``alternatives`` on the response are for, and
why a fall-back match is never presented as a confident one.

The model never contributes a number here. It contributes names; every figure
below is read from a database row or an upstream API and scaled by
``NutritionPer100gMixin.scaled_to``.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.food import Food
from app.enums import NutritionSource
from app.schemas.detection import (
    DetectedFood,
    NutritionFacts,
    NutritionMatch,
    ResolvedFoodItem,
)
from app.schemas.log import SURE_THRESHOLD
from app.services.nutrition.open_food_facts import OpenFoodFactsClient
from app.services.nutrition.usda import UsdaClient

logger = logging.getLogger(__name__)

# Curated rows beat fetched ones, and a fresher fetch beats a staler one. Any
# deterministic order would do; the point is that two identical lookups must not
# return different foods.
_SOURCE_RANK = {
    NutritionSource.SEED: 0,
    NutritionSource.USDA_FDC: 1,
    NutritionSource.OPEN_FOOD_FACTS: 2,
    NutritionSource.MANUAL: 3,
}

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class _Hit:
    """What one rung returned, and whether its key was precise enough to trust.

    ``precise`` travels with the match because it is the rung's property, not the
    match's: the same nutrition figures are trustworthy arriving from a barcode
    and a guess arriving from a free-text search.
    """

    match: NutritionMatch
    alternatives: list[NutritionMatch]
    precise: bool


def _as_utc(value: datetime) -> datetime:
    """Force a timestamp into UTC-aware form.

    Postgres hands back an aware datetime for ``DateTime(timezone=True)``;
    SQLite, which the test suite runs on, hands back a naive one for the same
    column. Comparing the two raises, so every read normalises here rather than
    at each call site.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def canonical_term(term: str) -> str:
    """The form a term is stored and looked up under.

    Lowercased and whitespace-collapsed so ``"Jasmine Rice"`` and
    ``"jasmine  rice"`` are one row rather than two. This is what makes
    write-back converge instead of accumulating near-duplicates.
    """
    return _WHITESPACE.sub(" ", term.strip()).lower()


def _facts(match: NutritionMatch | None, grams: float) -> NutritionFacts:
    """Scale a per-100 g match to the portion. Zeroes when nothing matched."""
    if match is None:
        return NutritionFacts(calories=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0)
    factor = grams / 100.0
    return NutritionFacts(
        calories=match.kcal_per_100g * factor,
        protein_g=match.protein_g_per_100g * factor,
        carbs_g=match.carbs_g_per_100g * factor,
        fat_g=match.fat_g_per_100g * factor,
    )


def _match_from_row(row: Food) -> NutritionMatch:
    return NutritionMatch(
        food_id=str(row.id),
        name=row.name,
        brand=row.brand,
        source=row.source,
        source_ref=row.source_ref,
        kcal_per_100g=row.kcal_per_100g,
        protein_g_per_100g=row.protein_g_per_100g,
        carbs_g_per_100g=row.carbs_g_per_100g,
        fat_g_per_100g=row.fat_g_per_100g,
    )


class NutritionResolver:
    def __init__(
        self,
        db: AsyncSession,
        usda: UsdaClient,
        open_food_facts: OpenFoodFactsClient,
    ) -> None:
        self._db = db
        self._usda = usda
        self._off = open_food_facts

    # ------------------------------------------------------------------
    # The ladder
    # ------------------------------------------------------------------

    async def resolve(self, detected: DetectedFood) -> ResolvedFoodItem:
        terms = [t for t in (detected.search_terms or []) if t and t.strip()]
        if not terms:
            # The schema requires search_terms but not that it be non-empty, and
            # the label is always a usable query.
            terms = [detected.label]

        for index, term in enumerate(terms):
            hit = await self._resolve_term(term)
            if hit is None:
                continue
            match = hit.match

            # Anything below the first term is an approximation by construction:
            # the model's most specific description did not resolve, so what we
            # found is broader than what the user ate.
            fell_back = index > 0
            is_rough = fell_back or not hit.precise or detected.confidence < SURE_THRESHOLD

            if not is_rough:
                # Only a first-term, confident match *from a precise rung* earns a
                # place in the shared table. A wrong row written back is served to
                # every future lookup and nobody ever sees it happen.
                match = await self._write_back(term, match)

            return ResolvedFoodItem(
                detected=detected,
                matched=match,
                nutrition=_facts(match, detected.estimated_grams),
                alternatives=hit.alternatives,
                confidence_label="Rough guess" if is_rough else "Fairly sure",
                is_rough=is_rough,
            )

        # Every rung missed. The item is still returned so the user can log it and
        # correct it by hand — losing the whole meal because one sauce was
        # unrecognisable would be a worse failure than a zero.
        logger.info("No nutrition match for %r (terms: %s)", detected.label, terms)
        return ResolvedFoodItem(
            detected=detected,
            matched=None,
            nutrition=_facts(None, detected.estimated_grams),
            alternatives=[],
            confidence_label="Rough guess",
            is_rough=True,
        )

    async def _resolve_term(self, term: str) -> _Hit | None:
        """One rung of the ladder for one term: cache, then USDA, then OFF.

        The ``precise`` flag on the result is what decides whether a match may be
        written back, and it is a property of the *rung*, not of the model's
        confidence. The two are genuinely different claims: the model can be
        certain it saw a banana while the source we matched it against is a bag
        of banana chips.
        """
        cached = await self._lookup_cached(term)
        if cached is not None:
            # Already vetted — it only got into the table by passing this same gate.
            return _Hit(cached, [], precise=True)

        usda_matches = await self._usda.search(term)
        if usda_matches:
            # FoodData Central is a curated food database searched by name. A
            # top hit here is real evidence about a generic food.
            return _Hit(usda_matches[0], usda_matches[1:], precise=True)

        off_matches = await self._off.search(term)
        if off_matches:
            # Open Food Facts is excellent by barcode and weak by name: the
            # corpus is branded packaged goods, so "banana" can rank banana
            # chips (360 kcal) above the fruit (89), and nothing in the response
            # says which you got. Useful as a last resort before nothing at all,
            # never trustworthy enough to freeze into the shared table — so
            # these always surface as "Rough guess" with alternatives to swap to.
            return _Hit(off_matches[0], off_matches[1:], precise=False)

        return None

    # ------------------------------------------------------------------
    # The foods table
    # ------------------------------------------------------------------

    async def _lookup_cached(self, term: str) -> NutritionMatch | None:
        """Read ``foods`` case-insensitively, ignoring rows that have gone stale."""
        rows = (
            await self._db.scalars(
                select(Food).where(func.lower(Food.name) == canonical_term(term))
            )
        ).all()
        if not rows:
            return None

        fresh = [r for r in rows if self._is_fresh(r)]
        if not fresh:
            # Every copy is past its TTL. Returning None sends the caller upstream
            # for a current figure, and the refetch overwrites the stale row.
            return None

        fresh.sort(
            key=lambda r: (
                _SOURCE_RANK.get(r.source, 99),
                # Postgres and SQLite disagree on NULL ordering, so normalise here
                # rather than in SQL.
                -_as_utc(r.fetched_at or datetime.min).timestamp(),
            )
        )
        return _match_from_row(fresh[0])

    def _is_fresh(self, row: Food) -> bool:
        # Seeded rows are curated by hand and have no upstream to re-check, so
        # they never expire. Only fetched rows carry a TTL.
        if row.source == NutritionSource.SEED or row.fetched_at is None:
            return True
        age = datetime.now(UTC) - _as_utc(row.fetched_at)
        return age < timedelta(days=settings.foods_ttl_days)

    async def _write_back(self, term: str, match: NutritionMatch) -> NutritionMatch:
        """Persist a resolved food so the next lookup is a database hit.

        Stored under the **canonical search term that resolved**, not the user's
        phrasing and not the upstream's own description. That is what lets
        "mom's lasagna" and "lasagna" converge on one row instead of
        accumulating five near-identical ones and making later matching worse.
        The user's own wording is display-only and lives in ``food_entries.name``.
        """
        name = canonical_term(term)
        now = datetime.now(UTC)

        existing = await self._db.scalar(
            select(Food).where(Food.name == name, Food.source == match.source)
        )
        if existing is not None:
            existing.kcal_per_100g = match.kcal_per_100g
            existing.protein_g_per_100g = match.protein_g_per_100g
            existing.carbs_g_per_100g = match.carbs_g_per_100g
            existing.fat_g_per_100g = match.fat_g_per_100g
            existing.brand = match.brand
            existing.source_ref = match.source_ref
            existing.fetched_at = now
            await self._db.flush()
            return _match_from_row(existing)

        row = Food(
            name=name,
            brand=match.brand,
            source=match.source,
            source_ref=match.source_ref,
            kcal_per_100g=match.kcal_per_100g,
            protein_g_per_100g=match.protein_g_per_100g,
            carbs_g_per_100g=match.carbs_g_per_100g,
            fat_g_per_100g=match.fat_g_per_100g,
            fetched_at=now,
        )
        self._db.add(row)
        try:
            await self._db.flush()
        except IntegrityError:
            # Another request resolved the same term first. The unique index is
            # the backstop that makes this a lost race rather than a duplicate
            # row; re-read and use the winner.
            await self._db.rollback()
            winner = await self._db.scalar(
                select(Food).where(Food.name == name, Food.source == match.source)
            )
            if winner is not None:
                return _match_from_row(winner)
            return match

        return _match_from_row(row)
