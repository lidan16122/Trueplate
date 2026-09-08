"""HTTP readiness representation; probe decisions are application data."""

from typing import Literal

from pydantic import BaseModel


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    redis: str
