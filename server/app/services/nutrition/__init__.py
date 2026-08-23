"""Nutrition resolution: the only place a calorie figure enters this app.

Split by upstream — one module per external source, plus the resolver that walks
them in order. Routes and services talk to ``NutritionResolver``; nothing else
imports the source clients directly.
"""

from app.services.nutrition.http import close_http_client, get_http_client
from app.services.nutrition.open_food_facts import BarcodeLookup, OpenFoodFactsClient
from app.services.nutrition.resolver import NutritionResolver, canonical_term
from app.services.nutrition.usda import UsdaClient

__all__ = [
    "BarcodeLookup",
    "NutritionResolver",
    "OpenFoodFactsClient",
    "UsdaClient",
    "canonical_term",
    "close_http_client",
    "get_http_client",
]
