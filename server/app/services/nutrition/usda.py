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
from app.services.nutrition.matches import kcal_from
from app.services.nutrition.relevance import SUBSTITUTE_MARKERS, content_tokens

logger = logging.getLogger(__name__)

# FDC identifies nutrients numerically; the names drift between data types but
# the ids do not. 1008 is kcal specifically — 1062 is the same energy in kJ, and
# matching on the name "Energy" alone silently picks up both.
_ENERGY_KCAL = 1008
_ENERGY_KJ = 1062
_PROTEIN = 1003
_CARBS = 1005
_FAT = 1004

# Even with a well-formed request FDC's edge fails perhaps one time in six, and
# it fails in two shapes: a 400 with an nginx error page, and a 404 serving the
# FoodData Central *website* — an Angular shell — in place of an API response.
# Both look like a permanent verdict on the request and are nothing of the kind.
#
# 404 belongs in this set for that reason. Absent from it, the first 404 exited
# the loop immediately and the retries never ran. 429 stays excluded on purpose:
# that one is real, per-IP, and hammering it extends the block.
_ATTEMPTS = 3
_RETRY_STATUSES = frozenset({400, 404, 500, 502, 503, 504})

# Fetched per search, before client-side ranking trims to the caller's limit.
# See ``UsdaClient._get`` for why the data-type filter is not sent upstream.
_FETCH_SIZE = 25
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


def _head(description: str) -> str:
    """The segment of an FDC description that names the food.

    FDC writes descriptions head-first — "Chicken, broilers or fryers, leg, meat
    and skin, cooked, roasted" — so everything before the first comma is the
    food's identity and the rest are qualifiers. That convention is the single
    most useful signal available here, because the worst matches announce
    themselves in exactly that position: *Spices*, curry powder. *Bratwurst*,
    chicken, cooked. *Emu*, fan fillet. *Bread*, potato.
    """
    return description.split(",", 1)[0]


def rank_foods(term: str, foods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order raw FDC results by how well they answer ``term``, best first.

    Pure, and public so ``scripts/eval_matching`` can score it against recorded
    responses without touching the network. That separation is what makes this
    tunable at all: FDC fails roughly one request in six, so an eval that
    re-fetched would be measuring their edge rather than this function.

    Rows sharing no content word with the query are **dropped rather than
    demoted**, so an answer about a different food entirely cannot be returned
    just because nothing better came back. The resolver's ladder has two more
    terms below this one, which is a far better place to end up than a confident
    stranger.
    """
    query = content_tokens(term)
    scored: list[tuple[tuple[int, ...], dict[str, Any]]] = []

    for index, food in enumerate(foods):
        description = food.get("description") or ""
        body = content_tokens(description)
        if query and not (query & body):
            continue
        head = content_tokens(_head(description))

        scored.append(
            (
                (
                    # Is the head about this food at all? "Spices", "Soup",
                    # "Bread" and "Emu" are not, whatever their qualifiers say.
                    0 if head & query else 1,
                    # A stand-in for the food is not the food. Only when the
                    # query did not ask for one, so "meatless chicken" still
                    # finds what it means.
                    1 if (body & SUBSTITUTE_MARKERS) and not (query & SUBSTITUTE_MARKERS) else 0,
                    # How much of the *query* the row accounts for, anywhere in
                    # the description. This is the relevance measure, and it has
                    # to lead: "Sauce, cheese sauce mix" answers nothing of
                    # "curry sauce" beyond the word sauce, while
                    # "Yogurt, Greek, plain, nonfat" answers all of
                    # "greek yogurt plain" with half of it in a qualifier.
                    -len(body & query),
                    # Identity words the query never mentioned. "Sweet potato
                    # leaves" carries two against a query for potato; "Potatoes"
                    # carries none. Without this a head that happens to contain
                    # every query word wins however much else it contains, which
                    # is how "Spanish rice with ground beef" beat "Beef, ground".
                    len(head - query),
                    # Branded rows are manufacturer-submitted and the least
                    # consistent, and their descriptions are the query typed
                    # back verbatim — so on relevance alone a packaged product
                    # wins every plain food name. Demoted once identity and
                    # coverage are equal, which is exactly "a branded row may
                    # win, but only when it is clearly the better match".
                    1 if food.get("dataType") == "Branded" else 0,
                    # How much of the head the query explains. Below the branded
                    # penalty on purpose — above it, "GREEK YOGURT PLAIN" beats
                    # "Yogurt, Greek, plain, nonfat" for repeating the query in
                    # the identity position. Below it, this is what separates
                    # "Chicken drumstick, rotisserie" from "Chicken, skin
                    # (drumsticks and thighs)": both mention a drumstick, only
                    # one *is* one, and they differ by 240 kcal.
                    -len(head & query),
                    # Everything else the row drags along. Separates "Bananas,
                    # raw" from "Bananas, overripe, raw".
                    len(body - query),
                    # Lab-analysed over modelled, among rows that are otherwise
                    # indistinguishable.
                    _DATA_TYPE_RANK.get(food.get("dataType", ""), 99),
                    # FDC's own relevance, last. It is better than it looks: for
                    # "chicken leg roasted with skin" its first result is already
                    # exactly right, so ties should fall back to it rather than
                    # to anything invented here.
                    index,
                ),
                food,
            )
        )

    scored.sort(key=lambda pair: pair[0])
    return [food for _, food in scored]


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

    kcal = kcal_from(values.get(_ENERGY_KCAL), values.get(_ENERGY_KJ))
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

    async def _retrying_get(self, term: str) -> httpx.Response:
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
            last = await self._get(term)
            if last.status_code not in _RETRY_STATUSES:
                return last
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        return last  # type: ignore[return-value]  # the loop always runs once

    async def _get(self, term: str) -> httpx.Response:
        """One search request.

        **``dataType`` is deliberately not sent**, and that is a fix rather than
        a simplification. FDC's edge rejects the value ``Survey (FNDDS)``
        outright — measured at 0/6 successful requests carrying it, against 5/6
        carrying no ``dataType`` at all — answering 400 or 404 with an nginx or
        Angular error page rather than anything that names the problem. The
        previous request sent all four types on every lookup, so the USDA rung
        failed *every* time and each whole-food match this app made was quietly
        coming from Open Food Facts instead. Nothing surfaced, because the
        resolver degrades politely and the user just sees a worse answer.

        Losing the server-side filter costs nothing: ``_DATA_TYPE_RANK`` already
        sorts the useful types to the front and pushes anything unrecognised to
        the back, so the ordering guarantee is unchanged — it now happens after
        the response instead of before it.
        """
        return await self._client.get(
            f"{settings.usda_fdc_base_url}/foods/search",
            params=[
                ("api_key", settings.usda_fdc_api_key),
                ("query", self._clean(term)),
                # Over-fetch on purpose. Without a server-side filter a page can
                # come back entirely Branded, and client-side ranking can only
                # promote a lab-analysed row that is actually in the page.
                ("pageSize", _FETCH_SIZE),
            ],
        )

    async def search(self, term: str, *, limit: int = 5) -> list[NutritionMatch]:
        """Best matches for ``term``, most plausible first. Empty on any failure."""
        if not self.configured:
            # Not an error worth logging on every lookup — an unconfigured key is
            # a deployment state, and the ladder is designed to run without it.
            return []

        try:
            response = await self._retrying_get(term)
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

        ranked = rank_foods(term, [f for f in foods if isinstance(f, dict)])
        matches = [m for m in (_to_match(f) for f in ranked) if m is not None]
        return matches[:limit]
