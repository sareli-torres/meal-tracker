"""Data model and validation for meal estimates.

The vision model is treated as an *untrusted* source: everything it returns goes
through ``parse_estimate`` before it can reach the database or the UI. Totals are
always recomputed here from the individual items, never taken from the model.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
CONFIDENCE_LEVELS = ("low", "medium", "high")

# kcal should be close to 4*protein + 4*carbs + 9*fat. Fibre, alcohol and rounding
# explain small gaps, so only flag large disagreements, and ignore tiny items.
ATWATER_TOLERANCE = 0.30
ATWATER_MIN_KCAL = 50.0
MAX_ITEM_KCAL = 3000.0
MAX_ITEMS = 25
MAX_NOTES = 8


class EstimateError(ValueError):
    """The model output could not be turned into a valid estimate."""


class NotFoodError(EstimateError):
    """The image does not appear to show food or drink."""


@dataclass
class FoodItem:
    name: str
    grams: float
    kcal: float
    kcal_low: float
    kcal_high: float
    protein_g: float
    carbs_g: float
    fat_g: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MealEstimate:
    items: list[FoodItem]
    confidence: str = "low"
    assumptions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Totals are derived, never stored, so they can't drift from the items.
    @property
    def kcal(self) -> float:
        return round(sum(i.kcal for i in self.items), 1)

    @property
    def kcal_low(self) -> float:
        return round(sum(i.kcal_low for i in self.items), 1)

    @property
    def kcal_high(self) -> float:
        return round(sum(i.kcal_high for i in self.items), 1)

    @property
    def protein_g(self) -> float:
        return round(sum(i.protein_g for i in self.items), 1)

    @property
    def carbs_g(self) -> float:
        return round(sum(i.carbs_g for i in self.items), 1)

    @property
    def fat_g(self) -> float:
        return round(sum(i.fat_g for i in self.items), 1)

    def totals(self) -> dict[str, float]:
        return {
            "kcal": self.kcal,
            "kcal_low": self.kcal_low,
            "kcal_high": self.kcal_high,
            "protein_g": self.protein_g,
            "carbs_g": self.carbs_g,
            "fat_g": self.fat_g,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "totals": self.totals(),
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "questions": list(self.questions),
            "warnings": list(self.warnings),
        }


def _number(value: Any, label: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise EstimateError(f"{label} is not a number: {value!r}") from None
    if not math.isfinite(x):
        raise EstimateError(f"{label} is not a finite number: {value!r}")
    return x


def normalize_item(item: FoodItem, warnings: list[str] | None = None) -> FoodItem:
    """Clamp negatives and make sure ``kcal_low <= kcal <= kcal_high``.

    Also used for rows the user edits in the app, so a manual correction can never
    leave the item with a range that excludes its own value.
    """
    warnings = warnings if warnings is not None else []
    name = (item.name or "").strip()[:80] or "unknown item"

    values = {
        "grams": item.grams,
        "kcal": item.kcal,
        "kcal_low": item.kcal_low,
        "kcal_high": item.kcal_high,
        "protein_g": item.protein_g,
        "carbs_g": item.carbs_g,
        "fat_g": item.fat_g,
    }
    for key, val in values.items():
        if val < 0:
            warnings.append(f"{name}: negative {key} set to 0")
            values[key] = 0.0

    low, high, kcal = values["kcal_low"], values["kcal_high"], values["kcal"]
    if low > high:
        low, high = high, low
    if not (low <= kcal <= high):
        warnings.append(f"{name}: kcal range widened to include the estimate")
        low, high = min(low, kcal), max(high, kcal)

    return FoodItem(
        name=name,
        grams=round(values["grams"], 1),
        kcal=round(kcal, 1),
        kcal_low=round(low, 1),
        kcal_high=round(high, 1),
        protein_g=round(values["protein_g"], 1),
        carbs_g=round(values["carbs_g"], 1),
        fat_g=round(values["fat_g"], 1),
    )


def consistency_warnings(items: list[FoodItem]) -> list[str]:
    """Flag items whose kcal disagree with their own macros, or look implausible."""
    out: list[str] = []
    for it in items:
        if it.kcal > MAX_ITEM_KCAL:
            out.append(f"{it.name}: {it.kcal:.0f} kcal for one item looks implausible")
        implied = 4 * it.protein_g + 4 * it.carbs_g + 9 * it.fat_g
        biggest = max(it.kcal, implied)
        if biggest >= ATWATER_MIN_KCAL and abs(implied - it.kcal) > ATWATER_TOLERANCE * biggest:
            out.append(
                f"{it.name}: kcal ({it.kcal:.0f}) and macros (≈{implied:.0f} kcal) disagree"
            )
    return out


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [str(v).strip()[:200] for v in value if str(v).strip()]
    return cleaned[:MAX_NOTES]


def parse_estimate(payload: dict[str, Any]) -> MealEstimate:
    """Validate the raw tool output of the vision model and build a ``MealEstimate``."""
    if not isinstance(payload, dict):
        raise EstimateError("model output is not an object")
    if payload.get("is_food") is False:
        raise NotFoodError("no food or drink detected in the image")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise EstimateError("model returned no food items")
    if len(raw_items) > MAX_ITEMS:
        raise EstimateError(f"model returned {len(raw_items)} items (max {MAX_ITEMS})")

    warnings: list[str] = []
    items: list[FoodItem] = []
    for idx, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise EstimateError(f"item {idx} is not an object")
        label = f"item {idx}"
        kcal = _number(raw.get("kcal"), f"{label} kcal")
        item = FoodItem(
            name=str(raw.get("name", "")),
            grams=_number(raw.get("grams"), f"{label} grams"),
            kcal=kcal,
            kcal_low=_number(raw.get("kcal_low", kcal), f"{label} kcal_low"),
            kcal_high=_number(raw.get("kcal_high", kcal), f"{label} kcal_high"),
            protein_g=_number(raw.get("protein_g"), f"{label} protein_g"),
            carbs_g=_number(raw.get("carbs_g"), f"{label} carbs_g"),
            fat_g=_number(raw.get("fat_g"), f"{label} fat_g"),
        )
        items.append(normalize_item(item, warnings))

    confidence = payload.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        warnings.append(f"unknown confidence {confidence!r}, treated as low")
        confidence = "low"

    warnings.extend(consistency_warnings(items))
    return MealEstimate(
        items=items,
        confidence=confidence,
        assumptions=_string_list(payload.get("assumptions")),
        questions=_string_list(payload.get("questions")),
        warnings=warnings,
    )
