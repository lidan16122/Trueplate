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
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.config import settings
from app.enums import DetectionMethod, MealType
from app.schemas.detection import (
    DetectedFood,
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

Return one entry per distinct food. "Chicken with rice and broccoli" is three entries; \
"toast with avocado and a boiled egg" is three entries. Never drop an item because it is \
small, a side, a garnish, a spread, a sauce or a drink, and never fold two foods into a \
single entry — a missing item is a missing meal to the person logging it.

Fill the tool in the order its fields are listed: name every food you can see in \
`components`, one short phrase each, then give `foods` exactly one entry per name. The \
server compares the two lists and hands the reply straight back to you naming what is \
missing, so a short list costs a whole extra round trip and gets caught anyway.

`components` is not a summary you write afterwards. Write it first, from the image, and \
then work down it.

A dish named as a combination ("toast with X and Y") is still its components. Silently \
reporting one of three is the most damaging mistake you can make here, because the user \
sees a plausible answer and has no idea anything is missing.

## Search terms are a ladder

`search_terms` is how a food gets looked up, and it is **not** a description of the plate. \
The database indexes foods, not meals. Name the food and how it was cooked; leave out the \
dish it was part of, the sauce it was sitting in, and filler like "only", "pieces" or \
"slices".

- "chicken drumstick curry meat only" → "chicken drumstick cooked"
- "potato cooked in curry" → "potato boiled"
- "onion masala gravy" → "curry sauce"

Go most specific first, each rung broader than the last: \
["basmati rice steamed", "white rice cooked", "rice"]. The server walks down until a \
database row matches.

The last rung must be a plain generic food a database certainly holds — one or two ordinary \
words, no brand, no cuisine, no cooking method. It is the only thing standing between an \
unusual component and no nutrition at all: an item that matches nothing is shown to the user \
and then dropped from the meal, so its calories vanish quietly. Always include one.

None of this costs you any detail: `label` is where the food's real description belongs — \
"pulled chicken in masala" — and `label` is what the user actually reads. Only the lookup \
terms need to be plain.

## One entry per component you can see

A plate is a list of parts, not a dish name. Return one entry for everything you can see and \
point at, each with its own grams: the rice, each piece of meat, each vegetable, the sauce. \
"Chicken curry with rice" is not one entry and it is not two — it is the rice, the chicken, \
whatever vegetables are in it, and the gravy, separately. "Mum's lasagna" is pasta, beef, \
ricotta, tomato and cheese.

**The same food in two forms is two entries.** A bone-in leg and the pulled pieces beside it \
are separately visible and separately weighable, so they are separate lines — as are roast \
potatoes and mash on one plate.

**A sauce, gravy, dressing or masala is a component, not a seasoning.** It carries most of \
the oil in a dish and is usually the largest single source of error in the whole reading, so \
give it its own entry and its own mass.

One entry is right only when the food arrives as a single indivisible thing: an apple, a \
canned drink, a packaged bar, a sandwich or burger whose parts you cannot see separately. Do \
not ask yourself whether a nutrition database might hold the dish as one row — that is the \
server's problem, and answering it here is what makes a whole meal come back as one line.

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

# Everything that determines the *shape* of an answer, in sixteen characters:
# the instructions and the schema they are filled into. `detection_cache` folds
# this into its keys so that editing either one retires the readings it would
# otherwise keep serving for `detections_ttl_days`.
#
# Without it a prompt change is invisible on exactly the photos that matter —
# the ones already submitted, which is every photo anyone complained about.
# The tool schema is included because field *order* is load-bearing here (see
# `FoodDetectionResult`), and a reorder changes the answer while leaving the
# prompt byte-identical.
PROMPT_FINGERPRINT = hashlib.sha256(
    (SYSTEM_PROMPT + json.dumps(anthropic_tool_schema(), sort_keys=True)).encode("utf-8")
).hexdigest()[:16]


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
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        "Analyse each portion of food in this photo. Name every component "
                        "you can see, then give the weight of each one."
                    ),
                }
            )

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
        # One re-ask per *kind* of fault, not one per detection. `_self_contradiction`
        # names three, so this self-caps at three re-asks — well inside `_MAX_TURNS`
        # — and a clean detection still costs a single turn. A fault already raised
        # is accepted as final: the model has had its say on that one.
        raised: set[str] = set()

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
                # `stop_reason` rides along because the expensive failure here
                # is a *silent* one: a food list truncated by the output budget
                # returns a perfectly valid result with items missing, and the
                # only distinguishing evidence is `max_tokens` next to an output
                # count sitting on the ceiling.
                logger.info(
                    "detection %s: %d turn(s), stop=%s, in=%d out=%d/%d "
                    "cache_read=%d cache_write=%d ~$%.4f",
                    "photo" if image is not None else "text",
                    spend.turns,
                    response.stop_reason,
                    spend.input,
                    spend.output,
                    settings.anthropic_max_tokens,
                    spend.cache_read,
                    spend.cache_write,
                    spend.usd,
                )
                try:
                    result, dropped = self._parse_result(final.input)
                except ValidationError as exc:
                    # The envelope itself is unusable, not just one item. A 503
                    # is the honest answer — the client already retries it,
                    # where an escaping ValidationError is a 500 and reads to
                    # the user as "this app is broken".
                    logger.warning("Unparseable detection payload: %s", exc)
                    raise DetectionUnavailable(
                        "Detection came back in a shape we could not read. Try again."
                    ) from exc

                # Ways the model contradicts itself, each worth one re-ask. Only
                # when it claims food: an empty list *with* `not_food` is the
                # guardrail working exactly as designed.
                complaint = self._self_contradiction(result, dropped=dropped)
                if complaint is not None and complaint[0] not in raised:
                    kind, message = complaint
                    raised.add(kind)
                    logger.info("Re-asking (%s): %s", kind, message)
                    messages.append({"role": "assistant", "content": response.content})
                    # The complaint travels as a `tool_result`, not as a plain
                    # text turn. Every `tool_use` block must be answered by a
                    # `tool_result` in the very next message or the API rejects
                    # the whole request — so the text-message version of this
                    # 400s instead of re-asking. It also reads correctly: the
                    # recording tool rejected what it was given.
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": message if block is final else "Superseded.",
                                    **({"is_error": True} if block is final else {}),
                                }
                                for block in tool_calls
                            ],
                        }
                    )
                    continue

                return result

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

    @staticmethod
    def _self_contradiction(
        result: FoodDetectionResult, *, dropped: int
    ) -> tuple[str, str] | None:
        """``(kind, message)`` when the reply does not hold together, else None.

        Every case here is answerable by looking again at what was already
        written, which is why re-asking works at all — there is nothing to look
        up, only an inconsistency to notice.

        The ``kind`` is what gives each fault its own attempt. Sharing one
        allowance across all of them meant the first complaint spent it and any
        *later, different* complaint went unasked: a miscount was queried, the
        reply came back carrying a food with an unusable mass, and that food was
        dropped in silence because there was no budget left to question it.
        """
        if result.input_kind == "not_food":
            return None

        if dropped:
            # Ordered before the count check on purpose. A salvaged list is
            # short because *we* removed something, so complaining that the
            # count disagrees would be blaming the model for our own edit — and
            # would send back a number it never wrote.
            return (
                "dropped",
                f"{dropped} of your entries had an unusable `estimated_grams`; it must be "
                "an edible mass in grams, greater than zero. Send the full list again "
                "with a real mass on every entry.",
            )

        if not result.foods:
            # Observed on the text path: it classifies the input as food, writes
            # `notes` describing the very items it saw, and hands back nothing.
            return (
                "empty",
                f"You reported no foods, but classified this as '{result.input_kind}'. "
                "List every distinct food in `foods`, one entry each. If it genuinely "
                "contains no food, set input_kind to 'not_food'.",
            )

        if len(result.components) != len(result.foods):
            # Names the foods rather than counting them. The arithmetic version
            # of this message — "you named 5 but returned 1" — made the model
            # rebuild its own list from a digit, and it came back with two.
            missing = [
                name
                for name in result.components
                if not any(name.lower() in food.label.lower() for food in result.foods)
            ]
            named = ", ".join(result.components)
            return (
                "count",
                f"You named {len(result.components)} component(s) — {named} — but `foods` "
                f"holds {len(result.foods)} entry/entries"
                + (f", missing: {', '.join(missing)}" if missing else "")
                + ". Return one entry per name, each with its own grams.",
            )

        return None

    @staticmethod
    def _parse_result(payload: Any) -> tuple[FoodDetectionResult, int]:
        """Parse the tool payload, dropping only the foods that do not stand up.

        Returns the result and how many entries were dropped. The caller needs
        that number: a salvaged list is a *short* list, and silently accepting
        it is the missing-item failure this pipeline exists to avoid.

        Strict tool use rejects numeric bounds, so ``estimated_grams`` reaches
        the model as prose — "between 0 and 5000" in a description — rather than
        as schema it must obey. It has been observed returning ``0``, which is
        the one value the description rules out and the wire schema cannot.

        Validating the payload as a unit turns that single bad field into a
        ValidationError that loses the entire meal. This is the same trade the
        resolver makes for an unmatched sauce: one unusable item is worth
        dropping, and the four good ones beside it are not worth losing with it.
        """
        try:
            return FoodDetectionResult.model_validate(payload), 0
        except ValidationError:
            if not isinstance(payload, dict):
                raise

        kept = []
        dropped = 0
        for entry in payload.get("foods") or []:
            try:
                DetectedFood.model_validate(entry)
            except ValidationError:
                dropped += 1
                continue
            kept.append(entry)

        if dropped:
            # Warned rather than logged at info: this is the model breaking a
            # rule it was told in prose, and how often it happens decides
            # whether the rule needs to move somewhere it can be enforced.
            logger.warning("Dropped %d food(s) that failed validation", dropped)

        # Anything still wrong is in the envelope — a missing meal_description,
        # an unknown input_kind — and there is nothing to salvage from that.
        return FoodDetectionResult.model_validate({**payload, "foods": kept}), dropped

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
            # The model's inventory, joined for display. The confirm screen wants
            # a line, not an array, and this keeps the names it actually wrote
            # rather than paraphrasing them.
            meal_description=", ".join(result.components),
            items=items,
            totals=totals,
            image_hash=image_hash,
            cached=False,
            is_provisional=self._looks_under_reported(result, kind),
            notes=result.notes,
        )

    @staticmethod
    def _looks_under_reported(result: FoodDetectionResult, kind: DetectionMethod) -> bool:
        """Whether this reading is too doubtful to freeze in the cache.

        Two shapes, and the second is the one that costs a user their meal.

        A list still shorter than the names it wrote, after every re-ask those
        faults were owed, is the model telling us outright that it did not report
        everything it saw.

        A *photographed* meal returning exactly one food is the failure this
        exists for: a five-component plate came back as 280 g of rice. There is
        not always a signal inside the reply to catch that — only the prior that
        a plate of food is rarely one thing.

        Restricted to photos, and to `food`: a nutrition label or a menu
        legitimately resolves to a single product, and the typed path is the
        user telling us what they ate rather than us guessing.
        """
        if len(result.components) != len(result.foods):
            return True
        return (
            kind == DetectionMethod.PHOTO
            and result.input_kind == "food"
            and len(result.foods) == 1
        )
