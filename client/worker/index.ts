/**
 * Forwards `/api` to the deployed API so the browser only ever sees one origin.
 *
 * This is the production half of what `server.proxy` in `vite.config.ts` does in
 * development, and it exists for the same reason. The auth cookies are
 * `SameSite=lax`, which browsers refuse to send on a cross-site fetch — so a
 * client calling the API on its own domain would sign in successfully and then
 * have every subsequent request arrive anonymous. Not an error anywhere: a 200,
 * a `Set-Cookie`, and a session that never applies.
 *
 * Proxying removes the problem rather than configuring around it. The
 * alternative — `SameSite=none` plus a CORS allowlist — trades a config change
 * for a weaker cookie and a dependency on third-party cookie support that
 * browsers are actively removing.
 *
 * Because the hop from here to the API is server-to-server, no browser is
 * involved and CORS never applies. `CORS_ORIGINS` on the server stays at its
 * default and unused, exactly as `app/config.py` says it is in development.
 */

interface Env {
  // Declared by `assets.binding` in wrangler.jsonc.
  ASSETS: { fetch(request: Request): Promise<Response> };
  // The API's origin, scheme and host only — no path. A Cloudflare
  // secret rather than a `vars` entry: `vars` are declared in wrangler.jsonc and
  // would live in the repo, and plain variables set in the dashboard are wiped
  // by the next `wrangler deploy`. Secrets survive one.
  //
  //   cd client && npx wrangler secret put API_ORIGIN
  API_ORIGIN: string;
}

// Render's free tier sleeps after 15 minutes and takes around 50 seconds to wake,
// so a ceiling under that would report an outage every time someone is first
// through the door. Cloudflare severs a subrequest near 100 seconds regardless;
// failing just before that is what turns an opaque platform error page into a
// message naming the cause.
const UPSTREAM_TIMEOUT_MS = 90_000;

/** JSON with a `detail`, matching what the API sends and `readErrorMessage` in
 *  api.ts reads. Every failure here goes through this: the client parses every
 *  response as JSON, so an HTML or bare-text body surfaces to the user as a
 *  parse failure that names nothing. */
function errorResponse(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // `run_worker_first` should mean only /api/* ever reaches this Worker, but
    // the asset path is the correct answer for anything else that does — a
    // Worker that 404s the app because a rule changed shape is a bad failure.
    if (!url.pathname.startsWith("/api/")) {
      return env.ASSETS.fetch(request);
    }

    // Fail loudly on a missing or malformed origin. The tempting alternative —
    // falling through to the assets — returns the SPA's index.html with a 200,
    // which the client then tries to parse as JSON. That is the single most
    // confusing failure this file could produce, so it is the one ruled out.
    if (!env.API_ORIGIN) {
      return errorResponse(500, "API_ORIGIN is not configured on the Worker");
    }

    let target: URL;
    let apiOrigin: string;
    try {
      // Path and query only. Rebuilding the URL against API_ORIGIN is what swaps
      // the host; carrying anything else across would defeat that.
      target = new URL(url.pathname + url.search, env.API_ORIGIN);
      apiOrigin = new URL(env.API_ORIGIN).origin;
    } catch {
      return errorResponse(500, "API_ORIGIN is not a valid origin");
    }

    let response: Response;
    try {
      // `redirect: "manual"` so a redirect from the API reaches the browser as a
      // redirect rather than being resolved here against the API's origin.
      response = await fetch(new Request(target, request), {
        redirect: "manual",
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      });
    } catch (error) {
      // Without this the rejection escapes and Cloudflare serves its own HTML
      // error page — which api.ts cannot parse, leaving the user with a bare
      // status and no cause. 502/504 because this Worker is a gateway, and the
      // failure is the upstream's, not the request's.
      const timedOut = error instanceof Error && error.name === "TimeoutError";
      return timedOut
        ? errorResponse(504, "The API did not respond in time")
        : errorResponse(502, "The API could not be reached");
    }

    // `manual` stops the Worker following a redirect; it does not rewrite the
    // Location it carries. Starlette builds absolute ones from the Host header —
    // the API's host — so handing that to the browser would move it off this
    // origin and strand the cookies, which is the whole failure this file exists
    // to prevent. Rewriting the Location back to a path keeps a redirect here.
    const location = response.headers.get("location");
    if (location) {
      const resolved = new URL(location, target);
      if (resolved.origin === apiOrigin) {
        const headers = new Headers(response.headers);
        headers.set("location", resolved.pathname + resolved.search + resolved.hash);
        return new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers,
        });
      }
    }

    return response;
  },
};
