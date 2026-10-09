import pytest

from mealtrack.models import parse_estimate
from mealtrack.store import Store
from mealtrack.summary import summarize_day, summarize_range


@pytest.fixture
def store(payload):
    est = parse_estimate(payload)  # 482 kcal, medium confidence
    low = parse_estimate({**payload, "confidence": "low"})
    with Store(":memory:") as s:
        s.add_meal(est, day="2026-10-01", meal_type="lunch")
        s.add_meal(low, day="2026-10-01", meal_type="dinner")
        s.add_meal(est, day="2026-10-03", meal_type="lunch")
        s.add_water(750, day="2026-10-01")
        s.add_workout(True, kind="gym", minutes=45, day="2026-10-01")
        s.add_workout(False, day="2026-10-02")
        yield s


def test_day_totals(store):
    d = summarize_day(store, "2026-10-01", 2000, 2000)
    assert d.kcal == 964 and d.n_meals == 2 and d.n_low_confidence == 1
    assert d.pct_of_goal == 48.2
    assert d.water_ml == 750
    assert d.workout_done is True and d.workout_minutes == 45 and d.workout_kinds == ["gym"]


def test_empty_day_is_not_logged_rather_than_zero(store):
    d = summarize_day(store, "2026-10-02", 2000, 2000)
    assert not d.logged and d.pct_of_goal is None
    assert d.workout_done is False  # explicitly skipped
    assert "no meals logged" in d.format_text() and "skipped" in d.format_text()
    assert summarize_day(store, "2026-10-05", 2000, 2000).workout_done is None


def test_week_average_ignores_days_without_meals(store):
    week = summarize_range(store, "2026-10-03", 3, 2000, 2000)
    assert week.logged_days == 2 and len(week.days) == 3
    assert week.avg_kcal == pytest.approx((964 + 482) / 2)
    assert week.workouts_done == 1
    assert "2 of 3 days" in week.format_text()


def test_week_with_nothing_logged(store):
    week = summarize_range(store, "2026-12-31", 7, 2000, 2000)
    assert week.avg_kcal is None
    assert "no meals logged" in week.format_text()
    assert week.to_dict()["avg_kcal_logged_days"] is None


def test_range_needs_at_least_one_day(store):
    with pytest.raises(ValueError):
        summarize_range(store, "2026-10-03", 0, 2000, 2000)
