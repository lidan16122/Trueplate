# Whole dishes in photo detection

Research date: 2026-09-09. Implementation date: 2026-09-10.

## Implementation outcome

The detection prompt, initial tool schema, default photo message, and retry instructions now use foods as served. Identical pizza slices share one portion; separate foods and different pizza types retain their own entries. Complete single-food photos can be cached without an incompleteness warning.

Live evaluation exposed a second issue: the model sometimes named every food but supplied a portion only for the first, even after a prose retry. A count mismatch now switches the retry to a generated `complete_food_portions` tool with one required property and fixed label for every named food. The same `DetectedFood` contract validates these portions, including the prohibition on nutrition fields; the public API still returns the original food-list shape. An invalid mass retains its separate retry allowance.

Pizza matching rejects components, unrelated pizza products, and explicit ingredient contradictions, and prefers ordinary recipes over unrequested variants. The resolver carries the original food identity through the fallback ladder and applies it to stored and upstream matches. New `foods` write-backs retain the source name in the existing JSON column. Legacy fetched pizza rows without that identity are refetched on demand; logged meal snapshots are not rewritten.

The new [live evaluation script](../server/scripts/eval_detection.py) runs repeated detections using an in-memory SQLite database. It supports the seven text scenarios below and an optional original pizza photo. The original uploaded image was not available in the workspace or accessible browser tabs, so original-photo validation remains unperformed.

## Verification record

- Captured five new USDA queries through the app's actual GET request format into [the existing matching fixture](../server/tests/fixtures/usda_search.json), preserving its previous cases.
- Compared the original ranker from `origin/main` with the updated ranker against identical data: **existing cases 29/31 → 29/31; dish cases 2/5 → 5/5**. The combined offline eval reports **34/36** and exits nonzero for the same two pre-existing misses: shredded chicken and generic sauce.
- Early live runs before the structured retry scored **19/21**, **1/3** on a diagnostic side-dish run, **3/3** on sides after clarifying the array description, and **19/21** on the next full run. The failures were incomplete inventories, which remained provisional; these results motivated the required-field repair instead of repeated prompt tuning.

- Final server suite: **315 passed, 1 skipped**. Ruff and `git diff --check` passed. The schema and ranking checks were also rerun after strengthening the repair-contract assertions: **54 passed**.
- With the structured retry, the targeted different-slice case passed **3/3**, including a real repair of an omitted pepperoni slice.
- Final live matrix on `claude-opus-5`, effort `medium`, prompt fingerprint `4753fa33ac6b9b74`: **21/21 passed**, three runs each for identical pizza slices, different pizza types, pizza with salad and dip, rice beside chicken, pasta beside beef, lasagna, and an apple. The required-field retry recovered a missing salad/dip and two missing beef portions in this run.

The live checks verify grouping and stated portions for those text inputs. They do not establish nutritional accuracy for a specific recipe or reproduce the unavailable original photo. The photo service and caching path are covered by deterministic tests with external responses substituted.

## Decision

Treat a recognizable prepared dish such as pizza as one loggable food, including its normal ingredients. Keep independently served foods separate. This is a product policy informed by [USDA research](composite-food-detection-research.md), not a claim that every recipe has one exact database match.

For two slices of the same pizza, return one pizza entry with `household_quantity: 2`, `household_unit: "slice"`, and `estimated_grams` equal to the combined edible mass. Resolve a suitable whole-pizza database row and scale its per-100 g nutrition to that mass. Slice count alone does not establish weight or nutrition.

Visible ingredients do not automatically require separate entries. A recognizable assembled dish can stay whole even when its cheese, sauce, or filling is visible. Conversely, sharing a plate does not make separate foods one dish.

| Input | Expected entries |
| --- | --- |
| Two slices of the same cheese pizza | One cheese-pizza entry, quantity two slices |
| One cheese slice and one pepperoni slice | Two pizza entries because the compositions differ |
| Pizza with a separately served salad or dipping sauce | Pizza plus the separate side or dip |
| Rice with a separately served chicken portion | Rice and chicken |
| Pasta with a separately served beef portion | Pasta and beef; include separately served sauce when present |
| Recognizable lasagna or pasta with incorporated meat sauce | One named dish, if that is what the image or user description establishes |
| Pizza ingredients laid out before assembly | The separate ingredients |
| Unclear mixed meal | Report identifiable foods conservatively and state what remains uncertain |

The same policy should apply to typed meal descriptions. Preserve explicit user amounts and requests to log separate ingredients. Never count both a complete dish and ingredients already included in that dish's nutrition profile.

## Findings from the original code

- The [system prompt](../server/app/services/detection/detector.py) explicitly tells the model to decompose dishes, including lasagna, and discourages considering whole-dish database entries. The default photo message repeats the instruction to name every visible component. These instructions conflict directly with the requested pizza behavior.
- The [model-facing schema and tool description](../server/app/schemas/detection.py) reinforce that policy. `components` is generated before `foods`, and the server checks their counts. Adding one pizza example without aligning these instructions would leave conflicting directions.
- The [detection service](../server/app/services/detection/detector.py) resolves each returned food independently; it does not split pizza after identification. The [client upload flow](../client/src/features/food-logging/hooks/useAddFood.ts) passes the server's proposal to confirmation without decomposing it.
- `_looks_under_reported` marks every actual-food photo with exactly one entry provisional, even if its inventory agrees. The [workflow](../server/app/services/detection/workflow.py) does not cache provisional readings, and [confirmation](../client/src/features/food-logging/components/Confirm.tsx) warns that foods may be missing. Correct whole-pizza detection would therefore still receive an inappropriate warning under the current rule.
- The [resolver](../server/app/services/nutrition/resolver.py) already accepts dish names. The [USDA client](../server/app/services/nutrition/usda.py) accepts Survey (FNDDS), SR Legacy, Foundation, and Branded results; dish support does not inherently require another data source or a database migration. Replaying [recorded USDA candidates](pizza-search-candidates.json) through its actual ranker selected a cheese-free pizza first for `pizza cheese`. This establishes a matching defect on that candidate set, although the research requests differ from the app's live query shape; see the research note for limits and the replay command.
- [Detection keys](../server/app/services/detection/cache.py) already include the model, effort, and prompt/schema fingerprint. Prompt changes naturally retire old detection results. Photo keys currently omit the note and meal type; that separate limitation matters when testing different captions against the same photo.

