# Google sign-in entry failure investigation

Started on 2026-10-02 from `bbbfc875d912170702af206c536366e5f2dd78f2`.

## Report and evidence

A first-time visitor sees an error after pressing **Continue with Google**, before
Google opens. The reported status is possibly 403; the exact response, browser,
and failing request are not yet available. This is distinct from the anonymous
startup 401s addressed in `google-first-sign-in-401-plan.md`.

Read-only production checks found:

- Session discovery returns 200 with `Cache-Control: no-store`.
- Google start returns 303 to `accounts.google.com`, with the public frontend
  callback URL, state, PKCE, and only `openid email profile` scopes.
- Desktop Chrome, iPhone Safari, Android Chrome, and Instagram-style request
  headers all receive that redirect. Header probes do not emulate those browsers.
- A browser visit reaches Google's email-entry screen. No Google account was used.
- Backend readiness reports both database and Redis healthy.
- The existing auth and first-session integration suite passes: 64 tests.

None of these checks reproduces the friend's rejection or verifies a real first-time
production login. No production setting or deployment has been changed.

## Plan

1. Exercise the public Worker request/response boundary with an upstream HTML 403
   on `GET /api/v1/auth/google/start`. The expected result is a safe return to the
   sign-in screen with an actionable message, not a raw provider error page.
2. If that regression fails, handle unavailable OAuth navigation at the proxy.
   Cover the callback too, but never retry an authorization-code exchange: a code
   can already have been consumed. Preserve successful redirects and all cookies.
3. Keep ordinary API status codes and bodies intact. Use bounded, sanitized
   diagnostics that record the stage and status without URLs, queries, cookies,
   credentials, or upstream response bodies.
4. Verify 403, upstream outages, connection failures, and successful sign-in
   redirects through the real Worker handler with only outbound fetch substituted.
   Re-run backend auth tests, client tests, lint, typecheck, and build.
5. Review the change against the report and repository standards, then update the
   PR with actual results and remaining limits.

The recovery behavior is a mitigation for an upstream rejection. It cannot remove
a Cloudflare block that happens before the Worker runs, fix a Google account policy,
or establish that either happened here. Keep the PR draft until the original failure
is identified or the narrower recovery scope is explicitly accepted.

## Evidence still needed

The exact message and whether the failing address is `/api/v1/auth/google/start`,
a Google address, or `/signin?error=...` will distinguish the responsible service.
For a proxy failure, correlate its timestamp with Worker/Render logs. Do not share
cookie values, OAuth state, authorization codes, or full callback URLs.

## Implemented recovery and verification

The Worker now returns `303 /signin?error=connection` with `Cache-Control: no-store`
when either OAuth GET route receives an upstream error, a non-redirect holding page,
a network failure, a timeout, or invalid proxy configuration. The sign-in screen
explains that the connection failed and offers the existing Google button for a new
attempt. Successful redirects and their cookies pass through unchanged; ordinary
API responses retain their status/body. No request is automatically retried.

The permanent `google-sign-in-proxy` warning records only `stage` and `status`.
For example, `{ stage: "start", status: 403 }` identifies a rejection received by the
Worker before Google authorization. Status 502/504 also covers connection/timeout
failures, and 500 covers invalid configuration; upstream responses can use those
same codes. The record deliberately excludes request URLs, query strings, cookies,
error objects, and response bodies. Logs emitted by hosting providers are outside
this application logging change.

The original regression invocation, from `client`, was:

```powershell
node --test test/worker-auth.test.mjs
```

Before implementation, the upstream 403 case failed with `403 !== 303`. A second
case proved that a 200 holding page replaced the account chooser (`200 !== 303`).
Both are deterministic simulations of upstream responses, not observations of the
friend's failed request.

After implementation:

- All 11 Worker tests pass, including unchanged state/session cookies, specific
  backend error redirects, no callback replay, and credential-free diagnostics.
- The full client suite passes: 34 tests.
- Client lint, typecheck, and production build pass.
- The existing backend auth/first-session suite passes: 64 tests, using SQLite,
  fakeredis, and substituted Google responses. No backend code changed.
- Local desktop and mobile browser inspection confirms that the recovery message
  and Google button render together on the sign-in page.

This does **not** establish a root-cause fix for the reported production incident.
The PR remains a draft recovery improvement pending the original error evidence.

## Standards review

No findings. Independent review confirmed that the diff preserves the existing
architecture, OAuth transport, bounded timeout, and external-dependency test seam.
New comments follow the one-to-two-sentence caption rule.

## Spec review

No new implementation findings. Independent review verified all 11 Worker tests,
cookie/redirect preservation, unchanged ordinary API responses, sanitized diagnostics,
and absence of callback replay. One acknowledged partial requirement remains: the
original production rejection has not been identified or fixed.

Review totals: Standards 0; Spec 0 new defects and 1 unresolved incident requirement.

## Architecture and test boundaries

`client/worker` owns the production same-origin proxy; auth routes live in
`server/app/api`, identity/session services in `server/app/services/auth`, SQL
queries in `server/app/db`, and Redis sessions in `server/app/stores`.
The React sign-in feature owns user-facing error messages. Tests use those existing
public request/response seams and replace external dependencies only.
