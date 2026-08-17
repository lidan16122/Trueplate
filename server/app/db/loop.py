"""Which event loop the async Postgres driver can actually run on.

Deliberately separate from ``session.py``: an entrypoint needs this answer
*before* it starts a loop, and importing ``session`` would build an engine as a
side effect just to ask the question.
"""

import asyncio
import sys
from collections.abc import Callable


def psycopg_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """The ``loop_factory`` any ``asyncio.run`` driving this engine must pass.

    psycopg refuses to run in async mode on Windows' ``ProactorEventLoop`` — it
    raises ``InterfaceError`` before resolving a single connection parameter —
    and that is exactly the loop ``asyncio.run`` builds from the default policy
    there. The server escapes it only by accident: uvicorn picks a selector loop
    when ``--reload`` or ``--workers>1`` is set, which the documented dev command
    happens to pass. Every other entrypoint is unshielded, so each asks here
    rather than rediscovering the failure against a live database.

    ``None`` elsewhere, because those platforms already default to a selector
    loop and naming one explicitly would override a deliberate uvloop choice.
    """
    return asyncio.SelectorEventLoop if sys.platform == "win32" else None
