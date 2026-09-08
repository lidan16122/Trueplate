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

Persisted food nutrition uses **per 100 g** values alongside a separate quantity in grams.
API responses and components may expose derived portion/day totals; those totals do not replace
the stored basis. Personal calorie and macro targets are separate daily-goal snapshots.

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

**Documentation and comments carry the reason, not the mechanics.** Their density is
deliberate and high — match it, while keeping each note to one or two straightforward
sentences. When the purpose is not obvious, state what the choice is for and why it exists:
what breaks without it, or what a reader would otherwise assume wrongly. The code already
shows how it works.

**Redis access lives behind a store** in `app/stores/`, one file per use case. Routes and
services talk to a store, never to a Redis client. Deliberately *not* cached: user
profiles, goals, and day totals — cheap Postgres queries whose caching would buy an
invalidation problem for nothing.

**Redis stores refresh-token families, rate-limit counters, and an optional access-token
denylist.** Completed detections and scanned products live in Postgres
(`app/services/detection/cache.py`, `barcode_products`) because their payloads are large and
long-lived. `app/stores/keys.py` records the key namespace; the unused `app/stores/json_cache.py`
helper is a legacy remainder, not the active detection or product cache.

Detection keys include the model, effort, and `PROMPT_FINGERPRINT`, a digest over the system
prompt and tool schema. Preserve these inputs when relocating code so cached results do not
silently outlive changes to the detector.

Photo keys currently omit the optional note and meal type; text keys include normalized text
and meal type. This is an existing cache limitation, not a complete key policy to copy into new work.

**Redis checks and their dependent mutations run together in Lua.**
`app/stores/refresh_tokens.py` uses this for rotation and owner-scoped revocation so another
request cannot interleave between checking a record and changing it.

A redis-py pipeline with `transaction=True` runs its queued commands without interleaving;
session creation uses that form. It does not protect reads performed beforehand in Python.
See [Redis pipelines and transactions](https://redis.io/docs/latest/develop/clients/redis-py/transpipe/).

**Return an explicit `JSONResponse` when a failure path sets or clears cookies.** FastAPI
discards the injected `Response` when an exception propagates, so cookies mutated on it
never reach the browser. `raise HTTPException` is correct only when the response carries
nothing but a status and a detail.

**Wrap a blocking third-party call in `run_in_threadpool`.** `google-auth` verifies tokens
over a synchronous transport; calling it directly stalls the event loop for every other
in-flight request on the worker.

**Authorization is the query.** Fetch a resource through a join to its owner
(`owned_entry` in `app/db/repositories/logs.py`) so an unauthorised id returns 404 by
construction. A separate ownership check after an unscoped fetch is a check someone can
forget.

**Every external client carries a timeout.** Postgres, Redis, and each health probe. The
library defaults are long enough that a dead dependency presents as a hang, which is far
harder to diagnose than an outage.

**Enums are `StrEnum` stored in `String` columns.** A PostgreSQL `ENUM` turns "add a login
provider" into a migration. `app/models/enums.py` is the single source.

Persisted models inherit the `MetaData` naming convention in `db/base.py` — without it
Alembic emits unnamed constraints that no later migration can drop.

## Resolving a food to a number

`app/services/nutrition/` owns food-nutrition source integration. Photo/text detection uses
`NutritionResolver`; the barcode service uses the package's `OpenFoodFactsClient` for exact
product lookup. Source clients normalize upstream payloads into the shared nutrition shapes.

**Every upstream here answers confidently and none of them validate.** Two guards exist
because of it, and they are siblings — `relevance.py` asks whether a row is about the right
*food* (it has offered *Emu, fan fillet* for salmon), `matches.py` whether its *numbers*
could describe food at all (kJ in a kcal field arrives looking ordinary). Both **drop**
rather than clamp: a dropped row sends the ladder to the next rung where there is usually
a real answer, where a clamped one is silently wrong and gets saved.

**Open Food Facts is a second pass over the whole ladder, not a fourth rung per term.** It
answers nearly any free-text query with a branded near-miss, so asked per rung it beats the
broader term USDA would have answered properly — the specific query winning purely for
being asked first.

**Ranking FDC results is our job, not theirs.** Their descriptions are head-first, so the
first comma-segment names the food and a bad match announces itself there. `rank_foods` is
pure and public so `scripts/eval_matching.py` can score it against recorded payloads:
FDC fails roughly one request in six, so an eval that re-fetched would measure their edge
instead of our code. Change the ranking, run the eval, report the number.

Two scripts, both worth knowing: `scripts/probe_resolver.py` runs the ladder against live
APIs with no model call and no cost; `scripts/probe_detection.py` runs a real photo through
the whole detection path, bypassing HTTP, auth and the cache — which is why it and the app
can disagree.

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

    uv run --directory server uvicorn app.main:app --reload --port 8000

Open the app on **:5173**, not :8000. The Vite proxy makes `/api` same-origin, which is
what lets the httpOnly cookies work with no CORS configuration at all.

Postgres and Redis are expected to come from `docker-compose.yml`. This machine runs
managed instances instead (Neon, Upstash); connection URLs live in the gitignored
`server/.env` — the app reads that one, the repo-root `.env` is Compose's — and
`DATABASE_URL` needs the `postgresql+psycopg://` prefix for the configured async SQLAlchemy
engine. Process environment variables override values loaded from `server/.env`.
