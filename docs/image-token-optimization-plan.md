# Reduce photo input tokens

Planned, implemented, and evaluated on a supplied meal photo on 2026-09-23.

## Implementation and rollout status

The PR proposes a 1024-pixel overview, 768-pixel crop limit, and unchanged JPEG
quality 88. `DetectionService.detect_photo` now accepts original bytes and performs
preparation in the worker thread itself, so HTTP, probes, and evaluations use the
same contract. Crops come from the oriented original and are never enlarged.

Photo cache keys include the preprocessing version and all three settings; the
original-byte image hash still groups logged entries. Existing overrides in
`server/.env` or deployment environment variables take precedence over defaults.
Set `DETECT_IMAGE_MAX_EDGE_PX=1568` to restore the previous overview dimensions;
this retains the new original-image crop behavior.

The supplied mixed-meal photo passed all nine grouping checks: three runs each at
1568, 1280, and 1024 pixels. The 1024 default is retained for review based on this
limited comparison. Broader photo coverage and measured portion weights remain
outstanding; one image does not establish general recognition or mass accuracy.
No deployed configuration changed.

The evaluation script now exports dimensions, encoded bytes, visual-token estimates,
recognition and grounding usage separately, combined token totals, zoom/repair counts,
elapsed time, provisional/unresolved results, and failed attempts. Counters cover
usage returned by the API; no usage is available for requests that fail before a
response. Hardcoded dollar estimates were replaced with explicit token categories
so changing the model does not silently apply the old model's prices.

Validation: **429 passed, 1 skipped** in the full server suite; Ruff passed. Real
Pillow tests verify the 4:3 token table below at quality 88 and 85, metadata stripping,
orientation, small images, crop limits, and original detail across a full tool loop.
These are preprocessing and integration checks, not food-recognition accuracy tests.

## Live evaluation: supplied mixed-meal photo

Evaluated `IMG_2767.JPEG` (1536 x 2048, 680,465 bytes) against code commit
`28fa3a4`, using `claude-opus-5`, medium effort, prompt fingerprint
`727f32c78a7b14b7`, quality 88, and the same 768-pixel original-crop policy for every
size. The photo was used from its local path and is not committed. Its SHA-256 is
`0cb39c32c88ba33516272077476ee139acf07687ad97f9f860bd8f422780446d`.
The [complete run report](image-token-evaluation-img2767.json) retains all attempts.

The expected categories, selected before running the model, were rice, chicken,
potato, and sauce/gravy. The photo case checks those labels and separate entries;
it does not assert the recipe or any of the text case's explicit weights. Each
run included nutrition retrieval and the grounded explanation, using an in-memory
database and bypassing the completed-detection cache.

| Maximum edge | Encoded bytes | Visual-token estimate | Grouping passed | Repair turns | Mean total input | Mean output | Mean seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1568 | 349,809 | 2352 | 3/3 | 1 | 20,988 | 754.0 | 22.67 |
| 1280 | 250,675 | 1610 | 3/3 | 3 | 29,648.7 | 856.0 | 20.43 |
| 1024 | 171,656 | 1036 | 3/3 | 1 | 19,251 | 776.7 | 18.24 |

All final results were non-provisional, all foods resolved to nutrition records,
and all grounded explanations succeeded. No run requested a zoom. That leaves
live zoom behavior untested on this photo; deterministic integration tests cover
the original-image crop path.

Compared with 1568, the 1024 overview has **56.0% fewer calculated visual tokens**
and **50.9% fewer encoded bytes**. Mean complete input usage was **8.3% lower** in
these runs, including detection, repairs, grounding, and cached input categories.
Mean output usage increased from 754.0 to 776.7 tokens. The large shared prompt/tool
prefix and extra calls explain why overview savings do not equal total savings.

The middle size needed a repair on every run and consumed more complete input
than either other size. With only three runs per size, this is an observed result,
not proof that the resolution caused the repair rate. Runs were serial in descending
size order, and the first request paid for a cold prompt cache while later requests
reused it. Cache write/read categories are preserved in the report; the input and
timing comparisons must not be presented as a controlled dollar-cost benchmark.

The 1024 runs estimated rice at 210-250 g versus 250 g in each 1568 run; chicken
and potato estimates also varied. There are no weighed portions, so preserving
the four food categories cannot establish which mass estimates were more accurate.
Keep quality 88 and the proposed 1024 overview; evaluate additional meals before
claiming broad accuracy or savings. A 1280 fallback did not improve this sample.

