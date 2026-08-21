"""The contract between the vision model, the nutrition database, and the UI.

The central rule of this app lives here: **the model never produces a calorie
number.** ``FoodDetectionResult`` — everything Claude is allowed to return — has
no energy or macro field anywhere in it. The model identifies foods and
estimates mass; the server then looks each one up and does the arithmetic.

That split is what makes the numbers defensible. A language model asked for
"calories in this photo" will produce a confident, plausible, unsourced figure.
Asked only "what is this and roughly how many grams", it is doing something it
is actually good at, and every calorie shown to the user traces back to a
database row.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums import DetectionMethod, MealType

Preparation = Literal["raw", "grilled", "fried", "baked", "boiled", "steamed", "roasted", "unknown"]

# What the submitted photo or sentence actually *is*. The guardrail against
# non-food input lives here, in the schema, rather than as a "please refuse"
# line in the system prompt: a refusal the model writes in prose is free text we
# would have to parse, whereas a field the model must fill is a typed outcome
# the server decides on.
#
# Three of the four are accepted. Users legitimately point a food app at a
# nutrition label, a menu, or a recipe screenshot — none of those are food, and
# a strict food-image classifier that rejects all three makes the feature feel
# broken. They resolve the same way everything else does: read the product or
# dish name, then look the nutrition up. Only ``not_food`` is refused.
InputKind = Literal["food", "nutrition_label", "menu_or_recipe", "not_food"]

# A closed set rather than a free string, and that is a correctness fix rather
# than tidiness: as free text this field attracted the model's justification for
# its own arithmetic — a paragraph of repeated half-sentences — which consumed
# the output budget and left the remaining foods unreported. An enum cannot hold
# a paragraph. `enum` is one of the few constraints strict tool use does accept,
# so unlike the numeric bounds this one survives into the wire schema.
HouseholdUnit = Literal[
    "cup",
    "tbsp",
    "tsp",
    "slice",
    "piece",
    "medium",
    "small",
    "large",
    "bowl",
    "plate",
    "glass",
    "can",
    "bottle",
    "scoop",
    "handful",
    "fillet",
    "egg",
]


# --------------------------------------------------------------------------
# What the model is allowed to return
# --------------------------------------------------------------------------


class DetectedFood(BaseModel):
    """One food the model believes is present.

    ``extra="forbid"`` propagates into the generated JSON Schema as
    ``additionalProperties: false``, which strict tool use requires — without it
    the model may invent fields, including the calorie field this design exists
    to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="Everyday name of the food, e.g. 'grilled chicken breast'")
    # The bounds are enforced on the way back in, not advertised in the tool
    # schema — strict tool use rejects numeric constraints. The range lives in
    # the description so the model still knows what is plausible.
    estimated_grams: float = Field(
        gt=0, le=5000, description="Estimated edible mass in grams, between 0 and 5000"
    )
    confidence: float = Field(
        ge=0, le=1, description="0-1 confidence in this identification and portion"
    )
    preparation: Preparation = Field(
        default="unknown", description="Cooking method, which changes the nutrition lookup"
    )
    search_terms: list[str] = Field(
        default_factory=list,
        description="Terms to query the nutrition database with, most specific first",
    )
    portion_reasoning: str | None = Field(
        default=None,
        description=(
            "One short sentence on what the estimate was based on, e.g. "
            "'covers half a 26cm plate'. Not a place to show your working."
        ),
    )

    # Nobody can correct "158 g", but everyone can correct "1 cup". These carry a
    # familiar handle for the same mass so the confirm screen has something a
    # person can actually reason about.
    #
    # Grams stay authoritative and there is no density table anywhere: the ratio
    # ``estimated_grams / household_quantity`` is the grams-per-unit for *this*
    # food in *this* photo, so editing 1.5 cups to 2 rescales grams by the
    # model's own anchor. That sidesteps "1 cup of rice != 1 cup of spinach"
    # entirely — we never convert between units, only scale within one.
    #
    # Optional on purpose, and deliberately absent from ``required``: a smear of
    # sauce is not "1" of anything, and forcing a unit invents one.
    household_quantity: float | None = Field(
        default=None,
        gt=0,
        description="How many household units, greater than 0 — e.g. 1.5 for '1.5 cups'",
    )
    household_unit: HouseholdUnit | None = Field(
        default=None,
        description="Familiar measure this food is naturally counted in. Omit if none fits.",
    )


