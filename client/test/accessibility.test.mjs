import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/features/accessibility/models/preferences.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { parsePreferences, DEFAULT_PREFERENCES } = await import(
  "data:text/javascript;base64," + Buffer.from(outputText).toString("base64")
);

test("missing or damaged browser preferences leave the site at its default presentation", () => {
  for (const stored of [null, "{broken", "null", "false", '"large"']) {
    assert.deepEqual(parsePreferences(stored), DEFAULT_PREFERENCES);
  }
});

test("restoring supported preferences preserves the reader's choices", () => {
  const preferences = { textSize: 150, highContrast: true, highlightLinks: true, reduceMotion: true };
  assert.deepEqual(parsePreferences(JSON.stringify(preferences)), preferences);
});

test("unsupported saved values cannot shrink text or enable settings by coercion", () => {
  const stored = JSON.stringify({ textSize: -10, highContrast: "false", highlightLinks: 1, reduceMotion: true });
  assert.deepEqual(parsePreferences(stored), { ...DEFAULT_PREFERENCES, reduceMotion: true });
});
