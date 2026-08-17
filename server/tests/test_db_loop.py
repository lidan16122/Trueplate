"""The async driver rejects one event loop, and only some entrypoints are shielded.

Regression cover for a bug that reached a live database first: `alembic upgrade
head` and `scripts.seed` both died on Windows against real Postgres while the
whole suite stayed green, because neither the suite nor CI on Linux can build
the loop that breaks them.
"""

import asyncio
import sys

import pytest

from app.db.loop import psycopg_loop_factory


@pytest.mark.skipif(sys.platform != "win32", reason="ProactorEventLoop is Windows-only")
def test_windows_entrypoints_get_a_loop_psycopg_accepts() -> None:
    factory = psycopg_loop_factory()
    assert factory is not None, "Windows must name a loop; the default one fails"

    loop = factory()
    try:
        # psycopg's guard verbatim (connection_async.py): it raises InterfaceError
        # when the running loop is a ProactorEventLoop, before it resolves any
        # connection parameter. Asserting the same predicate keeps this honest
        # without needing a database to connect to.
        assert not isinstance(loop, asyncio.ProactorEventLoop)
    finally:
        loop.close()


@pytest.mark.skipif(sys.platform == "win32", reason="covered by the Windows case above")
def test_other_platforms_keep_whatever_loop_the_runner_chose() -> None:
    # Returning a loop here would quietly override a uvloop runner, and the
    # default on these platforms is already a selector loop psycopg accepts.
    assert psycopg_loop_factory() is None
