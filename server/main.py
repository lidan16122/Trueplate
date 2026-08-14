"""Convenience entrypoint so ``fastapi dev main.py`` works from ``server/``.

The application itself lives in ``app.main``.
"""

from app.main import app

__all__ = ["app"]
