# Trueplate

Nutrition and calorie tracking, built around logging food by photo.

You photograph a meal, an AI identifies the foods and estimates portions in grams, and a nutrition
database resolves the actual calories and macros. **The model never produces a calorie number** —
it contributes labels and mass, and every figure shown to a user traces back to a database row.

Responsive web app, installable as a PWA.

---

## Stack

| Layer | Choice |
|---|---|
| Frontend | React 19 + TypeScript 5, Vite, Tailwind v4, React Router 7, `vite-plugin-pwa`, Recharts |
| Backend | Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 17 via psycopg3 |
| Cache / sessions | Redis 8 (async redis-py) |
| Auth | Google Identity Services → `google-auth` verification → JWT access cookie + rotated opaque refresh token |
| AI | Claude API, tool use with a strict JSON schema (not wired up yet) |

Monorepo: `client/` and `server/`. One PR spans both sides, which is what you want for a solo
project — the alternative is coordinating version bumps across two repos for every feature.

---

## Quick start

Prerequisites: [Docker Desktop](https://www.docker.com/products/docker-desktop/),
[uv](https://docs.astral.sh/uv/), and the Node version in `client/.nvmrc` — CI reads that
same file, so it is the one that has to match.

```bash
cp .env.example .env
```

Generate a signing key and paste it into `.env` as `JWT_SECRET_KEY` — the command is in
`.env.example` beside the variable itself. The app refuses to start without it, rather than
falling back to a default that would sign real tokens with a value published in this repo.

Start Postgres and Redis:

```bash
docker compose up -d
```

Using managed instances instead (Neon, Upstash) rather than Docker? Two things bite. `DATABASE_URL`
needs the `postgresql+psycopg://` prefix, not `postgresql://`, or SQLAlchemy selects the sync
driver and every request blocks the event loop. And a free tier that scales to zero makes the
first request after an idle period slower than the default timeouts allow, which presents as an
outage — `.env.example` carries the overrides to uncomment.

Migrate and seed:

```bash
cd server && uv sync && uv run alembic upgrade head && uv run python -m scripts.seed
```

Run the API:

```bash
cd server && uv run uvicorn app.main:app --reload --port 8000
```

Create `client/.env` from `client/.env.example` and run the client:

```bash
cd client && npm install && npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to `:8000`, so the browser sees
one origin and the auth cookies work with no CORS configuration at all.

> `fastapi dev app/main.py` also works on macOS and Linux, but not on Windows: it prints a
> Unicode banner that crashes on the default console codepage
> (`UnicodeEncodeError: 'charmap' codec`). The uvicorn command above works everywhere, which is
> why it is the one written down.

---

## Setting up Google Sign-In

Nothing signs in until you create an OAuth client. It is free and takes about five minutes.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project
   (e.g. *Trueplate*).
2. **APIs & Services → OAuth consent screen**
   - User type: **External**
   - Fill in app name, your email as support and developer contact, and save.
   - Under **Audience**, add your own Google account as a **Test user**. While the app is in
     testing, only listed accounts can sign in.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Web application**
   - **Authorised JavaScript origins:** `http://localhost:5173`
   - Leave redirect URIs empty — Google Identity Services returns the ID token to the page, so
     there is no redirect leg.
4. Copy the **Client ID** (`...apps.googleusercontent.com`) into **both**:
   - `.env` → `GOOGLE_CLIENT_ID` (the backend verifies tokens against it)
   - `client/.env` → `VITE_GOOGLE_CLIENT_ID` (create it from `client/.env.example`)

The client ID is not a secret — it is published in the page. The client secret is never used by
this flow and does not need to go anywhere.

Until it is configured the sign-in screen renders normally and shows
*"Google sign-in is not configured"* under the button.

---

## How auth works

**Access token** — a 15-minute HS256 JWT in an httpOnly, Secure, SameSite=Lax cookie at `/`.
Verified by signature alone, so the common path never touches Redis. Never in `localStorage`: a
token readable by JavaScript is a token stealable by any injected script.

**Refresh token** — 30 days, an opaque 256-bit random string, *not* a JWT, in an httpOnly cookie
scoped to `/api/v1/auth` so it is not attached to every API call. Only its SHA-256 reaches Redis.

**Rotation** — every refresh consumes the token and issues a new one, resetting the 30-day TTL
(sliding expiration: an active user is never forced to sign in again, a dormant session still ages
out). The swap runs as a Redis Lua script so the check-and-swap is atomic.

**Theft detection** — presenting an already-rotated token revokes that whole session family, not
just the one token, on the assumption it was captured.

Two things make that safe against false positives, and both are load-bearing:

- **A reuse grace window** (15s, configurable). Two browser tabs refreshing at the same instant
  produce a replay that is indistinguishable from theft. Inside the window it is treated as a
  retry and the session is left alone; outside it, the family is revoked.
- **Single-flight refresh on the client.** Concurrent 401s share one in-flight refresh promise, so
  N failures produce one rotation rather than N.

Without either, opening a second tab signs the user out. There are tests for exactly that
(`tests/test_refresh_tokens.py::TestConcurrency`).

Each refresh family carries device metadata, which is what makes `GET /api/v1/auth/sessions` and
per-device revocation possible — visible on the profile screen.

**CSRF** is deliberately deferred. `SameSite=Lax` blocks cross-site POSTs, which covers the
current surface; a double-submit token is the next step if that changes.

---

## What Redis is and isn't used for

Used for four things, each behind its own small store in `server/app/stores/`:

1. **Refresh tokens** — rotation, theft detection, per-device session listing.
2. **Rate limiting** — per-user fixed window on the AI endpoints, since vision calls cost money.
3. **Barcode cache** — in front of `barcode_products` (interface only; barcode scanning not built).
4. **AI detection cache** — keyed by image hash, so re-logging the same meal is free (interface
   only).

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

Everything nutritional is per 100 g. That one decision means the photo path (grams) and the
barcode path (servings) scale through identical code.

---

## Tests

```bash
cd server && uv run pytest
```

107 tests, no database or Redis required — Redis is `fakeredis` executing the **real Lua** via
lupa, and the identity tables run on in-memory SQLite. The rotation, theft-detection, and
concurrency behaviour is genuinely exercised, not mocked.

```bash
cd client && npm run typecheck && npm run build
```

---

## Project layout

```
server/app/
├── api/routes/     health, auth, onboarding, logs, ai
├── core/           nutrition (BMR/TDEE), security (JWT), limits, deps
├── db/models/      SQLAlchemy models
├── schemas/        Pydantic request/response models
├── services/       Google verification, user upsert, target derivation
└── stores/         Redis: refresh tokens, rate limit, barcode + AI caches

client/src/
├── auth/           AuthProvider, GoogleSignInButton
├── components/     DateStrip, MacroBars, MealGroup, ui primitives
├── lib/            api client, formatting, nutrition mirror
└── pages/          SignIn, Onboarding, TargetReveal, Today, AddFood, Confirm, Profile
```

---

## Not built yet

The Claude API call, USDA FoodData Central and Open Food Facts integration, barcode scanning, and
meal-plan generation.

`POST /api/v1/ai/detect/photo` and `/detect/text` return **501** — but behind working
authentication and rate limiting, and against the response contract the confirmation screen is
already built against. The Pydantic schema the model will be held to lives in
`server/app/schemas/detection.py`; `GET /api/v1/ai/tool-schema` returns the exact tool definition
so you can see for yourself that no calorie field can reach it.

`/log` and `/progress` are placeholder routes — neither has a design yet. The day view already
serves as the food log.
