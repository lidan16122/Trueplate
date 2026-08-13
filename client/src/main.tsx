import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";

/**
 * Entry point.
 *
 * Renders the design's brand mark only — routing and the auth provider land in
 * the next change. This exists so the scaffold is independently buildable and
 * the design tokens can be seen applied to something.
 */
function App() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-page">
      <div className="flex h-11 w-11 items-center justify-center rounded-card bg-ink text-title font-bold text-surface">
        T
      </div>
      <p className="font-mono text-label tracking-[0.14em] text-faint uppercase">Trueplate</p>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
