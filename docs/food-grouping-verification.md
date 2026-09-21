# Food grouping correction

Verified on 2026-09-21 with the configured `claude-opus-5` model at `medium` effort.

The previous instructions treated a recognizable prepared dish as one food but described
separate entries mainly as foods served independently. That left an ambiguous boundary
for chicken, potatoes and sauce touching or layered over rice. The text case below
reproduced the problem in three fresh detections: each merged chicken and sauce.

The shared photo/text prompt and tool descriptions now ask the model to distinguish an
assembled or cooked dish from individual plate items. Sharing a plate or sauce is not
enough to combine foods. Pizza, hamburgers and lasagna remain whole, and the examples are
explicitly non-exhaustive. Separate portions also get separate nutrition search terms;
otherwise a curry lookup could include sauce that already has its own entry.

The response shape and database nutrition calculation are unchanged. The prompt/schema
fingerprint changed from `32929e602dd19cec` to `727f32c78a7b14b7`, so both photo and text
cache keys bypass readings created with the previous instructions.

## Verification

- **Final live text suite: 15/15 passed.** This includes ordinary and topped plates,
  a rice bowl, chicken with sauce, whole pizza, hamburger and lasagna, a burrito absent
  from the prompt's examples, and complete dishes with separate sides.
- **Reproduced text failure:** `A plate of rice topped with cooked chicken and tomato
  sauce, with roasted potatoes` returned three entries in all three baseline runs
  (**0/3**). Expected: rice, chicken, sauce and potatoes. Two subsequent prompt revisions
  each passed **3/3** repeats of this case.
- **User-supplied photo, final prompt: 3/3 passed.** Each uncached detection returned
  separate rice, chicken, potato and sauce portions. The chicken searches returned cooked
  chicken rows, the potato searches returned boiled potato, and the sauce had its own
  source row. No real application database was written.
- **Earlier photo trials: 7/8 completed successfully.** One portion-repair request received
  an upstream HTTP 400; a fresh retry succeeded. Some early successful grouping trials
  still used curry-flavoured chicken queries that matched raw or canned chicken, prompting
  the final clarification to exclude separately logged sauce from those search terms.
- **97 deterministic tests passed** across the detection service, schema, cache and
  security suites. Coverage includes text, photos and captioned photos, preserving the
  model's separate entries and whole dishes through the real service and resolver.
- Ruff and `git diff --check` passed.

The original photo was first tested after the initial grouping revision; the red baseline
above is a related text reproduction. These checks assess grouping and source separation,
not the accuracy of visually estimated weights or an exact match to the sauce recipe.

## Replay

From `server`, using the project environment and configured API credentials:

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_detection --case topped_plate --runs 3
.\.venv\Scripts\python.exe -m scripts.eval_detection --runs 1
.\.venv\Scripts\python.exe -m scripts.eval_detection --case topped_plate --photo <meal-photo-path> --runs 3 --verbose
.\.venv\Scripts\python.exe -m pytest tests/test_detection_service.py tests/test_detection_schema.py tests/test_detection_cache.py tests/test_detection_security.py -q
```

The evaluator uses an in-memory SQLite database and fresh paid model calls. `--photo`
evaluates only the supplied image against the selected case's expected foods; without
`--case`, it retains the two-slice pizza expectation. `--verbose` also reports search terms
and matched source names. The supplied photo remains outside the repository.
