"""The HTTP pipeline runs real detection, resolution and caching over substituted upstreams."""

import json

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.db.models import Detection, Food
from app.models.enums import NutritionSource
from app.services.detection import detector
from app.services.grounding import service as grounding
from app.services.nutrition import http as nutrition_http
from tests.fakes import (
    FakeAnthropic,
    food_result,
    message,
    nutrition_transport,
    off_product_payload,
    tool_use,
    usda_food,
)
from tests.helpers import sign_in
from tests.test_detection_service import TINY_JPEG
from tests.test_grounding import plan

API = "/api/v1/ai/detect"


@pytest.fixture
async def upstreams(monkeypatch, db_session):
    detection = FakeAnthropic([message([tool_use(detector.TOOL_NAME, food_result())])])
    synthesis = FakeAnthropic([plan("portion_0")])
    seen = []

    def make_grounding_client(**kwargs):
        # The actual SDK seam observes transaction state at the start of the remote call.
        assert not db_session.in_transaction()
        assert kwargs["max_retries"] == 0
        return synthesis

    monkeypatch.setattr(detector, "AsyncAnthropic", lambda **kwargs: detection)
    monkeypatch.setattr(grounding.anthropic, "AsyncAnthropic", make_grounding_client)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "usda_fdc_api_key", "test-key")
    transport = nutrition_transport(usda=usda_food("Chicken breast, grilled", 165))

    async def handle(request):
        seen.append(request)
        return await transport.handle_async_request(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        monkeypatch.setattr(nutrition_http, "_client", http)
        yield detection, synthesis, seen


@pytest.mark.parametrize("kind", ["photo", "text"])
async def test_both_inputs_return_grounded_nutrition_and_reuse_the_completed_cache(
    client, google_ok, db_session, upstreams, kind
):
    detection, synthesis, seen = upstreams
    await sign_in(client)
    request = (
        {"files": {"image": ("meal.jpg", TINY_JPEG, "image/jpeg")}}
        if kind == "photo"
        else {"json": {"description": "150 g grilled chicken breast"}}
    )

    first = await client.post(f"{API}/{kind}", **request)
    again = await client.post(f"{API}/{kind}", **request)

    assert first.status_code == again.status_code == 200
    payload = first.json()
    assert payload["grounded_response"]["status"] == "generated"
    assert payload["items"][0]["matched"]["source_ref"] == "12345"
    assert payload["totals"]["calories"] == 247.5
    assert "247.5 kcal" in payload["grounded_response"]["statements"][0]["text"]
    assert again.json() == {**payload, "cached": True}
    assert len(detection.calls) == len(synthesis.calls) == len(seen) == 1
    assert await db_session.scalar(select(func.count()).select_from(Food)) == 1


async def test_a_generation_failure_retries_only_generation_and_preserves_food_writebacks(
    client, google_ok, db_session, upstreams
):
    detection, synthesis, seen = upstreams
    synthesis._responses = [TimeoutError(), plan("portion_0")]
    await sign_in(client)
    request = {"description": "150 g chicken breast"}
    failed = await client.post(f"{API}/text", json=request)
    assert failed.status_code == 200
    assert failed.json()["grounded_response"]["status"] == "fallback"
    row = await db_session.scalar(select(Detection))
    assert row.payload["grounded_response"] is None
    await db_session.commit()

    retried = await client.post(f"{API}/text", json=request)
    assert retried.json()["grounded_response"]["status"] == "generated"
    assert retried.json()["cached"] is True
    assert len(detection.calls) == len(seen) == 1
    assert len(synthesis.calls) == 2


@pytest.mark.parametrize("stale", ["legacy", "version", "malformed"])
async def test_old_or_stale_summaries_are_regenerated_without_recognizing_food_again(
    client, google_ok, db_session, upstreams, monkeypatch, stale
):
    detection, synthesis, _ = upstreams
    await sign_in(client)
    request = {"description": "chicken breast"}
    first = await client.post(f"{API}/text", json=request)
    assert first.status_code == 200
    row = await db_session.scalar(select(Detection))
    payload = dict(row.payload)
    if stale == "legacy":
        payload.pop("grounded_response")
        payload.pop("_grounding_fingerprint")
    elif stale == "malformed":
        payload["grounded_response"] = {"text": "an outdated format"}
    else:
        monkeypatch.setattr(grounding, "SYSTEM_PROMPT", grounding.SYSTEM_PROMPT + " Revised.")
    row.payload = payload
    await db_session.commit()
    synthesis._responses.append(plan("largest_protein_g"))

    refreshed = await client.post(f"{API}/text", json=request)
    assert refreshed.status_code == 200
    assert refreshed.json()["cached"] is True
    assert refreshed.json()["grounded_response"]["statements"][-1]["fact_id"] == "largest_protein_g"
    assert len(detection.calls) == 1
    assert len(synthesis.calls) == 2


async def test_a_postgres_reference_is_supplied_as_evidence_without_an_upstream_lookup(
    client, google_ok, db_session, upstreams
):
    _, synthesis, seen = upstreams
    db_session.add(
        Food(
            name="grilled chicken breast",
            source=NutritionSource.SEED,
            source_ref="local-reference",
            kcal_per_100g=165,
            protein_g_per_100g=31,
            carbs_g_per_100g=0,
            fat_g_per_100g=3.6,
        )
    )
    await db_session.commit()
    await sign_in(client)
    result = await client.post(f"{API}/text", json={"description": "chicken breast"})
    assert result.status_code == 200
    context = json.loads(synthesis.calls[0]["messages"][0]["content"])
    assert context["items"][0]["record"]["source"] == "seed"
    assert context["items"][0]["record"]["food_id"] is not None
    assert seen == []


async def test_open_food_facts_evidence_keeps_its_rough_match_warning(
    client, google_ok, upstreams, monkeypatch
):
    _, synthesis, _ = upstreams
    product = off_product_payload("Grilled chicken breast", 165)["product"]
    async with httpx.AsyncClient(
        transport=nutrition_transport(
            off_search={"products": [product]},
        )
    ) as http:
        monkeypatch.setattr(nutrition_http, "_client", http)
        await sign_in(client)
        result = await client.post(f"{API}/text", json={"description": "chicken breast"})
    assert result.status_code == 200
    context = json.loads(synthesis.calls[0]["messages"][0]["content"])
    assert context["items"][0]["record"]["source"] == "open_food_facts"
    assert "rough" in [s["fact_id"] for s in result.json()["grounded_response"]["statements"]]


async def test_barcode_lookup_does_not_generate_a_response(
    client, google_ok, upstreams, monkeypatch
):
    detection, synthesis, _ = upstreams
    async with httpx.AsyncClient(
        transport=nutrition_transport(
            off_product=off_product_payload("Test cereal", 350),
        )
    ) as http:
        monkeypatch.setattr(nutrition_http, "_client", http)
        await sign_in(client)
        result = await client.post(f"{API}/barcode", data={"upc": "5000112637939"})
    assert result.status_code == 200
    assert result.json()["grounded_response"] is None
    assert detection.calls == synthesis.calls == []


async def test_a_provisional_inventory_is_explained_but_never_cached(
    client, google_ok, db_session, upstreams
):
    detection, _, _ = upstreams
    inconsistent = food_result(components=["chicken", "rice"])
    # A mass mismatch is not needed: fewer inventory names than foods uses the normal re-ask.
    inconsistent["components"] = []
    detection._responses = [message([tool_use(detector.TOOL_NAME, inconsistent)])] * 2
    await sign_in(client)
    result = await client.post(f"{API}/text", json={"description": "chicken and rice"})
    assert result.status_code == 200
    assert result.json()["is_provisional"] is True
    summary = result.json()["grounded_response"]
    assert "provisional" in [s["fact_id"] for s in summary["statements"]]
    assert await db_session.scalar(select(func.count()).select_from(Detection)) == 0
