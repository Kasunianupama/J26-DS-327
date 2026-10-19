"""Synthetic forecasts only; no database access."""
from argparse import Namespace

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.milk_calibration import (
    MODEL, CalibrationConfig, calibrated_milk, comparison, run_command,
)

BASE = "milk_baseline_adaptive"


def forecasts(n=24, grain="monthly", horizon=3):
    origins = pd.date_range("2018-01-01", periods=n, freq="MS")
    return pd.DataFrame([
        dict(origin=o, period_start=o + pd.DateOffset(months=horizon-1),
             period_end=o + pd.DateOffset(months=horizon), grain=grain,
             horizon=horizon, series="herd_milk", model=BASE,
             forecast=125., actual=100., k_source="anchored:delpro",
             source="delpro", flags="", band="normal", lower90=90., upper90=150.)
        for o in origins
    ])


def test_constant_bias_improves_actual_errors_after_history():
    base = forecasts()
    revised = calibrated_milk(base, BASE)
    assert revised.iloc[0].forecast == 125
    assert revised.iloc[-1].forecast == pytest.approx(100)
    assert revised.iloc[-1].calibration_factor == pytest.approx(.8)
    assert "lower90" not in revised
    report = comparison(base, revised).set_index("candidate")
    assert report.loc["calibrated", "mae_litres"] < report.loc["existing", "mae_litres"]


def test_future_actuals_and_target_metadata_do_not_change_issued_forecast():
    base = forecasts()
    idx = 12
    expected = calibrated_milk(base, BASE).loc[idx, "forecast"]
    changed = base.copy()
    future = changed.period_end > changed.loc[idx, "origin"]
    changed.loc[future, "actual"] = 10000.
    changed.loc[future, "source"] = "shipment"
    changed.loc[future, "band"] = "unusable"
    assert calibrated_milk(changed, BASE).loc[idx, "forecast"] == expected


def test_completed_period_boundary_and_minimum_history():
    result = calibrated_milk(forecasts(), BASE)
    assert result.loc[7, "calibration_n"] == 5
    assert result.loc[7, "forecast"] == 125
    assert result.loc[8, "calibration_n"] == 6
    assert result.loc[8, "forecast"] == 100


@pytest.mark.parametrize("grain,horizon", [("daily", 14), ("weekly", 13), ("monthly", 1)])
def test_short_horizons_preserved(grain, horizon):
    base = forecasts(grain=grain, horizon=horizon)
    assert (calibrated_milk(base, BASE).forecast == base.forecast).all()


@pytest.mark.parametrize("change", ["source", "band", "stale"])
def test_unusable_history_does_not_calibrate(change):
    base = forecasts()
    cfg = CalibrationConfig()
    if change == "source":
        base.loc[:22, "source"] = "shipment"
    elif change == "band":
        base.loc[:22, "band"] = "unusable"
    else:
        cfg = CalibrationConfig(max_age_days=1)
    assert calibrated_milk(base, BASE, cfg).iloc[-1].forecast == 125


@pytest.mark.parametrize("actual,factor", [(0., .5), (1000., 1.5)])
def test_factor_bounds(actual, factor):
    base = forecasts()
    base["actual"] = actual
    assert calibrated_milk(base, BASE).iloc[-1].calibration_factor == factor


def test_shuffle_invariance():
    base = forecasts()
    expected = calibrated_milk(base, BASE).set_index("origin").forecast.sort_index()
    actual = calibrated_milk(base.sample(frac=1, random_state=1), BASE)
    pd.testing.assert_series_equal(expected, actual.set_index("origin").forecast.sort_index())


@pytest.mark.parametrize("quality", ["on", "off"])
def test_cli_synthetic_files_preserve_coverage_and_input(tmp_path, capsys, monkeypatch, quality):
    from components.predictive_farm_intelligence.pfoi.selection_report import FAMILIES
    from components.predictive_farm_intelligence.pfoi import selection_report
    days = pd.date_range("2017-01-01", "2022-12-31", freq="D")
    q = pd.DataFrame(dict(date=days.date, target_source="delpro", identified_share=.9,
                          gap=False, target_litres=100., milking=10., litres_per_cow=10.))
    def mocked_quality():
        assert quality == "on", "Quality off must not load database data"
        return q
    monkeypatch.setattr(selection_report, "load_quality", mocked_quality)
    tag = "synthetic_ad"
    original = {}
    for grain in ("monthly", "weekly"):
        data = forecasts(grain=grain)
        if grain == "weekly":
            data = pd.concat([data, forecasts(grain="daily", horizon=7)])
        path = tmp_path / f"milk_backtest_errors_{grain}_{tag}.csv"
        data.to_csv(path, index=False)
        original[path] = path.read_bytes()
    assert run_command(Namespace(tag=tag, base=BASE, out=tmp_path, quality=quality)) == 0
    for path, content in original.items():
        assert path.read_bytes() == content
    output = pd.read_csv(tmp_path / f"milk_backtest_errors_weekly_{tag}_maecalv1_q{quality}.csv")
    assert set(output.grain) == {"weekly", "daily"}
    assert set(output.model) == {MODEL}
    assert MODEL in FAMILIES["milk"][0]
    assert "mae_litres" in capsys.readouterr().out


def test_test_tag_rejected(tmp_path):
    with pytest.raises(ValueError, match="development"):
        run_command(Namespace(tag="synthetic_test", base=BASE, out=tmp_path, quality="off"))


def test_missing_dates_rejected():
    base = forecasts()
    base.loc[0, "period_end"] = pd.NaT
    with pytest.raises(ValueError, match="dates"):
        calibrated_milk(base, BASE)
