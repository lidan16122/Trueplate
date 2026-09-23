"""Read-only evidence supplied to the response model after nutrition resolution."""

from pydantic import BaseModel, ConfigDict

from app.schemas.detection import NutritionFacts, NutritionMatch
from app.schemas.grounding import GroundedStatement


class NutritionEvidence(BaseModel):
    """The chosen source snapshot and backend portion calculation for one detected food."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    item_index: int
    label: str
    estimated_grams: float
    record: NutritionMatch | None
    portion: NutritionFacts | None
    is_rough: bool


class NutritionContext(BaseModel):
    """Missing records stay explicit rather than masquerading as zero-calorie foods."""

    model_config = ConfigDict(extra="forbid")

    items: list[NutritionEvidence]
    matched_totals: NutritionFacts
    is_provisional: bool
    facts: list[GroundedStatement]
    required_fact_ids: list[str]
