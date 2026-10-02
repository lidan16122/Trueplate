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

## Architecture and test boundaries

`client/worker` owns the production same-origin proxy; auth routes live in
`server/app/api`, identity/session services in `server/app/services/auth`, SQL
queries in `server/app/db`, and Redis sessions in `server/app/stores`.
The React sign-in feature owns user-facing error messages. Tests use those existing
public request/response seams and replace external dependencies only.
