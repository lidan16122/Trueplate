import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

// Render the production component and run the real draft conversion; no UI dependencies are faked.
async function load(relative) {
  const source = await readFile(new URL("../src/features/food-logging/" + relative, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  });
  const code = outputText.replaceAll('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")));
  return import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
}

const { toDraft } = await load("models/draft.ts");
const { hasOriginalNutrition } = await load("models/grounding.ts");
const { GroundedSummary } = await load("components/GroundedSummary.tsx");

function proposal() {
  return {
    items: [{
      detected: { label: "Chicken", estimated_grams: 150.25, confidence: 0.9 },
      matched: { source: "usda_fdc", source_ref: "12345" },
      alternatives: [], is_rough: false, confidence_label: "Fairly sure",
    }],
    grounded_response: {
      status: "generated",
      statements: [{ fact_id: "totals", text: "The matched foods total 247.9 kcal.", item_indices: [0] }],
    },
  };
}

test("an untouched fractional portion keeps the summary consistent with the displayed totals", () => {
  const result = proposal();
  const drafts = result.items.map(toDraft);
  assert.equal(drafts[0].grams, 150.25);
  assert.equal(hasOriginalNutrition(result, drafts), true);
});

test("editing a portion, changing a source, adding or removing food hides the original summary", () => {
  const result = proposal();
  const drafts = result.items.map(toDraft);
  assert.equal(hasOriginalNutrition(result, [{ ...drafts[0], grams: 200 }]), false);
  assert.equal(hasOriginalNutrition(result, [{ ...drafts[0], matched: { source_ref: "different" } }]), false);
  assert.equal(hasOriginalNutrition(result, [...drafts, { ...drafts[0], key: "added" }]), false);
  assert.equal(hasOriginalNutrition(result, []), false);
});

test("the summary renders numbers with mono typography and cites the chosen source record", () => {
  const result = proposal();
  const html = renderToStaticMarkup(createElement(GroundedSummary, {
    summary: result.grounded_response, items: result.items,
  }));
  assert.match(html, /aria-label="Nutrition summary"/);
  assert.match(html, /class="font-mono">The matched foods total 247.9 kcal/);
  assert.match(html, /USDA FoodData Central \(12345\)/);
});

test("source labels and model strings render as text without executing markup", () => {
  const result = proposal();
  result.items[0].detected.label = '<img src="x" onerror="alert(1)">';
  const html = renderToStaticMarkup(createElement(GroundedSummary, {
    summary: result.grounded_response, items: result.items,
  }));
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});
