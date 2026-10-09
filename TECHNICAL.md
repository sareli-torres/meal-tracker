# Technical notes

## Data flow

```text
photo bytes
   │  vision.prepare_image   validate format · fix orientation · drop EXIF/GPS · ≤1568 px · JPEG
   ▼
cache lookup ── hit ──────────────────────────────────────────────┐
   │ miss                                                          │
   ▼                                                               │
Backend.estimate(image, hint)   ClaudeBackend (forced tool call)   │
                                MockBackend   (offline, fake data) │
   │ raw payload                                                   │
   ▼                                                               ▼
models.parse_estimate  ◄──────────────── raw payload ──────────────┘
   │  validate · clamp · repair ranges · recompute totals · consistency checks
   ▼
MealEstimate ──► store.add_meal (SQLite) ──► summary.summarize_day / summarize_range
                                         └─► CLI output / Streamlit
```

The raw payload is cached, not the parsed estimate, so a better validator applies to old cache entries too. A payload is cached only after it parsed successfully.

## Modules

| Module | Responsibility |
| --- | --- |
| `models.py` | `FoodItem`, `MealEstimate`, `parse_estimate`, `normalize_item`, consistency checks |
| `prompts.py` | system prompt, `report_meal` tool schema, `PROMPT_VERSION` |
| `vision.py` | image preparation, `Backend` protocol, `ClaudeBackend`, `MockBackend`, `Cache`, `analyze_photo` |
| `store.py` | SQLite schema and queries (meals, water, workouts) |
| `summary.py` | `DaySummary`, `WeekSummary` and their text/JSON formats |
| `evaluate.py` | label loading, metrics, report formatting |
| `editing.py` | turns rows edited in the app back into validated items |
| `demo.py` | deterministic synthetic data |
| `config.py` | paths and settings from environment variables |
| `cli.py` | argparse commands, JSON/text output, exit codes |

## Structured output

The model is called with one tool, `report_meal`, and `tool_choice` forces it, so the answer is always a JSON object matching the schema instead of free text to parse. Per item: `name`, `grams`, `kcal`, `kcal_low`, `kcal_high`, `protein_g`, `carbs_g`, `fat_g`. Per meal: `is_food`, `confidence` (`low|medium|high`), `assumptions`, `questions`.

The system prompt asks for ranges as wide as the real uncertainty, says to trust the user's note over the visual estimate, and forbids health commentary. Changing the prompt or the schema requires bumping `PROMPT_VERSION`, which is part of the cache key.

## Validation rules (`models.parse_estimate`)

| Situation | Behaviour |
| --- | --- |
| `is_food` is false | `NotFoodError` (CLI exit code 4) |
| not an object, no items, more than 25 items | `EstimateError` |
| a number is missing, non-numeric, NaN or infinite | `EstimateError` |
| negative value | clamped to 0, warning |
| `kcal_low > kcal_high` | swapped |
| `kcal` outside its own range | range widened to include it, warning |
| `kcal_low` / `kcal_high` missing | both default to `kcal` |
| unknown `confidence` | treated as `low`, warning |
| kcal differs from 4·P + 4·C + 9·F by more than 30% (items ≥ 50 kcal) | warning. The tolerance is loose on purpose: fibre, alcohol and rounding explain small gaps |
| one item above 3,000 kcal | warning |
| any model-supplied total | ignored. Totals are properties computed from the items |

Warnings are stored with the meal and shown in the app. A meal total range is the sum of the item ranges, which is wider than a statistically combined range. That errs on the side of overstating uncertainty.

## Data model

```text
meals    id, day, ts, meal_type, note, image_sha, backend, model, confidence,
         kcal, kcal_low, kcal_high, protein_g, carbs_g, fat_g, items_json, warnings_json
water    id, day, ts, ml                       (negative rows correct mistakes; the daily sum floors at 0)
workouts id, day, ts, done, kind, minutes      (done = 0 means "skipped")
```

Images are never stored, only a 16-character hash of the prepared image. `day` is the local calendar date as `YYYY-MM-DD`.

## Summary semantics

- A day with no meal rows is **not logged**: it has no kcal figure and is excluded from averages.
- Workout status is tri-state: `None` (nothing logged), `False` (only skipped entries), `True` (at least one done entry).
- Percent of goal is only computed for days with meals.

## Cache

Key: `sha256(PROMPT_VERSION | backend | model | note | image_hash)`. Stored as `<key>.json` in `.mealtrack/cache/`. Delete the folder to force fresh estimates, for example when measuring run-to-run variation.

## Backends

`Backend` is a small protocol: `name`, `model`, and `estimate(image_jpeg, hint) -> dict`. To add a provider, implement it, return the same payload shape, and register it in `vision.get_backend`. `MockBackend` returns one of four fixed meals chosen from the image hash, labelled as a placeholder in `assumptions`. `get_backend` never falls back to the mock silently, and mock runs use `demo.db`.

## Evaluation metrics

For `n` successfully estimated photos with truth `t_i`, estimate `e_i`, range `[l_i, h_i]`:

- MAE = mean(|e − t|), bias = mean(e − t), MAPE = mean(|e − t| / t)
- within ±20% = share with |e − t| ≤ 0.2·t
- range coverage = share with l ≤ t ≤ h
- mean range width = mean(h − l)
- optional MAE for protein, carbs and fat when the labels CSV has them

Photos that fail (unreadable, no food, API error) are listed in the report and excluded from the metrics, so the numbers are never silently computed on a smaller or easier set.

## Tests

`pytest` runs without network access or an API key. The Claude backend is tested twice: against a fake client, and through the real Anthropic SDK pointed at a local stub server, which checks that the request (image block, forced tool, model, hint) is serialised correctly and that a Messages-API-shaped response becomes a valid estimate. Other tests cover validation edge cases, the image pipeline (EXIF removal, orientation, HEIC rejection, transparency), cache behaviour, the store, summaries, evaluation metrics computed by hand, every CLI exit code, and a headless run of the Streamlit app using Streamlit's `AppTest`.

## Known gaps

- The live API path has not been run against Anthropic's servers with real photos yet; the request and response handling is tested against a stub, and accuracy is unmeasured (see the Evaluation section of the README).
- Totals sum item ranges, which overstates uncertainty. A calibrated alternative would need evaluation data to fit.
- No food-composition database, no barcode or label reading, no per-user memory of repeated meals.
- Single user, local only.
