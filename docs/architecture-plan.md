# Behavior-preserving architecture reorganization

Branch: `architecture-reorganization`.

## Scope and rules

Relocate existing implementation into files that own its responsibility. Preserve HTTP paths,
handler names, request/response schemas, cookies, query predicates, transaction boundaries,
nutrition calculations, model prompts, cache keys, UI markup, styling, and lazy loading.
Keep existing synchronous pure functions and React callbacks synchronous; this is not an async
conversion, domain-model rewrite, dependency upgrade, or schema migration.

Preserve the existing user edits in `AGENTS.md` and `CLAUDE.md`; the enum relocation only
updates their enum-module reference to `app/models/enums.py`.
The [research findings](architecture-research.md) explain the primary-source guidance and the
repository-specific decisions below.

## Ownership

| Area | Location and responsibility |
| --- | --- |
| HTTP endpoints | `server/app/api/routes/`: transport validation, cookies, status/error mapping |
| HTTP dependency wiring | `server/app/api/deps.py`, `api/limits.py` |
| Application workflows | `server/app/services/auth/`, `profile/`, `detection/`; shared logs, prompt allowance, readiness, and errors remain at the service root |
| SQL and persistence | `server/app/db/repositories/`: cohesive feature queries and writes |
| Transactions | `server/app/db/`: existing request session and explicit commit/refresh operations |
| Database model/schema infrastructure | Existing `db/models/`, `db/base.py`, `db/session.py`, `alembic/` |
| Redis adapters | Existing `server/app/stores/`; retain current semantics |
| Nutrition rules and upstreams | Existing `core/nutrition.py`, `services/nutrition/` |
| General backend helpers | `server/app/utils/`: readable device labels; nutrition rules and JWT security remain in `core/` |
| Shared application/schema shapes | Existing `server/app/schemas/`; keep the model tool contract intact |
| Shared domain enums | `server/app/models/enums.py`; enum values and meal ordering remain unchanged |
| Client bootstrap and routing | `client/src/app/`; preserve Vite's `src/main.tsx` entry point |
| Route composition | `client/src/pages/` |
| Product capabilities | `client/src/features/<feature>/`: components, hooks, models, services |
| Cross-feature HTTP transport | `client/src/services/http.ts`: one refresh promise and listener set |
| Shared UI, models and formatting | `components/`, `models/`, `utils/`, existing `types/` |

Shared UI elements have individual files in `components/` (for example `Logo.tsx`,
`Avatar.tsx`, and `PrimaryButton.tsx`). API declarations are grouped by context in
`types/auth.ts`, `profile.ts`, `onboarding.ts`, `meals.ts`, `nutrition.ts`, `logs.ts`, and
`detection.ts`; consumers import their definitions directly from these modules.
The split preserves all nine component bodies and 24 type declarations. Lint, typecheck,
all six client tests, the production build, and a sign-in browser smoke check passed.

Existing session-bound ORM entities remain internal application data during this relocation.
Introducing parallel domain entities, generic repositories, or a new transaction framework would
change substantially more than file ownership. Repositories materialize their queries and keep
existing eager loading; services retain the current transaction decisions.

## Execution plan

- [x] Inspect instructions, routes, services, SQL, client imports, framework versions, and checks.
- [x] Create the branch and record primary-source research.
- [x] Record baseline tests, API/schema fingerprints, and client build output.
- [x] Extract server persistence and workflows; relocate HTTP dependencies to `api/`.
- [x] Group client feature UI/state/models and split endpoint modules from shared HTTP transport.
- [x] Update imports, scripts, relevant documentation, and test references.
- [x] Run server tests/lint, client lint/typecheck/build, contract comparisons, and structure checks.
- [x] Review the complete diff and record results and any verification limits.

## Verification

Use the existing SQLite/fakeredis suite, preserving its external-boundary substitutions. Add
behavior coverage only for material moved paths not already covered, particularly food-log
ownership, portion corrections, and day assembly. Compare OpenAPI, all registered routes
(including hidden routes), model tool schema, and prompt/cache fingerprints before and after.
Check client transport behavior at the network boundary, retain the separate Recharts chunk,
and inspect the UI where local browser tooling permits. Do not run paid model calls or mutate
the managed database to validate a relocation.

## Results

Baseline: 268 server tests passed, one skipped; server lint and client lint/build passed.

Final verification on 2026-09-07:

- Server: 273 maintained behavior tests passed, one existing test skipped. Two temporary
  baseline comparisons also passed (275 passed in the combined run); the same two existing
  Starlette status-constant deprecation warnings remain. Ruff passed.
