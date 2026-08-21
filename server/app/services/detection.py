"""The vision/text call, and the guardrails around it.

The model's entire contribution is names and masses. Every number the user
eventually sees is looked up by ``NutritionResolver`` from a database row — see
``schemas/detection.py`` for why that split is the product rather than a style
choice.

Two things here are easy to get wrong and expensive to discover later:

- **Thinking stays on.** On Opus 5 it is on by default, and disabling it makes
  the model occasionally write a tool call into its visible *text* instead of
  emitting a ``tool_use`` block. The turn then succeeds, the call silently never
  runs, and this pipeline — which consists entirely of reading that block — gets
  nothing back with no error to catch. Cost is controlled with ``effort``.
- **``stop_reason`` is checked before ``content``.** A safety refusal returns
  HTTP 200 with empty or partial content, so indexing ``content[0]`` raises an
  IndexError that looks nothing like the refusal it actually was.
"""

import base64
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.enums import DetectionMethod, MealType
from app.schemas.detection import (
    FoodDetectionResponse,
    FoodDetectionResult,
    NutritionFacts,
    ResolvedFoodItem,
    anthropic_tool_schema,
)
from app.services import imaging
from app.services.nutrition import NutritionResolver

logger = logging.getLogger(__name__)

TOOL_NAME = "record_detected_foods"
ZOOM_TOOL_NAME = "zoom_region"

# The model may go around the loop this many times before we give up. Each pass
# is a zoom, a web search continuation, or a paused turn resuming; a healthy
# detection uses two or three.
_MAX_TURNS = 8

# Claude Opus 5 list rates, per token. Used only to put a number in the log —
# this is observability, not billing, and it is deliberately not a config value:
# a stale price here produces a misleading log line, whereas a stale price in
# config would look authoritative.
_USD_PER_INPUT_TOKEN = 5.00 / 1_000_000
_USD_PER_OUTPUT_TOKEN = 25.00 / 1_000_000
# Cached reads bill at a tenth of the input rate; writes carry a 25% premium.
_CACHE_READ_RATE = 0.10
_CACHE_WRITE_RATE = 1.25


@dataclass
class _Spend:
    """Running token total for one detection, across every loop iteration.

    A detection is several API calls — zooms, web-search continuations, paused
    turns — and only the sum is meaningful. Reading usage off the final response
    alone silently undercounts every multi-turn detection, which are exactly the
    expensive ones.
    """

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    turns: int = 0

    def add(self, usage: Any) -> None:
        self.turns += 1
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

    @property
    def usd(self) -> float:
        billable_input = (
            self.input
            + self.cache_read * _CACHE_READ_RATE
            + self.cache_write * _CACHE_WRITE_RATE
        )
        return billable_input * _USD_PER_INPUT_TOKEN + self.output * _USD_PER_OUTPUT_TOKEN


class DetectionError(Exception):
    """Base for every failure the routes translate into a status code."""


class DetectionUnavailable(DetectionError):
    """No API key, or the upstream is unreachable. Maps to 503."""


class DetectionRefused(DetectionError):
    """The model's safety classifiers declined. Maps to 502."""


class NotFoodError(DetectionError):
    """The guardrail fired: this input is not food. Maps to 422."""


class NothingDetected(DetectionError):
    """Food, but nothing identifiable in it. Maps to 422."""


