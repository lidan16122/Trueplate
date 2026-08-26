FROM python:3.14-slim-bookworm

# Pinned rather than :latest — Render caches build layers, and a floating tag
# lets a silent toolchain change ride in on a cache hit.
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

# Not optional, and not about barcodes. pyzbar loads libzbar.so.0 through ctypes
# at module scope and app.main reaches it via the router, so without this the app
# fails to *boot* — an ImportError before the port binds, not a 500 from the scan
# endpoint. The Linux wheel is a 32 kB ctypes shim with no library inside; the
# Windows wheels bundle the DLLs, which is why this never surfaces locally.
#
# bookworm rather than trixie for this package specifically: Debian 12 still
# names it `libzbar0`, where trixie and Ubuntu 24.04 renamed it `libzbar0t64` in
# the 64-bit time_t transition.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libzbar0 \
 && rm -rf /var/lib/apt/lists/*

# Nested one level deep so app/config.py's REPO_ROOT — Path(__file__).parents[2]
# — lands on /app instead of /. Nothing reads a .env in the image (Render supplies
# real environment variables, and pydantic-settings ignores a missing env_file),
# but a coherent path costs one line.
WORKDIR /app/server

# Dependencies before source, so editing a route does not re-resolve the tree.
# --no-dev drops pytest, ruff, fakeredis, aiosqlite and python-barcode, none of
# which a serving process needs.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev

ENV PATH="/app/server/.venv/bin:$PATH"

# Shell form on purpose: the exec-form array would hand uvicorn the literal string
# "$PORT". --host 0.0.0.0 is mandatory — uvicorn defaults to 127.0.0.1, which is
# unreachable from outside the container. No --reload: it is a dev flag, and on
# Linux it forces a selector loop in place of uvloop.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
