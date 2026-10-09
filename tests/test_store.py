import pytest

from mealtrack.models import parse_estimate
from mealtrack.store import Store, check_day


@pytest.fixture
def store():
    with Store(":memory:") as s:
        yield s


def test_meal_roundtrip(store, payload):
    est = parse_estimate(payload)
    meal_id = store.add_meal(est, day="2026-10-01", meal_type="lunch", note="rice 90 g",
                             image_sha="abc", backend="mock", model="mock-1")
    meals = store.meals("2026-10-01")
    assert [m["id"] for m in meals] == [meal_id]
    m = meals[0]
    assert m["kcal"] == est.kcal and m["meal_type"] == "lunch" and m["note"] == "rice 90 g"
    assert [i.name for i in m["items"]] == ["Chicken breast", "White rice, cooked"]
    assert store.meals("2026-10-02") == []


def test_delete_meal(store, payload):
    meal_id = store.add_meal(parse_estimate(payload), day="2026-10-01")
    assert store.delete_meal(meal_id) is True
    assert store.delete_meal(meal_id) is False
    assert store.meals("2026-10-01") == []


def test_invalid_meal_type_is_rejected(store, payload):
    with pytest.raises(ValueError):
        store.add_meal(parse_estimate(payload), meal_type="brunch")


def test_water_sums_and_can_be_corrected(store):
    store.add_water(500, day="2026-10-01")
    store.add_water(250, day="2026-10-01")
    store.add_water(-250, day="2026-10-01")
    assert store.water_ml("2026-10-01") == 500


def test_water_never_goes_below_zero(store):
    store.add_water(-250, day="2026-10-01")
    assert store.water_ml("2026-10-01") == 0


@pytest.mark.parametrize("ml", [0, 6000, -6000])
def test_water_amount_is_validated(store, ml):
    with pytest.raises(ValueError):
        store.add_water(ml)


def test_workouts(store):
    store.add_workout(True, kind="gym", minutes=45, day="2026-10-01")
    store.add_workout(False, day="2026-10-01")
    rows = store.workouts("2026-10-01")
    assert [r["done"] for r in rows] == [1, 0]
    with pytest.raises(ValueError):
        store.add_workout(True, minutes=0)


def test_day_validation():
    assert check_day("2026-10-01") == "2026-10-01"
    with pytest.raises(ValueError):
        check_day("01/10/2026")
