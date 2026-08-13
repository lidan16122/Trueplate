import asyncio
from collections.abc import Awaitable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.stores.client import get_redis

router = APIRouter(tags=["health"])


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    redis: str


async def _probe(awaitable: Awaitable[object]) -> str:
    """Run one dependency check under a hard deadline.

    The client-level timeouts already bound a single connect, but a probe is the
    one endpoint that must never hang: an orchestrator reading a timeout cannot
    tell "slow" from "down", whereas a 503 with a reason is actionable.
    """
    try:
        await asyncio.wait_for(awaitable, timeout=settings.health_check_timeout_seconds)
        return "ok"
    except TimeoutError:
        return "error: timeout"
    except Exception as exc:  # noqa: BLE001 - reported in the body, not raised
        return f"error: {type(exc).__name__}"


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: is the process up and serving? Always 200.

    Deliberately touches no dependency — a restart loop triggered by a
    transient database blip is worse than the blip.
    """
    return {"status": "ok"}


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ReadinessResponse:
    """Readiness: can this instance actually serve traffic?

    Returns 503 when a dependency is down, with per-component detail so the
    failing one is obvious without reading logs.
    """
    database = await _probe(db.execute(text("SELECT 1")))
    redis_status = await _probe(redis.ping())

    healthy = database == "ok" and redis_status == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if healthy else "degraded",
        database=database,
        redis=redis_status,
    )
