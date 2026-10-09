# Measuring accuracy

`mealtrack eval` compares the tool's estimates with ground truth you provide, so the accuracy claim in the main README is a measurement and not an impression.

## 1. Collect about 20 meals with known nutrition

- Weigh the ingredients with a kitchen scale and take the nutrition from package labels or a food-composition table. Prefer meals you cook yourself over restaurant food, where the truth is unknown.
- Cover variety: simple plates and mixed dishes, light and heavy, different cuisines. If every photo is an easy one, the result will flatter the tool.
- One clear photo from above or at a slight angle, the whole plate in frame, normal lighting. Take it **before** you weigh anything.
- Keep the photos in a folder that is **not committed** (`my_photos/` and `photos/` are in `.gitignore`).

## 2. Write the labels

A CSV with one row per photo. Copy [labels_template.csv](labels_template.csv) and replace the example rows:

```csv
file,true_kcal,true_protein_g,true_carbs_g,true_fat_g
chicken_rice_01.jpg,612,48,66,14
oats_banana_02.jpg,355,12,60,7
```

`file` and `true_kcal` are required. The macro columns are optional; leave a cell empty when you do not know it.

## 3. Run it

```bash
mealtrack eval --photos my_photos --labels my_labels.csv --out eval/report.json
```

The first run calls the API once per photo. Repeats are served from the cache; delete `.mealtrack/cache/` to measure the run-to-run variation of the model.

## 4. Read the report

- **MAE / MAPE**: average error in kcal and in percent.
- **bias**: positive means it over-estimates on average.
- **within ±20%**: share of photos where the estimate would be good enough to be useful.
- **range covers truth**: the tool reports a range for every meal. This is the share of photos where the truth fell inside it. If the model's ranges are meant to be believable and this number is far below what you would expect, they are overconfident, and that is worth saying openly.
- **largest errors**: look at those photos. They usually show what the tool cannot see (oil, sauces, depth).

Photos that fail are listed and excluded; the report states how many.

## 5. Share the result, not the photos

Commit `eval/report.json` if you like (it has file names and aggregate numbers, no images), and copy the headline numbers into the table in the main README with the date and model. Report the numbers as they came out, including the unflattering ones: a measured result with its limits is worth more than a good-looking one.

## Going further

Run the same labels with and without `--hint`-style information, compare two models by changing `MEALTRACK_MODEL`, and repeat a run after clearing the cache to see how stable a single photo's estimate is.
