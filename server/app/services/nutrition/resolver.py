"""The resolution ladder: turn a detected food into a sourced nutrition row.

```
every term:  foods (cached)  ->  barcode_products  ->  USDA FDC
then:        every term again, against Open Food Facts
then:        unresolved
```

The model supplies ``["jasmine rice steamed", "white rice cooked", "rice"]``,
most specific first, and the server walks down until something hits.

**Open Food Facts is a second pass, not a fourth rung**, and that ordering is
load-bearing. It answers nearly any free-text query with a branded near-miss, so
consulted per rung it beats the broader term a whole-food source would have
answered properly — the specific query wins purely for being asked first. Every
term therefore gets the trustworthy sources before any term gets OFF.

The load-bearing idea is that **most foods do not need an exact match**. The
naming space of food is enormous and the nutritional space is small, so
"Nonna's Sunday gravy" resolving to "tomato pasta sauce" is a far better outcome
than failing — *provided the user can see that it was approximate and correct
it*. That is what ``is_rough`` and ``alternatives`` on the response are for, and
why a fall-back match is never presented as a confident one.

There is deliberately no separate "generic category" rung. The model's own
broadest search term *is* that rung — it is asked for a widening ladder ending
in a category ("…, 'rice'"), so a hand-built food taxonomy here would duplicate
something already in the request and immediately start drifting from it.

The model never contributes a number here. It contributes names; every figure
below is read from a database row or an upstream API and scaled by
``NutritionFacts.for_portion``.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import as_utc
from app.db.models.barcode import BarcodeProduct
from app.db.models.food import Food
from app.enums import NutritionSource
from app.schemas.detection import (
    DetectedFood,
    NutritionFacts,
    NutritionMatch,
    ResolvedFoodItem,
)
from app.schemas.log import SURE_THRESHOLD
from app.services.nutrition import matches
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


def _usable(match: NutritionMatch | None) -> NutritionMatch | None:
    """Drop a match whose figures cannot describe food, so the ladder widens.

    Every source funnels through the two pass methods below, which is why the
    check sits here rather than in each client: a stored row, a scanned product
    and a fetched one are all capable of carrying a unit error.

    Dropping beats clamping. A clamped figure is silently wrong and gets saved;
    a dropped one sends the resolver to the next rung, where there is usually a
    real answer. It also keeps `FoodEntryCreate`'s bounds from rejecting the
    user's entire meal at save time over one bad row.
    """
    if match is None or not matches.is_plausible(match):
        return None
    return match


def canonical_term(term: str) -> str:
    """The form a term is stored and looked up under.

    Lowercased and whitespace-collapsed so ``"Jasmine Rice"`` and
    ``"jasmine  rice"`` are one row rather than two. This is what makes
    write-back converge instead of accumulating near-duplicates.
    """
    return _WHITESPACE.sub(" ", term.strip()).lower()


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

        # Two passes over the same ladder, and the order *between* them is the
        # point. Open Food Facts is a barcode database searched by name: it
        # answers nearly anything, usually with a branded near-miss. Asked once
        # per rung it wins on the model's most *specific* term — "basmati rice
        # steamed" resolving to a packaged microwave rice at 70 kcal/100 g —
        # and the broader rung a whole-food source would have answered properly
        # is never reached, because the loop has already returned.
        #
        # So every rung gets the whole-food sources before any rung gets OFF. A
        # weak branded guess can then only ever lose to a real match, never
        # outrank one for being more literally worded. This matters more the
        # more finely a meal is decomposed, since each extra component arrives
        # with its own narrow first term.
        for index, term in enumerate(terms):
            hit = await self._resolve_precise(term)
            if hit is not None:
                return await self._resolved(detected, hit, term, fell_back=index > 0)

        for index, term in enumerate(terms):
            hit = await self._resolve_fallback(term)
            if hit is not None:
                return await self._resolved(detected, hit, term, fell_back=index > 0)

        # Every rung missed. The item is still *returned* — the confirm screen
        # shows it, warns, and lets the user delete it — but it carries no
        # nutrition, and `Confirm.save()` therefore leaves it out of the meal.
        #
        # Saying "so the user can correct it by hand" here would be a comment
        # describing a feature that does not exist: correcting it by hand needs
        # a manual-nutrition form, and an honest one takes four per-100 g fields
        # rather than a calorie box, or the macro bars silently under-report the
        # day. `NutritionSource.MANUAL` is reserved for it; the UI is not built.
        logger.info("No nutrition match for %r (terms: %s)", detected.label, terms)
        return ResolvedFoodItem(
            detected=detected,
            matched=None,
            nutrition=NutritionFacts.for_portion(None, detected.estimated_grams),
            alternatives=[],
            confidence_label="Rough guess",
            is_rough=True,
        )

    async def _resolve_precise(self, term: str) -> _Hit | None:
        """The whole-food rungs for one term: our table, a scanned product, USDA.

        The ``precise`` flag on the result is what decides whether a match may be
        written back, and it is a property of the *rung*, not of the model's
        confidence. The two are genuinely different claims: the model can be
        certain it saw a banana while the source we matched it against is a bag
        of banana chips.
        """
        cached = _usable(await self._lookup_cached(term))
        if cached is not None:
            # Already vetted — it only got into the table by passing this same gate.
            return _Hit(cached, [], precise=True)

        scanned = _usable(await self._lookup_barcode_product(term))
        if scanned is not None:
            # Something previously scanned by name. The row got there through an
            # exact UPC, so the figures are as good as a barcode's — but the
            # *name* match that found it here is not, so this is not `precise`
            # and never earns a write-back into `foods`. It stays in this pass
            # regardless: a locally scanned product is a far better answer than
            # a free-text search of every packaged good on earth.
            return _Hit(scanned, [], precise=False)

        usda_matches = [m for m in await self._usda.search(term) if matches.is_plausible(m)]
        if usda_matches:
            # FoodData Central is a curated food database searched by name. A
            # top hit here is real evidence about a generic food.
            return _Hit(usda_matches[0], usda_matches[1:], precise=True)

        return None

    async def _resolve_fallback(self, term: str) -> _Hit | None:
        """Open Food Facts, reached only once every rung above has missed.

        Excellent by barcode and weak by name: the corpus is branded packaged
        goods, so "banana" can rank banana chips (360 kcal) above the fruit (89),
        and nothing in the response says which you got. Useful as a last resort
        before nothing at all, never trustworthy enough to freeze into the shared
        table — so these always surface as "Rough guess" with alternatives to
        swap to.
        """
        off_matches = [m for m in await self._off.search(term) if matches.is_plausible(m)]
        if off_matches:
            return _Hit(off_matches[0], off_matches[1:], precise=False)
        return None

    async def _resolved(
        self, detected: DetectedFood, hit: _Hit, term: str, *, fell_back: bool
    ) -> ResolvedFoodItem:
        """Turn a hit into the row the confirm screen shows, writing back if earned.

        ``fell_back`` says the model's most specific description did not resolve,
        so what we found is broader than what the user actually ate — an
        approximation by construction, whichever source supplied it.
        """
        match = hit.match

        # What the *user* is shown. SURE_THRESHOLD is the display split, and
        # lives in schemas/log.py so the confirm screen and the day view
        # collapse a confidence float to the same two words.
        is_rough = fell_back or not hit.precise or detected.confidence < SURE_THRESHOLD

        # What enters the *shared table* — a separate decision with a separate
        # floor, because the two answer different questions. "Is this worth
        # warning one user about" is not "is this worth serving to every future
        # user", and the second deserves its own dial.
        trustworthy = (
            hit.precise
            and not fell_back
            and detected.confidence >= settings.foods_writeback_min_confidence
        )
        if trustworthy:
            # A wrong row written back is served to every future lookup and
            # nobody ever sees it happen.
            match = await self._write_back(term, match)

        return ResolvedFoodItem(
            detected=detected,
            matched=match,
            nutrition=NutritionFacts.for_portion(match, detected.estimated_grams),
            alternatives=hit.alternatives,
            confidence_label="Rough guess" if is_rough else "Fairly sure",
            is_rough=is_rough,
        )

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
                -as_utc(r.fetched_at or datetime.min).timestamp(),
            )
        )
        return matches.from_food_row(fresh[0])

    async def _lookup_barcode_product(self, term: str) -> NutritionMatch | None:
        """Look for a previously scanned product by name.

        Someone scans a protein bar on Monday and types its name on Friday; the
        nutrition is already sitting in ``barcode_products``, and reaching a
        packaged product this way beats a free-text search for it every time.
        """
        row = await self._db.scalar(
            select(BarcodeProduct).where(func.lower(BarcodeProduct.name) == canonical_term(term))
        )
        if row is None:
            return None
        return matches.from_barcode_product(row)

    def _is_fresh(self, row: Food) -> bool:
        # Seeded rows are curated by hand and have no upstream to re-check, so
        # they never expire. Only fetched rows carry a TTL.
        if row.source == NutritionSource.SEED or row.fetched_at is None:
            return True
        age = datetime.now(UTC) - as_utc(row.fetched_at)
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
            return matches.from_food_row(existing)

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
        try:
            # A SAVEPOINT, not the whole transaction. This session is shared by
            # the entire request and committed once at the end, and a decomposed
            # dish resolves several foods through here in a loop — so a bare
            # rollback on the fourth would silently discard the write-backs for
            # the first three, and leave the route committing a dead session.
            async with self._db.begin_nested():
                self._db.add(row)
        except IntegrityError:
            # Another request resolved the same term first. The unique index is
            # the backstop that makes this a lost race rather than a duplicate
            # row; re-read and use the winner.
            winner = await self._db.scalar(
                select(Food).where(Food.name == name, Food.source == match.source)
            )
            if winner is not None:
                return matches.from_food_row(winner)
            return match

        return matches.from_food_row(row)
