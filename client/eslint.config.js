import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "dev-dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The one rule this project actually needs a linter for. `tsc` cannot see
      // a missing dependency, and the failure it causes — a stale closure
      // reading last render's state — is the hardest class of bug here to spot
      // by reading.
      "react-hooks/exhaustive-deps": "error",
      // The severity split below is about *reading* the output, not about what
      // blocks a merge: `npm run lint` passes --max-warnings 0, so CI stops on
      // this rule exactly as hard as on the one above. Warn keeps it legible as
      // the lesser problem — a fast-refresh nicety rather than a live bug — while
      // still holding the line at zero.
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
);
