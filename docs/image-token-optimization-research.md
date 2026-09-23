# Image-token optimization research

Research date: 2026-09-23. Scope: plan reductions to Claude image-input cost without changing application code. No inference or token-count API calls were made; runtime secrets were not inspected.

## Behavior inspected before implementation

[Settings](../server/app/config.py) default to `claude-opus-5`, `medium` effort, and a 1568 px image long edge. Environment overrides can change these values, so they are code defaults rather than verified deployment settings.

[Image preparation](../server/app/services/detection/imaging.py) already applies EXIF orientation, downsizes large images, and encodes JPEG at quality 88. Its zoom helper crops the prepared image and enlarges smaller crops to the same long-edge setting. Enlarging those pixels does not restore detail removed by the first resize; reducing the overview size should therefore be evaluated together with the zoom path.

The [detector](../server/app/services/detection/detector.py) already caches its system prompt and preceding tool definitions, and `_Spend` accumulates input, output, cache-read, and cache-write usage across turns. The optimization should extend these mechanisms rather than add duplicate preprocessing or accounting.

## Resolution controls image tokens

Anthropic currently describes images as 28×28 px patches. Opus 5 belongs to the high-resolution tier: 2576 px maximum long edge and 4784 visual tokens. Standard-tier models allow 1568 px and 1568 visual tokens. The model automatically downsizes to satisfy both limits. JPEG/WebP compression reduces request bytes and latency; keeping the same dimensions does not reduce the patch count. Lossy recompression can harm clarity. [Anthropic vision](https://platform.claude.com/docs/en/build-with-claude/vision#resolution-and-token-cost)

For dimensions that already fit the model, calculate visual tokens as `ceil(width / 28) × ceil(height / 28)`. The following are local calculations for a 4:3 photo on Opus 5, where none of these sizes trigger further resizing. They exclude prompts, tool schemas, image-block overhead, repeated turns, and output. [Anthropic resize and padding rules](https://platform.claude.com/docs/en/build-with-claude/vision-coordinates#how-claude-resizes-and-pads-images)

| Image dimensions | Visual tokens | Reduction from current example |
| --- | ---: | ---: |
| 1568×1176 | 2352 | — |
| 1280×960 | 1610 | 31.5% |
| 1024×768 | 1036 | 56.0% |

These are image-only reductions, not promised reductions in the whole detection bill. Small uploads that already fit the proposed dimensions save less or nothing. A long-edge setting also allows different token totals by aspect ratio: a 1024×1024 square costs 1369 visual tokens. A direct pixel/patch budget would control this more consistently than the long edge alone.

The current image-block schema has no `detail: "low"` setting. Its `transformations.oversized_image` control chooses automatic downsizing or rejection; it is not a user-selected low-resolution tier. Reduce dimensions in the application. [Messages image-block schema](https://platform.claude.com/docs/en/api/messages/create), [image transformations](https://platform.claude.com/docs/en/build-with-claude/vision-coordinates#turn-resizing-into-an-error-with-transformations)

## Measure the complete detection

The free `messages.count_tokens` endpoint supports base64 images, system prompts, and client tools; its result is an estimate. It rejects server web-search tools and URL/file image sources. Trueplate includes web search, so count image-only or equivalent requests with that server tool omitted and label them partial estimates. Use real Messages response usage for complete tool-loop costs. Token counting does not exercise prompt caching. [Anthropic token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)

For a later evaluation, compare identical photos at 1568, 1280, and 1024 px; initially keep quality 88 to isolate the dimension change. Record food identity/count, whole-dish grouping, grams, review/unresolved rates, zooms, repair turns, latency, bytes, and all usage categories. Then compare JPEG quality separately. A smaller first image is a regression if it induces enough extra zooms or repairs to cost more overall.

## Further opportunities

**Preserve the existing prompt cache and measure reuse.** For Opus 5, the minimum cacheable prefix is 512 tokens; 5-minute writes cost 1.25× base input price and reads 0.1×. Images can be cached, but the prefix must match exactly. Assess caching the original image across client-tool continuations; avoid blanket caching of one-shot unique uploads, which adds a write premium without reuse. Changing tool definitions invalidates the prefix. [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

Server-tool results such as web search already receive automatic 5-minute breakpoints when the request enables caching. Consequently, existing cache-write/read usage may include more than the explicit system breakpoint. Inspect usage before attributing new savings to image caching. [Tool use with prompt caching](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching#server-tool-results-are-cached-automatically)

**Evaluate zooms from original pixels.** Keep original bytes available for on-demand crops, send a smaller overview, and give crops an independent size/token budget. This is a design hypothesis: food labels and mass estimates need evaluation before selecting a default, and crop coordinates must map to the oriented original. Do not automatically crop away plate/reference context used to estimate mass.

**Compare low effort separately.** Anthropic recommends testing low/medium effort on Opus 5 when quality holds. Effort controls reasoning expenditure and tool behavior, not the image's patch count. Treat this as a total-cost experiment rather than an image-input optimization. [Anthropic effort](https://platform.claude.com/docs/en/build-with-claude/effort#recommended-effort-levels-for-claude-opus-5)

**Keep transport changes separate.** Browser compression can reduce upload bandwidth; server preprocessing is still needed for every caller. Files API references can avoid resending base64 bytes, but are not an image-token discount and add file lifecycle work. Prioritize dimension and tool-loop measurements first. [Anthropic image transport](https://platform.claude.com/docs/en/build-with-claude/vision#files-api-image-example)

## Evidence limits

No food-photo accuracy evaluation, bill comparison, deployment-setting check, or live API verification was performed. The table is derived from current official documentation and known dimensions. The optimal size, quality, crop budget, and cache strategy remain workload-dependent; preserve the invariant that Claude supplies labels and grams while database rows supply nutrition.
