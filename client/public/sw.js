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
// check. Delete it once those have all had a chance to.
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
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));

      await self.registration.unregister();

      // Reload open tabs so they leave the precached index.html for the one
      // served fresh from the network.
      const clients = await self.clients.matchAll({ type: "window" });
      for (const client of clients) client.navigate(client.url);
    })(),
  );
});
