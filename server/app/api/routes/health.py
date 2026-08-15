import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.stores.client import get_redis
from app.stores.health import HealthStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    redis: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of one dependency check.

    A single string packing both outcome and reason ("ok" / "error: timeout")
    forces every caller to recover the boolean by string comparison, which is a
    silent break the first time the wording changes.
    """

    healthy: bool
    detail: str

    @classmethod
    def ok(cls) -> ProbeResult:
        return cls(healthy=True, detail="ok")

    @classmethod
    def failed(cls, reason: str) -> ProbeResult:
        return cls(healthy=False, detail=f"error: {reason}")


async def _check(name: str, awaitable: Awaitable[object]) -> ProbeResult:
    """Run one dependency check under a hard deadline.

    The client-level timeouts already bound a single connect, but a probe is the
    one endpoint that must never hang: an orchestrator reading a timeout cannot
    tell "slow" from "down", whereas a 503 with a reason is actionable.
    """
    try:
        await asyncio.wait_for(awaitable, timeout=settings.health_check_timeout_seconds)
    except TimeoutError:
        # Logged as well as returned: the response body is read by an
        # orchestrator, which has nowhere to put a stack trace.
        logger.warning("readiness probe timed out", extra={"probe": name})
        return ProbeResult.failed("timeout")
    except Exception as exc:  # noqa: BLE001 - reported in the body, not raised
        logger.warning("readiness probe failed", extra={"probe": name}, exc_info=exc)
        return ProbeResult.failed(type(exc).__name__)
    return ProbeResult.ok()


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
    # Concurrently, so the endpoint's worst case is one timeout rather than one
    # per dependency — a sequential pair would blow the stated deadline by 2x.
    database, cache = await asyncio.gather(
        _check("database", db.execute(text("SELECT 1"))),
        _check("redis", HealthStore(redis).ping()),
    )

    if not database.healthy:
        # A timeout cancels the SELECT mid-statement, and this route swallows
        # that so it can report a body — so nothing else will reconcile the
        # connection. Without this, it returns to the pool with the server still
        # mid-query and poisons whoever checks it out next.
        await db.rollback()

    healthy = database.healthy and cache.healthy
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if healthy else "degraded",
        database=database.detail,
        redis=cache.detail,
    )
