import csv

import pytest

from mealtrack.evaluate import compute_metrics, format_report, load_labels, run_eval
from mealtrack.vision import Cache, MockBackend

from conftest import make_image


def rows():
    return [
        dict(file="a.jpg", true_kcal=500, est_kcal=550, kcal_low=450, kcal_high=600,
             true_protein_g=30, est_protein_g=36),
        dict(file="b.jpg", true_kcal=400, est_kcal=300, kcal_low=250, kcal_high=350,
             true_protein_g=20, est_protein_g=18),
        dict(file="c.jpg", true_kcal=800, est_kcal=800, kcal_low=700, kcal_high=900),
    ]


def test_metrics_by_hand():
    m = compute_metrics(rows())
    assert m["n"] == 3
    assert m["mae_kcal"] == round((50 + 100 + 0) / 3, 1)
    assert m["bias_kcal"] == round((50 - 100 + 0) / 3, 1)
    assert m["mape_pct"] == round((10 + 25 + 0) / 3, 1)
    assert m["median_ape_pct"] == 10.0
    assert m["within_20pct"] == round(2 / 3, 3)  # a.jpg (10%) and c.jpg (0%)
    assert m["range_coverage"] == round(2 / 3, 3)  # b.jpg's range excludes the truth
    assert m["mean_range_width_kcal"] == round((150 + 100 + 200) / 3, 1)
    assert m["mae_protein_g"] == 4.0  # only the two rows that have protein labels
    assert m["worst"][0]["file"] == "b.jpg" and m["worst"][0]["error_kcal"] == -100


def test_metrics_need_rows():
    with pytest.raises(ValueError):
        compute_metrics([])


def write_labels(path, lines, header=("file", "true_kcal", "true_protein_g")):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(lines)


def test_load_labels(tmp_path):
    p = tmp_path / "labels.csv"
    write_labels(p, [("a.jpg", "500", "30"), ("b.jpg", "400", ""), ("", "", "")])
    labels = load_labels(p)
    assert [l["file"] for l in labels] == ["a.jpg", "b.jpg"]
    assert labels[0]["true_protein_g"] == 30 and "true_protein_g" not in labels[1]


def test_load_labels_errors(tmp_path):
    p = tmp_path / "bad.csv"
    write_labels(p, [("a.jpg", "lots", "")])
    with pytest.raises(ValueError, match="numbers"):
        load_labels(p)
    write_labels(p, [], header=("name", "kcal"))
    with pytest.raises(ValueError, match="missing column"):
        load_labels(p)
    write_labels(p, [])
    with pytest.raises(ValueError, match="no rows"):
        load_labels(p)


def test_run_eval_end_to_end_records_failures(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(make_image(color=(10, 20, 30)))
    (photos / "b.jpg").write_bytes(make_image(color=(200, 20, 30)))
    labels = tmp_path / "labels.csv"
    write_labels(labels, [("a.jpg", "500", "30"), ("b.jpg", "600", ""), ("missing.jpg", "700", "")])

    report = run_eval(photos, labels, MockBackend(), cache=Cache(tmp_path / "cache"))
    assert report["n"] == 2 and report["n_failed"] == 1
    assert report["failures"][0]["file"] == "missing.jpg"
    assert report["backend"] == "mock"
    text = format_report(report)
    assert "Evaluated 2 photo(s)" in text and "range contains truth" in text


def test_run_eval_when_everything_fails(tmp_path):
    labels = tmp_path / "labels.csv"
    write_labels(labels, [("nope.jpg", "500", "")])
    report = run_eval(tmp_path, labels, MockBackend())
    assert report["n"] == 0 and report["n_failed"] == 1
    assert "No photos could be evaluated" in format_report(report)
