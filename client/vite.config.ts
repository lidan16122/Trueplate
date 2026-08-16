import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "icons/icon-192.png"],
      manifest: {
        name: "Trueplate",
        short_name: "Trueplate",
        description:
          "Photograph a meal. Trueplate estimates the portions, you correct them, the numbers come from a food database.",
        start_url: "/",
        display: "standalone",
        background_color: "#f0f0ef",
        theme_color: "#14161a",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/icons/icon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        // The API is never cached. These responses are per-user and
        // authenticated; a service worker cache is shared across accounts on a
        // device, so a cached /logs response could be served to whoever signs in
        // next.
        navigateFallbackDenylist: [/^\/api/],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api"),
            handler: "NetworkOnly",
          },
        ],
      },
      devOptions: {
        // Off in dev: an auto-updating service worker fighting HMR produces
        // stale-module bugs that look like application errors.
        enabled: false,
      },
    }),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Same-origin in development. Without this the browser treats :5173 and
      // :8000 as different origins, and the httpOnly auth cookies need CORS
      // plus credentials handling to survive the trip. Proxying removes the
      // problem rather than configuring around it.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
