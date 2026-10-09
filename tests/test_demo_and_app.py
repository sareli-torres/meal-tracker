from pathlib import Path

import pytest

from mealtrack.demo import seed_demo
from mealtrack.store import Store
from mealtrack.summary import summarize_range

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def test_demo_data_is_deterministic_and_has_one_empty_day():
    def build():
        with Store(":memory:") as s:
            seed_demo(s, days=14, end_day="2026-10-14", seed=7)
            return summarize_range(s, "2026-10-14", 14, 2000, 2000).to_dict()

    a, b = build(), build()
    assert a == b
    assert a["days_with_meals_logged"] == 13


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEALTRACK_HOME", str(tmp_path / ".mt"))
    monkeypatch.setenv("MEALTRACK_BACKEND", "mock")
    monkeypatch.delenv("MEALTRACK_DB", raising=False)


def test_app_renders_in_demo_mode_and_buttons_work(app_env):
    testing = pytest.importorskip("streamlit.testing.v1")
    at = testing.AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Log a meal", "Day", "Week"]

    next(b for b in at.button if b.label.startswith("Fill with synthetic")).click()
    at.run()
    assert not at.exception and any("Demo data" in s.value for s in at.success)

    before = [p.text for p in at.get("progress")]
    next(b for b in at.button if b.label == "+500 ml").click()
    at.run()
    after = [p.text for p in at.get("progress")]
    assert not at.exception and before != after
