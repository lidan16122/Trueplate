// Demolition worker. The app used to register a Workbox service worker through
// vite-plugin-pwa; removing the plugin stops /sw.js being emitted but leaves
// that worker installed in every browser that already visited, still serving a
// precached index.html — the one carrying the manifest link this change exists
// to remove.
//
// A missing file would not fix it. `not_found_handling` in wrangler.jsonc
// answers an unmatched path with index.html at 200 and a text/html content
// type, which the browser treats as a failed update rather than the 404 that
// would unregister the worker. So the file has to exist, and has to be real
// JavaScript.
//
// Nothing registers this — the injected registerSW.js is gone — so only
// browsers holding the old registration ever fetch it, on their next update
// check. Delete it after 2026-09-21, by which point they have all had one.
//
// No fetch handler on purpose: this worker must never serve a response, only
// take itself and its caches out.

self.addEventListener("install", () => {
  // Without this the new worker waits for every controlled tab to close, which
  // on an app someone has bookmarked can be never.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Caches first: unregistering can end this worker's life, and an orphaned
      // workbox-precache-v2 entry would go on occupying storage with no worker
      // left to clear it.
      //
      // But nothing in this sweep may throw. `Promise.all` would reject on the
      // first failed delete and take the whole handler down with it, so
      // `unregister()` below would never run and the worker would survive —
      // precisely the outcome this file exists to prevent. A cache that resists
      // deletion is worth far less than getting the worker off the device.
      try {
        const keys = await caches.keys();
        await Promise.allSettled(keys.map((key) => caches.delete(key)));
      } catch {
        // Storage that will not even open is not a reason to stay installed.
      }

      await self.registration.unregister();

      // Reload open tabs so they leave the precached index.html for the one
      // served fresh from the network. `navigate()` rejects for any client this
      // worker does not control, and awaiting it matters: an unawaited promise
      // inside `waitUntil` lets the worker be terminated mid-reload, and an
      // uncaught one surfaces as an unhandled rejection nobody will ever read.
      // A tab that fails to reload here simply clears on its next navigation.
      const clients = await self.clients.matchAll({ type: "window" });
      await Promise.all(
        clients.map((client) => client.navigate(client.url).catch(() => {})),
      );
    })(),
  );
});
