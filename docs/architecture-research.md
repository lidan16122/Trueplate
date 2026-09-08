# Server and client structure research

Research date: 2026-09-07. Scope: move existing responsibilities into clear owners while preserving behavior, contracts, schema, styling, and dependencies.

This is a historical research record: paths in the starting inventory and initial proposals
deliberately describe the pre-refactor checkout. For current locations and verification, use
the [architecture plan](architecture-plan.md) and [README layout](../README.md#project-layout).

## What the primary sources establish

- FastAPI supports separate `APIRouter` modules composed by the application, with shared dependencies applied at the appropriate boundary. Its example is a supported organization, not a mandatory universal directory tree. Keep endpoint definitions in API modules and application composition separate. [FastAPI: Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- FastAPI dependencies using `yield` can own database-session setup and cleanup. Preserve the existing session lifecycle when moving dependency wiring; a folder refactor does not justify changing response or transaction timing. [FastAPI: Dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
- SQLAlchemy states that one `AsyncSession` must not be used by concurrent tasks. Its async guidance also covers explicit eager relationship loading and `expire_on_commit=False` for access after commit. Preserve Trueplate's `selectinload`, flush/refresh order, and session settings when extracting queries. [SQLAlchemy 2.0: AsyncIO](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- React recommends custom hooks with a concrete purpose; hooks share stateful logic, not one shared state instance. A cohesive existing preview or loading workflow can move into a feature hook without introducing a new state library. [React: Reusing Logic with Custom Hooks](https://react.dev/learn/reusing-logic-with-custom-hooks)
- React associates state with component identity and tree position. Keep JSX structure, keys, and provider placement stable during relocation. Lazy imports delay loading until rendering, and lazy component declarations should remain at module scope. [React: Preserving and Resetting State](https://react.dev/learn/preserving-and-resetting-state), [React: lazy](https://react.dev/reference/react/lazy)
- Pydantic's `extra="forbid"` rejects unrecognized inputs. Trueplate's model-facing detection schema is a product boundary, so retain it and compare its generated schema exactly. [Pydantic: ConfigDict.extra](https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict.extra)

The feature names, repository modules, and ownership decisions below are **Trueplate-specific recommendations**, informed by those constraints and the senior backend/frontend skills. The cited frameworks do not prescribe `bll`, `dal`, repository classes, or a feature-folder naming scheme.

## Starting inventory and concrete moves

The server uses FastAPI, Pydantic 2, SQLAlchemy 2 async sessions, Redis stores, and Alembic. Existing names already express useful boundaries: `app/services` is business/application logic, `app/db` is persistence, `app/stores` is Redis access, and `app/schemas` contains shared application and transport shapes. Retain these names rather than add parallel `bll`/`dal` trees.

| Starting owner | Finding | Initial proposed owner and boundary |
| --- | --- | --- |
| `app/api/routes/logs.py` | HTTP handlers also query/create logs, mutate entries, calculate totals, and assemble days. | Keep endpoint declarations and response mapping in API; move day and entry workflows into `services/logs.py`, scoped queries and storage mutations into `db/repositories/logs.py`. |
| `app/api/routes/onboarding.py` | Six endpoints mix profile/onboarding transport, name rules, profile/weight persistence, and goal sequencing. | Keep onboarding HTTP handlers together; group profile HTTP handlers separately where useful. Put workflows in profile/onboarding services and profile/weight queries in cohesive repositories. |
| `app/services/auth_service.py`, `app/core/deps.py`, auth routes | Identity lookup, email collision checks, onboarding completeness checks, and current-user retrieval touch Postgres. Cookie/OAuth HTTP behavior already has a distinct boundary. | Identity/user/profile/goal repositories own queries. Auth service retains identity decisions. `api/deps.py` owns FastAPI wiring; cookies, redirects, and HTTP error translation remain in API. |
| `app/services/targets.py` | Target formulas/mapping coexist with latest-weight queries, active-goal lookup, and historical-goal updates. | Weight/goal repositories own persistence; target services retain formula inputs and goal sequencing. Preserve `core/nutrition.py` as pure synchronous functions. |
| `app/services/prompt_limits.py` | Usage policy and the owned-entry count query share a module. | A prompt-usage repository owns the two counters; the service retains `PromptUsage` and allowance policy. Preserve the existing approximate text-detection count. |
| `app/services/detection_cache.py`, `app/services/barcode.py` | Cache/lookup policy includes Postgres reads, writes, and savepoint conflict handling. | Detection and barcode-product repositories own storage. Existing services keep cache keys, expiry/validation decisions, upstream order, default portions, and response construction. |
| `app/services/nutrition/resolver.py` | The resolution ladder includes exact-name food queries, barcode-name queries, and food write-back. | Food/barcode-product repositories own those SQL operations. Keep source clients, ranking, relevance, number validation, and resolution order in `services/nutrition/`. |
| `app/core/readiness.py`, `scripts/seed.py` | Infrastructure liveness SQL and seed SQL sit outside persistence. | A small `db/health.py` adapter owns `SELECT 1` and failed-probe cleanup; readiness retains timeout/report coordination. Seed storage belongs in `db`, with the script retaining CLI/session setup. |
| `app/db/models`, `app/db/base.py`, `app/db/session.py`, `alembic`, `app/stores`, `app/schemas` | Existing coherent persistence, migration, Redis, and data-shape ownership. | Retain their established locations and behavior. Do not move model-facing schemas merely because they use Pydantic. |

Repositories should expose cohesive operations rather than a generic CRUD framework. Keep the current shared unit of work: extracting several repository calls must not make each call commit independently. Existing services may retain their present session/ORM interfaces during this mechanical extraction; replacing all entities with domain DTOs and introducing protocols everywhere would be a separate architecture migration.

At the start of the refactor, the client used React 19.2, React Router 7, TypeScript, Vite,
Tailwind theme tokens, and a hand-written HTTP client, with no client test runner. Node's test
runner was added during the refactor. Routes are explicitly configured rather than inferred
from the filesystem.

| Starting owner | Finding | Initial proposed owner and boundary |
| --- | --- | --- |
| `src/router.tsx`, `src/main.tsx`, `components/ProtectedRoute.tsx` | Routing, bootstrap, guards, and lazy fallback form the application shell. | `app/router.tsx` and application routing components; keep the Vite entry stable and preserve provider order. |
| `src/auth/*`, `pages/SignIn.tsx` | One coherent authentication feature. | `features/auth` for state, sign-in UI, and hooks; application-level guards consume its public API. |
| `src/lib/api.ts` | Refresh coordination, transport errors, and every endpoint group are combined. | `services/http.ts` owns the single refresh promise, listeners, cookies, parsing, and retry. Feature services own auth/onboarding/profile/detection/log endpoint methods. Cross-feature calls may remain shared services. |
| `pages/Onboarding.tsx`, `TargetReveal.tsx`, `wizardSteps.ts` | Wizard screens, preview hook, and pure wizard rules already form one feature. | `features/onboarding` with components, `hooks/useTargetPreview`, and `models/wizardSteps`. Keep route entry components or page composition explicit. |
| `pages/AddFood.tsx`, `Confirm.tsx` | Detection input, confirmation drafts, and save workflow are one product capability. | `features/food-detection` for screens, state, models, and detection transport. Preserve navigation-state payloads and every existing transformation. |
| `pages/Today.tsx`, `FoodLog.tsx`, `Profile.tsx`, `Progress.tsx` | Distinct feature screens; `DateStrip` and `MealGroup` are log-specific UI. | Food-log/profile/progress feature owners; move specialized components with their feature. Preserve the separate lazy progress entry. |
| `lib/format.ts`, `lib/labels.ts`, `lib/portion.ts`, `types/api.ts`, `components/*` | Domain rules, generic formatting, shared types, and reusable UI overlap. | Domain-neutral date/number formatting in `utils`; shared nutrition/meal/profile concepts in `models`; wire declarations in `types` or beside owning services. Shared UI stays in `components`; feature-specific controls move only when their consumers justify ownership. Keep `index.css` tokens intact. |

## Preservation and verification plan

1. Record the existing branch/status and baseline server/client checks before moving files. Preserve unrelated user edits. Capture the OpenAPI document, complete route table (including the hidden AI tool-schema endpoint), detection tool schema, and prompt fingerprint.
2. Extract server persistence and workflows while retaining all existing endpoint paths, HTTP methods, handler operation IDs, request/response shapes, status codes, cookie effects, and validation messages. The starting route inventory is seven auth endpoints, six onboarding/profile endpoints, five log endpoints, four AI endpoints including the hidden schema route, and two health endpoints.
3. Move client features and split transport ownership without changing markup, CSS classes, URLs, navigation state, form defaults, render-time calculations, or request sequencing. Keep exactly one shared auth refresh instance, including 409 handling and session-expired notifications. Keep Recharts reachable through the existing lazy route boundary only.
4. Preserve query predicates and eager-loading options, owner-scoped entry joins, commit/flush/refresh boundaries, and cache/savepoint conflict behavior. Preserve Redis Lua operations, expiry/grace windows, and all upstream timeouts. Do not replace real SQLite/fakeredis behavior tests with mocks of internal repositories.
5. Preserve the product invariant: the model supplies labels and grams only; nutrition originates from resolved source rows. Keep per-100 g snapshots separate from quantity, goal history intact, detection cache fingerprint inputs unchanged, and nutrition ranking untouched. No migration, dependency upgrade, formula change, retry change, or unrelated async conversion belongs in this task.
6. Re-run server Ruff and pytest, client typecheck/lint/build, and compare captured API/schema artifacts. Inspect all remaining SQL and network call sites for ownership; SQL in migrations, tests, session setup, and dedicated database adapters is intentional. Review import cycles and the built progress chunk, then smoke-check relocated screens when a runnable browser session is available.

Completion evidence belongs in the implementation plan/report: this research document recommends the checks and does not claim they have run.

## Decisions adopted after the initial proposal

- Food input, confirmation, and diary screens share `client/src/features/food-logging/`.
- Auth provider/guard wiring lives in `client/src/app/`; the shared auth hook/context live in
  `hooks/` and `models/`, with sign-in UI in `features/auth/`.
- Backend services are grouped into `auth/`, `detection/`, and `profile/`, alongside nutrition
  resolution. Shared enums live in `server/app/models/enums.py`.
- Shared client components and API types use individual component files and context-specific
  type modules. The old aggregate modules are no longer current import locations.
- The 2026-09-08 documentation audit checked Redis transaction semantics against the
  [redis-py pipeline documentation](https://redis.io/docs/latest/develop/clients/redis-py/transpipe/).
  A transactional pipeline protects its queued commands; read-dependent mutations here use Lua.
