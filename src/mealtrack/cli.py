"""Command line interface. Every command can print machine-readable JSON with ``--json``.

Exit codes: 0 ok · 2 bad input or usage · 3 vision/API/estimate failure · 4 no food in the image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import config
from .demo import seed_demo
from .evaluate import format_report, run_eval
from .models import MEAL_TYPES, EstimateError, MealEstimate, NotFoodError
from .store import Store, check_day, today
from .summary import summarize_day, summarize_range
from .vision import Cache, ImageError, VisionError, analyze_photo, get_backend

EXIT_OK, EXIT_USAGE, EXIT_FAILURE, EXIT_NOT_FOOD = 0, 2, 3, 4


def _emit(args: argparse.Namespace, payload: dict[str, Any], text: str) -> None:
    print(json.dumps(payload, indent=2) if args.json else text)


def _fail(args: argparse.Namespace, code: int, kind: str, message: str) -> int:
    if args.json:
        print(json.dumps({"error": {"type": kind, "message": message}}, indent=2))
    else:
        print(f"error: {message}", file=sys.stderr)
    return code


def _format_estimate(est: MealEstimate) -> str:
    lines = []
    for it in est.items:
        lines.append(
            f"  {it.name:<32} {it.grams:>5.0f} g  {it.kcal:>5.0f} kcal "
            f"({it.kcal_low:.0f}-{it.kcal_high:.0f})  "
            f"P {it.protein_g:.0f}  C {it.carbs_g:.0f}  F {it.fat_g:.0f}"
        )
    lines.append(
        f"  {'TOTAL':<32} {'':>7} {est.kcal:>5.0f} kcal ({est.kcal_low:.0f}-{est.kcal_high:.0f})  "
        f"P {est.protein_g:.0f}  C {est.carbs_g:.0f}  F {est.fat_g:.0f}"
    )
    lines.append(f"  confidence: {est.confidence}")
    for label, notes in (
        ("assumed", est.assumptions),
        ("would help to know", est.questions),
        ("warning", est.warnings),
    ):
        lines.extend(f"  {label}: {n}" for n in notes)
    return "\n".join(lines)


def _open_store(args: argparse.Namespace) -> Store:
    return Store(args.db or config.db_path(getattr(args, "backend", None)))


# --------------------------------------------------------------------------- commands
def cmd_log_meal(args: argparse.Namespace) -> int:
    path = Path(args.photo)
    try:
        data = path.read_bytes()
    except OSError as exc:
        return _fail(args, EXIT_USAGE, "file", f"cannot read {path}: {exc.strerror or exc}")
    day = check_day(args.day or today())

    try:
        backend = get_backend(args.backend)
        analysis = analyze_photo(data, backend, hint=args.hint, cache=Cache(config.cache_dir()))
    except NotFoodError as exc:
        return _fail(args, EXIT_NOT_FOOD, "not_food", str(exc))
    except ImageError as exc:
        return _fail(args, EXIT_USAGE, "image", str(exc))
    except (VisionError, EstimateError) as exc:
        return _fail(args, EXIT_FAILURE, "estimate", str(exc))

    meal_id = None
    if not args.dry_run:
        with _open_store(args) as store:
            meal_id = store.add_meal(
                analysis.estimate,
                day=day,
                meal_type=args.type,
                note=args.hint,
                image_sha=analysis.image_sha,
                backend=analysis.backend,
                model=analysis.model,
            )

    payload = {
        "saved": meal_id is not None,
        "id": meal_id,
        "day": day,
        "meal_type": args.type,
        "cached": analysis.cached,
        "backend": analysis.backend,
        "model": analysis.model,
        "estimate": analysis.estimate.to_dict(),
    }
    header = f"{args.type} on {day}" + (f" (saved as #{meal_id})" if meal_id else " (dry run, not saved)")
    suffix = "  [from cache]" if analysis.cached else ""
    _emit(args, payload, f"{header}{suffix}\n{_format_estimate(analysis.estimate)}")
    return EXIT_OK


def cmd_water(args: argparse.Namespace) -> int:
    day = check_day(args.day or today())
    with _open_store(args) as store:
        store.add_water(args.ml, day=day)
        total = store.water_ml(day)
    _emit(args, {"day": day, "added_ml": args.ml, "total_ml": total}, f"{day}: {total:,} ml of water logged")
    return EXIT_OK


def cmd_workout(args: argparse.Namespace) -> int:
    day = check_day(args.day or today())
    with _open_store(args) as store:
        store.add_workout(done=not args.skipped, kind=args.kind, minutes=args.minutes, day=day)
    state = "skipped" if args.skipped else "done"
    _emit(args, {"day": day, "workout": state, "kind": args.kind, "minutes": args.minutes}, f"{day}: workout {state}")
    return EXIT_OK


def cmd_today(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        summary = summarize_day(store, args.day or today(), config.goal_kcal(), config.goal_water_ml())
    _emit(args, summary.to_dict(), summary.format_text())
    return EXIT_OK


def cmd_week(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        week = summarize_range(store, args.end or today(), args.days, config.goal_kcal(), config.goal_water_ml())
    _emit(args, week.to_dict(), week.format_text())
    return EXIT_OK


def cmd_meals(args: argparse.Namespace) -> int:
    day = check_day(args.day or today())
    with _open_store(args) as store:
        meals = store.meals(day)
    payload = {
        "day": day,
        "meals": [
            {
                "id": m["id"],
                "meal_type": m["meal_type"],
                "confidence": m["confidence"],
                "kcal": m["kcal"],
                "kcal_low": m["kcal_low"],
                "kcal_high": m["kcal_high"],
                "protein_g": m["protein_g"],
                "carbs_g": m["carbs_g"],
                "fat_g": m["fat_g"],
                "items": [i.to_dict() for i in m["items"]],
                "note": m["note"],
            }
            for m in meals
        ],
    }
    if meals:
        lines = [day] + [
            f"  #{m['id']:<4} {m['meal_type']:<9} {m['kcal']:>5.0f} kcal  "
            f"{', '.join(i.name for i in m['items'])}"
            for m in meals
        ]
    else:
        lines = [f"{day}: no meals logged"]
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def cmd_delete_meal(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        removed = store.delete_meal(args.id)
    if not removed:
        return _fail(args, EXIT_USAGE, "not_found", f"no meal with id {args.id}")
    _emit(args, {"deleted": args.id}, f"deleted meal #{args.id}")
    return EXIT_OK


def cmd_demo_data(args: argparse.Namespace) -> int:
    path = args.db or config.db_path("mock")
    with Store(path) as store:
        seed_demo(store, days=args.days)
    _emit(args, {"db": str(path), "days": args.days}, f"seeded {args.days} days of synthetic data into {path}")
    return EXIT_OK


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        backend = get_backend(args.backend)
        report = run_eval(args.photos, args.labels, backend, cache=Cache(config.cache_dir()))
    except (ValueError, OSError) as exc:
        return _fail(args, EXIT_USAGE, "input", str(exc))
    except VisionError as exc:
        return _fail(args, EXIT_FAILURE, "estimate", str(exc))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    _emit(args, report, format_report(report))
    return EXIT_OK if report.get("n", 0) else EXIT_FAILURE


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print machine-readable JSON")
    common.add_argument("--db", help="path to the SQLite log (default: .mealtrack/log.db)")
    common.add_argument("--backend", choices=["claude", "mock"], help="vision backend (default: claude)")

    parser = argparse.ArgumentParser(
        prog="mealtrack",
        description="Log meals from photos, water and workouts; see an honest daily summary.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("log-meal", parents=[common], help="estimate a meal from a photo and log it")
    p.add_argument("photo", help="path to a JPG, PNG, WEBP or GIF photo")
    p.add_argument("--type", choices=MEAL_TYPES, default="snack", help="meal type (default: snack)")
    p.add_argument("--hint", help="what you know about the meal, e.g. 'rice 90 g, chicken 140 g'")
    p.add_argument("--day", help="YYYY-MM-DD (default: today)")
    p.add_argument("--dry-run", action="store_true", help="show the estimate without saving it")
    p.set_defaults(func=cmd_log_meal)

    p = sub.add_parser("water", parents=[common], help="log water in ml (negative to correct)")
    p.add_argument("ml", type=int)
    p.add_argument("--day")
    p.set_defaults(func=cmd_water)

    p = sub.add_parser("workout", parents=[common], help="log whether you trained")
    p.add_argument("--skipped", action="store_true", help="log the workout as skipped")
    p.add_argument("--kind", help="e.g. gym, run, yoga")
    p.add_argument("--minutes", type=int)
    p.add_argument("--day")
    p.set_defaults(func=cmd_workout)

    p = sub.add_parser("today", parents=[common], help="summary for a day")
    p.add_argument("--day")
    p.set_defaults(func=cmd_today)

    p = sub.add_parser("week", parents=[common], help="summary for the last N days")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--end", help="last day of the range (default: today)")
    p.set_defaults(func=cmd_week)

    p = sub.add_parser("meals", parents=[common], help="list the meals logged on a day")
    p.add_argument("--day")
    p.set_defaults(func=cmd_meals)

    p = sub.add_parser("delete-meal", parents=[common], help="remove a logged meal by id")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_delete_meal)

    p = sub.add_parser("demo-data", parents=[common], help="fill the demo database with synthetic data")
    p.add_argument("--days", type=int, default=14)
    p.set_defaults(func=cmd_demo_data)

    p = sub.add_parser("eval", parents=[common], help="compare estimates with ground truth you provide")
    p.add_argument("--photos", required=True, help="folder with the photos")
    p.add_argument("--labels", required=True, help="CSV: file,true_kcal[,true_protein_g,true_carbs_g,true_fat_g]")
    p.add_argument("--out", help="also write the full report as JSON to this path")
    p.set_defaults(func=cmd_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:  # bad date, bad amount, ...
        return _fail(args, EXIT_USAGE, "input", str(exc))


if __name__ == "__main__":
    sys.exit(main())