- Client: six network-boundary tests passed, along with ESLint, TypeScript, and the Vite
  production build. The tests now run in client CI and require no additional dependency.
- All 24 effective application routes match their original paths, HTTP methods, and handler
  names, including the hidden tool-schema endpoint. Effective routes were expanded using
  FastAPI's route contexts, because this version stores included routers lazily.
- The complete OpenAPI hash remains
  `3df9bb388066d7a3754d6a0a8824e53fa4ecd81c71170090312b32621b794d74`.
  The tool schema remains `e9f4ddd375475bbfe2a1b9a6e125b34710a15761a15f5e6c2dab7aa246a97622`,
  and the prompt fingerprint remains `8985ecc8bc4b11c6`. Sample photo/text cache keys also match.
- Every one of the 68 original JSX trees is byte-identical after relocation. There are no
  client import cycles across 59 modules. The generated stylesheet retains its original
  `index-BvcTDnxc.css` filename/hash and 36.05 kB size.
- The main client bundle is 355.32 kB (baseline 353.29 kB); Progress remains a separate
  389.86 kB lazy bundle (baseline 389.87 kB).
- A browser smoke check verified the production sign-in screen and the signed-out redirect
  from `/today` to `/signin`. Authenticated browser workflows and live external integrations
  were not exercised; their server behavior is covered using SQLite, fakeredis, and mocked
  upstream transports. No paid model calls or managed-database writes were used for testing.
- A source audit found no direct SQL/session operations remaining in API routes, services,
  core, or operational scripts. SQL lives in database adapters, with intentional exceptions
  for migration definitions and test fixtures. Database models, migrations, formulas, model
  prompts, nutrition ranking, theme tokens, and dependency lockfiles are unchanged.

Run the maintained checks with `uv run pytest` and `uv run ruff check .` from `server/`,
and `npm run lint`, `npm test`, `npm run typecheck`, and `npm run build` from `client/`.
Temporary relocation scripts and baseline-capture checks were removed after verification.

## Concrete module map

| Capability | HTTP entry | Workflow | Persistence |
| --- | --- | --- | --- |
| Google sign-in, refresh, session revocation | `api/routes/auth.py` | `services/auth/identity.py`, `services/auth/sessions.py`, `services/auth/google_oauth.py` | `db/repositories/users.py`, profile/goal reads, existing token stores |
| Onboarding and preview | `api/routes/onboarding.py` | `services/profile/service.py`, `services/profile/targets.py` | `db/repositories/profiles.py`, `goals.py` |
| Profile, targets, prompt allowance | `api/routes/profile.py` | `services/profile/service.py`, `prompt_limits.py` | profile/goal repositories, `prompt_usage.py` |
| Day logs and entries | `api/routes/logs.py` | `services/logs.py` | `db/repositories/logs.py`, `goals.py` |
| Photo, text, barcode | `api/routes/ai.py` | `services/detection/workflow.py`, sibling detector/barcode/cache modules, `services/nutrition/resolver.py` | `db/repositories/detections.py`, `barcode_products.py`, `foods.py` |
| Readiness | `api/routes/health.py` | `services/readiness.py` | `db/health.py`, `stores/health.py` |
| Reference-food seeding | `scripts/seed.py` | CLI/session setup | `db/seeding.py` |

Food input, confirmation, and the day log share `features/food-logging` because they are one
logging workflow. This avoids cross-feature imports between confirmation and its save operation.
The auth provider is app wiring, its context/hook are shared, and sign-in UI belongs to
`features/auth`. Auth and profile endpoint adapters are shared because several features use them.

Some existing instruction references retain their original paths because those files were user edits. Their
`core/deps.py`, `core/limits.py`, and `core/readiness.py` references now correspond to `api/deps.py`,
`api/limits.py`, and `services/readiness.py`; the owner-scoped entry query lives in
`db/repositories/logs.py`. Their `services/detection_cache.py` reference now points to
`services/detection/cache.py`. Model schemas and pure nutrition calculations retain their original paths.

## Service package grouping

Related services now share `auth/`, `detection/`, and `profile/` packages. Nutrition resolution
remains in `services/nutrition/`; shared logs, prompt allowance, readiness, and errors remain
at the service root. `app/core/` remains the single home for the existing target calculations
and JWT security functions.

The relocation updates application, test, and script imports without compatibility shims.
Comparison with the pre-grouping snapshot confirms all 113 existing Python files retain their
code outside import declarations and documentation-path corrections.

Validation after grouping: Ruff passed; the complete backend suite passed with 273 tests,
one existing skip, and two existing Starlette deprecation warnings.
