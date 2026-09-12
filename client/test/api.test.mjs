import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import { test } from "node:test";
import ts from "typescript";

let instance = 0;

// Compile the production modules with Vite's environment supplied by this harness.
// Only fetch is substituted; refresh coordination and each endpoint adapter run for real.
async function modules() {
  const version = ++instance;
  async function compile(relative, transport) {
    const source = await readFile(new URL("../src/" + relative, import.meta.url), "utf8");
    const { outputText } = ts.transpileModule(
      source.replace("import.meta.env.VITE_API_BASE_URL", '""'),
      { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } },
    );
    const code = outputText.replaceAll("@/services/http", transport ?? "") + "\n// " + version;
    return "data:text/javascript;base64," + Buffer.from(code).toString("base64");
  }
  const transport = await compile("services/http.ts");
  return {
    http: await import(transport),
    auth: (await import(await compile("services/auth.ts", transport))).authApi,
    logs: (await import(await compile("features/food-logging/services/logs.ts", transport))).logsApi,
    detection: (await import(await compile("features/food-logging/services/detection.ts", transport))).detectionApi,
  };
}

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

test("anonymous startup makes one successful request without refreshing or expiring", async (t) => {
  const { http, auth } = await modules();
  const seen = [];
  let expired = 0;
  http.onSessionExpired(() => { expired++; });
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(options.credentials, "include");
    seen.push(url);
    return json(null);
  });

  assert.equal(await auth.session(), null);
  assert.deepEqual(seen, ["/api/v1/auth/session"]);
  assert.equal(expired, 0);
});

test("startup and protected requests share refresh recovery", async (t) => {
  const { auth, logs } = await modules();
  let refreshed = false;
  let refreshes = 0;
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.endsWith("/auth/refresh")) {
      refreshes++;
      await pending;
      refreshed = true;
      return json({ detail: "Session refreshed" });
    }
    return refreshed ? json({ path: url }) : json({ detail: "Not authenticated" }, 401);
  });

  const requests = Promise.all([auth.session(), logs.day("2026-09-12")]);
  await setImmediate();
  assert.equal(refreshes, 1);
  release();
  assert.deepEqual((await requests).map((value) => value.path), [
    "/api/v1/auth/session", "/api/v1/logs/2026-09-12",
  ]);
});

test("a temporary startup failure remains an error without triggering refresh", async (t) => {
  const { http, auth } = await modules();
  const seen = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    seen.push(url);
    return json({ detail: "Temporarily unavailable" }, 503);
  });

  await assert.rejects(auth.session(), (err) => err instanceof http.ApiError && err.status === 503);
  assert.deepEqual(seen, ["/api/v1/auth/session"]);
});

test("startup remains compatible while the older API is still deployed", async (t) => {
  const { auth } = await modules();
  const seen = [];
  const session = { user: { id: "alice" }, needs_onboarding: false };
  t.mock.method(globalThis, "fetch", async (url) => {
    seen.push(url);
    return url.endsWith("/auth/session") ? json({ detail: "Not Found" }, 404) : json(session);
  });

  assert.deepEqual(await auth.session(), session);
  assert.deepEqual(seen, ["/api/v1/auth/session", "/api/v1/auth/me"]);
});

test("startup stops after one rejected refresh without falling back to another session check", async (t) => {
  const { http, auth } = await modules();
  const seen = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    seen.push(url);
    return json({ detail: "Session expired" }, 401);
  });

  await assert.rejects(auth.session(), http.SessionExpiredError);
  assert.deepEqual(seen, ["/api/v1/auth/session", "/api/v1/auth/refresh"]);
});

test("concurrent requests from different services share one refresh", async (t) => {
  const { auth, logs } = await modules();
  let refreshed = false;
  let refreshes = 0;
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(options.credentials, "include");
    if (url.endsWith("/auth/refresh")) {
      refreshes++;
      await pending;
      refreshed = true;
      return json({ detail: "Session refreshed" });
    }
    return refreshed ? json({ path: url }) : json({ detail: "expired" }, 401);
  });
  const requests = Promise.all([auth.me(), logs.day("2026-09-07")]);
  await setImmediate();
  assert.equal(refreshes, 1);
  release();
  const result = await requests;
  assert.deepEqual(result.map((value) => value.path), [
    "/api/v1/auth/me", "/api/v1/logs/2026-09-07",
  ]);
});

test("a 409 refresh retries without expiring the session", async (t) => {
  const { http, auth } = await modules();
  let reads = 0;
  let expired = 0;
  http.onSessionExpired(() => { expired++; });
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.endsWith("/auth/refresh")) return json({}, 409);
    return ++reads === 1 ? json({}, 401) : json({ user: "still signed in" });
  });
  assert.deepEqual(await auth.me(), { user: "still signed in" });
  assert.equal(reads, 2);
  assert.equal(expired, 0);
});

test("a rejected retry notifies the auth provider and stops refreshing", async (t) => {
  const { http, auth } = await modules();
  let refreshes = 0;
  let expired = 0;
  http.onSessionExpired(() => { expired++; });
  t.mock.method(globalThis, "fetch", async (url) => {
    if (url.endsWith("/auth/refresh")) { refreshes++; return json({}); }
    return json({}, 401);
  });
  await assert.rejects(auth.me(), http.SessionExpiredError);
  assert.equal(refreshes, 1);
  assert.equal(expired, 1);
});

test("bad sign-in credentials do not trigger refresh", async (t) => {
  const { http, auth } = await modules();
  const seen = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    seen.push(url);
    return json({ detail: "Google sign-in could not be verified" }, 401);
  });
  await assert.rejects(auth.signInWithGoogle("bad"), (err) => (
    err instanceof http.ApiError && !(err instanceof http.SessionExpiredError) && err.status === 401
  ));
  assert.deepEqual(seen, ["/api/v1/auth/google"]);
});

test("photo and barcode adapters retain multipart fields and browser boundaries", async (t) => {
  const { detection } = await modules();
  const seen = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    seen.push({ url, options });
    return json({});
  });
  const photo = new File(["image"], "meal.png", { type: "image/png" });
  await detection.detectPhoto(photo, "  half a plate  ");
  await detection.detectBarcode({ upc: " 12345678 " });
  assert.equal(seen[0].options.body.get("note"), "half a plate");
  assert.equal(seen[0].options.body.get("image").name, "meal.png");
  assert.equal(seen[1].options.body.get("upc"), "12345678");
  assert.ok(seen.every(({ options }) => !("Content-Type" in options.headers)));
});

test("validation failures retain readable details and deletes accept empty responses", async (t) => {
  const { http, logs } = await modules();
  t.mock.method(globalThis, "fetch", async (_, options) => options.method === "DELETE"
    ? new Response(null, { status: 204 })
    : json({ detail: [{ msg: "Portion too small" }, { msg: "Meal required" }] }, 422));
  await assert.rejects(logs.updateEntry("entry", 0), (err) => (
    err instanceof http.ApiError && err.message === "Portion too small, Meal required"
  ));
  assert.equal(await logs.deleteEntry("entry"), undefined);
});
