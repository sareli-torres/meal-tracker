"""Daily and weekly summaries.

Design choice (borrowed from the reference project's "conservative" stance): a day with
nothing logged is *not logged*, not "0 kcal". Averages therefore only use days that have
at least one meal, and the output always says how many days that was.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .store import Store, check_day


@dataclass
class DaySummary:
    day: str
    n_meals: int = 0
    n_low_confidence: int = 0
    kcal: float = 0.0
    kcal_low: float = 0.0
    kcal_high: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    water_ml: int = 0
    workout_done: bool | None = None  # None = nothing logged, False = logged as skipped
    workout_minutes: int = 0
    workout_kinds: list[str] = field(default_factory=list)
    goal_kcal: int = 2000
    goal_water_ml: int = 2000

    @property
    def logged(self) -> bool:
        return self.n_meals > 0

    @property
    def pct_of_goal(self) -> float | None:
        return round(100 * self.kcal / self.goal_kcal, 1) if self.logged else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "meals_logged": self.n_meals,
            "low_confidence_meals": self.n_low_confidence,
            "kcal": self.kcal,
            "kcal_low": self.kcal_low,
            "kcal_high": self.kcal_high,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
            "kcal_goal": self.goal_kcal,
            "pct_of_goal": self.pct_of_goal,
            "water_ml": self.water_ml,
            "water_goal_ml": self.goal_water_ml,
            "workout_done": self.workout_done,
            "workout_minutes": self.workout_minutes,
            "workout_kinds": self.workout_kinds,
        }

    def format_text(self) -> str:
        lines = [self.day]
        if self.logged:
            lines.append(
                f"  Calories  {self.kcal:,.0f} kcal "
                f"(range {self.kcal_low:,.0f}-{self.kcal_high:,.0f}) · goal {self.goal_kcal:,} "
                f"· {self.pct_of_goal:.0f}%"
            )
            lines.append(
                f"  Macros    protein {self.protein_g:.0f} g · carbs {self.carbs_g:.0f} g "
                f"· fat {self.fat_g:.0f} g"
            )
            meals = f"{self.n_meals} logged"
            if self.n_low_confidence:
                meals += f" ({self.n_low_confidence} low confidence)"
            lines.append(f"  Meals     {meals}")
        else:
            lines.append("  Calories  no meals logged")
        lines.append(f"  Water     {self.water_ml:,} / {self.goal_water_ml:,} ml")
        if self.workout_done is None:
            lines.append("  Workout   not logged")
        elif self.workout_done:
            detail = ", ".join(self.workout_kinds)
            if self.workout_minutes:
                detail = f"{detail} {self.workout_minutes} min".strip()
            lines.append("  Workout   done" + (f" ({detail})" if detail else ""))
        else:
            lines.append("  Workout   skipped")
        return "\n".join(lines)


@dataclass
class WeekSummary:
    days: list[DaySummary]

    @property
    def logged_days(self) -> int:
        return sum(1 for d in self.days if d.logged)

    @property
    def avg_kcal(self) -> float | None:
        logged = [d for d in self.days if d.logged]
        return round(sum(d.kcal for d in logged) / len(logged), 1) if logged else None

    @property
    def avg_protein_g(self) -> float | None:
        logged = [d for d in self.days if d.logged]
        return round(sum(d.protein_g for d in logged) / len(logged), 1) if logged else None

    @property
    def workouts_done(self) -> int:
        return sum(1 for d in self.days if d.workout_done)

    def to_dict(self) -> dict[str, Any]:
        return {
            "days": [d.to_dict() for d in self.days],
            "days_with_meals_logged": self.logged_days,
            "days_total": len(self.days),
            "avg_kcal_logged_days": self.avg_kcal,
            "avg_protein_g_logged_days": self.avg_protein_g,
            "workouts_done": self.workouts_done,
        }

    def format_text(self) -> str:
        head = f"{self.days[0].day} to {self.days[-1].day}"
        if self.avg_kcal is None:
            body = "no meals logged in this period"
        else:
            body = (
                f"average {self.avg_kcal:,.0f} kcal and {self.avg_protein_g:.0f} g protein "
                f"over the {self.logged_days} of {len(self.days)} days with meals logged"
            )
        rows = []
        for d in self.days:
            kcal = f"{d.kcal:>6,.0f} kcal" if d.logged else "   not logged"
            workout = {None: "-", True: "done", False: "skipped"}[d.workout_done]
            rows.append(f"  {d.day}  {kcal}   water {d.water_ml:>5,} ml   workout {workout}")
        return "\n".join([head, body, *rows])


def summarize_day(store: Store, day: str, goal_kcal: int, goal_water_ml: int) -> DaySummary:
    day = check_day(day)
    meals = store.meals(day)
    workouts = store.workouts(day)

    summary = DaySummary(day=day, goal_kcal=goal_kcal, goal_water_ml=goal_water_ml)
    summary.n_meals = len(meals)
    summary.n_low_confidence = sum(1 for m in meals if m["confidence"] == "low")
    summary.kcal = round(sum(m["kcal"] for m in meals), 1)
    summary.kcal_low = round(sum(m["kcal_low"] for m in meals), 1)
    summary.kcal_high = round(sum(m["kcal_high"] for m in meals), 1)
    summary.protein_g = round(sum(m["protein_g"] for m in meals), 1)
    summary.carbs_g = round(sum(m["carbs_g"] for m in meals), 1)
    summary.fat_g = round(sum(m["fat_g"] for m in meals), 1)
    summary.water_ml = store.water_ml(day)

    if workouts:
        summary.workout_done = any(w["done"] for w in workouts)
        summary.workout_minutes = sum(w["minutes"] or 0 for w in workouts if w["done"])
        summary.workout_kinds = [w["kind"] for w in workouts if w["done"] and w["kind"]]
    return summary


def summarize_range(
    store: Store, end_day: str, days: int, goal_kcal: int, goal_water_ml: int
) -> WeekSummary:
    end = date.fromisoformat(check_day(end_day))
    if days < 1:
        raise ValueError("days must be at least 1")
    start = end - timedelta(days=days - 1)
    return WeekSummary(
        days=[
            summarize_day(store, (start + timedelta(days=i)).isoformat(), goal_kcal, goal_water_ml)
            for i in range(days)
        ]
    )