## Running the comparison

From the repository root, compare encoded images without API calls:

```powershell
uv run --directory server python -m scripts.eval_detection --photo C:/photos/meal.jpg --image-edges 1568 1280 1024 --images-only --report C:/photos/image-sizes.json
```

For a photo matching an existing evaluation case, run three paid detections at each
size, including the grounding pass, with an isolated in-memory nutrition database:

```powershell
uv run --directory server python -m scripts.eval_detection --photo C:/photos/meal.jpg --case topped_plate --runs 3 --image-edges 1568 1280 1024 --report C:/photos/detection-comparison.json
```

Repeat for the representative photos and expected cases. Review returned grams
against weighed portions separately; the built-in photo cases check grouping, not
mass accuracy. All runs use the new crop policy, so this isolates overview-size
differences; it is not a comparison against the previous enlarged-crop behavior.
Compare that behavior separately against the base revision if needed.

After choosing a size, use `--jpeg-qualities 88 85` with a single `--image-edges`
value. Image-only mode measures bytes without drawing conclusions about accuracy.
Live reports show cache-read/write categories, so do not compare warm runs to cold
runs as if both had the same billing or latency. Nutrition retrieval may also warm
within an evaluation process. No image data or captions enter the usage logs.

## Recommendation

Evaluate a 1024-pixel maximum edge for the first image, with 1280 pixels as the
fallback if food recognition suffers. Keep JPEG quality at 88 during the resolution
comparison; separately test quality 85 for smaller request bodies. Resolution is
the input-token lever, while JPEG quality primarily affects bytes and latency.
See the [research note](image-token-optimization-research.md) and
[Anthropic's vision guidance](https://platform.claude.com/docs/en/build-with-claude/vision).

For a sufficiently large 4:3 photo on the repository's default `claude-opus-5`,
these are calculated visual-token counts, excluding text, tools, framing, and retries:

| Prepared dimensions | Visual tokens | Reduction from current |
| --- | ---: | ---: |
| 1568 x 1176 | 2352 | Baseline |
| 1280 x 960 | 1610 | 31.5% |
| 1024 x 768 | 1036 | 56.0% |

Calculated with `ceil(width / 28) * ceil(height / 28)` from the current
[vision documentation](https://platform.claude.com/docs/en/build-with-claude/vision#resolution-and-token-cost).
These are image-only savings for this shape and model tier, not a prediction of the
whole request's token or dollar reduction. Actual deployed overrides and usage must
be recorded during evaluation.

## Behavior inspected before implementation

- [Image preparation](../server/app/services/detection/imaging.py) already corrects
  EXIF orientation, preserves aspect ratio, downsizes to the configured edge, and
  sends JPEG at quality 88 without the original metadata. The configured default
  in [settings](../server/app/config.py) is 1568 pixels. Pillow is already installed.
- The [photo workflow](../server/app/services/detection/workflow.py) checks the
  completed-detection cache before running preparation in a thread pool. The
  [client](../client/src/features/food-logging/services/detection.ts) uploads the
  original file; preprocessing happens before the server sends it to Claude.
- The [detector](../server/app/services/detection/detector.py) already requests
  caching for the static tools/system prefix and accumulates input, output, and
  cache usage across turns. Images remain in subsequent conversation requests.
- Its zoom tool crops the prepared image and enlarges small crops to the same
  configured maximum edge. Enlarging cannot restore discarded original detail;
  the extra pixels also increase the calculated visual-token count.
- [Grounded explanations](../server/app/services/grounding/service.py) use a
  separate text-only Claude call. Detection's current spend log does not include
  that call. Barcode lookup uses no model and needs the original fine detail.

## Original implementation sequence

1. **Measure the current path.** Extend the existing evaluation workflow to report
   original/prepared dimensions and bytes, image-token estimates, total input and
   output usage, cache reads/writes, elapsed time, zoom count, repair count, and
   provisional results. Report grounding usage separately and an end-to-end total.
   Keep image content and user captions out of logs. Compare model runs with the
   completed-result cache bypassed and identify warm versus cold prompt caches.

2. **Tune the existing server preprocessor.** Reuse `DETECT_IMAGE_MAX_EDGE_PX`
   rather than introducing another compression pipeline. Benchmark 1568, 1280,
   and 1024 at quality 88, then compare quality 85 against the winning resolution.
   Add a validated JPEG-quality setting only when implementing the quality trial.
   Preserve orientation, aspect ratio, metadata removal, and no upscaling of the
   initial image. Keep CPU work in the thread pool and apply the same preparation
   contract to production, evaluation, and probe callers.

3. **Make zooms use real detail.** Retain the original upload in request memory
   as a crop source while sending only the smaller overview initially. Map the
   existing normalized coordinates onto the EXIF-corrected original. Encode each
   requested crop directly from that source, with a separately configurable
   initial cap of 768 pixels and no enlargement of undersized crops. Keep existing
   bounded tool turns; measure whether extra zooms offset overview savings before
   adding any further retry or zoom policy. Benchmark this change independently
   before evaluating the combined result.

4. **Keep results traceable across changes.** Preserve the original-byte
   `image_hash`, which groups logged entries. Add the preprocessing policy/version
   and effective resize/quality/zoom settings only to the derived photo cache key,
   alongside its existing model, effort, prompt fingerprint, note, and meal type.
   This deliberately causes a cold recognition cache for a new policy and allows
   rollback without serving results produced by the rejected policy. Text cache
   keys and existing logged nutrition snapshots remain unchanged.

5. **Validate before selecting the new default.** Use representative real photos
   covering a single food, pizza, separate foods on a plate, small sauces/sides,
   low light, and portrait/landscape/square images. Compare repeated runs under
   the same model, effort, and prompt. Check identified foods and omissions;
   evaluate grams against weighed portions where available, rather than treating
   agreement with the old model as proof of accuracy. Choose 1024 only if it
   lowers total input usage without a material regression in these checks or a
   higher provisional/repair rate. Otherwise select 1280 or retain 1568 and record
   the observed tradeoff. Update the settings example and measured results.

## Verification

Use the real Pillow implementation for orientation, aspect ratio, metadata removal,
small-image behavior, crop source detail, and separate overview/crop bounds. In
service tests, substitute the external Anthropic response and inspect the actual
image blocks across a zoom turn. Verify that preprocessing settings affect the
photo cache key without changing the raw image hash or losing caption/meal scoping.

Run the relevant imaging, detection, security, and cache checks plus Ruff. Keep
nutrition schema constraints intact: Claude supplies food identity and mass;
nutrition continues to come from database records. The real-photo evaluation uses
an isolated evaluation database, not the probe's configured database write-backs.

The fixtures contain recorded nutrition responses, not a representative meal-photo
dataset. The supplied photo provides the limited live evidence above; broader
recognition accuracy, weighed portions, and controlled billing comparisons remain open.

## Other cost-saving options

- **Reuse image context across tool turns.** Static prompt caching already exists.
  Evaluate an additional cache breakpoint covering the original image/message for
  multi-turn detections. Measure cache eligibility, actual hit rate, write premium,
  and tool-schema changes during repairs. This reduces billed input cost on reuse,
  not the image's underlying context size. Server-tool iterations can already
  receive automatic cache breakpoints; measure those separately from client zoom
  continuations before attributing savings to a new breakpoint. See
  [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
- **Reduce the second model pass.** Measure the grounded explanation separately.
  A deterministic selection of the already available evidence facts could avoid
  that call, or a smaller model could be evaluated for it. This is a separate
  product choice because it changes how facts are selected and presented.
- **Evaluate lower effort or a smaller detector model separately.** These target
  output/thinking usage or per-token price, not a guaranteed reduction in image
  input tokens. Keep them out of the resolution comparison to isolate the cause
  of any accuracy change. See [effort guidance](https://platform.claude.com/docs/en/build-with-claude/effort).
- **Prefer an existing barcode or text path when suitable.** Barcode lookup avoids
  Claude completely. Text descriptions avoid visual tokens, but still use the
  detector and grounding flows. Do not automatically replace a photo containing
  useful evidence with an uncertain generated description.
- **Consider browser compression later for slow uploads.** It reduces bandwidth
  to the server, but adds no further image-token savings if Claude receives the
  same dimensions. It also removes the original detail needed for server crops;
  evaluate that tradeoff separately and preserve barcode image quality.

Start with resolution, useful crops, and measurement. A model migration, automatic
plate segmentation, prompt rewrite, or Files API migration is unnecessary for this
first change.
