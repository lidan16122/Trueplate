"""Can this instance serve traffic?

One question, one call. The route that answers it should not also know how a
Postgres liveness check is spelled, how long to wait, how to run two probes
concurrently, or what a cancelled statement does to a pooled connection —
those are the reasons this module exists rather than six lines in the handler.

Adding a third dependency later is a change here and nowhere else.
"""

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import health, transaction
from app.stores.health import HealthStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of one dependency check.

    Two fields rather than one string: packing outcome and reason together
    ("ok" / "error: timeout") forces every caller to recover the boolean by
    string comparison, which breaks silently the first time the wording changes.
    """

    healthy: bool
    detail: str

    @classmethod
    def ok(cls) -> ProbeResult:
        return cls(healthy=True, detail="ok")

    @classmethod
    def failed(cls, reason: str) -> ProbeResult:
        return cls(healthy=False, detail=f"error: {reason}")


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    healthy: bool
    database: str
    redis: str


async def _probe(name: str, awaitable: Awaitable[object]) -> ProbeResult:
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


async def check_readiness(db: AsyncSession, redis: Redis) -> ReadinessReport:
    """Probe every dependency this instance needs, concurrently."""
    # Concurrently, so the worst case is one timeout rather than one per
    # dependency — a sequential pair would blow the stated deadline by 2x.
    database, cache = await asyncio.gather(
        # Both probes use storage adapters so this workflow controls deadlines
        # without depending on the statement or command used to check liveness.
        _probe("database", health.ping(db)),
        _probe("redis", HealthStore(redis).ping()),
    )

    if not database.healthy:
        # A timeout cancels the SELECT mid-statement, and we swallow that to
        # report a body — so nothing else will reconcile the connection. Without
        # this it returns to the pool with the server still mid-query and
        # poisons whoever checks it out next.
        await transaction.rollback(db)

    return ReadinessReport(
        healthy=database.healthy and cache.healthy,
        database=database.detail,
        redis=cache.detail,
    )
