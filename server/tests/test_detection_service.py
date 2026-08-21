"""Behaviour of the detection loop, with the model and the upstreams substituted.

Every test here is named for the symptom it would show if the behaviour broke.
"""

import io

import httpx
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.detection import (
    TOOL_NAME,
    ZOOM_TOOL_NAME,
    DetectionRefused,
    DetectionService,
    DetectionUnavailable,
    NotFoodError,
    NothingDetected,
)
from app.services.nutrition import NutritionResolver, OpenFoodFactsClient, UsdaClient
from tests.fakes import (
    FakeAnthropic,
    food_result,
    message,
    nutrition_transport,
    text_block,
    tool_use,
    usda_food,
)


def _jpeg(width: int = 64, height: int = 48) -> bytes:
    """A real, decodable JPEG. Built rather than hardcoded so PIL genuinely
    opens it — the crop path is only exercised if it does."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (180, 140, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


TINY_JPEG = _jpeg()


@pytest.fixture(autouse=True)
def usda_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The repo ships a placeholder key, and the client correctly declines to
    send one — which would make every USDA rung in these tests a silent no-op."""
    monkeypatch.setattr(settings, "usda_fdc_api_key", "test-key-000000000000000000")


def _service(db: AsyncSession, responses: list, *, transport=None) -> tuple:
    http = httpx.AsyncClient(transport=transport or nutrition_transport())
    resolver = NutritionResolver(db, UsdaClient(http), OpenFoodFactsClient(http))
    fake = FakeAnthropic(responses)
    return DetectionService(resolver, client=fake), fake


async def test_text_detection_resolves_every_food_it_reports(db_session: AsyncSession) -> None:
    transport = nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0))
    service, _ = _service(
        db_session,
        [message([tool_use(TOOL_NAME, food_result())])],
        transport=transport,
    )

    response = await service.detect_text("grilled chicken breast")

    assert len(response.items) == 1
    item = response.items[0]
    assert item.matched is not None
    assert item.matched.source == "usda_fdc"
    # 165 kcal/100 g scaled to the model's 150 g estimate.
    assert item.nutrition.calories == pytest.approx(247.5)
    assert response.totals.calories == pytest.approx(247.5)


async def test_non_food_input_is_refused_rather_than_answered(db_session: AsyncSession) -> None:
    service, _ = _service(
        db_session,
        [
            message(
                [tool_use(TOOL_NAME, food_result(input_kind="not_food", foods=[], notes="A dog."))]
            )
        ],
    )

    with pytest.raises(NotFoodError):
        await service.detect_text("my dog")


async def test_food_photo_with_nothing_identifiable_is_not_silently_empty(
    db_session: AsyncSession,
) -> None:
    service, _ = _service(
        db_session,
        [message([tool_use(TOOL_NAME, food_result(foods=[], notes="Too blurry."))])],
    )

    with pytest.raises(NothingDetected):
        await service.detect_text("something")


async def test_a_model_refusal_does_not_surface_as_an_index_error(
    db_session: AsyncSession,
) -> None:
    """A refusal is HTTP 200 with empty content; reading content[0] would raise."""
    service, _ = _service(db_session, [message([], stop_reason="refusal")])

    with pytest.raises(DetectionRefused):
        await service.detect_text("anything")


async def test_paused_turn_is_resumed_rather_than_abandoned(db_session: AsyncSession) -> None:
    """web_search can exhaust its server-side loop; the turn must be re-sent."""
    service, fake = _service(
        db_session,
        [
            message([text_block("searching...")], stop_reason="pause_turn"),
            message([tool_use(TOOL_NAME, food_result())]),
        ],
    )

    await service.detect_text("some regional dish")

    assert len(fake.calls) == 2
    # The paused assistant turn is echoed back verbatim; adding a "continue"
    # user message instead would break the resume.
    resumed = fake.calls[1]["messages"]
    assert resumed[-1]["role"] == "assistant"


async def test_zoom_request_returns_a_crop_and_the_loop_continues(
    db_session: AsyncSession,
) -> None:
    service, fake = _service(
        db_session,
        [
            message(
                [tool_use(ZOOM_TOOL_NAME, {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5,
                                           "reason": "check the sauce"}, "toolu_zoom")]
            ),
            message([tool_use(TOOL_NAME, food_result())]),
        ],
    )

    await service.detect_photo(TINY_JPEG)

    assert len(fake.calls) == 2
    follow_up = fake.calls[1]["messages"][-1]
    assert follow_up["role"] == "user"
    result_block = follow_up["content"][0]
    assert result_block["type"] == "tool_result"
    assert result_block["tool_use_id"] == "toolu_zoom"
    # The crop comes back as an image, not a description of one.
    assert result_block["content"][0]["type"] == "image"


async def test_zoom_tool_is_withheld_when_there_is_no_photo(db_session: AsyncSession) -> None:
    service, fake = _service(db_session, [message([tool_use(TOOL_NAME, food_result())])])

    await service.detect_text("chicken and rice")

    tool_names = {t.get("name") for t in fake.calls[0]["tools"]}
    assert ZOOM_TOOL_NAME not in tool_names
    assert TOOL_NAME in tool_names


async def test_thinking_stays_enabled(db_session: AsyncSession) -> None:
    """Disabling it makes the model emit tool calls as plain text, which this
    pipeline reads as "no result" with no error to catch."""
    service, fake = _service(db_session, [message([tool_use(TOOL_NAME, food_result())])])

    await service.detect_text("chicken")

    assert fake.calls[0]["thinking"] == {"type": "adaptive"}


async def test_system_prompt_carries_a_cache_breakpoint(db_session: AsyncSession) -> None:
    """Render order is tools -> system -> messages, so this caches both."""
    service, fake = _service(db_session, [message([tool_use(TOOL_NAME, food_result())])])

    await service.detect_text("chicken")

    system = fake.calls[0]["system"]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}


async def test_web_search_is_scoped_to_allowed_domains(db_session: AsyncSession) -> None:
    service, fake = _service(db_session, [message([tool_use(TOOL_NAME, food_result())])])

    await service.detect_text("chicken")

    search = next(t for t in fake.calls[0]["tools"] if t.get("name") == "web_search")
    assert search["allowed_domains"]
    # Declaring code_execution alongside the _20260209 search tool gives the
    # model two execution environments and confuses it.
    assert not any(t.get("type", "").startswith("code_execution") for t in fake.calls[0]["tools"])


async def test_missing_api_key_is_a_clear_failure_not_a_crash(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-...")
    http = httpx.AsyncClient(transport=nutrition_transport())
    resolver = NutritionResolver(db_session, UsdaClient(http), OpenFoodFactsClient(http))

    with pytest.raises(DetectionUnavailable, match="ANTHROPIC_API_KEY"):
        await DetectionService(resolver).detect_text("chicken")
