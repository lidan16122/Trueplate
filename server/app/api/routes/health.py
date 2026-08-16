from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.readiness import check_readiness
from app.db.session import get_db
from app.stores.client import get_redis

router = APIRouter(tags=["health"])


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    redis: str


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
    report = await check_readiness(db, redis)

    if not report.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if report.healthy else "degraded",
        database=report.database,
        redis=report.redis,
    )
