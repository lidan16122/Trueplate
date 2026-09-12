# Google first-session 401 investigation and implementation

Investigated on 2026-09-12, from `e7f6581`, on branch `google-first-sign-in-401`.

## Finding

The two reported status codes alone do not establish a Google sign-in failure. The original
client produced that exact sequence on an anonymous page load, before Google sign-in started.
A failure to enter the app after completing Google sign-in remains unconfirmed without the
callback response and request ordering from the affected browser.

The implemented change addresses that confirmed startup behavior. It has been verified
locally; it has not been deployed or verified through a real production Google login.

## Implemented behavior

The auth provider now calls `GET /api/v1/auth/session` on startup. The server reuses the
existing access-token verification and current-user lookup, with these outcomes:

| Browser session | Discovery response | Client behavior |
| --- | --- | --- |
| No valid access, no refresh cookie | `200`, JSON `null` | Render sign-in without requesting refresh |
| Valid access and active user | `200`, existing session shape | Route using the user's onboarding state |
| Rejected access with a refresh cookie | `401` | Use the existing shared refresh and retry |
| Rejected refresh token | Existing refresh `401` | End recovery and render sign-in |
| Database/infrastructure failure | Error propagates | Existing startup failure handling applies |

Both successful discovery outcomes have `Cache-Control: no-store`. `/auth/me` and all other
protected routes retain their authentication requirements; no cookie is exposed to JavaScript.
The refresh store, concurrency grace window, and Google OAuth flow were not changed.

Prefer deploying the backend endpoint before the client. Deployments finish independently,
so the new client falls back to `/auth/me` only if discovery returns 404 from an older backend.
The initial 401 pair may persist during that rollout window; other errors do not invoke this
compatibility fallback.

## Evidence

The production HTTP client was compiled with the public production origin and run using
anonymous Node fetch requests. It produced:

```text
GET  /api/v1/auth/me       401  {"detail":"Not authenticated"}
POST /api/v1/auth/refresh  401  {"detail":"No refresh token"}
```

These are observations from an independent anonymous request, not the response bodies from
the user's failed attempt. The harness asserted both statuses and their order.

A separate anonymous request to the production `/api/v1/auth/google/start` returned:

```text
303 -> https://accounts.google.com/o/oauth2/v2/auth
redirect_uri=https://trueplate.lidan16122.workers.dev/api/v1/auth/google/callback
Set-Cookie: tp_oauth=<REDACTED>; HttpOnly; Max-Age=600;
            Path=/api/v1/auth/google/callback; SameSite=lax; Secure
CF-Cache-Status: DYNAMIC
```

This verifies the deployed start route, callback URL, and outgoing state-cookie attributes.
It does not verify the Google exchange, browser cookie acceptance, or a successful production
callback. No real Google account was used.

The relevant flow at the investigation's starting commit was:

1. [AuthProvider](../client/src/app/providers/AuthProvider.tsx) calls `authApi.me()` on mount,
   including when the visitor has no session. Route guards wait for this check to settle.
2. [The HTTP client](../client/src/services/http.ts) attempts one shared refresh after a 401.
   Without a refresh cookie, the server returns another 401 and clears the auth cookies.
3. [The Google button](../client/src/features/auth/components/GoogleSignInButton.tsx) starts
   a full-page navigation to `/api/v1/auth/google/start`.
4. [The callback](../server/app/api/routes/auth.py) redirects to `/today` or `/onboarding`
   with access and refresh cookies on success. Handled failures redirect to
   `/signin?error=...`, which causes a new page load and another session check.
5. [The Worker](../client/worker/index.ts) preserves upstream redirects. The callback's
   relative redirect is returned directly, including its response headers.

The server owns HTTP handling in `app/api`, session logic in `app/services/auth`, database
access in `app/db`, and refresh-token storage in `app/stores`. Diagnostic cases use the
existing integration fixtures in `server/tests`.

## Validation

