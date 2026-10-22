"""Hybrid cow correction on synthetic herd-level paths only (no database)."""
import json
import math
from datetime import date

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.cow_torch_outlook import (
    HYBRID_VERSION,
    CalibrationCell,
    build_correction_artifact,
    calibration_from_errors,
    hybrid_document,
    run,
)
from components.predictive_farm_intelligence.pfoi.cow_torch_production import (
    estimate_origin_factor,
    produce_correction_artifact,
    structural_daily_from_document,
    structural_daily_from_outlook,
)
from components.predictive_farm_intelligence.pfoi.cow_accuracy import AccuracyModels


ORIGIN = date(2024, 1, 1)  # Monday, so daily / weekly / monthly periods align simply.


def _aggregate(origin=ORIGIN, days=370):
    return pd.DataFrame({
        "date": pd.date_range(origin, periods=days),
        "structural_litres": 100.0,
        "cow_model_litres": 110.0,
        "cow_reference_litres": 100.0,
        "n_cows": 20,
    })


def _artifact(origin=ORIGIN):
    cells = [
        CalibrationCell("day", 1, math.log(0.9), math.log(1.1), 40),
        CalibrationCell("week", 1, math.log(0.8), math.log(1.2), 30),
        CalibrationCell("month", 1, math.log(0.85), math.log(1.15), 20),
    ]
    return build_correction_artifact(
        origin, _aggregate(origin), cells, taper_days=0,
        anchor_correction_litres_per_day=2.0,
    )


def _row(grain, horizon, target, forecast, series="milk_litres"):
    return {
        "origin_date": ORIGIN.isoformat(), "target_period": target, "grain": grain,
        "horizon": horizon, "series": series, "forecast": forecast,
        "lower": forecast * 0.9, "upper": forecast * 1.1, "quality_flag": "high",
        "model_version": "pfoi-1.2.0-dev", "core_version": "synthetic",
    }


def _doc(origin=ORIGIN):
    return {
        "source": "model", "origin_date": origin.isoformat(), "model_version": "pfoi-1.2.0-dev",
        "core_version": "synthetic", "interval_method": {"milk": "old"},
        "outlook": [
            _row("day", 1, "2024-01-01", 100.0),
            _row("week", 1, "2024-01-01", 700.0),
            _row("month", 1, "2024-01-01", 3100.0),
            _row("month", 1, "2024-01-01", 20.0, "milking"),
        ],
        "corrections": [{"series": "milk_litres", "correction": 5.0}],
        "attribution": [{
            "origin_date": origin.isoformat(), "target_period": "2024-01-01", "grain": "month",
            "series": "milk_litres", "factor": "herd_size", "contribution": 3.0,
            "model_version": "pfoi-1.2.0-dev", "core_version": "synthetic",
        }],
        "heat": {"status": "synthetic weather-only section"},
    }


def test_artifact_is_aggregate_continuous_and_reconciled():
    a = _artifact()
    assert a["daily"][0]["forecast_litres"] == 110.0
    assert a["daily"][0]["correction_litres"] == 10.0
    assert set(a["daily"][0]) <= {
        "date", "structural_litres", "cow_factor", "correction_litres",
        "forecast_litres", "n_cows", "taper_weight",
    }
    bad = _aggregate().assign(animal_key="A_PLACEHOLDER")
    with pytest.raises(ValueError, match="animal-level"):
        build_correction_artifact(ORIGIN, bad)


def test_hybrid_replaces_only_milk_calibrates_ranges_and_explains_exact_correction():
    new = hybrid_document(_doc(), _artifact())
    milk = {(r["grain"], r["horizon"]): r for r in new["outlook"] if r["series"] == "milk_litres"}
    assert milk[("day", 1)]["forecast"] == 110.0
    assert milk[("week", 1)]["forecast"] == 770.0
    assert milk[("month", 1)]["forecast"] == 3410.0
    assert milk[("day", 1)]["lower"] == 99.0 and milk[("day", 1)]["upper"] == 121.0
    herd = next(r for r in new["outlook"] if r["series"] == "milking")
    assert herd["forecast"] == 20.0
    assert new["heat"] == _doc()["heat"]
    correction = next(r for r in new["corrections"] if r["grain"] == "month")
    assert correction["structural"] + correction["correction"] == correction["forecast"]
    neural = next(r for r in new["attribution"] if r["factor"] == "cow_model_correction")
    assert neural["contribution"] == 8.0  # 10 L/day correction now minus 2 L/day at the anchor.
    assert new["model_version"] == HYBRID_VERSION
    assert new["cow_model"]["method"] == "structural_plus_cow_torch_v1"