SYSTEM_PROMPT = """\
You are the food-identification step of a nutrition tracker.

Your job is to say *what* food is present and *how much* of it there is, in grams. You do \
not calculate calories, protein, carbohydrate or fat. A separate step looks those up from a \
nutrition database using the names you provide, so that every figure shown to a user traces \
back to a source. The tool schema has no field for them; supplying them anyway is the one \
thing that breaks this product.

Record your answer with the `record_detected_foods` tool.

## Classify the input first

Set `input_kind`:
- `food` — an actual meal, ingredient or drink.
- `nutrition_label` — packaging or a nutrition panel. Identify the *product*: its name and \
serving size, not the numbers printed on it.
- `menu_or_recipe` — a menu, recipe or screenshot describing food. Treat the dish described \
as the meal.
- `not_food` — anything else. Return an empty `foods` list and say what you saw in `notes`.

## Report every food

Return one entry per distinct food. "Chicken with rice and broccoli" is three entries, not \
one. Never drop an item because it is small, a side, a garnish, a sauce or a drink, and never \
fold two foods into a single entry — a missing item is a missing meal to the person logging it. \
If the input names five things, `foods` has five entries.

## Search terms are a ladder

`search_terms` goes most specific first, each rung broader than the last:
["jasmine rice steamed", "white rice cooked", "rice"]. The server walks down it until a \
database row matches, so the broad final rung is what keeps an unusual dish loggable. Always \
include one.

## Decompose dishes that will not resolve as a unit

A homemade or regional dish is a sum of ingredients: return one entry per component. \
"Mum's lasagna" becomes pasta, beef, ricotta, tomato and cheese, each with its own grams. A \
dish a food database plausibly holds as a single row — "margherita pizza", "caesar salad" — \
stays whole.

## Portions

Estimate the *edible* mass: not packaging, not bone, not the plate. Record what you based it \
on in `portion_reasoning`.

Where a food has a natural household measure, give `household_quantity` and \
`household_unit` as well ("1.5" + "cups", "2" + "slices"). Keep them consistent with your \
gram estimate — the ratio between the two is what later lets someone correct the portion by \
editing the familiar number. Leave both out when a food has no natural unit; a smear of \
sauce is not "1" of anything.

**A quantity the user states is not a guess.** "100 g of rice", "two slices", "a 330 ml can" \
— a stated amount overrides whatever you would have estimated, in a photo caption exactly as \
much as in typed text.

Set `confidence` to what you actually believe about the identification *and* the portion \
together. A confident name with a wild mass guess is not a confident entry.

## Tools

`zoom_region` returns a magnified crop of the photo. Reach for it whenever a portion is \
genuinely hard to judge — a small item, an ambiguous sauce, something partly hidden behind \
something else. Looking again is cheaper and far more accurate than guessing harder.

`web_search` is for working out *what a food is*: an unfamiliar regional dish, a brand, a \
preparation method. Never use it to look up calories or macros. Those come from the \
database, and a number read off a web page would be untraceable to any source — use what \
you learn to write a better `label` and better `search_terms` instead.\
"""


def _zoom_tool() -> dict[str, Any]:
    return {
        "name": ZOOM_TOOL_NAME,
        "description": (
            "Return a magnified crop of the meal photo. Use when a portion is hard to "
            "judge at full-frame scale. Coordinates are fractions of the image, with "
            "(0,0) at the top-left and (1,1) at the bottom-right."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "Left edge, 0-1"},
                "y": {"type": "number", "description": "Top edge, 0-1"},
                "width": {"type": "number", "description": "Width as a fraction, 0-1"},
                "height": {"type": "number", "description": "Height as a fraction, 0-1"},
                "reason": {
                    "type": "string",
                    "description": "What you are trying to see more clearly",
                },
            },
            "required": ["x", "y", "width", "height", "reason"],
            "additionalProperties": False,
        },
    }


def _web_search_tool() -> dict[str, Any]:
    return {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": settings.web_search_max_uses,
        # Scoped rather than open web. This is the control that keeps an SEO
        # recipe blog from influencing what a food is identified as — and the
        # reason the resolver can still claim provenance for every number.
        "allowed_domains": settings.web_search_allowed_domains,
    }


def _image_block(data: bytes) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": imaging.OUTPUT_MEDIA_TYPE,
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


