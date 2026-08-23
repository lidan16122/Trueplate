"""Open Food Facts — packaged goods, and the only source for a UPC.

Same contract as the USDA client: returns ``NutritionMatch``, never raises for
an upstream problem, and lets the caller fall through to the next rung.

Open Food Facts publishes no hard rate limit but asks that clients identify
themselves with a descriptive User-Agent. An anonymous client is what gets
blocked, so ``settings.open_food_facts_user_agent`` is sent on every request.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.enums import NutritionSource
from app.schemas.detection import NutritionMatch
from app.services.nutrition.matches import kcal_from
from app.services.nutrition.relevance import is_relevant

logger = logging.getLogger(__name__)

# Only the fields we actually read. OFF products carry hundreds of keys and the
# full document is large enough to matter across several lookups per detection.
_PRODUCT_FIELDS = (
    "code,product_name,product_name_en,generic_name,brands,quantity,"
    "serving_size,serving_quantity,nutriments,categories_tags"
)


@dataclass(frozen=True, slots=True)
class BarcodeLookup:
    """A resolved UPC, carrying the extra label detail a barcode row keeps."""

    match: NutritionMatch
    serving_size_g: float | None
    serving_description: str | None
    raw_payload: dict[str, Any]


def _first_text(product: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _number(nutriments: dict[str, Any], key: str) -> float | None:
    value = nutriments.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_match(product: dict[str, Any]) -> NutritionMatch | None:
    """Convert an OFF product to a match, or None if it is not usable as food.

    A product with no energy figure at all is either a non-food that drifted
    into the database (the shampoo case) or an incomplete crowd-sourced entry.
    Either way there is nothing to show a user, so it is not a match.
    """
    nutriments = product.get("nutriments")
    if not isinstance(nutriments, dict):
        return None

    kcal = kcal_from(
        _number(nutriments, "energy-kcal_100g"),
        _number(nutriments, "energy_100g") or _number(nutriments, "energy-kj_100g"),
    )
    if kcal is None:
        return None

    name = _first_text(product, "product_name_en", "product_name", "generic_name")
    if not name:
        return None

    # Fibre, sugar and sodium are available here and have columns on the food
    # tables, but NutritionMatch — the shape the client mirrors — carries only
    # the four figures the design shows. Widening the contract for data no
    # screen renders would be a change to make when a screen needs it.
    return NutritionMatch(
        name=name,
        brand=_first_text(product, "brands"),
        source=NutritionSource.OPEN_FOOD_FACTS,
        source_ref=_first_text(product, "code"),
        kcal_per_100g=round(kcal, 2),
        protein_g_per_100g=round(_number(nutriments, "proteins_100g") or 0.0, 2),
        carbs_g_per_100g=round(_number(nutriments, "carbohydrates_100g") or 0.0, 2),
        fat_g_per_100g=round(_number(nutriments, "fat_100g") or 0.0, 2),
    )


class OpenFoodFactsClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {"User-Agent": settings.open_food_facts_user_agent}

    async def product(self, upc: str) -> BarcodeLookup | None:
        """Look up one UPC. None means unknown *or* not a food."""
        try:
            response = await self._client.get(
                f"{settings.open_food_facts_base_url}/api/v2/product/{upc}.json",
                params={"fields": _PRODUCT_FIELDS},
                headers=self._headers,
            )
            # OFF answers an unknown barcode with 404 and a status:0 body. Both
            # mean the same thing to us, so 404 is not worth an exception.
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("Open Food Facts lookup for %s failed: %s", upc, exc)
            return None

        if payload.get("status") != 1:
            return None
        product = payload.get("product")
        if not isinstance(product, dict):
            return None

        match = _to_match(product)
        if match is None:
            return None

        serving_quantity = _number(product, "serving_quantity")
        return BarcodeLookup(
            match=match,
            serving_size_g=serving_quantity,
            serving_description=_first_text(product, "serving_size"),
            raw_payload=product,
        )

    async def search(self, term: str, *, limit: int = 5) -> list[NutritionMatch]:
        """Best packaged-goods matches for ``term``. Empty on any failure."""
        try:
            response = await self._client.get(
                f"{settings.open_food_facts_base_url}/cgi/search.pl",
                params={
                    "search_terms": term,
                    "search_simple": 1,
                    "action": "process",
                    "json": 1,
                    "page_size": limit,
                    "fields": _PRODUCT_FIELDS,
                },
                headers=self._headers,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("Open Food Facts search for %r failed: %s", term, exc)
            return []

        products = payload.get("products")
        if not isinstance(products, list):
            return []

        matches = [
            m
            for m in (_to_match(p) for p in products if isinstance(p, dict))
            if m is not None and is_relevant(term, m.name)
        ]
        return matches[:limit]
