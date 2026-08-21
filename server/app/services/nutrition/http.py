"""One shared HTTP client for every outbound nutrition lookup.

Mirrors ``stores/client.py``: a pooled client built once for the process, torn
down in the app lifespan. Creating an ``AsyncClient`` per request would re-do
the TLS handshake on every food we resolve — and a single detection resolves
several — which is the difference between a fast confirm screen and a slow one.
"""

import httpx

from app.config import settings

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """The shared client, created on first use.

    Lazy rather than module-level so importing this module never opens a socket —
    which is what lets the test suite import the app without a network stack.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            # Every external client in this app carries a timeout. httpx's own
            # default is None, so a hung upstream would pin a worker forever and
            # present as an app outage rather than a USDA outage.
            timeout=httpx.Timeout(settings.nutrition_timeout_seconds),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
