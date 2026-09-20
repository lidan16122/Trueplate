# Trueplate

Trueplate is a nutrition and calorie tracker for phones and computers. Log what you eat with
a meal photo, a written description, or a packaged product's barcode, then follow your daily
calories, protein, carbohydrates, and fat.

## How it works

1. **Set your goal.** Sign in with Google, enter your body measurements, and choose to lose,
   maintain, or gain weight. Trueplate calculates daily calorie and nutrient targets from your
   profile, activity level, and chosen pace, and shows how it reached those targets.
2. **Add your food.** Take or upload a photo, describe a meal in your own words, or photograph
   or type a barcode. You can choose the day and group food into breakfast, lunch, dinner, or snacks.
3. **Review before saving.** Check the foods and estimated portions, adjust grams or available
   household measures, remove an item, or add something missed. Review the nutrition source
   and choose an alternative match when one is available.
4. **Follow your day.** See meal totals and progress toward your daily targets, browse previous
   days, and view the last 14 days of calorie history. Update your profile or goal as your needs change.

### Where the numbers come from

**AI identifies food and estimates its weight; it never supplies calories or nutrients.**
Trueplate matches those foods to nutrition records from USDA FoodData Central or Open Food Facts,
then scales the recorded values to your portion. Barcode lookups use the product's nutrition record
directly, without AI.

Portions and food matches can be uncertain. The confirmation screen flags rough matches and foods
without a usable nutrition record; unmatched items are excluded when saving. Correcting a portion
recalculates its calories and nutrients immediately.

Each saved entry keeps the nutrition values used at the time, so later source updates do not
change your food history. Changes to your goals apply from the day you make them and preserve
earlier days' targets.

### Current availability

- Google is the supported sign-in method.
- Photo and text recognition use an external AI service and have an account allowance.
  New accounts currently start with **one AI detection**; barcode lookups remain available
  after that allowance is used.
- Day-by-day food history works in **Today**. The separate **Food log** page is a placeholder.
- The calorie progress chart uses your logs; the weight chart still shows illustrative data.
- Meal-plan generation is not available.

