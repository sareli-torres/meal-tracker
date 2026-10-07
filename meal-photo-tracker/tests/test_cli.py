import csv
import json

import pytest

from mealtrack import cli
from mealtrack.demo import seed_demo
from mealtrack.store import Store, today

from conftest import make_image


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEALTRACK_HOME", str(tmp_path / ".mt"))
    for var in ("MEALTRACK_DB", "MEALTRACK_BACKEND", "ANTHROPIC_API_KEY", "MEALTRACK_GOAL_KCAL"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def photo(isolated_home):
    path = isolated_home / "plate.jpg"
    path.write_bytes(make_image(color=(90, 140, 60)))
    return str(path)


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_log_meal_json_then_today(capsys, photo):
    code, out, _ = run(capsys, "log-meal", photo, "--type", "lunch", "--backend", "mock", "--json")
    data = json.loads(out)
    assert code == 0 and data["saved"] is True and data["meal_type"] == "lunch"
    assert data["estimate"]["totals"]["kcal"] > 0 and data["cached"] is False

    code, out, _ = run(capsys, "today", "--backend", "mock", "--json")
    day = json.loads(out)
    assert code == 0 and day["meals_logged"] == 1 and day["kcal"] == data["estimate"]["totals"]["kcal"]


def test_second_log_of_same_photo_uses_the_cache(capsys, photo):
    run(capsys, "log-meal", photo, "--backend", "mock", "--json")
    _, out, _ = run(capsys, "log-meal", photo, "--backend", "mock", "--json")
    assert json.loads(out)["cached"] is True


def test_dry_run_does_not_save(capsys, photo):
    run(capsys, "log-meal", photo, "--backend", "mock", "--dry-run")
    _, out, _ = run(capsys, "meals", "--backend", "mock", "--json")
    assert json.loads(out)["meals"] == []


def test_mock_data_never_touches_the_real_log(capsys, photo, isolated_home):
    run(capsys, "log-meal", photo, "--backend", "mock")
    assert (isolated_home / ".mt" / "demo.db").exists()
    assert not (isolated_home / ".mt" / "log.db").exists()


def test_water_workout_and_text_summary(capsys):
    run(capsys, "water", "500", "--backend", "mock")
    run(capsys, "water", "250", "--backend", "mock")
    run(capsys, "workout", "--kind", "run", "--minutes", "30", "--backend", "mock")
    _, out, _ = run(capsys, "today", "--backend", "mock")
    assert "750 / 2,000 ml" in out and "done (run 30 min)" in out and "no meals logged" in out


def test_goal_comes_from_the_environment(capsys, monkeypatch):
    monkeypatch.setenv("MEALTRACK_GOAL_KCAL", "1800")
    _, out, _ = run(capsys, "today", "--backend", "mock", "--json")
    assert json.loads(out)["kcal_goal"] == 1800


def test_missing_file_exits_2(capsys):
    code, _, err = run(capsys, "log-meal", "nope.jpg", "--backend", "mock")
    assert code == 2 and "cannot read" in err


def test_json_errors_are_json(capsys, photo):
    code, out, _ = run(capsys, "log-meal", photo, "--json")  # no key, claude backend
    assert code == 3 and json.loads(out)["error"]["type"] == "estimate"


def test_not_food_exits_4(capsys, photo, monkeypatch):
    class NoFood:
        name, model = "fake", "fake-1"

        def estimate(self, image, hint):
            return {"is_food": False, "items": [], "confidence": "high", "assumptions": [], "questions": []}

    monkeypatch.setattr(cli, "get_backend", lambda name=None: NoFood())
    code, out, _ = run(capsys, "log-meal", photo, "--json")
    assert code == 4 and json.loads(out)["error"]["type"] == "not_food"


def test_bad_date_exits_2(capsys):
    code, _, err = run(capsys, "today", "--day", "yesterday", "--backend", "mock")
    assert code == 2 and "YYYY-MM-DD" in err


def test_delete_meal(capsys, photo):
    _, out, _ = run(capsys, "log-meal", photo, "--backend", "mock", "--json")
    meal_id = json.loads(out)["id"]
    assert run(capsys, "delete-meal", str(meal_id), "--backend", "mock")[0] == 0
    code, _, err = run(capsys, "delete-meal", str(meal_id), "--backend", "mock")
    assert code == 2 and "no meal" in err


def test_demo_data_and_week(capsys):
    run(capsys, "demo-data", "--days", "10")
    _, out, _ = run(capsys, "week", "--days", "10", "--backend", "mock", "--json")
    week = json.loads(out)
    assert week["days_total"] == 10 and week["days_with_meals_logged"] == 9  # one empty day on purpose


def test_eval_command(capsys, isolated_home, photo):
    labels = isolated_home / "labels.csv"
    with open(labels, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "true_kcal"])
        w.writerow(["plate.jpg", "500"])
    code, out, _ = run(
        capsys, "eval", "--photos", str(isolated_home), "--labels", str(labels), "--backend", "mock",
        "--out", str(isolated_home / "report.json"), "--json",
    )
    assert code == 0 and json.loads(out)["n"] == 1
    assert (isolated_home / "report.json").exists()


def test_eval_with_bad_labels_exits_2(capsys, isolated_home):
    (isolated_home / "empty.csv").write_text("file,true_kcal\n")
    code, _, err = run(capsys, "eval", "--photos", str(isolated_home), "--labels",
                       str(isolated_home / "empty.csv"), "--backend", "mock")
    assert code == 2 and "no rows" in err
