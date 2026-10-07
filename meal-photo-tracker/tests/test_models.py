import copy

import pytest

from mealtrack.models import EstimateError, NotFoodError, parse_estimate


def test_totals_are_recomputed_from_items(payload):
    payload["total_kcal"] = 99999  # a model-supplied total must be ignored
    est = parse_estimate(payload)
    assert est.kcal == 482.0
    assert est.kcal_low == 400.0
    assert est.kcal_high == 580.0
    assert est.protein_g == 51.4
    assert est.carbs_g == 51.0
    assert est.warnings == []
    assert est.confidence == "medium"


def test_negative_values_are_clamped_with_a_warning(payload):
    payload["items"][0]["grams"] = -5
    est = parse_estimate(payload)
    assert est.items[0].grams == 0
    assert any("negative grams" in w for w in est.warnings)


def test_range_is_widened_to_include_the_estimate(payload):
    payload["items"][0]["kcal_low"] = 260
    payload["items"][0]["kcal_high"] = 300
    est = parse_estimate(payload)
    assert est.items[0].kcal_low == 248
    assert any("widened" in w for w in est.warnings)


def test_inverted_range_is_swapped(payload):
    payload["items"][0]["kcal_low"], payload["items"][0]["kcal_high"] = 290, 210
    est = parse_estimate(payload)
    assert (est.items[0].kcal_low, est.items[0].kcal_high) == (210, 290)


def test_kcal_that_disagrees_with_macros_is_flagged(payload):
    payload["items"][1]["kcal"] = 900
    payload["items"][1]["kcal_high"] = 950
    est = parse_estimate(payload)
    assert any("disagree" in w for w in est.warnings)


def test_tiny_items_are_not_flagged_for_macro_mismatch(payload):
    payload["items"].append(
        {"name": "Coffee", "grams": 200, "kcal": 2, "kcal_low": 0, "kcal_high": 5,
         "protein_g": 0.3, "carbs_g": 0, "fat_g": 0}
    )
    assert parse_estimate(payload).warnings == []


def test_implausible_item_is_flagged(payload):
    payload["items"][0].update(kcal=4000, kcal_low=3500, kcal_high=4500, protein_g=300, carbs_g=500, fat_g=100)
    assert any("implausible" in w for w in parse_estimate(payload).warnings)


def test_unknown_confidence_becomes_low(payload):
    payload["confidence"] = "certain"
    est = parse_estimate(payload)
    assert est.confidence == "low"
    assert any("confidence" in w for w in est.warnings)


def test_not_food_raises(payload):
    payload["is_food"] = False
    with pytest.raises(NotFoodError):
        parse_estimate(payload)


@pytest.mark.parametrize("bad", [None, [], "text", 3])
def test_non_object_payload_raises(bad):
    with pytest.raises(EstimateError):
        parse_estimate(bad)


def test_empty_items_raise(payload):
    payload["items"] = []
    with pytest.raises(EstimateError):
        parse_estimate(payload)


@pytest.mark.parametrize("value", ["lots", None, float("nan"), float("inf")])
def test_non_finite_or_non_numeric_values_raise(payload, value):
    bad = copy.deepcopy(payload)
    bad["items"][0]["kcal"] = value
    with pytest.raises(EstimateError):
        parse_estimate(bad)


def test_too_many_items_raise(payload):
    payload["items"] = [payload["items"][0]] * 26
    with pytest.raises(EstimateError):
        parse_estimate(payload)


def test_notes_are_cleaned_and_capped(payload):
    payload["assumptions"] = ["  a  ", "", *[f"n{i}" for i in range(20)]]
    est = parse_estimate(payload)
    assert est.assumptions[0] == "a"
    assert len(est.assumptions) == 8


def test_missing_range_defaults_to_the_point_estimate(payload):
    del payload["items"][0]["kcal_low"]
    del payload["items"][0]["kcal_high"]
    est = parse_estimate(payload)
    assert est.items[0].kcal_low == est.items[0].kcal_high == 248