class FoodDetectionResult(BaseModel):
    """The complete tool-use payload.

    Note the absence of any nutrition field. This model is turned into the
    Anthropic tool ``input_schema`` via ``model_json_schema()``, so the schema is
    the enforcement mechanism, not a convention someone has to remember.

    Every field below except ``notes`` is required, and that is load-bearing
    rather than tidiness: strict tool use demands ``additionalProperties: false``
    **and** a ``required`` array, and Pydantic only emits a field as required
    when it has no default. Giving ``foods`` a ``default_factory`` — the obvious,
    harmless-looking choice — silently drops ``required`` from the generated
    schema and the API rejects the tool. Do not add defaults here.
    """

    model_config = ConfigDict(extra="forbid")

    input_kind: InputKind = Field(
        description=(
            "What was submitted. Use 'food' for an actual meal or ingredient; "
            "'nutrition_label' for a packaging label; 'menu_or_recipe' for a menu, "
            "recipe or screenshot describing food; 'not_food' for anything else. "
            "When this is 'not_food', return an empty foods list."
        )
    )
    foods: list[DetectedFood]
    meal_description: str = Field(description="One-line summary of the plate")
    overall_confidence: float = Field(
        ge=0, le=1, description="0-1 confidence in the reading of the meal as a whole"
    )
    notes: str | None = Field(
        default=None, description="Anything unidentifiable, e.g. 'sauce could not be identified'"
    )


# --------------------------------------------------------------------------
# What the server sends back, after resolving nutrition
# --------------------------------------------------------------------------


class NutritionFacts(BaseModel):
    """Resolved totals for one portion.

    Server-filled, and the app's most-used value type — the food log imports it
    from here rather than declaring its own, so the two shapes cannot drift.
    Note this is a *response* type: it never appears in the tool schema the
    model fills in.
    """

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class NutritionMatch(BaseModel):
    """A candidate row from the nutrition database."""

    food_id: str | None = None
    name: str
    brand: str | None = None
    source: str
    source_ref: str | None = None
    kcal_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float


class ResolvedFoodItem(BaseModel):
    """One row of the confirmation screen."""

    detected: DetectedFood
    matched: NutritionMatch | None
    # Computed server-side from `matched` scaled to `detected.estimated_grams`.
    nutrition: NutritionFacts
    # Offered so a wrong match is one tap to fix rather than a re-shoot.
    alternatives: list[NutritionMatch] = Field(default_factory=list)
    confidence_label: str
    is_rough: bool


class FoodDetectionResponse(BaseModel):
    """Everything the confirm screen needs, in the shape the design expects."""

    detection_id: str
    kind: DetectionMethod
    # Human provenance line, e.g. "From your photo".
    source_label: str
    meal_type: MealType
    items: list[ResolvedFoodItem]
    totals: NutritionFacts
    image_hash: str | None = None
    # True when this came from the AI cache rather than a fresh model call.
    cached: bool = False
    notes: str | None = None

    @property
    def rough_count(self) -> int:
        return sum(1 for item in self.items if item.is_rough)


class TextDetectionRequest(BaseModel):
    description: str = Field(min_length=2, max_length=500)
    meal_type: MealType | None = None


# Strict tool use accepts only a subset of JSON Schema. Numeric bounds and
# string/array length constraints are rejected outright — the API answers
# "For 'number' type, properties exclusiveMinimum, maximum are not supported"
# and the whole request 400s.
#
# Pydantic emits these from `Field(gt=0, le=5000)` and friends, so they have to
# come off on the way out. They are *not* removed from the models: the bounds
# still run when `model_validate` parses what the model sent back. The schema
# stops being the enforcement point and becomes advisory; validation moves to
# where it can reject a bad value rather than merely discourage one.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
)


def _strip_unsupported(node: object) -> object:
    """Recursively drop constraint keywords strict tool use rejects."""
    if isinstance(node, dict):
        return {
            key: _strip_unsupported(value)
            for key, value in node.items()
            if key not in _UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(node, list):
        return [_strip_unsupported(item) for item in node]
    return node


def anthropic_tool_schema() -> dict:
    """The tool definition to hand to the Claude API.

    Generated from the Pydantic model so the two can never drift. Paired with
    ``strict: true``, which requires ``additionalProperties: false`` — supplied
    by the models' ``extra="forbid"`` — and a populated ``required`` array,
    supplied by those fields having no defaults.

    The bounds Pydantic would emit are stripped here; see
    ``_UNSUPPORTED_SCHEMA_KEYS``. Field descriptions carry the range in prose
    instead, so the model still knows what a plausible value looks like.
    """
    return {
        "name": "record_detected_foods",
        "description": (
            "Record the foods visible in the meal and estimate the edible mass of each "
            "in grams. Do not estimate calories or macronutrients — those are looked up "
            "from a nutrition database using the labels and search terms you provide."
        ),
        "strict": True,
        "input_schema": _strip_unsupported(FoodDetectionResult.model_json_schema()),
    }
