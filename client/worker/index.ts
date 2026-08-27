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

/** JSON, because api.ts parses every response as JSON — an HTML or bare-text
 *  error surfaces to the user as a parse failure that names nothing. */
function configError(detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status: 500,
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
      return configError("API_ORIGIN is not configured on the Worker");
    }

    let target: URL;
    try {
      // Path and query only. Rebuilding the URL against API_ORIGIN is what swaps
      // the host; carrying anything else across would defeat that.
      target = new URL(url.pathname + url.search, env.API_ORIGIN);
    } catch {
      return configError("API_ORIGIN is not a valid origin");
    }

    // `redirect: "manual"` so a redirect from the API reaches the browser as a
    // redirect. Followed here, the Location would resolve against the API origin
    // and put it in the address bar — which is the one thing this file exists to
    // prevent the browser from seeing.
    return fetch(new Request(target, request), { redirect: "manual" });
  },
};
