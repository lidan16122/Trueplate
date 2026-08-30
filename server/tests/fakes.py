"""Stand-ins for the external services this app talks to.

Every one substitutes at the real boundary — the Anthropic SDK object, the httpx
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
        # `messages` is one list the service appends to across the whole loop, so
        # recording `kwargs` as handed over stores a live reference: every call
        # would share it and `calls[0]["messages"][-1]` would report the *last*
        # thing sent, not the first. Snapshotting the list is what lets a test
        # say "on the second call we sent this" and be right.
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if not self._responses:
            raise AssertionError("FakeAnthropic ran out of scripted responses")
        return self._responses.pop(0)


def food_result(**overrides: Any) -> dict[str, Any]:
    """A valid ``FoodDetectionResult`` payload, minus whatever a test overrides."""
    payload: dict[str, Any] = {
        "input_kind": "food",
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
    # Derived rather than fixed, so a test that overrides `foods` does not
    # accidentally also assert a self-contradicting reply: the service re-asks
    # when the names and the entries disagree, which would silently consume a
    # second queued response and make an unrelated test fail on the wrong thing.
    # A test that *wants* the mismatch passes `components` explicitly.
    payload.setdefault("components", [f["label"] for f in payload["foods"]])
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


def google_token_transport(
    *,
    id_token: str = "good-token",
    status_code: int = 200,
    body: dict[str, Any] | None = None,
    seen: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    """Google's token endpoint, substituted at the transport.

    ``id_token`` defaults to "good-token" because the ``google_ok`` fixture's
    stand-in verifier already treats that string as valid and "bad-token" as
    forged — so the two legs of the flow speak the same language, and a test that
    wants a rejected credential changes one word.

    ``seen`` collects the requests, which is what lets a test assert the PKCE
    verifier and the client secret were actually sent. Stubbing our own exchange
    function instead would quietly stop proving the two things a confidential
    client and PKCE exist for.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status_code != 200:
            return httpx.Response(status_code, json={"error": "invalid_grant"})
        return httpx.Response(200, json=body or {"id_token": id_token, "token_type": "Bearer"})

    return httpx.MockTransport(handler)
