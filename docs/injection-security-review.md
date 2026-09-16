# Injection review — 2026-09-16

The detection endpoint now rejects unrelated tasks with HTTP 422 and this fixed response:

```json
{"detail":"Invalid request. Describe a meal, food or drink, or upload a food photo, menu or nutrition label."}
```

The review covered text detection, photo captions, model tools and response parsing,
nutrition resolution, detection caching, database repositories, and client error rendering.

## Findings and changes

- **Model-written rejection text:** `not_food` and empty-food responses previously forwarded
  the model's `notes` into HTTP errors. An injected answer could therefore reach the UI even
  when the food classifier rejected the request. Rejections now use server-written messages;
  rejected payloads never reach nutrition lookup or cache writes.
- **Unclear request scope:** The prompt now explicitly rejects programming, unrelated writing,
  role overrides, and mixed requests that ask to hide an answer inside food fields. The
  `invalid_request` outcome is part of the strict tool schema. Meal descriptions, portion
  corrections, existing recipes, menus and labels remain supported in any language.
- **Untrusted input boundaries:** Descriptions and captions are JSON-encoded data fields.
  The system prompt treats image text, search results and earlier model payloads as untrusted.
  JSON escaping preserves data boundaries; it is not itself a semantic injection defense.
- **Unexpected model output:** Free-text answers, unknown tools and duplicate recording calls
  fail closed. The application does not execute model-written SQL or code. Model field lengths,
  array lengths and finite numbers are validated locally. The salvage path now only tolerates
  invalid masses; extra fields and other invalid output reject the response.
- **Photo cache contamination:** Cache keys previously omitted captions and meal types. The same
  photo could replay another caption's result or skip classification of a new caption. Both now
  participate in the key. JSON encoding prevents delimiter ambiguity. Model, effort and prompt/
  schema fingerprint remain key inputs, retiring results from the earlier behavior.
- **Input/UI behavior:** Captions and descriptions are limited to 500 characters. Whitespace-only
  text is rejected. The existing client preserves HTTP 422 guidance without retrying or opening
  confirmation; errors are now announced as alerts.

## SQL injection

No exploitable SQL-injection path was found in the inspected application queries. Repositories
use SQLAlchemy expressions and bound parameters for names, identities, products, dates and
ownership criteria. Raw SQL expressions are fixed health-check or schema expressions; no
user/model text is interpolated into executable SQL. No query rewrite was necessary.

The regression tests exercise real SQLite reads, inserts, updates and HTTP log writes with
quotes, tautologies, UNION/DDL payloads, wildcard characters and ordinary apostrophes. They
also capture driver statements to verify that supplied values remain separate parameters.
Identity and product lookups do not match unrelated rows, and existing ownership tests pass.

## Validation and limits

- Backend: **355 passed, 1 skipped**; Ruff lint passed.
- Client: **12 passed**; TypeScript, ESLint and the production build passed.
- Live configured model (`claude-opus-5`, medium effort): **8/8** scope checks passed. Five
  unrelated/injection requests were rejected; ordinary food, a food correction and Hebrew food
  descriptions were accepted. These calls used an in-memory database and substituted nutrition
  HTTP, without production data changes.
- Browser verification was unavailable: no local app was listening on port 5173.

Run `python -m scripts.eval_request_scope` from `server` to repeat the live scope evaluation.
It uses the configured paid Anthropic account. `--case react_component` runs only that case.

Model classification remains probabilistic. A successful adversarial misclassification can
still produce a schema-valid but incorrect food description; these checks do not prove every
language, image injection or indirect web injection is blocked. Keep the model isolated from
database/code execution and rerun adversarial evaluations when changing prompts or models.
Database regression execution used SQLite, not a live PostgreSQL penetration test.

## Code review

The Standards review found no documented-standard violations and one optional P3 maintenance
issue: duplicate input-kind rejection checks. The duplicate was removed from nutrition resolution;
the model-response parser owns those rejections. No Standards findings remain open.

The Spec review found no missing requirements, unintended scope expansion or concrete
implementation regressions against the original injection-protection request.

The approach follows [Anthropic's prompt-injection guidance](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks)
and [SQLAlchemy's bound-parameter guidance](https://docs.sqlalchemy.org/en/14/faq/sqlexpressions.html).