class DetectionService:
    def __init__(self, resolver: NutritionResolver, client: AsyncAnthropic | None = None) -> None:
        self._resolver = resolver
        self._client = client

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def detect_text(
        self, description: str, meal_type: MealType | None = None
    ) -> FoodDetectionResponse:
        result = await self._run(
            [{"type": "text", "text": f"The user describes their meal as:\n\n{description}"}],
            image=None,
        )
        return await self._resolve(
            result,
            kind=DetectionMethod.TEXT,
            source_label=f"From “{description.strip()[:60]}”",
            meal_type=meal_type,
        )

    async def detect_photo(
        self,
        image: bytes,
        *,
        note: str | None = None,
        meal_type: MealType | None = None,
        image_hash: str | None = None,
    ) -> FoodDetectionResponse:
        blocks: list[dict[str, Any]] = [_image_block(image)]
        if note and note.strip():
            # After the image, because the caption qualifies what is in it — and
            # because anything volatile belongs behind the cached prefix.
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        f"The user adds: {note.strip()}\n\n"
                        "Any quantity stated here overrides your visual estimate."
                    ),
                }
            )
        else:
            blocks.append({"type": "text", "text": "Identify this meal and estimate the portions."})

        result = await self._run(blocks, image=image)
        return await self._resolve(
            result,
            kind=DetectionMethod.PHOTO,
            source_label="From your photo",
            meal_type=meal_type,
            image_hash=image_hash,
        )

    # ------------------------------------------------------------------
    # The model call
    # ------------------------------------------------------------------

    @staticmethod
    def _key_is_usable() -> bool:
        """Whether the configured key is worth sending.

        ``.env.example`` ships ``sk-ant-...`` as a placeholder, and a bare
        truthiness check treats that as configured — so every detection makes a
        round trip only to come back 401. Real keys are far longer and contain
        no ellipsis.
        """
        key = settings.anthropic_api_key.strip()
        return bool(key) and "..." not in key

    def _require_client(self) -> AsyncAnthropic:
        if self._client is not None:
            return self._client
        if not self._key_is_usable():
            raise DetectionUnavailable(
                "Food detection is not configured on this server. "
                "Set ANTHROPIC_API_KEY in the repo-root .env."
            )
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.anthropic_timeout_seconds,
        )
        return self._client

    async def _run(
        self, blocks: list[dict[str, Any]], *, image: bytes | None
    ) -> FoodDetectionResult:
        client = self._require_client()

        tools: list[dict[str, Any]] = [anthropic_tool_schema(), _web_search_tool()]
        if image is not None:
            tools.append(_zoom_tool())

        messages: list[dict[str, Any]] = [{"role": "user", "content": blocks}]
        spend = _Spend()

        for _ in range(_MAX_TURNS):
            try:
                response = await client.beta.messages.create(
                    model=settings.anthropic_model,
                    max_tokens=settings.anthropic_max_tokens,
                    # Explicit rather than relying on the default, which differs
                    # by model: omitting this runs adaptive on Opus 5 but *no*
                    # thinking on Opus 4.8, so a config change to the model id
                    # would otherwise silently alter behaviour.
                    thinking={"type": "adaptive"},
                    output_config={"effort": settings.anthropic_effort},
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            # Render order is tools -> system -> messages, so a
                            # breakpoint on the last system block caches the tool
                            # schemas with it. Everything volatile (the image, the
                            # user's words) sits after this and never invalidates it.
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=tools,
                    messages=messages,
                    # A refusal on food is unlikely, but the classifiers are not
                    # food-aware; this re-runs a declined request on a fallback
                    # model server-side instead of surfacing a dead end.
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except anthropic.RateLimitError as exc:
                raise DetectionUnavailable(
                    "Detection is busy right now. Try again shortly."
                ) from exc
            except anthropic.AuthenticationError as exc:
                # A rejected key is a deployment mistake, not a blip, and it
                # would otherwise read as "temporarily unavailable" forever.
                logger.error(
                    "Anthropic rejected the API key. Set a valid ANTHROPIC_API_KEY "
                    "in the repo-root .env; food detection is down until then."
                )
                raise DetectionUnavailable(
                    "Food detection is not configured correctly on this server."
                ) from exc
            except anthropic.APIStatusError as exc:
                logger.warning("Anthropic returned HTTP %s: %s", exc.status_code, exc.message)
                raise DetectionUnavailable("Food detection is temporarily unavailable.") from exc
            except anthropic.APIConnectionError as exc:
                raise DetectionUnavailable("Could not reach the detection service.") from exc

            spend.add(response.usage)

            if response.stop_reason == "refusal":
                # Checked before touching content: a refusal is a 200 whose
                # content may be empty or half-written.
                raise DetectionRefused("The model declined to analyse this input.")

            if response.stop_reason == "pause_turn":
                # A server-side tool (web search) hit its internal iteration
                # limit. Resuming means echoing the turn back verbatim — adding a
                # "continue" message would break the resume.
                messages.append({"role": "assistant", "content": response.content})
                continue

            tool_calls = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            final = next((b for b in tool_calls if b.name == TOOL_NAME), None)
            if final is not None:
                # One line per detection, at INFO. Output tokens dominate the
                # bill at 5x the input rate, so the split matters more than the
                # total when deciding whether to lower `effort`.
                logger.info(
                    "detection %s: %d turn(s), in=%d out=%d cache_read=%d cache_write=%d ~$%.4f",
                    "photo" if image is not None else "text",
                    spend.turns,
                    spend.input,
                    spend.output,
                    spend.cache_read,
                    spend.cache_write,
                    spend.usd,
                )
                return FoodDetectionResult.model_validate(final.input)

            zooms = [b for b in tool_calls if b.name == ZOOM_TOOL_NAME]
            if zooms and image is not None:
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": await self._zoom_results(zooms, image)})
                continue

            # Ended its turn without recording anything. One more pass with an
            # explicit nudge is cheap; a second failure is a real problem.
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Record what you found using the {TOOL_NAME} tool now.",
                }
            )

        raise DetectionUnavailable("Detection did not converge on a result.")

    async def _zoom_results(self, zooms: list[Any], image: bytes) -> list[dict[str, Any]]:
        """Crop each requested region and hand the magnified views back.

        All results go in a single user message. Splitting them across messages
        trains the model out of requesting several crops at once, which is the
        efficient shape.
        """
        results: list[dict[str, Any]] = []
        for call in zooms:
            args = call.input or {}
            try:
                crop = await run_in_threadpool(
                    imaging.crop_region,
                    image,
                    float(args.get("x", 0.0)),
                    float(args.get("y", 0.0)),
                    float(args.get("width", 1.0)),
                    float(args.get("height", 1.0)),
                )
            except (ValueError, TypeError, OSError) as exc:
                logger.info("zoom_region failed: %s", exc)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": "Could not crop that region.",
                        "is_error": True,
                    }
                )
                continue
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": [_image_block(crop)],
                }
            )
        return results

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def _resolve(
        self,
        result: FoodDetectionResult,
        *,
        kind: DetectionMethod,
        source_label: str,
        meal_type: MealType | None,
        image_hash: str | None = None,
    ) -> FoodDetectionResponse:
        if result.input_kind == "not_food":
            raise NotFoodError(result.notes or "That does not look like food.")
        if not result.foods:
            raise NothingDetected(
                result.notes or "Nothing recognisable as food was found in that."
            )

        items: list[ResolvedFoodItem] = []
        for detected in result.foods:
            items.append(await self._resolver.resolve(detected))

        totals = NutritionFacts(
            calories=sum(i.nutrition.calories for i in items),
            protein_g=sum(i.nutrition.protein_g for i in items),
            carbs_g=sum(i.nutrition.carbs_g for i in items),
            fat_g=sum(i.nutrition.fat_g for i in items),
        )

        return FoodDetectionResponse(
            detection_id=str(uuid.uuid4()),
            kind=kind,
            source_label=source_label,
            meal_type=meal_type or MealType.DINNER,
            items=items,
            totals=totals,
            image_hash=image_hash,
            cached=False,
            notes=result.notes,
        )
