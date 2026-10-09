"""Prompt and tool schema sent to the vision model.

Bump ``PROMPT_VERSION`` whenever either changes: it is part of the cache key, so old
cached estimates are not reused with a new prompt.
"""

from __future__ import annotations

from typing import Any

PROMPT_VERSION = "1"

SYSTEM_PROMPT = """\
You estimate the nutrition of a meal from a single photo. You are one step in a
personal food log, so honest uncertainty matters more than a confident-looking number.

Rules:
- List every distinct food or drink you can see as a separate item, including likely
  cooking oil, sauces and dressings (state those in `assumptions`).
- For each item estimate the portion in grams *as shown* (cooked weight for cooked food),
  using visible references such as plate size, cutlery, hands or packaging.
- Give kcal, protein_g, carbs_g and fat_g for that portion, plus a plausible range
  kcal_low..kcal_high. Make the range as wide as your real uncertainty: mixed dishes,
  sauces and hidden fats deserve wide ranges. Never claim more precision than the photo allows.
- If the user's note gives weights or ingredients, trust it over your visual estimate and
  say so in `assumptions`.
- `confidence` is your overall confidence in the total: low, medium or high.
- `questions` lists up to three things that would most improve the estimate
  (for example "Is the rice weighed cooked or dry?").
- If the image does not show food or drink, set is_food to false and return no items.
- Write item names in the language of the user's note if there is one, otherwise English.
- This is a rough logging aid, not medical or dietary advice. Do not comment on health,
  weight or whether the meal is good or bad.
"""

REPORT_MEAL_TOOL: dict[str, Any] = {
    "name": "report_meal",
    "description": "Report the foods visible in the photo with portions and estimated nutrition.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_food": {
                "type": "boolean",
                "description": "False if the image does not show food or drink.",
            },
            "items": {
                "type": "array",
                "description": "One entry per distinct food or drink.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "grams": {"type": "number", "description": "Portion shown, in grams."},
                        "kcal": {"type": "number"},
                        "kcal_low": {"type": "number"},
                        "kcal_high": {"type": "number"},
                        "protein_g": {"type": "number"},
                        "carbs_g": {"type": "number"},
                        "fat_g": {"type": "number"},
                    },
                    "required": [
                        "name",
                        "grams",
                        "kcal",
                        "kcal_low",
                        "kcal_high",
                        "protein_g",
                        "carbs_g",
                        "fat_g",
                    ],
                },
            },
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Assumptions made, e.g. hidden oil or sauce.",
            },
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to three questions whose answers would improve the estimate.",
            },
        },
        "required": ["is_food", "items", "confidence", "assumptions", "questions"],
    },
}


def build_user_text(hint: str | None) -> str:
    text = "Estimate the nutrition of the meal in this photo."
    if hint and hint.strip():
        text += f"\n\nNote from the user (trust this over your visual guess): {hint.strip()[:500]}"
    return text
