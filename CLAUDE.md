# Trueplate — working agreements

Conventions this codebase follows that its tooling cannot express. Ruff, tsc, and
`pyproject.toml` are the source of truth for anything mechanical — read them rather
than duplicating them here.

## The one invariant

**The model never produces a nutrition number.** It contributes a food label and an
estimated mass in grams; the server resolves calories and macros from a database row.

`app/schemas/detection.py` enforces this structurally rather than by convention:
`FoodDetectionResult` has no energy or macro field, and `extra="forbid"` becomes
`additionalProperties: false` in the generated tool schema, so a model that volunteers
`"calories": 450` is rejected instead of believed. Adding a nutrition field to anything
the model fills in defeats the product — every calorie shown to a user must trace to a
source row.

## Nutrition data is per 100 g

Every table, schema, and component that carries nutrition stores it **per 100 g**
alongside a separate quantity in grams. Never a pre-multiplied total.

This is what lets a corrected portion recompute with a single-field edit, and it means
the photo path (grams) and the barcode path (servings) scale through identical code.
`food_entries` keeps its per-100 g values as a *snapshot*, not a foreign key — a later
upstream revision must not silently rewrite a day already logged.

## Store inputs, derive the rest

`user_profiles` holds birth date, sex, height, and activity level. It does not hold BMR,
TDEE, or a calorie target, because those are outputs of a formula that will change.

Two consequences worth knowing:

- Age is stored as a birth date. An age integer is a snapshot that silently goes stale.
- `goals` snapshots its computed targets on purpose — they are the numbers the user was
  held to. Superseding a goal closes the old row and opens a new one; mutating it in
  place rewrites history.

`app/core/nutrition.py` is pure functions over raw values: no I/O, no ORM.

## Backend

**Comments carry the reason, not the mechanics.** The density here is deliberate and high
— match it. State why a choice was made, what breaks without it, or what a reader would
otherwise assume wrongly. The code already shows what it does.

**Redis access lives behind a store** in `app/stores/`, one file per use case. Routes and
services talk to a store, never to a Redis client. Deliberately *not* cached: user
profiles, goals, and day totals — cheap Postgres queries whose caching would buy an
invalidation problem for nothing.

**A multi-step Redis mutation that must not interleave goes in Lua.** A pipeline is not
atomic. `stores/refresh_tokens.py` rotates tokens this way because two concurrent
refreshes otherwise both observe the same token as live.

**Return an explicit `JSONResponse` when a failure path sets or clears cookies.** FastAPI
discards the injected `Response` when an exception propagates, so cookies mutated on it
never reach the browser. `raise HTTPException` is correct only when the response carries
nothing but a status and a detail.

**Wrap a blocking third-party call in `run_in_threadpool`.** `google-auth` verifies tokens
over a synchronous transport; calling it directly stalls the event loop for every other
in-flight request on the worker.

**Authorization is the query.** Fetch a resource through a join to its owner
(`_owned_entry` in `api/routes/logs.py`) so an unauthorised id returns 404 by
construction. A separate ownership check after an unscoped fetch is a check someone can
forget.

**Every external client carries a timeout.** Postgres, Redis, and each health probe. The
library defaults are long enough that a dead dependency presents as a hang, which is far
harder to diagnose than an outage.

**Enums are `StrEnum` stored in `String` columns.** A PostgreSQL `ENUM` turns "add a login
provider" into a migration. `app/enums.py` is the single source.

Persisted models inherit the `MetaData` naming convention in `db/base.py` — without it
Alembic emits unnamed constraints that no later migration can drop.

## Client

**Every number renders in `font-mono`.** Figures, dates, step counters, uppercase
micro-labels. It is the design's strongest signature and it keeps digits from reflowing as
values change.

**Colour, radius, and type come from the `@theme` tokens** in `src/index.css`. A raw hex in
a component is a token that went missing.

**Auth tokens are invisible to JavaScript.** The cookies are httpOnly, so expiry can only
be discovered from a 401. Never try to read, store, or inspect a token client-side.

**Refresh is single-flight.** Concurrent 401s share one in-flight promise. Without it, N
failures fire N rotations, and every loser presents a consumed token — which the server
cannot distinguish from theft. This is the client half of a two-part fix; the server half
is the reuse grace window in `stores/refresh_tokens.py`. Changing either alone reopens the
hole.

**Reach for CSS before a charting library.** The designed macro bars and progress fills are
plain divs. Recharts is loaded lazily and only on `/progress`; importing it eagerly put
390 kB in the entry bundle for a screen nobody had navigated to.

## Tests

Substitute the *external* dependency, never our own code. `fakeredis` executes the real Lua
via lupa, and the identity tables run on in-memory SQLite, so rotation and theft detection
are genuinely exercised. The suite needs no running Postgres or Redis — keep it that way.

Name a test for the behaviour it pins, so a failure reads as a symptom:
`test_parallel_refreshes_do_not_revoke_the_session`, not `test_rotate_2`.

## Commits

**No AI-tool attribution in commit messages or PR bodies.** Authorship here is not shared
with the tooling, so a `Co-Authored-By:` trailer pointing at a model, or a "Generated with"
line in a PR description, does not belong in this repo's history.

`.githooks/commit-msg` enforces it rather than trusting each tool to have been told. Enable
it once per clone:

    git config core.hooksPath .githooks

It matches the tool trailers by address, so a genuine human co-author on a pairing session
still survives. This is about credit, not about the product — Trueplate calls the Claude API,
so references to it in code and docs are correct and stay.

## Environment gotchas

`fastapi dev` crashes on Windows — its banner cannot encode to the console codepage. Run:

    uv run uvicorn app.main:app --reload --port 8000

Open the app on **:5173**, not :8000. The Vite proxy makes `/api` same-origin, which is
what lets the httpOnly cookies work with no CORS configuration at all.

Postgres and Redis are expected to come from `docker-compose.yml`. This machine runs
managed instances instead (Neon, Upstash); connection URLs live in the gitignored root
`.env`, and `DATABASE_URL` needs the `postgresql+psycopg://` prefix or SQLAlchemy selects
the sync driver.
