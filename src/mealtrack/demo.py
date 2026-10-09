"""Synthetic demo data, so the app can be shown without anyone's real food log."""

from __future__ import annotations

import random
from datetime import date, timedelta

from .models import parse_estimate
from .store import Store
from .vision import mock_payload

_WORKOUTS = [("gym", 45), ("run", 30), ("yoga", 40), ("cycling", 50)]


def seed_demo(store: Store, days: int = 14, end_day: str | None = None, seed: int = 7) -> int:
    """Fill ``store`` with ``days`` days of made-up logs. One day is left empty on purpose.

    Days that already have meals are left untouched, so running this twice never doubles
    the data. Returns the number of days that were filled.
    """
    rng = random.Random(seed)
    end = date.fromisoformat(end_day) if end_day else date.today()
    empty_offset = rng.randrange(2, max(days, 3))
    meal_types = ["breakfast", "lunch", "dinner", "snack"]
    filled = 0

    for offset in range(days):
        day = (end - timedelta(days=offset)).isoformat()
        if offset == empty_offset or store.meals(day):
            continue
        filled += 1
        n_meals = rng.choice([3, 3, 4])
        for meal_type in meal_types[:n_meals]:
            estimate = parse_estimate(mock_payload(rng.randrange(4)))
            store.add_meal(
                estimate,
                day=day,
                meal_type=meal_type,
                backend="mock",
                model="mock-1",
            )
        for _ in range(rng.randint(3, 5)):
            store.add_water(rng.choice([250, 300, 500, 500]), day=day)
        roll = rng.random()
        if roll < 0.55:
            kind, minutes = rng.choice(_WORKOUTS)
            store.add_workout(True, kind=kind, minutes=minutes, day=day)
        elif roll < 0.75:
            store.add_workout(False, day=day)
    return filled
