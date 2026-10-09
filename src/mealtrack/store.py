"""Local SQLite log: meals, water and workouts. Nothing leaves the machine."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import MEAL_TYPES, FoodItem, MealEstimate

SCHEMA = """
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    ts TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    note TEXT,
    image_sha TEXT,
    backend TEXT,
    model TEXT,
    confidence TEXT NOT NULL,
    kcal REAL NOT NULL,
    kcal_low REAL NOT NULL,
    kcal_high REAL NOT NULL,
    protein_g REAL NOT NULL,
    carbs_g REAL NOT NULL,
    fat_g REAL NOT NULL,
    items_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS water (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    ts TEXT NOT NULL,
    ml INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    ts TEXT NOT NULL,
    done INTEGER NOT NULL,
    kind TEXT,
    minutes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_meals_day ON meals(day);
CREATE INDEX IF NOT EXISTS idx_water_day ON water(day);
CREATE INDEX IF NOT EXISTS idx_workouts_day ON workouts(day);
"""


def today() -> str:
    return date.today().isoformat()


def check_day(day: str) -> str:
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        raise ValueError(f"invalid date {day!r}, expected YYYY-MM-DD") from None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ meals
    def add_meal(
        self,
        estimate: MealEstimate,
        day: str | None = None,
        meal_type: str = "snack",
        note: str | None = None,
        image_sha: str | None = None,
        backend: str | None = None,
        model: str | None = None,
    ) -> int:
        if meal_type not in MEAL_TYPES:
            raise ValueError(f"meal_type must be one of {', '.join(MEAL_TYPES)}")
        cur = self.conn.execute(
            """INSERT INTO meals (day, ts, meal_type, note, image_sha, backend, model, confidence,
                                  kcal, kcal_low, kcal_high, protein_g, carbs_g, fat_g,
                                  items_json, warnings_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                check_day(day or today()),
                _now(),
                meal_type,
                note,
                image_sha,
                backend,
                model,
                estimate.confidence,
                estimate.kcal,
                estimate.kcal_low,
                estimate.kcal_high,
                estimate.protein_g,
                estimate.carbs_g,
                estimate.fat_g,
                json.dumps([i.to_dict() for i in estimate.items]),
                json.dumps(estimate.warnings),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def meals(self, day: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM meals WHERE day = ? ORDER BY ts, id", (check_day(day),)
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["items"] = [FoodItem(**i) for i in json.loads(d.pop("items_json"))]
            d["warnings"] = json.loads(d.pop("warnings_json"))
            out.append(d)
        return out

    def delete_meal(self, meal_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ water
    def add_water(self, ml: int, day: str | None = None) -> int:
        if ml == 0 or abs(ml) > 5000:
            raise ValueError("water must be a non-zero amount of at most 5000 ml")
        cur = self.conn.execute(
            "INSERT INTO water (day, ts, ml) VALUES (?, ?, ?)",
            (check_day(day or today()), _now(), int(ml)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def water_ml(self, day: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(ml), 0) AS total FROM water WHERE day = ?", (check_day(day),)
        ).fetchone()
        return max(int(row["total"]), 0)

    # ------------------------------------------------------------------ workouts
    def add_workout(
        self,
        done: bool = True,
        kind: str | None = None,
        minutes: int | None = None,
        day: str | None = None,
    ) -> int:
        if minutes is not None and not (0 < minutes <= 600):
            raise ValueError("minutes must be between 1 and 600")
        cur = self.conn.execute(
            "INSERT INTO workouts (day, ts, done, kind, minutes) VALUES (?, ?, ?, ?, ?)",
            (check_day(day or today()), _now(), 1 if done else 0, kind, minutes),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def workouts(self, day: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM workouts WHERE day = ? ORDER BY ts, id", (check_day(day),)
        ).fetchall()
        return [dict(r) for r in rows]
