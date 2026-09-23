"""The model selects evidence; only the server supplies sentences and nutrition values."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GroundedResponsePlan(BaseModel):
    """A bounded selection of facts, with no channel for model-written nutrition or prose."""

    model_config = ConfigDict(extra="forbid", strict=True)

    fact_ids: list[str] = Field(min_length=1, max_length=5)


class GroundedStatement(BaseModel):
    """A server-rendered fact citing zero-based positions in the response's items."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    text: str
    item_indices: list[int]


class GroundedNutritionResponse(BaseModel):
    """Generated means Claude selected the facts; fallback means the server selected them."""

    model_config = ConfigDict(extra="forbid")

    # This is a generation outcome, not a claim that a match or portion is certain.
    status: Literal["generated", "fallback"]
    statements: list[GroundedStatement]
