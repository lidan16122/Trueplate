import uuid
from datetime import date
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from app.enums import DetectionMethod, MealType, NutritionSource
from app.schemas.detection import NutritionFacts

# The design shows confidence as two states, not a percentage: "Fairly sure"
# (green) or "Rough guess" (amber). The float is stored; this is where it
# collapses to what the user actually sees.
SURE_THRESHOLD = 0.75


class ConfidenceView(NamedTuple):
    """How one confidence score is shown. Both halves, or they drift apart.

    The label and the "is this rough" flag are the same decision read twice —
    computing them separately means a change to the threshold has to be made in
    two places and will eventually be made in one.
    """

    label: str | None
    is_rough: bool


def confidence_view(value: float | None) -> ConfidenceView:
    if value is None:
        # Barcode and manual entries are not estimates, so there is nothing to
        # be confident about and nothing to warn the user of.
        return ConfidenceView(label=None, is_rough=False)
    sure = value >= SURE_THRESHOLD
    return ConfidenceView(label="Fairly sure" if sure else "Rough guess", is_rough=not sure)


class FoodEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    brand: str | None
    meal_type: str
    quantity_g: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    detection_method: str
    nutrition_source: str
    detection_confidence: float | None
    confidence_label: str | None
    is_rough: bool


class MealGroupOut(BaseModel):
    meal_type: str
    calories: float
    entries: list[FoodEntryOut]


class DayLogOut(BaseModel):
    log_date: date
    groups: list[MealGroupOut]
    totals: NutritionFacts
    # Nullable because a day can be viewed before onboarding sets a target.
    target_calories: int | None
    target_protein_g: int | None
    target_carbs_g: int | None
    target_fat_g: int | None


class FoodEntryCreate(BaseModel):
    """One confirmed item from the add-food flow.

    Nutrition arrives per 100 g and is stored that way, so correcting the
    portion later is a single-field edit rather than a recomputation the client
    has to get right.
    """

    name: str = Field(min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    meal_type: MealType
    quantity_g: float = Field(gt=0, le=5000)

    # The household form of the same portion — "1.5 cups", "1 bar (40 g)".
    # Display only: grams remain what everything is computed from. Kept so the
    # day view can read "1 cup rice" rather than "158 g rice", which is the form
    # a person recognises as the thing they actually ate.
    serving_description: str | None = Field(default=None, max_length=120)

    kcal_per_100g: float = Field(ge=0, le=1000)
    protein_g_per_100g: float = Field(default=0, ge=0, le=100)
    carbs_g_per_100g: float = Field(default=0, ge=0, le=100)
    fat_g_per_100g: float = Field(default=0, ge=0, le=100)

    detection_method: DetectionMethod
    nutrition_source: NutritionSource
    source_ref: str | None = Field(default=None, max_length=64)
    detection_confidence: float | None = Field(default=None, ge=0, le=1)
    image_hash: str | None = Field(default=None, max_length=64)


class CreateEntriesRequest(BaseModel):
    entries: list[FoodEntryCreate] = Field(min_length=1, max_length=50)


class UpdateEntryRequest(BaseModel):
    """Correcting a portion after the fact.

    Editing the grams marks the entry confirmed — the design treats a user
    touching the number as the strongest signal available that it is right.
    """

    quantity_g: float = Field(gt=0, le=5000)
    meal_type: MealType | None = None


class DaySummary(BaseModel):
    """One cell of the date strip."""

    log_date: date
    calories: float
    has_entries: bool
