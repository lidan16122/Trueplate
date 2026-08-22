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
    """Asked twice, still nothing — then it really is nothing, and saying so is
    better than saving a meal with no items in it."""
    empty = food_result(foods=[], notes="Too blurry.")
    service, fake = _service(
        db_session,
        [
            message([tool_use(TOOL_NAME, empty)]),
            message([tool_use(TOOL_NAME, empty)]),
        ],
    )

    with pytest.raises(NothingDetected):
        await service.detect_text("something")

    # Nudged exactly once — a model that insists is believed the second time.
    assert len(fake.calls) == 2


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


async def test_an_empty_food_list_that_claims_food_is_queried_again(
    db_session: AsyncSession,
) -> None:
    """Observed live: the model classifies the input as `food`, writes notes
    describing the items it saw, and hands back an empty `foods` list. Reporting
    "nothing recognisable" over a meal it just described is the wrong answer."""
    service, fake = _service(
        db_session,
        [
            message([tool_use(TOOL_NAME, food_result(foods=[], notes="Toast and an egg."))]),
            message([tool_use(TOOL_NAME, food_result())]),
        ],
    )

    response = await service.detect_text("toast and a boiled egg")

    assert len(fake.calls) == 2, "should have asked again rather than giving up"
    assert len(response.items) == 1


async def test_an_empty_list_with_not_food_is_left_alone(db_session: AsyncSession) -> None:
    """That combination is the guardrail working, not a contradiction."""
    service, fake = _service(
        db_session,
        [message([tool_use(TOOL_NAME, food_result(input_kind="not_food", foods=[]))])],
    )

    with pytest.raises(NotFoodError):
        await service.detect_text("my dog")

    assert len(fake.calls) == 1, "a not_food refusal must not be second-guessed"


