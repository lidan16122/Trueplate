"""USDA FoodData Central — the whole-food rung of the resolution ladder.

Everything here returns ``NutritionMatch`` rather than a USDA-shaped dict, so
the resolver never learns FDC's vocabulary and a second upstream can be added
without touching it.

**This module never raises for an upstream problem.** A 429, a timeout, a
blocked key or a schema surprise all come back as an empty list, because the
caller's correct response to "USDA is unavailable" is to try the next rung, not
to fail the user's meal. FoodData Central rate-limits per *IP address* — one
bucket shared by every user of this app — and the penalty is an hour-long block
rather than throttling, so "USDA said no" is a state this app will reach.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings
from app.enums import NutritionSource
from app.schemas.detection import NutritionMatch

logger = logging.getLogger(__name__)

# FDC identifies nutrients numerically; the names drift between data types but
# the ids do not. 1008 is kcal specifically — 1062 is the same energy in kJ, and
# matching on the name "Energy" alone silently picks up both.
_ENERGY_KCAL = 1008
_ENERGY_KJ = 1062
_PROTEIN = 1003
_CARBS = 1005
_FAT = 1004

_KJ_PER_KCAL = 4.184

# FDC's front end answers valid requests with a spurious 400 roughly half the
# time. Three attempts takes the chance of losing a lookup from ~50% to ~12%.
# 429 is excluded on purpose — that one means what it says.
_ATTEMPTS = 3
_RETRY_STATUSES = frozenset({400, 500, 502, 503, 504})
_RETRY_BACKOFF_SECONDS = 0.25

# Foundation and SR Legacy are lab-analysed whole foods; Survey is modelled from
# them; Branded is manufacturer-submitted and the least consistent. A search for
# "chicken breast" should land on the analysed entry, not on someone's frozen
# ready meal, so results are re-ranked by this before anything else.
_DATA_TYPE_RANK = {
    "Foundation": 0,
    "SR Legacy": 1,
    "Survey (FNDDS)": 2,
    "Branded": 3,
}


def _nutrient_values(payload: dict[str, Any]) -> dict[int, float]:
    """Flatten FDC's two different nutrient shapes into {nutrient_id: value}.

    ``/foods/search`` returns ``{"nutrientId": 1008, "value": 165}`` while
    ``/food/{id}`` returns ``{"nutrient": {"id": 1008}, "amount": 165}``. Both
    are handled here so callers never branch on which endpoint they hit.
    """
    values: dict[int, float] = {}
    for entry in payload.get("foodNutrients") or []:
        if not isinstance(entry, dict):
            continue
        nutrient_id = entry.get("nutrientId")
        amount = entry.get("value")
        if nutrient_id is None:
            nested = entry.get("nutrient")
            if isinstance(nested, dict):
                nutrient_id = nested.get("id")
            amount = entry.get("amount")
        if nutrient_id is None or amount is None:
            continue
        try:
            values[int(nutrient_id)] = float(amount)
        except (TypeError, ValueError):
            continue
    return values


def _to_match(payload: dict[str, Any]) -> NutritionMatch | None:
    """Convert one FDC food into a match, or None if it carries no usable energy."""
    values = _nutrient_values(payload)

    kcal = values.get(_ENERGY_KCAL)
    if kcal is None and _ENERGY_KJ in values:
        # Some branded rows publish only kJ. Deriving kcal is arithmetic on a
        # sourced figure, not an estimate, so provenance survives it.
        kcal = values[_ENERGY_KJ] / _KJ_PER_KCAL
    if kcal is None:
        # No energy means nothing to show the user. Better to fall through to the
        # next rung than to render a food with 0 kcal that looks resolved.
        return None

    name = (payload.get("description") or "").strip()
    if not name:
        return None

    fdc_id = payload.get("fdcId")
    brand = (payload.get("brandName") or payload.get("brandOwner") or "").strip() or None

    return NutritionMatch(
        name=name,
        brand=brand,
        source=NutritionSource.USDA_FDC,
        source_ref=str(fdc_id) if fdc_id is not None else None,
        kcal_per_100g=round(kcal, 2),
        protein_g_per_100g=round(values.get(_PROTEIN, 0.0), 2),
        carbs_g_per_100g=round(values.get(_CARBS, 0.0), 2),
        fat_g_per_100g=round(values.get(_FAT, 0.0), 2),
    )


class UsdaClient:
    """Search FoodData Central by name.

    Takes its ``httpx.AsyncClient`` rather than building one, so a test can
    substitute the transport at the real network boundary instead of mocking our
    own code.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @property
    def configured(self) -> bool:
        """Whether a key worth sending is present.

        A non-empty string is not enough. ``.env.example`` ships the placeholder
        ``your-usda-fdc-key``, and a bare truthiness check treats that as a real
        key — so the whole USDA rung silently 403s on every lookup while still
        reporting itself configured.

        ``DEMO_KEY`` is deliberately allowed through: it is api.data.gov's real
        shared key, rate-limited to 30 requests an hour, which is enough to prove
        the rung works without provisioning anything.
        """
        key = settings.usda_fdc_api_key.strip()
        return bool(key) and "your-" not in key.lower()

    @staticmethod
    def _clean(term: str) -> str:
        """Normalise a search term.

        Punctuation carries no search signal here — "sourdough bread, toasted"
        and "sourdough bread toasted" return the same thing — and the model
        emits comma-separated labels routinely. Cosmetic, not a fix for
        anything; see ``_ATTEMPTS`` for the failure that actually mattered.
        """
        return " ".join(term.replace(",", " ").split())

    async def _retrying_get(self, term: str, limit: int) -> httpx.Response:
        """Fetch, retrying the statuses FDC returns for no reason.

        Their front end intermittently answers a perfectly valid request with a
        400 and an nginx HTML error page: measured over eight identical requests
        for ``avocado``, roughly half came back 400 and half 200, with no
        relation to the query — so a single attempt loses about half of all
        whole-food lookups. Each loss is invisible, because the resolver
        degrades politely to Open Food Facts and the user just sees a worse
        answer.

        429 is deliberately *not* retried: that one is real, per-IP, and
        hammering it extends the block.
        """
        last: httpx.Response | None = None
        for attempt in range(_ATTEMPTS):
            last = await self._get(term, limit)
            if last.status_code not in _RETRY_STATUSES:
                return last
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        return last  # type: ignore[return-value]  # the loop always runs once

    async def _get(self, term: str, limit: int) -> httpx.Response:
        return await self._client.get(
            f"{settings.usda_fdc_base_url}/foods/search",
            # A list of pairs, so `dataType` is sent as a repeated query
            # parameter. Joining the values with commas instead — the shape
            # FDC's own docs suggest — is rejected outright.
            params=[
                ("api_key", settings.usda_fdc_api_key),
                ("query", self._clean(term)),
                ("pageSize", limit),
                # Ask for the useful data types explicitly; the default
                # includes experimental sets that pollute the ranking.
                ("dataType", "Foundation"),
                ("dataType", "SR Legacy"),
                ("dataType", "Survey (FNDDS)"),
                ("dataType", "Branded"),
            ],
        )

    async def search(self, term: str, *, limit: int = 5) -> list[NutritionMatch]:
        """Best matches for ``term``, most plausible first. Empty on any failure."""
        if not self.configured:
            # Not an error worth logging on every lookup — an unconfigured key is
            # a deployment state, and the ladder is designed to run without it.
            return []

        try:
            response = await self._retrying_get(term, limit)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 403:
                # The key is present but rejected. Worth a warning rather than a
                # debug line: the ladder keeps working via Open Food Facts, so
                # nothing visibly breaks — the app just quietly gets worse at
                # whole foods, which is the hardest kind of failure to notice.
                logger.warning(
                    "USDA rejected the API key (HTTP 403). Whole-food lookups will fall "
                    "through to Open Food Facts, which is much weaker for generic names. "
                    "Set USDA_FDC_API_KEY in the repo-root .env."
                )
            elif status == 429:
                # The per-IP bucket is spent and the key is blocked for the hour.
                # Loud, because it affects every user at once.
                logger.warning("USDA rate limit hit for %r; falling through", term)
            else:
                logger.info("USDA search for %r failed: HTTP %s", term, status)
            return []
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("USDA search for %r failed: %s", term, exc)
            return []

        foods = payload.get("foods")
        if not isinstance(foods, list):
            return []

        ranked = sorted(
            (f for f in foods if isinstance(f, dict)),
            key=lambda f: _DATA_TYPE_RANK.get(f.get("dataType", ""), 99),
        )
        matches = [m for m in (_to_match(f) for f in ranked) if m is not None]
        return matches[:limit]