These are source-code findings. The original uploaded image and its exact model response were not available in the inspected workspace, so this research does not claim to reproduce that particular detection or establish its selected nutrition sources.

## Original implementation plan

1. **Capture the reported case and establish a baseline.** Make the original two-slice photo available to the evaluation harness and record its current labels, search terms, combined grams, matched rows, and provisional status. Run repeated uncached detections to distinguish a prompt improvement from a lucky model response. The existing `scripts/probe_detection.py` is useful, but it calls the paid model and commits resolver write-backs to the configured database; use a dedicated evaluation database. Add explicit assertions to a small evaluation harness, since that probe currently prints results without checking whether pizza was split.

2. **Align every model instruction around loggable foods.** Update the system prompt, default photo message, `components` field description, tool description, and retry wording together. Keep the existing schema shape: `components` becomes an inventory of intended food entries, including complete dishes. Replace the unconditional ingredient-splitting instructions with the policy and examples above. Preserve the missing-food and invalid-mass retries, without asking the model to add ingredients that are already included in a dish.

3. **Preserve dish identity through lookup.** For an identified thin-crust cheese pizza, use a ladder such as `pizza cheese thin crust` → `pizza cheese` → `pizza`. Keep the original dish type in the lookup; do not widen to cheese, tomato sauce, or bread. Do not invent a crust style, brand, or topping. Capture complete USDA candidates using the app's request shape, then add a failing case for cheese pizza selecting a `no cheese` row. Add query-aware rejection for that contradiction and verify that whole-pizza queries cannot select topping-only, crust-only, dessert-pizza, or pizza-roll entries. Keep those entries available when explicitly requested. Retain FNDDS dish candidates; expand or refine candidate retrieval only if suitable entries are absent. If no suitable match exists, keep the unresolved/rough outcome visible instead of inventing nutrition or silently constructing an ingredient recipe.

   Apply identity requirements from the original detected dish across fallback rungs: widening a cheese-pizza query to `pizza` must not erase the known cheese. Verify cached food and scanned-product matches as well as upstream candidates. A prompt fingerprint change invalidates detection responses but does not invalidate `foods` write-backs; inspect affected pizza terms and refresh only confirmed incompatible rows if any exist. No such stored rows were inspected during this research.

4. **Allow complete single-food photos.** Remove the rule that one returned food alone proves incompleteness. Keep inventory mismatches provisional and preserve the existing validation/retry behavior. Update the associated schema comments and tests. This removes a coarse safeguard against missed sides, so the mixed-plate photo cases must pass before accepting the change; matching counts alone cannot prove visual completeness. Avoid adding another model-generated classification field unless those evaluations show a concrete need.

5. **Verify the user-visible result and cache behavior.** Confirm that two slices appear as one editable pizza entry, changing slice quantity rescales grams and nutrition once, and saving retains the source reference and per-100 g snapshot. Check that an old detection key misses after the prompt/schema change and a complete one-food result can be cached. Test both photo and text paths. Use the uncached harness for caption comparisons because of the existing photo-key limitation.

## Verification and acceptance

Use two complementary checks. Deterministic service tests should replay external model responses and USDA payloads through the real detection/resolution code with SQLite, following the existing suite. They verify parsing, retries, matching, portion scaling, provenance, and caching; they cannot prove that a real model follows the prompt. Repeated photo evaluations verify the actual food-grouping behavior.

Required cases are the table above, plus a pizza photo with an explicit gram amount, a legitimate one-food photo such as an apple, an inventory mismatch, an invalid mass, and an unresolved dish. Record all attempted photo runs and grouping failures, not just successful examples. The original pizza should remain whole across the agreed repeated runs, and the separate-meal cases must retain their foods and sides.

For ranking changes, add recorded pizza candidates to `tests/fixtures/usda_search.json` and cases to `scripts/eval_matching.py`, then report the old and new scores separately for the existing set and the added cases. Run the current offline eval without `--refresh` to measure ranking changes against stable data. Do not replace all baseline payloads with fresh responses during that comparison.

Baseline verification performed during research, from `server`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_detection_service.py tests/test_detection_schema.py tests/test_detection_cache.py tests/test_usda_ranking.py tests/test_nutrition_resolver.py -q
```

Result: **82 passed in 2.76 seconds**. This confirms the inspected baseline passes its existing checks; it is not evidence that the requested pizza behavior already works. No live model call or original-photo evaluation was performed.

## Scope

Start with the detection instructions, the single-food provisional rule, and evidence-backed matching adjustments. The existing response shape and confirmation controls support the requested outcome. Keep the model limited to food identification and estimated mass; all nutrition continues to come from source rows. A recipe builder, new nutrition provider, image-segmentation model, and automatic ingredient-decomposition fallback are unnecessary for this first change.
