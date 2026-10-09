# Using mealtrack from an AI agent

`mealtrack` is designed so an agent can drive it from a shell: every command accepts `--json`, prints one JSON document to stdout, and signals the outcome with its exit code.

## Rules for agents

1. **Always pass `--json`** and read stdout as JSON. Never parse the human-readable text.
2. **Never invent a value.** Do not guess calories, grams or a date. If you do not have a photo or a number, ask the user.
3. **`log-meal` is not idempotent.** Each successful call adds a meal, even for the same photo (the cache only saves API calls). Run it with `--dry-run` first, show the user the estimate, then run it again without `--dry-run` once they agree. To fix a mistake, `delete-meal <id>` and log again.
4. **Pass what the user knows as `--hint`.** Weights and ingredients they give are trusted over the model's visual guess.
5. **Report uncertainty.** Quote `kcal_low`-`kcal_high` together with `confidence`, and surface `assumptions`, `questions` and `warnings`. Do not present a single number as exact.
6. **No health commentary.** Do not tell the user a meal or a day is good, bad, too much or too little. Report what was logged, compared with the goal if asked.
7. **`--backend mock` returns fake placeholder data** (and uses a separate demo database). Use it only for demos and tests, never to answer a real question.
8. A day with no meals is *not logged*. Do not describe it as 0 kcal.

## Commands

| Command | Purpose |
| --- | --- |
| `mealtrack log-meal PHOTO [--type breakfast\|lunch\|dinner\|snack] [--hint TEXT] [--day YYYY-MM-DD] [--dry-run]` | estimate from a photo and log it |
| `mealtrack water ML [--day]` | add water; a negative number corrects a mistake |
| `mealtrack workout [--skipped] [--kind K] [--minutes N] [--day]` | log a workout as done or skipped |
| `mealtrack today [--day]` | summary for one day |
| `mealtrack week [--days N] [--end YYYY-MM-DD]` | summary for the last N days (default 7) |
| `mealtrack meals [--day]` | list logged meals with their ids |
| `mealtrack delete-meal ID` | remove a meal |
| `mealtrack eval --photos DIR --labels CSV [--out FILE]` | measure accuracy against ground truth |
| `mealtrack demo-data [--days N]` | fill the demo database with synthetic data |

All commands also accept `--db PATH` and `--backend claude|mock`. Goals come from `MEALTRACK_GOAL_KCAL` and `MEALTRACK_GOAL_WATER_ML`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 2 | bad input: unreadable file, unsupported image, invalid date or amount, unknown id |
| 3 | the estimate failed: missing API key, API error, invalid model output (also `eval` when no photo could be evaluated) |
| 4 | the image does not show food or drink |

With `--json`, errors are printed to stdout as:

```json
{"error": {"type": "not_food", "message": "no food or drink detected in the image"}}
```

`type` is one of `file`, `image`, `input`, `not_found`, `estimate`, `not_food`.

## Output shapes

`log-meal`

```json
{
  "saved": true, "id": 12, "day": "2026-10-07", "meal_type": "lunch",
  "cached": false, "backend": "claude", "model": "...",
  "estimate": {
    "items": [{"name": "Chicken breast", "grams": 150.0, "kcal": 248.0, "kcal_low": 210.0,
               "kcal_high": 290.0, "protein_g": 46.5, "carbs_g": 0.0, "fat_g": 5.4}],
    "totals": {"kcal": 248.0, "kcal_low": 210.0, "kcal_high": 290.0,
               "protein_g": 46.5, "carbs_g": 0.0, "fat_g": 5.4},
    "confidence": "medium",
    "assumptions": ["1 tsp oil used for cooking"],
    "questions": ["Is the chicken weighed raw or cooked?"],
    "warnings": []
  }
}
```

With `--dry-run`, `saved` is `false` and `id` is `null`.

`today`

```json
{"day": "2026-10-07", "meals_logged": 3, "low_confidence_meals": 1,
 "kcal": 1326.0, "kcal_low": 1075.0, "kcal_high": 1605.0,
 "protein_g": 122.0, "carbs_g": 119.0, "fat_g": 37.0,
 "kcal_goal": 2000, "pct_of_goal": 66.3,
 "water_ml": 1550, "water_goal_ml": 2000,
 "workout_done": true, "workout_minutes": 50, "workout_kinds": ["cycling"]}
```

`workout_done` is `true`, `false` (logged as skipped) or `null` (nothing logged). `pct_of_goal` is `null` when no meals are logged.

`week` returns `{"days": [<today objects>], "days_with_meals_logged", "days_total", "avg_kcal_logged_days", "avg_protein_g_logged_days", "workouts_done"}`. The averages are `null` when no day has meals.

`water` returns `{"day", "added_ml", "total_ml"}`. `workout` returns `{"day", "workout": "done"|"skipped", "kind", "minutes"}`. `meals` returns `{"day", "meals": [{"id", "meal_type", "confidence", "kcal", "kcal_low", "kcal_high", "protein_g", "carbs_g", "fat_g", "items", "note"}]}`. `delete-meal` returns `{"deleted": <id>}`.

## A typical session

```bash
mealtrack log-meal lunch.jpg --type lunch --hint "rice 90 g, chicken 140 g" --dry-run --json
# show the estimate to the user and wait for their go-ahead, then:
mealtrack log-meal lunch.jpg --type lunch --hint "rice 90 g, chicken 140 g" --json
mealtrack water 500 --json
mealtrack today --json
```
