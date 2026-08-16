"""Test bootstrap, loaded before anything under ``tests/`` is imported.

``app.config`` builds its ``Settings`` at import time, and ``JWT_SECRET_KEY``
deliberately has no default — a deploy that forgets it must fail to boot rather
than sign real tokens with a value published in this repo. That is right for
production and wrong for a test run: the root ``.env`` is gitignored, so a fresh
clone or a CI job has nothing to supply it and the whole suite fails to collect
before a single test runs.

Setting it here keeps both properties. The value is obviously fake and never
leaves the process; anything actually exercising signing mints and verifies with
this same key, so nothing is weakened by it being known.

This file sits at the rootdir rather than in ``tests/`` on purpose: pytest
imports the rootdir conftest before collecting, which is the only point early
enough to beat the import chain.
"""

import os

# setdefault, not assignment: a real environment (a developer with a .env, or CI
# with a secret configured) keeps whatever it already set.
os.environ.setdefault("JWT_SECRET_KEY", "test-only-key-not-used-outside-the-suite-0123456789")