def test_multi_origin_file_adapter(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    source_dir = tmp_path / "outlook" / "pfoi-1.2.0-dev"
    artifact_dir.mkdir()
    source_dir.mkdir(parents=True)
    (source_dir / "run_202401.json").write_text(json.dumps(_doc()))
    (artifact_dir / "cow_correction_202401.json").write_text(json.dumps(_artifact()))
    written = run(tmp_path, "pfoi-1.2.0-dev", artifact_dir, ["2024-01-01"])
    assert len(written) == 1 and written[0].exists()
    assert json.loads(written[0].read_text())["model_version"] == HYBRID_VERSION


def test_rejects_training_that_reaches_the_forecast_period():
    a = _artifact()
    a["trained_through"] = ORIGIN.isoformat()
    with pytest.raises(ValueError, match="leaks"):
        hybrid_document(_doc(), a)


def test_calibration_is_past_only_and_cli_persists_artifact(tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    errors = pd.DataFrame({
        "grain": ["daily"] * 10, "horizon": [1] * 10,
        "forecast": [100.0] * 10, "actual": [90.0] * 8 + [110.0, 500.0],
        "period_end": ["2023-12-01"] * 9 + ["2024-02-01"],
    })
    cells = calibration_from_errors(errors, ORIGIN)
    assert len(cells) == 1 and cells[0].n == 9
    path, err, artifacts = tmp_path / "path.csv", tmp_path / "errors.csv", tmp_path / "artifacts"
    _aggregate(days=31).to_csv(path, index=False)
    errors.to_csv(err, index=False)
    assert cli.main(["cow-torch-artifact", "--origin", ORIGIN.isoformat(), "--path", str(path),
                     "--errors", str(err), "--artifacts", str(artifacts), "--taper-days", "0"]) == 0
    saved = json.loads((artifacts / "cow_correction_202401.json").read_text())
    assert saved["calibration"][0]["n"] == 9
    assert "No animal rows" in capsys.readouterr().out


def test_artifact_command_explains_missing_upstream_path(tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    missing = tmp_path / "aggregate_path_202401.csv"
    assert cli.main(["cow-torch-artifact", "--origin", ORIGIN.isoformat(),
                     "--path", str(missing), "--artifacts", str(tmp_path / "artifacts")]) == 1
    message = capsys.readouterr().err
    assert "Notebook 6 currently creates historical evaluation predictions only" in message
    assert "Do not create a dummy CSV" in message


def _daily_doc(days=10):
    doc = _doc()
    doc["outlook"] = [
        _row("day", i + 1, d.date().isoformat(), 100.0)
        for i, d in enumerate(pd.date_range(ORIGIN, periods=days))
    ]
    return doc


def _origin_models():
    frame = pd.DataFrame({
        "cow_id": [1, 1, 2, 2],
        "date": pd.to_datetime(["2023-12-20", "2023-12-31", "2023-12-21", "2023-12-30"]),
        "period": ["validation"] * 4,
        "score_eligible": [True] * 4,
    })
    predictions = {
        "wood_mixed_grp": pd.Series([10.0, 10.0, 20.0, 20.0]).to_numpy(),
        "torch_mlp_small_grp": pd.Series([12.0, 11.0, 22.0, 22.0]).to_numpy(),
    }
    return AccuracyModels(frame, predictions, {})


def test_origin_factor_uses_latest_prediction_once_per_cow():
    estimate = estimate_origin_factor(
        _origin_models(), ORIGIN, "torch_mlp_small_grp", recent_days=28, min_cows=2,
    )
    assert estimate["n_cows"] == 2
    assert estimate["reference_model"] == "wood_mixed_grp"
    assert estimate["factor"] == pytest.approx(33.0 / 30.0)


def test_producer_fits_before_origin_and_outputs_only_aggregate_daily_rows():
    seen = {}

    def fake_fit(raw, **kwargs):
        seen["latest_raw"] = pd.to_datetime(raw["date"]).max().date()
        seen.update(kwargs)
        return _origin_models()

    raw = pd.DataFrame({"date": ["2023-01-01", "2023-12-31", "2024-01-02"]})
    artifact = produce_correction_artifact(
        _daily_doc(), raw, {}, ORIGIN,
        min_cows=2, taper_days=0, fit_fn=fake_fit,
    )
    assert seen["latest_raw"] < ORIGIN
    assert seen["validation_end"] == date(2023, 12, 31)
    assert seen["grains"] == ("daily",)
    assert seen["model_names"] == ("torch_mlp_small",)
    assert artifact["origin_estimate"]["weights_trained_through"] == "2023-10-08"
    assert artifact["daily"][0]["forecast_litres"] == pytest.approx(110.0)
    assert set(artifact["daily"][0]) <= {
        "date", "structural_litres", "cow_factor", "correction_litres",
        "forecast_litres", "n_cows", "taper_weight",
    }


def test_structural_daily_extraction_rejects_gaps():
    doc = _daily_doc(3)
    doc["outlook"][1]["target_period"] = "2024-01-03"
    with pytest.raises(ValueError, match="unique|continuous"):
        structural_daily_from_document(doc, ORIGIN)


def test_complete_structural_path_comes_from_aggregate_outlook_table():
    table = pd.DataFrame({
        "target_period": pd.date_range(ORIGIN, periods=5),
        "grain": "daily",
        "series": "herd_milk",
        "forecast": 100.0,
    })
    path = structural_daily_from_outlook(table, ORIGIN)
    assert len(path) == 5
    assert path["structural_litres"].sum() == 500.0
