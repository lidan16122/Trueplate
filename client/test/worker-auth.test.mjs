import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import ts from "typescript";

// Exercise the deployed handler; only the upstream network is substituted.
const source = await readFile(new URL("../worker/index.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { default: worker } = await import(
  "data:text/javascript;base64," + Buffer.from(outputText).toString("base64")
);

const env = {
  API_ORIGIN: "https://api.example.com",
  ASSETS: { fetch: async () => new Response("sign-in page") },
};
const startUrl = "https://app.example.com/api/v1/auth/google/start";
const callbackUrl = "https://app.example.com/api/v1/auth/google/callback?code=private-code&state=private-state";

test("an upstream 403 during Google start returns to sign-in with recovery guidance", async (t) => {
  t.mock.method(console, "warn", () => {});
  t.mock.method(globalThis, "fetch", async () => new Response(
    "<html><h1>Forbidden</h1></html>",
    { status: 403, headers: { "content-type": "text/html" } },
  ));

  const response = await worker.fetch(new Request(startUrl), env);

  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/signin?error=connection");
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(await response.text(), "");
});

test("an upstream holding page cannot replace the Google account chooser", async (t) => {
  t.mock.method(console, "warn", () => {});
  t.mock.method(globalThis, "fetch", async () => new Response(
    "<html><h1>Service starting</h1></html>",
    { headers: { "content-type": "text/html" } },
  ));

  const response = await worker.fetch(new Request(startUrl), env);

  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/signin?error=connection");
});

test("OAuth failures log only stage and status and never replay a callback", async (t) => {
  const warnings = [];
  t.mock.method(console, "warn", (...args) => warnings.push(args));
  let requests = 0;
  t.mock.method(globalThis, "fetch", async () => {
    requests++;
    return new Response("private upstream diagnostic", {
      status: 403,
      headers: { "set-cookie": "provider_challenge=private-cookie" },
    });
  });

  const response = await worker.fetch(new Request(callbackUrl, {
    headers: { cookie: "tp_oauth=private-state.private-verifier" },
  }), env);

  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/signin?error=connection");
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(await response.text(), "");
  assert.equal(requests, 1);
  assert.deepEqual(warnings, [["google-sign-in-proxy", { stage: "callback", status: 403 }]]);
});

test("an unavailable API returns both OAuth navigations to sign-in", async (t) => {
  t.mock.method(console, "warn", () => {});
  t.mock.method(globalThis, "fetch", async () => new Response("Unavailable", { status: 503 }));

  for (const url of [startUrl, callbackUrl]) {
    const response = await worker.fetch(new Request(url), env);
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("location"), "/signin?error=connection");
    assert.equal(response.headers.get("cache-control"), "no-store");
  }
});

for (const [name, failure, status] of [
  ["connection failure", new TypeError("private network details"), 502],
  ["timeout", new DOMException("private network details", "TimeoutError"), 504],
]) {
  test(`an OAuth ${name} can be retried from sign-in while API calls retain their status`, async (t) => {
    t.mock.method(console, "warn", () => {});
    t.mock.method(globalThis, "fetch", async () => { throw failure; });

    for (const url of [startUrl, callbackUrl]) {
      const response = await worker.fetch(new Request(url), env);
      assert.equal(response.status, 303);
      assert.equal(response.headers.get("location"), "/signin?error=connection");
    }
    const api = await worker.fetch(new Request("https://app.example.com/api/v1/auth/session"), env);
    assert.equal(api.status, status);
    assert.match((await api.json()).detail, /The API/);
  });
}

test("missing or invalid proxy configuration returns OAuth visitors to sign-in", async (t) => {
  t.mock.method(console, "warn", () => {});
  const upstream = t.mock.method(globalThis, "fetch", async () => assert.fail("must not call upstream"));

  for (const API_ORIGIN of ["", "not a URL"]) {
    const response = await worker.fetch(new Request(startUrl), { ...env, API_ORIGIN });
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("location"), "/signin?error=connection");
    assert.equal(await response.text(), "");
  }
  assert.equal(upstream.mock.callCount(), 0);
});

test("Google start preserves its redirect and the httpOnly state cookie", async (t) => {
  const cookie = "tp_oauth=state.verifier; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth/google/callback";
  const location = "https://accounts.google.com/o/oauth2/v2/auth?state=state&code_challenge=challenge";
  t.mock.method(globalThis, "fetch", async (request, options) => {
    assert.equal(request.url, "https://api.example.com/api/v1/auth/google/start");
    assert.equal(options.redirect, "manual");
    return new Response(null, { status: 303, headers: { location, "set-cookie": cookie } });
  });

  const response = await worker.fetch(new Request(startUrl), env);

  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), location);
  assert.deepEqual(response.headers.getSetCookie(), [cookie]);
});

test("successful callbacks keep every session cookie and the onboarding destination", async (t) => {
  const cookies = [
    "tp_access=access; HttpOnly; Secure; SameSite=Lax; Path=/",
    "tp_refresh=refresh; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth",
    "tp_oauth=; Max-Age=0; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth/google/callback",
  ];
  t.mock.method(globalThis, "fetch", async (request, options) => {
    assert.equal(request.url, "https://api.example.com/api/v1/auth/google/callback?code=private-code&state=private-state");
    assert.equal(request.headers.get("cookie"), "tp_oauth=private-state.private-verifier");
    assert.equal(options.redirect, "manual");
    const headers = new Headers({ location: "/onboarding" });
    for (const cookie of cookies) headers.append("set-cookie", cookie);
    return new Response(null, { status: 303, headers });
  });

  const response = await worker.fetch(new Request(callbackUrl, {
    headers: { cookie: "tp_oauth=private-state.private-verifier" },
  }), env);

  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/onboarding");
  assert.deepEqual(response.headers.getSetCookie(), cookies);
});

test("handled callback errors retain the server's specific recovery message", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(null, {
    status: 303, headers: { location: "/signin?error=state" },
  }));

  const response = await worker.fetch(new Request(callbackUrl), env);

  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/signin?error=state");
});

test("ordinary API failures and non-navigation auth requests keep their status and body", async (t) => {
  const detail = "Request forbidden";
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ detail }), {
    status: 403, headers: { "content-type": "application/json" },
  }));

  for (const request of [
    new Request("https://app.example.com/api/v1/detect/text", { method: "POST" }),
    new Request("https://app.example.com/api/v1/auth/google", { method: "POST" }),
    new Request(startUrl, { method: "POST" }),
  ]) {
    const response = await worker.fetch(request, env);
    assert.equal(response.status, 403);
    assert.equal(response.headers.get("location"), null);
    assert.deepEqual(await response.json(), { detail });
  }
});