async def test_one_food_with_an_impossible_mass_does_not_lose_the_meal(
    db_session: AsyncSession,
) -> None:
    """Observed live on a five-item plate: the model returned `estimated_grams: 0`.

    Strict tool use rejects numeric bounds, so the range reaches the model as
    prose in a description and nothing on the wire forbids a zero. Validating
    the payload as a unit turned that one field into a ValidationError that
    escaped the route as a 500 and took the other four foods with it.
    """
    good = food_result()["foods"][0]
    bad = {**good, "label": "curry gravy", "estimated_grams": 0}
    service, fake = _service(
        db_session,
        [
            message([tool_use(TOOL_NAME, food_result(foods=[good, bad]))]),
            # The re-ask; this one refuses to fix it, so the salvaged list stands.
            message([tool_use(TOOL_NAME, food_result(foods=[good, bad]))]),
        ],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    response = await service.detect_text("chicken and gravy")

    assert len(fake.calls) == 2, "a dropped food should be worth asking about once"
    assert [item.detected.label for item in response.items] == ["grilled chicken breast"]


async def test_a_dropped_food_is_not_blamed_on_the_count(db_session: AsyncSession) -> None:
    """The re-ask must name the real fault. Salvage shortens the list, so the
    count check would otherwise quote back a number the model never wrote."""
    good = food_result()["foods"][0]
    bad = {**good, "estimated_grams": 0}
    service, fake = _service(
        db_session,
        [
            message([tool_use(TOOL_NAME, food_result(foods=[good, bad]))]),
            message([tool_use(TOOL_NAME, food_result(foods=[good]))]),
        ],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    await service.detect_text("chicken")

    sent = fake.calls[1]["messages"][-1]["content"][0]["content"]
    assert "estimated_grams" in sent
    assert "component" not in sent, "a food we removed ourselves is not a miscount"


async def test_naming_more_components_than_it_lists_is_asked_again(
    db_session: AsyncSession,
) -> None:
    """The failure the whole check exists for: a five-component plate coming back
    as one line of rice, which looks entirely plausible to the person logging it."""
    one = food_result()["foods"][0]
    service, fake = _service(
        db_session,
        [
            message(
                [
                    tool_use(
                        TOOL_NAME,
                        food_result(foods=[one], components=["rice", "chicken", "broccoli"]),
                    )
                ]
            ),
            message([tool_use(TOOL_NAME, food_result(foods=[one, one, one]))]),
        ],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    response = await service.detect_text("chicken, rice and broccoli")

    assert len(fake.calls) == 2
    assert len(response.items) == 3


async def test_a_count_that_agrees_is_not_second_guessed(db_session: AsyncSession) -> None:
    """One re-ask is cheap; one on every well-formed detection is not."""
    service, fake = _service(
        db_session,
        [message([tool_use(TOOL_NAME, food_result())])],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    await service.detect_text("grilled chicken breast")

    assert len(fake.calls) == 1


async def test_a_stubborn_miscount_still_returns_what_it_found(
    db_session: AsyncSession,
) -> None:
    """Re-asking is capped at one. A model that disagrees with itself twice must
    not cost the user their meal — a short list beats no list."""
    one = food_result()["foods"][0]
    short = food_result(foods=[one], components=["rice", "chicken", "peas", "gravy"])
    service, fake = _service(
        db_session,
        [message([tool_use(TOOL_NAME, short)]), message([tool_use(TOOL_NAME, short)])],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    response = await service.detect_text("a big plate")

    assert len(fake.calls) == 2, "asked once, then accepted"
    assert len(response.items) == 1


async def test_a_payload_broken_beyond_its_food_list_is_a_clean_failure(
    db_session: AsyncSession,
) -> None:
    """Nothing to salvage from a broken envelope — but it must still arrive as a
    503 the client retries, not a ValidationError escaping as a 500."""
    payload = food_result()
    del payload["components"]
    service, _ = _service(db_session, [message([tool_use(TOOL_NAME, payload)])])

    with pytest.raises(DetectionUnavailable):
        await service.detect_text("chicken")


async def test_a_re_ask_answers_the_tool_call_it_rejects(db_session: AsyncSession) -> None:
    """Measured against the live API: a re-ask sent as a plain text turn is a 400.

    Every `tool_use` block must be answered by a `tool_result` in the very next
    message, so the obvious shape — append the assistant turn, append a sentence
    — rejects the whole request and the detection dies instead of retrying.
    """
    one = food_result()["foods"][0]
    service, fake = _service(
        db_session,
        [
            message(
                [
                    tool_use(
                        TOOL_NAME,
                        food_result(foods=[one], components=["rice", "chicken", "broccoli"]),
                    )
                ]
            ),
            message([tool_use(TOOL_NAME, food_result(foods=[one, one, one]))]),
        ],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    await service.detect_text("chicken, rice and broccoli")

    reply = fake.calls[1]["messages"][-1]
    assert reply["role"] == "user"
    blocks = reply["content"]
    assert isinstance(blocks, list), "a bare string here is the shape the API rejects"
    assert [b["type"] for b in blocks] == ["tool_result"]
    assert blocks[0]["tool_use_id"] == "toolu_1"
    assert blocks[0]["is_error"] is True
    assert "component" in blocks[0]["content"]


class TestProvisionalReadings:
    """A reading the server doubts must not be frozen against the photo's hash.

    Cached, it answers that photo the same way for `detections_ttl_days` — so a
    user looking at a five-component plate rendered as one row has no way to ask
    again. "Try again" replays the failure.
    """

    async def test_a_photographed_meal_of_one_food_is_provisional(
        self, db_session: AsyncSession
    ) -> None:
        """The failure this exists for: a plate of rice, chicken, potato and
        gravy came back as 280 g of rice, with a matching one-name inventory,
        so it contradicted nothing and the list check stayed quiet."""
        one = food_result()["foods"][0]
        service, _ = _service(
            db_session,
            [message([tool_use(TOOL_NAME, food_result(foods=[one]))])],
            transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
        )

        response = await service.detect_photo(TINY_JPEG)

        assert response.is_provisional is True

    async def test_a_photo_that_found_several_foods_is_kept(
        self, db_session: AsyncSession
    ) -> None:
        """Not caching anything would make every detection cost twice."""
        one = food_result()["foods"][0]
        service, _ = _service(
            db_session,
            [message([tool_use(TOOL_NAME, food_result(foods=[one, one]))])],
            transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
        )

        response = await service.detect_photo(TINY_JPEG)

        assert response.is_provisional is False

    async def test_a_typed_single_food_is_not_second_guessed(
        self, db_session: AsyncSession
    ) -> None:
        """"a banana" is the user telling us what they ate, not us guessing from
        a plate — one item is the correct answer and worth caching."""
        one = food_result()["foods"][0]
        service, _ = _service(
            db_session,
            [message([tool_use(TOOL_NAME, food_result(foods=[one]))])],
            transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
        )

        response = await service.detect_text("a grilled chicken breast")

        assert response.is_provisional is False

    async def test_a_count_that_never_agreed_is_provisional(
        self, db_session: AsyncSession
    ) -> None:
        """Re-asking is capped at one. A reading still short after that is the
        model saying it did not list everything — worth showing, not keeping."""
        one = food_result()["foods"][0]
        short = food_result(foods=[one, one], components=["rice", "chicken", "peas", "gravy"])
        service, _ = _service(
            db_session,
            [message([tool_use(TOOL_NAME, short)]), message([tool_use(TOOL_NAME, short)])],
            transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
        )

        response = await service.detect_text("a big plate")

        assert response.is_provisional is True

    async def test_the_model_inventory_reaches_the_confirm_screen(
        self, db_session: AsyncSession
    ) -> None:
        """The inventory was written on every detection and read by nobody."""
        one = food_result()["foods"][0]
        two = {**one, "label": "a chicken leg"}
        service, _ = _service(
            db_session,
            [message([tool_use(TOOL_NAME, food_result(foods=[one, two]))])],
            transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
        )

        response = await service.detect_text("chicken")

        assert response.meal_description == "grilled chicken breast, a chicken leg"


async def test_a_second_different_fault_gets_its_own_re_ask(db_session: AsyncSession) -> None:
    """Reconstructed from a live log, where this cost the user four of five foods.

    The reply miscounted, was asked about it, and came back carrying a food with
    an unusable mass. That second fault is not the first one — but the re-ask
    budget was a single shared flag the miscount had already spent, so the bad
    food was dropped in silence and one row reached the screen.
    """
    good = food_result()["foods"][0]
    other = {**good, "label": "curry gravy"}
    bad = {**other, "estimated_grams": 0}

    service, fake = _service(
        db_session,
        [
            # Names three, lists one.
            message([tool_use(TOOL_NAME, food_result(foods=[good], components=["a", "b", "c"]))]),
            # Asked again: two foods now, but one has an impossible mass.
            message([tool_use(TOOL_NAME, food_result(foods=[good, bad]))]),
            # Asked about *that*: both usable.
            message([tool_use(TOOL_NAME, food_result(foods=[good, other]))]),
        ],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    response = await service.detect_text("chicken and gravy")

    assert len(fake.calls) == 3, "the two faults are different and each is worth asking about"
    assert len(response.items) == 2, "nothing should have been dropped in silence"

    first, second = (
        fake.calls[i]["messages"][-1]["content"][0]["content"] for i in (1, 2)
    )
    assert "component" in first
    assert "estimated_grams" in second


async def test_the_re_ask_names_the_missing_foods(db_session: AsyncSession) -> None:
    """"You named 5 but returned 1" made the model rebuild its own list from a
    digit, and it came back with two. Naming them removes that step."""
    one = food_result()["foods"][0]
    service, fake = _service(
        db_session,
        [
            message(
                [
                    tool_use(
                        TOOL_NAME,
                        food_result(foods=[one], components=["basmati rice", "onion gravy"]),
                    )
                ]
            ),
            message([tool_use(TOOL_NAME, food_result(foods=[one, one]))]),
        ],
        transport=nutrition_transport(usda=usda_food("Chicken, breast, grilled", 165.0)),
    )

    await service.detect_text("rice and gravy")

    sent = fake.calls[1]["messages"][-1]["content"][0]["content"]
    assert "basmati rice" in sent
    assert "onion gravy" in sent
