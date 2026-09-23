"""Evaluation totals exercise real detection and grounding with external responses replayed."""

import httpx
import pytest

from app.config import settings
from app.services.detection.detector import TOOL_NAME, DetectionService
from app.services.grounding import GroundedResponseService
from app.services.nutrition import NutritionResolver, OpenFoodFactsClient, UsdaClient
from scripts.eval_detection import Case, _measure_run
from tests.fakes import (
    FakeAnthropic,
    food_result,
    message,
    nutrition_transport,
    tool_use,
    usda_food,
)


@pytest.mark.parametrize("refused", [False, True])
async def test_evaluation_counts_both_model_passes_and_keeps_failed_runs(
    db_session, monkeypatch, refused
):
    monkeypatch.setattr(settings, "usda_fdc_api_key", "test-key")
    responses = (
        [message([], stop_reason="refusal")]
        if refused
        else [
            message([tool_use(TOOL_NAME, food_result())]),
            message([tool_use("compose_nutrition_response", {"fact_ids": ["portion_0"]})]),
        ]
    )
    client = FakeAnthropic(responses)
    async with httpx.AsyncClient(
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165))
    ) as http:
        detector = DetectionService(
            NutritionResolver(db_session, UsdaClient(http), OpenFoodFactsClient(http)),
            client=client,
        )
        row = await _measure_run(
            detector,
            GroundedResponseService(client),
            Case("chicken", "grilled chicken breast", ("chicken",)),
            None,
            1,
        )
    assert row["detection"]["turns"] == 1
    assert row["grounding"]["turns"] == (0 if refused else 1)
    assert row["total_input"] == (2320 if refused else 4640)
    assert row["total_output"] == (340 if refused else 680)
    assert row["errors"] == (["DetectionRefused"] if refused else [])
    if not refused:
        assert row["grounding_status"] == "generated"
