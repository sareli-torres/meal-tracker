"""Turn rows the user edited in the app back into validated ``FoodItem`` objects."""

from __future__ import annotations

import math
from typing import Any

from .models import FoodItem, normalize_item

NUMERIC = ("grams", "kcal", "kcal_low", "kcal_high", "protein_g", "carbs_g", "fat_g")


def _num(value: Any) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def items_from_rows(rows: list[dict[str, Any]]) -> list[FoodItem]:
    """Blank rows are dropped. A row without a kcal range gets ``low = high = kcal``
    (a value typed by hand is a point value); a range that excludes the kcal is widened."""
    items: list[FoodItem] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if name.lower() in ("nan", "none"):
            name = ""
        values = {k: _num(row.get(k)) for k in NUMERIC}
        if not name and not any(values.values()):
            continue
        if values["kcal_low"] == 0 and values["kcal_high"] == 0 and values["kcal"] > 0:
            values["kcal_low"] = values["kcal_high"] = values["kcal"]
        items.append(normalize_item(FoodItem(name=name, **values)))
    return items
