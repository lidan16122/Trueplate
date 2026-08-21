"""Stand-ins for the two external services the detection path talks to.

Both substitute at the real boundary — the Anthropic SDK object and the httpx
transport — rather than behind an abstraction of our own. That is what keeps the
tests honest: the request we build, the response parsing, the retry loop and the
JSON shapes upstream actually returns are all still exercised.
"""

from types import SimpleNamespace
from typing import Any

import httpx


def tool_use(name: str, payload: dict[str, Any], block_id: str = "toolu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload, id=block_id)


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def message(content: list[Any], stop_reason: str = "tool_use") -> SimpleNamespace:
    # Real responses always carry usage, and the service sums it across turns to
    # log per-detection cost. Omitting it here would let a change that breaks
    # that accounting pass the suite.
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=340,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=2200,
        ),
    )


class FakeAnthropic:
    """Replays a scripted list of responses, one per call.

    Records every request so a test can assert on what was actually sent — the
    tool list, the cache breakpoint, whether thinking was left enabled.
    """

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        return self._responses.pop(0)


def food_result(**overrides: Any) -> dict[str, Any]:
    """A valid ``FoodDetectionResult`` payload, minus whatever a test overrides."""
    payload: dict[str, Any] = {
        "input_kind": "food",
        "meal_description": "Chicken with rice",
        "overall_confidence": 0.9,
        "notes": None,
        "foods": [
            {
                "label": "grilled chicken breast",
                "estimated_grams": 150.0,
                "confidence": 0.9,
                "preparation": "grilled",
                "search_terms": ["grilled chicken breast", "chicken breast cooked"],
                "portion_reasoning": "covers a third of the plate",
            }
        ],
    }
    payload.update(overrides)
    return payload


def nutrition_transport(
    *,
    usda: dict[str, Any] | None = None,
    off_search: dict[str, Any] | None = None,
    off_product: dict[str, Any] | None = None,
    usda_status: int = 200,
) -> httpx.MockTransport:
    """An httpx transport standing in for USDA and Open Food Facts.

    Routes on path so one transport serves both upstreams, which is how the
    resolver actually reaches them.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/fdc/" in path or "foods/search" in path:
            if usda_status != 200:
                return httpx.Response(usda_status, json={"error": "nope"})
            return httpx.Response(200, json=usda or {"foods": []})
        if "/api/v2/product/" in path:
            if off_product is None:
                return httpx.Response(404, json={"status": 0})
            return httpx.Response(200, json=off_product)
        if "search.pl" in path:
            return httpx.Response(200, json=off_search or {"products": []})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def usda_food(name: str, kcal: float, fdc_id: int = 12345) -> dict[str, Any]:
    return {
        "foods": [
            {
                "fdcId": fdc_id,
                "description": name,
                "dataType": "SR Legacy",
                "foodNutrients": [
                    {"nutrientId": 1008, "value": kcal},
                    {"nutrientId": 1003, "value": 31.0},
                    {"nutrientId": 1005, "value": 0.0},
                    {"nutrientId": 1004, "value": 3.6},
                ],
            }
        ]
    }


def off_product_payload(name: str, kcal: float, code: str = "5000112637939") -> dict[str, Any]:
    return {
        "status": 1,
        "product": {
            "code": code,
            "product_name": name,
            "brands": "Testco",
            "serving_size": "30 g",
            "serving_quantity": 30,
            "nutriments": {
                "energy-kcal_100g": kcal,
                "proteins_100g": 5.0,
                "carbohydrates_100g": 60.0,
                "fat_100g": 10.0,
            },
        },
    }