**Use Trueplate:** [trueplate.lidan16122.workers.dev](https://trueplate.lidan16122.workers.dev)

## Stack

| Area | Technology |
| --- | --- |
| Frontend | React 19, TypeScript 5, Vite 7, Tailwind CSS 4, React Router 7, Recharts |
| Backend | Python 3.14, FastAPI, Pydantic 2 |
| Database | PostgreSQL 17, async SQLAlchemy 2 with psycopg 3, Alembic migrations |
| Sessions and request limits | Redis 8; secure HTTP-only cookies with revocable refresh sessions |
| Sign-in | Google OAuth 2.0 |
| Food recognition | Anthropic Claude API; Pillow for image preparation, pyzbar/ZBar for barcodes |
| Nutrition sources | USDA FoodData Central and Open Food Facts |
| Hosting and CI | Cloudflare Workers for the client/API proxy, Render Docker for the API, GitHub Actions |

The repository contains the frontend in `client/` and the backend in `server/`.
Detection results and product records are cached in PostgreSQL; Redis holds session and rate-limit data.

## Run locally after cloning

Run the commands below from the repository root unless a step says otherwise.

### 1. Install prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python dependencies.
  The project pins Python **3.14** in `server/.python-version`; uv can download it during setup.
- Node.js **24** with npm, matching `client/.nvmrc`.
- Docker with Docker Compose for local PostgreSQL and Redis, or your own connections to those services.
- The native **ZBar** library, required when the API starts:
  - **Windows:** included in the pyzbar wheel.
  - **macOS:** `brew install zbar`.
  - **Debian/Ubuntu:** `sudo apt-get install libzbar0`; Ubuntu 24.04 and newer use
    [`libzbar0t64`](https://packages.ubuntu.com/noble/libzbar0t64).

See [pyzbar installation](https://github.com/NaturalHistoryMuseum/pyzbar#installation)
for platform details.

### 2. Create the environment files

**macOS/Linux:**

```bash
cp .env.example .env
cp .env.example server/.env
cp client/.env.example client/.env
```

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
Copy-Item .env.example server/.env
Copy-Item client/.env.example client/.env
```

| File | Read by | What to configure |
| --- | --- | --- |
| `.env` | Docker Compose | Local PostgreSQL credentials and published PostgreSQL/Redis ports |
| `server/.env` | FastAPI and Alembic | Database connections, signing key, Google credentials, and integration keys |
| `client/.env` | Vite | Keep `VITE_API_BASE_URL=` empty so requests use the local proxy |

Real environment files are gitignored. Backend process environment variables override
`server/.env`. Values prefixed with `VITE_` are public browser configuration; keep secrets
in `server/.env`.

### 3. Install dependencies and configure the backend

```bash
uv sync --directory server --locked
npm --prefix client ci
```

Generate a signing key:

```bash
uv run --directory server python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Paste the result into `JWT_SECRET_KEY` in `server/.env`. The server and migrations require
a key of at least 32 characters.

Configure these values in `server/.env`:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` / `REDIS_URL` | Defaults match Docker Compose; replace them when using your own services |
| `JWT_SECRET_KEY` | Required signing key generated above |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Required for signing in; configure them in step 4 |
| `ANTHROPIC_API_KEY` | Required for photo/text recognition; use an Anthropic API account with model access and credits |
| `USDA_FDC_API_KEY` | Enables USDA food matching; obtain a [FoodData Central API key](https://fdc.nal.usda.gov/api-key-signup.html) |

Without Google credentials, the API can start but sign-in is unavailable. Without an Anthropic
key, photo/text recognition is unavailable. Without a USDA key, matching can still use existing
records and Open Food Facts, but generic-food coverage is reduced. Open Food Facts requires no API key.

Optional model, timeout, cache, and request-limit settings are listed in
[.env.example](.env.example); [server/app/config.py](server/app/config.py) defines all settings and defaults.

### 4. Configure Google Sign-In

1. Create or select a project in the [Google Cloud Console](https://console.cloud.google.com/).
2. Configure the OAuth consent screen with the app name, support email, and audience.
   If using testing mode, add your Google account as a test user.
3. Create an OAuth client with application type **Web application**.
4. Add this exact **Authorized redirect URI**:
   `http://localhost:5173/api/v1/auth/google/callback`.
5. Put the client ID and client secret in `server/.env`, and set:
   `GOOGLE_REDIRECT_URI=http://localhost:5173/api/v1/auth/google/callback`.

The redirect URI must match exactly, including the scheme, port, and path.
This flow uses a server-side redirect; no Google variables are needed in `client/.env`.
See [Google's web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server).

### 5. Start PostgreSQL and Redis

With Docker running:

```bash
docker compose up -d --wait
```

Compose starts the databases only; the API and frontend run in the next steps.

If a local port is occupied, change `POSTGRES_PORT` or `REDIS_PORT` in the root `.env`
and update the corresponding URL in `server/.env`. Credentials and database names must
also agree between the two files.

**Using managed services:** skip Docker and set `DATABASE_URL` and `REDIS_URL` in
`server/.env`. Use the `postgresql+psycopg://` scheme for PostgreSQL, preserve any provider
TLS options, and use `rediss://` when Redis requires TLS. The example includes larger
timeout overrides for connections that need time to wake up.

### 6. Apply database migrations

Confirm that `DATABASE_URL` points to the database intended for local development, then run:

```bash
uv run --directory server alembic upgrade head
```

Seeding is optional: `uv run --directory server python -m scripts.seed` inserts or updates
development reference foods. These figures are unverified seed data; use a development database.

### 7. Start the API and frontend

In one terminal:

```bash
uv run --directory server uvicorn app.main:app --reload --port 8000
```

In a second terminal, also at the repository root:

```bash
npm --prefix client run dev -- --strictPort
```

Open [http://localhost:5173](http://localhost:5173), sign in with Google, and complete onboarding.
Vite forwards `/api` requests to port 8000, keeping sign-in and API calls on the same browser origin.
The strict port option prevents Vite from silently choosing a port that differs from your Google redirect URI.

### 8. Check the setup

- [API health](http://localhost:8000/health) should return `{"status":"ok"}`.
- [Database and Redis readiness](http://localhost:8000/health/ready) should report `"status":"ok"`.
  A `503` response identifies a dependency that is unavailable.
- [Interactive API docs](http://localhost:8000/docs) list the backend endpoints.

Stop each development server with **Ctrl+C**. Use `docker compose stop` to stop the local
databases while keeping their data.

### Common setup problems

| Symptom | Check |
| --- | --- |
| Signing-key validation error | Set `JWT_SECRET_KEY` to the generated value in `server/.env`; check for an overriding process variable |
| Google `redirect_uri_mismatch` | Match the Google Console URI and `GOOGLE_REDIRECT_URI` exactly; open the app on `localhost:5173` |
| Sign-in does not persist | Leave `VITE_API_BASE_URL` empty; if the browser rejects secure cookies over local HTTP, set `COOKIE_SECURE=false` for local development only |
| Database/Redis readiness fails | Check service status, connection URLs, credentials, TLS requirements, and timeout settings |
| ZBar library or DLL import error | Check the platform requirements in the pyzbar installation guide above |
| `fastapi dev` fails on Windows | Use the documented uvicorn command to avoid the console banner encoding issue |

## Development checks

```bash
uv run --directory server ruff check .
uv run --directory server pytest
npm --prefix client run lint
npm --prefix client run typecheck
npm --prefix client test
npm --prefix client run build
```

Backend tests use SQLite and fakeredis and need no running PostgreSQL or Redis.
Frontend tests cover the API transport and endpoint adapters; they do not cover full browser journeys.

Enable the repository's commit-message hook once per clone:

```bash
git config core.hooksPath .githooks
```

## Important notes

### Detection limits and caching

- New accounts default to `users.max_prompts = 1`. For local development, adjust that
  account's database value or use `NULL` for no account cap; there is no environment setting
  or settings-screen control for this allowance.
- Allowance usage is derived from saved entries. Foods from one photo are grouped together,
  but multiple foods saved from one text result can count separately.
- Photo, text, and barcode endpoints also share a per-user rate limit: **20 requests per hour**
  by default, configurable in `server/.env`.
- Reusing an identical photo can return a cached result even after changing its note or meal type.
  Photo cache keys currently omit those two inputs.
- Uploads default to an **8 MiB** limit. Use JPEG, PNG, or WebP; HEIC/HEIF decoding depends
  on image-library support in the runtime.

### Deployment

- The client is served by Cloudflare Workers using [client/wrangler.jsonc](client/wrangler.jsonc).
  Set the Worker's `API_ORIGIN` secret to the backend's origin, with no path.
- Client CI deploys matching pushes to `main` after lint, typecheck, tests, and build pass.
  It needs GitHub Actions secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
- The API uses [render.yaml](render.yaml) and [server/Dockerfile](server/Dockerfile).
  Render is configured to deploy after checks pass; supply backend credentials in its environment.
- Keep `VITE_API_BASE_URL` empty in production. Set `GOOGLE_REDIRECT_URI` to the public
  frontend origin plus `/api/v1/auth/google/callback`, register it in Google, and use `COOKIE_SECURE=true`.
- **Migrations are separate from deployment.** Run `alembic upgrade head` against the explicitly
  selected production `DATABASE_URL`; settings also require a valid `JWT_SECRET_KEY`.
- The Worker pings API health every ten minutes to reduce cold starts. This consumes instance hours
  and remains subject to [Render's free-service limits](https://render.com/docs/free).

### Further reference

- [Working agreements](AGENTS.md): nutrition-data invariants and contribution conventions.
- [Architecture plan](docs/architecture-plan.md): module boundaries and implementation decisions.
- [Developer scripts](server/scripts/): resolver probes, detection checks, and recorded matching evaluations.
  Photo detection probes and detection evaluations make paid model calls; the seed and live probes
  can write to the configured database. `python -m scripts.eval_matching` runs from `server/`
  against recorded fixtures without network or database access.
- [MIT license](LICENSE).
