"""Measure how far the estimates are from ground truth you know.

You provide photos of meals whose nutrition you can verify (weighed ingredients, package
labels) and a CSV with the true values. The report says how wrong the tool is, which way
it errs, and whether its own uncertainty ranges are honest.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

from .models import EstimateError
from .vision import Backend, Cache, ImageError, VisionError, analyze_photo

LABEL_COLUMNS = ("file", "true_kcal")
OPTIONAL_MACROS = ("protein_g", "carbs_g", "fat_g")


def load_labels(csv_path: Path | str) -> list[dict[str, Any]]:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in LABEL_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"labels CSV is missing column(s): {', '.join(missing)}")
        rows = []
        for line_no, raw in enumerate(reader, start=2):
            if not (raw.get("file") or "").strip():
                continue
            try:
                row: dict[str, Any] = {
                    "file": raw["file"].strip(),
                    "true_kcal": float(raw["true_kcal"]),
                }
                for macro in OPTIONAL_MACROS:
                    val = (raw.get(f"true_{macro}") or "").strip()
                    if val:
                        row[f"true_{macro}"] = float(val)
            except (TypeError, ValueError):
                raise ValueError(f"labels CSV line {line_no}: true values must be numbers") from None
            rows.append(row)
    if not rows:
        raise ValueError("labels CSV has no rows")
    return rows


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``rows``: dicts with true_kcal, est_kcal, kcal_low, kcal_high (+ optional macro pairs)."""
    if not rows:
        raise ValueError("no successful estimates to evaluate")

    errors = [r["est_kcal"] - r["true_kcal"] for r in rows]
    ape = [abs(r["est_kcal"] - r["true_kcal"]) / r["true_kcal"] * 100 for r in rows if r["true_kcal"] > 0]
    n = len(rows)

    metrics: dict[str, Any] = {
        "n": n,
        "mae_kcal": round(statistics.fmean(abs(e) for e in errors), 1),
        "bias_kcal": round(statistics.fmean(errors), 1),  # > 0 means it over-estimates
        "mape_pct": round(statistics.fmean(ape), 1) if ape else None,
        "median_ape_pct": round(statistics.median(ape), 1) if ape else None,
        "within_20pct": round(
            sum(
                1
                for r in rows
                if r["true_kcal"] > 0
                and abs(r["est_kcal"] - r["true_kcal"]) <= 0.2 * r["true_kcal"]
            )
            / n,
            3,
        ),
        "range_coverage": round(
            sum(1 for r in rows if r["kcal_low"] <= r["true_kcal"] <= r["kcal_high"]) / n, 3
        ),
        "mean_range_width_kcal": round(statistics.fmean(r["kcal_high"] - r["kcal_low"] for r in rows), 1),
    }

    for macro in OPTIONAL_MACROS:
        pairs = [
            (r[f"true_{macro}"], r[f"est_{macro}"])
            for r in rows
            if f"true_{macro}" in r and f"est_{macro}" in r
        ]
        if pairs:
            metrics[f"mae_{macro}"] = round(statistics.fmean(abs(e - t) for t, e in pairs), 1)

    worst = sorted(rows, key=lambda r: abs(r["est_kcal"] - r["true_kcal"]), reverse=True)[:3]
    metrics["worst"] = [
        {
            "file": r["file"],
            "true_kcal": r["true_kcal"],
            "est_kcal": r["est_kcal"],
            "error_kcal": round(r["est_kcal"] - r["true_kcal"], 1),
        }
        for r in worst
    ]
    return metrics


def run_eval(
    photos_dir: Path | str,
    labels_csv: Path | str,
    backend: Backend,
    cache: Cache | None = None,
) -> dict[str, Any]:
    photos_dir = Path(photos_dir)
    labels = load_labels(labels_csv)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for label in labels:
        path = photos_dir / label["file"]
        try:
            analysis = analyze_photo(path.read_bytes(), backend, hint=None, cache=cache)
        except (OSError, ImageError, VisionError, EstimateError) as exc:
            failures.append({"file": label["file"], "error": str(exc)})
            continue
        est = analysis.estimate
        row = {
            **label,
            "est_kcal": est.kcal,
            "kcal_low": est.kcal_low,
            "kcal_high": est.kcal_high,
            "est_protein_g": est.protein_g,
            "est_carbs_g": est.carbs_g,
            "est_fat_g": est.fat_g,
        }
        rows.append(row)

    report = compute_metrics(rows) if rows else {"n": 0}
    report["n_failed"] = len(failures)
    report["failures"] = failures
    report["backend"] = backend.name
    report["model"] = backend.model
    report["note"] = "photo-only estimates (no text hint)"
    return report


def format_report(report: dict[str, Any]) -> str:
    if report.get("n", 0) == 0:
        return f"No photos could be evaluated ({report.get('n_failed', 0)} failed)."
    lines = [
        f"Evaluated {report['n']} photo(s) with {report['backend']} / {report['model']} "
        f"({report['n_failed']} failed)",
        f"  mean absolute error   {report['mae_kcal']:.0f} kcal",
        f"  bias                  {report['bias_kcal']:+.0f} kcal "
        f"({'over' if report['bias_kcal'] > 0 else 'under'}-estimates on average)",
        f"  mean abs % error      {report['mape_pct']}%   (median {report['median_ape_pct']}%)",
        f"  within ±20% of truth  {report['within_20pct'] * 100:.0f}% of photos",
        f"  range contains truth  {report['range_coverage'] * 100:.0f}% of photos "
        f"(mean range width {report['mean_range_width_kcal']:.0f} kcal)",
    ]
    for macro in OPTIONAL_MACROS:
        key = f"mae_{macro}"
        if key in report:
            lines.append(f"  {macro} MAE{' ' * (14 - len(macro))}{report[key]:.1f} g")
    lines.append("  largest errors:")
    for w in report["worst"]:
        lines.append(
            f"    {w['file']}: truth {w['true_kcal']:.0f}, estimated {w['est_kcal']:.0f} "
            f"({w['error_kcal']:+.0f})"
        )
    return "\n".join(lines)
