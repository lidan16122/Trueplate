"""Readiness probing, exercised through `check_readiness` itself.

Tests cross the same seam callers do. Going through the route instead would
mean spinning up FastAPI to assert on things the route does not decide — the
timeout, the concurrency, the rollback — and would leave this module reachable
only via HTTP.

Only the external dependencies are substituted: `fakeredis` for Redis, and a
stand-in session whose `execute` behaves however a case needs.
"""

import asyncio

import pytest

from app.config import settings
from app.core.readiness import ProbeResult, check_readiness


class FakeSession:
    """A session that answers `SELECT 1` however the test needs it to.

    Records whether it was rolled back, which is the behaviour a cancelled
    statement depends on and which nothing else would reveal.
    """

    def __init__(self, *, fails: Exception | None = None, hangs: bool = False) -> None:
        self._fails = fails
        self._hangs = hangs
        self.rolled_back = False

    async def execute(self, _statement):
        if self._hangs:
            await asyncio.sleep(3600)
        if self._fails:
            raise self._fails
        return object()

    async def rollback(self) -> None:
        self.rolled_back = True


class TestProbeResult:
    def test_outcome_is_a_field_not_a_string_to_compare(self):
        # The whole point of the type: callers read `.healthy` rather than
        # matching on wording that can change.
        assert ProbeResult.ok().healthy is True
        assert ProbeResult.failed("timeout").healthy is False

    def test_failure_keeps_the_reason_for_the_response_body(self):
        assert ProbeResult.failed("timeout").detail == "error: timeout"


class TestBothDependenciesUp:
    async def test_reports_healthy(self, redis):
        report = await check_readiness(FakeSession(), redis)

        assert report.healthy is True
        assert report.database == "ok"
        assert report.redis == "ok"

    async def test_does_not_roll_back_a_working_session(self, redis):
        session = FakeSession()
        await check_readiness(session, redis)
        assert session.rolled_back is False


class TestDatabaseDown:
    async def test_reports_the_exception_type_without_raising(self, redis):
        report = await check_readiness(FakeSession(fails=RuntimeError("boom")), redis)

        assert report.healthy is False
        assert report.database == "error: RuntimeError"
        # Redis is unaffected — the point of per-component detail.
        assert report.redis == "ok"

    async def test_a_failed_probe_reconciles_the_connection(self, redis):
        """Otherwise it returns to the pool mid-statement and poisons the next user."""
        session = FakeSession(fails=RuntimeError("boom"))

        await check_readiness(session, redis)

        assert session.rolled_back is True


class TestDatabaseHangs:
    async def test_a_hang_becomes_a_timeout_rather_than_hanging_the_endpoint(
        self, redis, monkeypatch
    ):
        # A probe that waits on a dead dependency is worse than one that fails:
        # an orchestrator cannot tell "slow" from "down".
        monkeypatch.setattr(settings, "health_check_timeout_seconds", 0.05)
        session = FakeSession(hangs=True)

        report = await asyncio.wait_for(check_readiness(session, redis), timeout=5)

        assert report.healthy is False
        assert report.database == "error: timeout"

    async def test_a_cancelled_statement_is_still_rolled_back(self, redis, monkeypatch):
        monkeypatch.setattr(settings, "health_check_timeout_seconds", 0.05)
        session = FakeSession(hangs=True)

        await check_readiness(session, redis)

        assert session.rolled_back is True


class UnreachableRedis:
    """Stands in for Redis the way FakeSession stands in for the database.

    `fakeredis` has no way to be "down" — closing it does not make a later ping
    fail — so an unreachable instance needs its own double. Still substituting
    the external dependency: `HealthStore` and the probe both run for real.
    """

    async def ping(self):
        raise ConnectionError("Error 22 connecting to localhost:6379")


class TestRedisDown:
    async def test_reports_redis_separately_from_the_database(self):
        report = await check_readiness(FakeSession(), UnreachableRedis())

        assert report.healthy is False
        # The database is fine, and the body says so — that separation is the
        # reason the response carries per-component detail at all.
        assert report.database == "ok"
        assert report.redis == "error: ConnectionError"

    async def test_a_healthy_database_is_not_rolled_back_when_redis_fails(self):
        session = FakeSession()
        await check_readiness(session, UnreachableRedis())
        assert session.rolled_back is False


class TestConcurrency:
    async def test_probes_run_together_not_one_after_the_other(self, redis, monkeypatch):
        """Sequential probes would bound the endpoint at 2x the stated deadline."""
        monkeypatch.setattr(settings, "health_check_timeout_seconds", 0.2)
        session = FakeSession(hangs=True)

        loop = asyncio.get_running_loop()
        started = loop.time()
        await check_readiness(session, redis)
        elapsed = loop.time() - started

        # One timeout's worth, not two. Generous upper bound so this pins the
        # concurrency without being a stopwatch test.
        assert elapsed < 0.4


@pytest.mark.parametrize("failure", [RuntimeError("boom"), ValueError("nope")])
async def test_no_dependency_failure_ever_raises_out_of_the_probe(redis, failure):
    # A readiness endpoint that 500s tells an orchestrator nothing.
    report = await check_readiness(FakeSession(fails=failure), redis)
    assert report.healthy is False
