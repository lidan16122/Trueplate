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
    estimated_grams: float = Field(gt=0, le=5000, description="Estimated edible mass in grams")
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
        description="What the estimate was based on, e.g. 'covers half a 26cm plate'",
    )


class FoodDetectionResult(BaseModel):
    """The complete tool-use payload.

    Note the absence of any nutrition field. This model is turned into the
    Anthropic tool ``input_schema`` via ``model_json_schema()``, so the schema is
    the enforcement mechanism, not a convention someone has to remember.
    """

    model_config = ConfigDict(extra="forbid")

    foods: list[DetectedFood] = Field(default_factory=list)
    meal_description: str = Field(default="", description="One-line summary of the plate")
    overall_confidence: float = Field(default=0.0, ge=0, le=1)
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


def anthropic_tool_schema() -> dict:
    """The tool definition to hand to the Claude API.

    Generated from the Pydantic model so the two can never drift. Paired with
    ``strict: true``, which requires ``additionalProperties: false`` — supplied
    by the models' ``extra="forbid"``.
    """
    return {
        "name": "record_detected_foods",
        "description": (
            "Record the foods visible in the meal and estimate the edible mass of each "
            "in grams. Do not estimate calories or macronutrients — those are looked up "
            "from a nutrition database using the labels and search terms you provide."
        ),
        "strict": True,
        "input_schema": FoodDetectionResult.model_json_schema(),
    }
