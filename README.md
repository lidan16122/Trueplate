# Trueplate

Nutrition and calorie tracking, built around logging food by photo.

You photograph a meal, an AI identifies the foods and estimates portions in grams, and a nutrition
database resolves the actual calories and macros. **The model never produces a calorie number** —
it contributes labels and mass, and food nutrition is resolved from source records. Personal
calorie targets are calculated separately from profile inputs.

Responsive web app.

---

## Stack

| Layer | Choice |
|---|---|
| Frontend | React 19 + TypeScript 5, Vite, Tailwind v4, React Router 7, Recharts |
| Backend | Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 17 via psycopg3 |
| Sessions / request limits | Redis 8 (async redis-py); detection and product caches live in PostgreSQL |
| Auth | Google OAuth 2.0 authorization-code redirect → `google-auth` verification → JWT access cookie + rotated opaque refresh token |
| AI | Claude API through the Anthropic SDK, strict food-detection tool schema, photo and text workflows |

Monorepo: `client/` and `server/`. One PR spans both sides, which is what you want for a solo
project — the alternative is coordinating version bumps across two repos for every feature.

---

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), the Node version in `client/.nvmrc`, and
PostgreSQL/Redis connections. [Docker Desktop](https://www.docker.com/products/docker-desktop/)
is optional: `docker-compose.yml` supplies local PostgreSQL and Redis instead of managed services.
The commands below run from the repository root.

```bash
cp .env.example .env
cp .env.example server/.env
```

Two copies on purpose: `docker compose` reads the root one for container credentials and ports;
the app loads `server/.env`, with process environment variables taking precedence.

Generate a signing key and paste it into `server/.env` as `JWT_SECRET_KEY` — the command is in
`.env.example` beside the variable itself. The app refuses to start without it, rather than
falling back to a default that would sign real tokens with a value published in this repo.

For local databases, start Postgres and Redis; skip this when using managed connections:

```bash
docker compose up -d
```

Using managed instances instead (Neon, Upstash) rather than Docker? Two things bite. `DATABASE_URL`
needs the `postgresql+psycopg://` prefix so SQLAlchemy selects the configured async-capable
psycopg driver. Set `DATABASE_URL` and `REDIS_URL` in `server/.env`; use `rediss://` when the
Redis provider requires TLS. `.env.example` lists timeout overrides for managed connections.

Install server dependencies and apply migrations to the configured database:

```bash
uv sync --directory server --locked
uv run --directory server alembic upgrade head
```

Optionally load development reference foods with `uv run --directory server python -m scripts.seed`.
These are development figures tagged as seed data, not verified upstream records.

Run the API:

```bash
uv run --directory server uvicorn app.main:app --reload --port 8000
```

Create `client/.env` from `client/.env.example` and run the client:

```bash
npm --prefix client ci
npm --prefix client run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to `:8000`, so the browser sees
one origin and the auth cookies work with no CORS configuration at all.

> Use the uvicorn command above on Windows. `fastapi dev` has failed here while printing its
> banner to the console codepage (`UnicodeEncodeError: 'charmap' codec`).

---

## Setting up Google Sign-In

Configure a Google OAuth web client before signing in. Google's
[web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server)
describes client registration and redirect-URI requirements.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project
   (e.g. *Trueplate*).
2. **APIs & Services → OAuth consent screen**
   - User type: **External**
   - Fill in app name, your email as support and developer contact, and save.
   - Under **Audience**, add your own Google account as a **Test user**. While the app is in
     testing, only listed accounts can sign in.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Web application**
   - **Authorised redirect URIs:** `http://localhost:5173/api/v1/auth/google/callback`, plus the
     same path on any deployed origin.

   > This list is the easy one to skip, and nothing works without it. Sign-in is a full
   > authorization-code redirect: the browser leaves for Google and comes back to that exact
   > URI, which Google matches against this entry byte for byte. Get it wrong and you never
   > reach the app at all — Google shows its own `redirect_uri_mismatch` page. Authorised
   > JavaScript origins are not used by this flow and can stay empty.
4. Copy the **Client ID** and the **Client secret** into `server/.env`:
   - `GOOGLE_CLIENT_ID` — the audience every ID token is checked against
   - `GOOGLE_CLIENT_SECRET` — sent server-to-server when the code is exchanged
   - `GOOGLE_REDIRECT_URI` — the same string you pasted into the Console

This flow needs no Google variables in `client/.env`. The client ID is public and appears in
the authorization URL; the client secret stays on the server and must never be put in a
`VITE_*` variable exposed to the browser bundle.

Until it is configured the sign-in screen renders normally, and pressing the button returns you
to it with *"Google sign-in is unavailable right now."*

---

## How auth works

The values below are the defaults in `server/app/config.py`; deployments can override them.

**Startup session discovery** — `GET /api/v1/auth/session` returns `200` with JSON `null`
when there is no authenticated user and no refresh cookie, so opening the sign-in page does
not generate a pair of failed auth requests. An authenticated visitor receives the same user
and onboarding state as `/auth/me`; both startup results use `Cache-Control: no-store`.

If access is rejected but a refresh cookie exists, discovery returns `401` to invoke the
client's shared refresh-and-retry flow. `/auth/me` and other protected endpoints still require
authentication, and database or infrastructure errors remain errors during discovery.

**Access token** — a 15-minute HS256 JWT in an httpOnly, Secure, SameSite=Lax cookie at `/`.
Verified by signature alone, so the common path never touches Redis. Never in `localStorage`: a
token readable by JavaScript is a token stealable by any injected script.

**Refresh token** — 1 day, an opaque 256-bit random string, *not* a JWT, in an httpOnly cookie
scoped to `/api/v1/auth` so it is not attached to every API call. Only its SHA-256 reaches Redis.

**Rotation** — every refresh consumes the token and issues a new one, resetting the 1-day TTL
(sliding expiration: an active user is never forced to sign in again, a dormant session still ages
out). The swap runs as a Redis Lua script so the check-and-swap is atomic.

The tombstone a rotation leaves behind keeps its own, longer life
(`REFRESH_REUSE_TOMBSTONE_DAYS`, 7 days). Because expiry slides, an active family outlives every
token rotated out of it; a tombstone that expired with the session would make a late replay of a
stolen token read as merely unknown — rejected, but with the family left alive and nothing logged.
Seven days rather than thirty because the catch that matters lands in minutes — the victim's next
refresh — and this only extends it to cover an attacker who waits.

**Theft detection** — presenting an already-rotated token revokes that whole session family, not
just the one token, on the assumption it was captured.

Two things make that safe against false positives, and both are load-bearing:

- **A reuse grace window** (15s, configurable). Two browser tabs refreshing at the same instant
  produce a replay that is indistinguishable from theft. Inside the window it is treated as a
  retry and the session is left alone; outside it, the family is revoked.
- **Single-flight refresh on the client.** Concurrent 401s share one in-flight refresh promise, so
  N failures produce one rotation rather than N.

Without either, opening a second tab signs the user out. There are tests for exactly that
(`server/tests/test_refresh_tokens.py::TestConcurrency`).

Each refresh family carries its own id and device metadata, which is what makes per-device
revocation (`DELETE /api/v1/auth/sessions/{family_id}`) possible without disturbing the
user's other devices.

**Request-origin protection.** The API currently relies on its cookie SameSite policy and
does not implement a general CSRF-token check. The OAuth callback additionally compares a
random `state` with a short-lived httpOnly cookie and clears that cookie after use.

**The callback is a GET.** The OAuth state cookie uses `SameSite=Lax` explicitly so it can
accompany Google's top-level redirect back to `/api/v1/auth/google/callback`.

The same cookie carries a **PKCE** verifier. The server supplies it, together with the client
secret, when exchanging the authorization code; the code alone is insufficient for that exchange.

---

## What Redis is and isn't used for

Redis operations live behind adapters in `server/app/stores/`:

1. **Refresh tokens** — rotation, reuse detection, and per-device session revocation. Metadata
   is stored per session, but there is no current session-list endpoint.
2. **Rate limiting** — a per-user sliding window shared by photo, text, and barcode endpoints.
3. **Optional access-token denylist** — disabled by default; enables revoking a token before expiry.

`stores/health.py` provides the readiness ping. Completed detection responses and scanned products
are cached in PostgreSQL's `detections` and `barcode_products` tables. The unused generic
`stores/json_cache.py` helper remains from the earlier design and has no current callers.

Deliberately **not** cached: user profiles, goals, and today's totals. They are cheap Postgres
queries, and caching them would buy an invalidation problem in exchange for nothing measurable.

---

## Data model

| Table | Notes |
|---|---|
| `users` | Holds no credential. `first_name` / `last_name` separately, since the profile screen edits them independently. |
| `auth_identities` | `(provider, provider_user_id)` unique. Adding Apple or email sign-in is a new row, not a migration. |
| `user_profiles` | The **inputs** to BMR — birth date, sex, height, activity level, timezone — never the derived number, so the formula can change without invalidating history. |
| `weight_entries` | Weight is a time series, not a profile field: the trend chart needs history, and it is the one metric expected to move. |
| `goals` | Targets snapshotted and date-ranged. Superseding closes the old row rather than mutating it, so a day is still judged against the target actually in force then. |
| `daily_logs` | Keyed on the user's **local** date — hence storing a timezone. No cached totals. |
| `food_entries` | Nutrition stored **per 100 g** alongside the portion, so correcting grams recomputes exactly. Records `detection_method` (`photo`/`text`/`barcode`/`manual`) and source provenance. |
| `foods` | Name-keyed reference (USDA FDC + dev seed). |
| `barcode_products` | UPC-keyed reference (Open Food Facts). Separate from `foods` because the lookup key and upstream differ. |
| `detections` | Completed photo/text response payloads, keyed by content and detection configuration. |

Stored food nutrition uses a per-100 g basis plus a separate gram quantity. Responses can carry
derived portion/day totals; personal goals store their computed daily targets as historical snapshots.

---

## Tests

```bash
uv run --directory server ruff check .
uv run --directory server pytest
```

No running PostgreSQL or Redis is required: the suite uses SQLite and `fakeredis`, which executes
the real Lua scripts through lupa. `server/conftest.py` supplies the test signing key before
application imports; `server/tests/conftest.py` supplies shared fixtures.

```bash
npm --prefix client run lint
npm --prefix client run typecheck
npm --prefix client test
npm --prefix client run build
```

`client/test/api.test.mjs` uses Node's test runner to exercise the real transport and endpoint
adapters with substituted network responses. It covers refresh coordination, expired sessions,
multipart uploads, validation errors, and empty responses. The client workflow runs these four
checks for matching pushes and pull requests; it does not provide full browser-journey coverage.

## Developer scripts

These commands also run from the repository root. They are separate from the HTTP server:

| Command | Purpose and effects |
| --- | --- |
| `uv run --directory server python -m scripts.seed` | Insert/update development reference foods in the configured database. |
| `uv run --directory server python -m scripts.probe_resolver` | Probe predefined foods against the configured database and live nutrition APIs; commit resolver write-backs, without calling the model. |
| `uv run --directory server python -m scripts.probe_detection path/to/meal.jpg` | Run a fresh, paid model detection for a local photo; bypass auth/rate limits/detection cache and commit resolver write-backs. An optional second argument supplies a note. |
| `uv run --directory server python -m scripts.eval_detection --runs 3` | Check prepared dishes and separate foods with fresh paid model calls and an in-memory database. Add `--photo path/to/two-slices.jpg` for the pizza photo case or `--verbose` for retry diagnostics. |
| `uv run --directory server python -m scripts.eval_matching` | Score USDA ranking against the recorded fixture without network or database operations. |
| `uv run --directory server python -m scripts.eval_matching --refresh` | Fetch USDA responses and update `server/tests/fixtures/usda_search.json`. |

---

## Deploying

The client goes to Cloudflare Workers (`client/wrangler.jsonc`); the API goes to Render as a
Docker image (`render.yaml` at the repo root, `server/Dockerfile`). Both deploy on a push to
`main` only, and only once CI is green — Cloudflare from a GitHub Actions job, Render through
`autoDeployTrigger: checksPass`.

The API runs under Docker rather than Render's native Python runtime for one reason: `pyzbar`
loads `libzbar.so.0` at import, `app.main` reaches it through the router, and Render's native
runtime has no `apt` step. Without that system package the app does not fail to scan a
barcode — it fails to boot.

**The Worker is configured to keep the API awake.** A Cloudflare Cron Trigger in `client/wrangler.jsonc`
pings `/health` every ten minutes, inside the fifteen-minute idle window that would
otherwise spin the free instance down. Without it the wake is not merely slow, it is
*visible*: sign-in is a top-level navigation to `/api/v1/auth/google/start`, so a sleeping
Render answers the browser with its own branded holding page instead of the redirect to
Google. It pings liveness and not `/health/ready` — the job is to keep the container up,
not to query the database and Redis every ten minutes as well. The idle behavior is described
in [Render's free-service documentation](https://render.com/docs/free); the schedule alone is
not a guarantee of service availability.

The cost is instance-hours. Always-warm spends close to the whole free monthly allowance,
which must fit the workspace's shared allowance; narrowing the cron to
`"*/10 6-23 * * *"` gives back roughly a quarter of it in exchange for a cold start on the
first sign-in of the early morning. [Cloudflare Cron Triggers use UTC](https://developers.cloudflare.com/workers/configuration/cron-triggers/).

Production start command, for reference — no `--reload`, and `--host 0.0.0.0` because uvicorn
otherwise binds `127.0.0.1` and nothing outside the container can reach it:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}
```

**Migrations are run separately from deployment.** Neither the Docker start command nor
`render.yaml` applies them automatically. Run them from a machine with database access and
**pass the intended production URL explicitly**; the Quick start command otherwise targets
whatever the process environment or `server/.env` specifies, including a managed database.
`server/alembic/env.py` imports the settings, so it also requires `JWT_SECRET_KEY` with at least
32 characters. The following Bash command uses a migration-only placeholder because it does not sign tokens:

```bash
DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/DATABASE?sslmode=require' JWT_SECRET_KEY='migration-only-placeholder-at-least-32-characters' uv run --directory server alembic upgrade head
```

> Use the `postgresql+psycopg://` scheme for this application's async SQLAlchemy engine.
> `GET /health/ready` checks database and Redis connectivity; `GET /health` only checks that
> the HTTP process is responding.

---

## Project layout

```
server/app/
├── api/            HTTP routes, cookies, dependencies, limits, error mapping
│   └── routes/     health, auth, onboarding, profile, logs, ai
├── core/           pure nutrition calculations, JWT security
├── db/             sessions, transactions, health probe, reference-food seeding
│   ├── models/     SQLAlchemy models
│   └── repositories/  users, profiles, goals, logs, prompt usage, foods, caches
├── models/         shared domain enums, independent of database models
├── schemas/        shared Pydantic shapes and the strict model tool contract
├── services/       shared logs, prompt allowance, readiness, application errors
│   ├── auth/       identity, sessions, Google OAuth integration
│   ├── detection/  detector, workflows, cache policy, barcodes, image preparation
│   ├── profile/    onboarding/profile workflows and goal targets
│   └── nutrition/  resolution policy, source clients, ranking and validation
├── stores/         Redis adapters for sessions, limits, optional denylist, health
└── utils/          general helpers such as readable device labels

client/src/
├── app/            router, route guards, auth provider wiring
├── pages/          stable route entries exporting their feature screens
├── features/       auth, onboarding, profile, food-logging, progress
│   └── <feature>/  components, hooks, models, services, public index
├── components/     one file per shared UI element, such as Logo and Avatar
├── hooks/          shared auth hook
├── models/         shared auth context, meal labels, profile choices, portion scaling
├── services/       one HTTP transport and cross-feature auth/profile endpoints
├── types/          API declarations grouped by auth, profile, onboarding, meals, nutrition, logs, detection
└── utils/          date and number formatting
```

Routes handle HTTP; services sequence application work; repositories execute SQL on the
existing request session. Detection and barcode caches remain in Postgres. Client hooks own
feature state and requests, while every service shares the same single-flight refresh transport.

The [architecture research](docs/architecture-research.md) records the source guidance and
[refactoring plan](docs/architecture-plan.md) records the decisions, boundaries, and verification.

---

## Implemented behavior and remaining limits

Photo/text model detection, USDA and Open Food Facts resolution, barcode scanning, confirmation,
food logging, onboarding, and profile/goal updates are implemented. Configure the required API
credentials in `server/.env` before using live integrations; photo/text detection also checks
the account allowance. `GET /api/v1/ai/tool-schema` exposes the model tool definition to an
authenticated user and is intentionally hidden from OpenAPI.

- `/log` remains a placeholder; `/today` provides date-by-date food history.
- `/progress` displays real calorie history, but its weight chart still uses illustrative data.
- Meal-plan generation is not implemented.
- Account prompt usage is derived from saved food entries. Photo entries are grouped by image
  hash; multiple entries from one text detection can overcount usage.
- Photo cache keys include the image hash, model, effort, and prompt fingerprint, but currently
  omit the optional note and meal type. Reusing an image can therefore return a previous response
  despite changes to those inputs; the relocation preserved this existing behavior.
- Progress currently imports food logging's API adapter directly. Feature folders improve
  organization but do not yet provide complete isolation between those two features.