Commands run from `server`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth_first_session.py tests/test_auth_routes.py tests/test_refresh_tokens.py -q -p no:cacheprovider
```

Result after the change: **95 passed in 2.61s**. First-session tests cover anonymous discovery,
OAuth start and callback for new and returning users, authenticated discovery, expired/missing
access-cookie recovery, invalid access without refresh, deactivated users, and database failure.
The new anonymous regression cases were run before implementation and failed as expected.

The routes, identity logic, JWT handling, and refresh store execute normally. Google responses
are substituted, SQLite replaces Postgres, and fakeredis executes the real Lua. These tests
do not model browser SameSite enforcement or the deployed Cloudflare/Render path.

The complete backend suite passed: **322 passed, 1 skipped**. The client suite passed:
**11 tests**, including anonymous discovery without refresh, shared recovery between discovery
and a protected request, propagation of a temporary discovery failure, older-backend
compatibility, and stopping after a rejected refresh. Backend Ruff,
client lint, typecheck, and the production build passed.

A local browser check rendered the sign-in page without console warnings/errors. Navigating
to `/today` while anonymous returned to sign-in, and the API logged only successful discovery
requests with no `/auth/me` or `/auth/refresh` calls. Vite development StrictMode issued two
discovery requests per load; each returned 200. Real Google verification and production
browser cookie acceptance remain outside these checks.

## Evidence needed from one failed attempt

Enable **Preserve log** in the browser Network panel before reproducing. Supply:

- Whether sign-in succeeds, stays on sign-in, or needs a second attempt; browser/version and
  the attempt's timestamp with timezone.
- The status and `Location` of `/api/v1/auth/google/callback`, with its request query removed.
  A redirect to `/signin?error=state`, `exchange`, `verification`, or `unavailable` is useful.
- Whether the two 401s occurred before or after that callback, and their response JSON bodies.
- If the callback redirects to `/today` or `/onboarding`: cookie names and attributes from
  its `Set-Cookie` headers, any browser blocked-cookie reason, and whether `tp_access` and
  `tp_refresh` were attached to the following auth requests. Replace all cookie values with
  `<REDACTED>`; do not copy authorization codes, state values, tokens, or full callback URLs.
- For a failed callback, the matching Render log message and redacted exception, if any.
  Existing messages distinguish state rejection, token exchange, credential verification,
  and unexpected callback failure. Begin with those before adding instrumentation.

## Follow-up plan if Google sign-in still fails

1. **Identify the failing transition.** Correlate one browser sequence with the callback
   outcome and server timestamp. If the pair only precedes a successful login, classify it
   as the current anonymous-session protocol; there is no demonstrated login failure to fix.

2. **Reproduce a confirmed failure at its actual boundary.** For a failed callback, extend
   the route integration tests with the observed external failure. For a successful callback
   followed by missing cookies, use a browser reproduction through the Worker: server-only
   cookie-jar tests cannot establish browser acceptance. Include the first attempt and retry.

3. **Apply the smallest evidence-supported change.** A callback error determines whether the
   fix belongs in OAuth configuration, state handling, verification, or dependency recovery.
   A successful callback with absent cookies requires tracing `Set-Cookie` across the proxy
   and checking the browser's rejection reason and subsequent cookie scope. If cookies arrive
   but are rejected, inspect token validation and refresh-store outcomes using the exact
   response detail. Preserve httpOnly cookies, state/PKCE checks, single-flight refresh, and
   atomic rotation.

4. **Keep startup discovery separate from protected reads.** The implemented anonymous
   response removes the confirmed initial 401 noise. A callback failure is a distinct
   problem that still requires the affected browser's redirect and cookie evidence.

5. **Verify against the original browser sequence.** Require successful first-attempt login
   for both new and returning users, correct onboarding routing, reload persistence, expired
   access-token recovery, and the existing refresh concurrency/reuse tests. Add Worker tests
   for multiple `Set-Cookie` headers only if the confirmed fix touches the proxy. Run the
   relevant backend/client checks, then validate the affected browser against the deployed
   fix when deployment is authorized.

The branch implements the confirmed anonymous-startup improvement. Any remaining failure
after the Google callback needs its own reproduction before changing OAuth or cookie policy.
