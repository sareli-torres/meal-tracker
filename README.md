# mealtrack

Log a meal from a photo and get calories and macros **with an honest uncertainty range**, then track water and workouts and see a daily summary. It ships as a command-line tool (every command has `--json`, so scripts and AI agents can drive it) and a small Streamlit app.

I built it to replace the manual meal, water and workout tracking I was keeping in Notion, and to practise the part of applied AI that tutorials skip: treating a model's output as untrusted, measuring how wrong it is, and saying so.

> **Status: working MVP.** The code, validation and summaries are covered by an automated test suite (`pytest`). The live Claude call is wired in, but its accuracy on real photos is **not measured yet**: see [Evaluation](#evaluation) for how to measure it, and add your numbers to the table there.

## What it does

- **Photo to nutrition.** A vision model lists each food in the photo with an estimated portion, kcal, protein, carbs, fat, and a kcal range. Overall confidence, assumptions ("assumed 1 tsp of oil") and the questions that would most improve the estimate come with it.
- **Tell it what you know.** `--hint "rice 90 g, chicken 140 g"` is trusted over the model's visual guess.
- **Water and workouts.** One command each. A workout can be *done*, *skipped* or *not logged*, and those are different things.
- **Daily and weekly summary** against a goal you set (default 2,000 kcal and 2,000 ml; change them with environment variables).
- **You stay in control.** In the app every estimate is an editable table, and nothing is saved until you press Save.

```text
$ mealtrack today --backend mock          # synthetic demo data
2026-10-07
  Calories  1,326 kcal (range 1,075-1,605) · goal 2,000 · 66%
  Macros    protein 122 g · carbs 119 g · fat 37 g
  Meals     3 logged (3 low confidence)
  Water     1,550 / 2,000 ml
  Workout   done (cycling 50 min)
```

## Design choices

- **The model is an untrusted source.** Its output is forced into a structured tool call, then validated: negatives are clamped, ranges are repaired, and totals are *recomputed from the items* instead of trusting the model's own sum. Items whose kcal disagree with their macros (4·P + 4·C + 9·F) are flagged.
- **Ranges, not single numbers.** A photo cannot show hidden oil or the depth of a bowl, so the tool reports a range and the evaluation checks whether those ranges are honest.
- **Not logged is not zero.** Averages only use days that have meals, and say how many that was.
- **Free to re-run.** Estimates are cached by image, note, model and prompt version, so repeating a command costs nothing and an evaluation is reproducible.
- **Fake data can't pollute the real log.** The `mock` backend (for demos and tests) writes to a separate database and is never selected unless you ask for it.
- **Privacy by default.** Photos are re-encoded before upload, which drops EXIF metadata including GPS. Your log is a local SQLite file. The only network call is to the vision API.

## Quickstart

Requires Python 3.10+ and an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/sareli-torres/meal-tracker.git
cd meal-tracker
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[app]"
cp .env.example .env                                  # then put your ANTHROPIC_API_KEY in .env
```

Try it without a key first:

```bash
mealtrack demo-data                     # fills a separate demo database with synthetic days
mealtrack today --backend mock          # the demo database is only read with the mock backend
streamlit run app/streamlit_app.py      # pick the "mock" backend in the sidebar
```

Use it for real:

```bash
mealtrack log-meal photo.jpg --type lunch --hint "brown rice 90 g, chicken 140 g"
mealtrack log-meal photo.jpg --dry-run            # show the estimate without saving
mealtrack water 500
mealtrack workout --kind gym --minutes 45         # or: mealtrack workout --skipped
mealtrack today                                   # or: --day 2026-10-06
mealtrack week --days 7
mealtrack meals                                   # list today's meals with ids
mealtrack delete-meal 12                          # fix a mistake
```

Add `--json` to any command for machine-readable output. See [AGENT.md](AGENT.md) for the JSON shapes and exit codes.

Everything is configured through environment variables (see [.env.example](.env.example)): the model (`MEALTRACK_MODEL`), the backend, the goals, and where data lives (`MEALTRACK_HOME`, default `.mealtrack/`, git-ignored).

## Evaluation

The point of an estimate is how far it is from the truth, so the tool can measure itself:

```bash
mealtrack eval --photos my_photos --labels my_labels.csv --out eval/report.json
```

You supply 20 or so photos of meals whose nutrition you can verify (weigh the ingredients, use package labels), and a CSV with the true values. The report gives:

| Metric | Meaning |
| --- | --- |
| MAE, MAPE | average error in kcal and in percent |
| bias | does it over- or under-estimate on average |
| within ±20% | share of photos where the estimate is close enough to be useful |
| range coverage | share of photos where the **true value falls inside the model's own range**. If a "90% range" covers 50%, the ranges are overconfident |

Details and the CSV format are in [eval/README.md](eval/README.md). Results go here once measured:

| Date | Model | Photos | MAE (kcal) | Bias (kcal) | Within ±20% | Range covers truth |
| --- | --- | --- | --- | --- | --- | --- |
| _not run yet_ | | | | | | |

## Limitations

- One photo cannot show oil, sauces, what is under the food, or how deep the bowl is. Portion size is where most of the error will come from.
- The same photo can get slightly different answers on different days; the cache hides that. Measure it before trusting a single number.
- There is no food-composition database behind the numbers: they are the model's estimates.
- HEIC photos are not supported (export as JPG). It is a single-user tool with no accounts.

## Project layout

```text
src/mealtrack/   models (validation) · vision (image prep, backends, cache) · store (SQLite)
                 summary · evaluate · editing · demo · cli · config · prompts
app/             Streamlit front end
tests/           pytest suite (includes a headless test of the app)
eval/            evaluation guide and labels template
TECHNICAL.md     architecture, data model, validation rules
AGENT.md         how an AI agent should drive the CLI
```

## Credits and disclaimer

The command-line-first structure, the `--json` output and the README / TECHNICAL / AGENT documentation split are inspired by [elmerescandon/ucl-tinyfish-freestyle](https://github.com/elmerescandon/ucl-tinyfish-freestyle).

Estimates from a photo can be off by a wide margin. This is a logging aid, not medical or dietary advice, and it is fine to stop tracking if it stops being useful or starts to feel stressful.

MIT licence.
