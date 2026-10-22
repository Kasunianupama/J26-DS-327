"""Direct ML forecaster on SYNTHETIC data only (no database, no Farm X data)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.data import DATA_START, LeakageError
from components.predictive_farm_intelligence.pfoi.ml_direct import (
    MLConfig, explain_groups, fit_predict, inverse, refit_date, run_ml_backtest, summary,
    training_mask, transform,
)
from components.predictive_farm_intelligence.pfoi.ml_features import (
    GESTATION_DAYS, MILK, _due, build_table, daily_frame, feature_origins, history_features,
    load_snapshot, load_snapshots,
)
from components.predictive_farm_intelligence.tests.synthetic import FakeHerdSource

CFG = EngineConfig()
END = date(2018, 7, 1)
CUTOFF = date(2018, 1, 1)
SERIES = (MILK, "milking", "calvings")
SMALL = MLConfig(n_estimators=30, min_train=50)


def _frame(src, end=END):
    return daily_frame(src.panel_daily(DATA_START, end), src.target_daily(DATA_START, end))


def _origins(start=date(2017, 1, 1), end=END):
    return [o for o in feature_origins(start, end)]


def test_due_days_follow_gestation():
    clock = pd.DataFrame({"gest": [250.0, np.nan, 300.0], "n": [2.0, 5.0, 1.0]})
    due = _due(clock)
    assert due[GESTATION_DAYS - 250 - 1] == 2.0
    assert due[0] == 1.0  # overdue pregnancies are expected at once
    assert due.sum() == 3.0  # open cows are not in the pipeline


def test_history_features_ignore_the_future():
    origin = CUTOFF
    a = history_features(_frame(FakeHerdSource()), origin)
    b = history_features(_frame(FakeHerdSource(cutoff=CUTOFF, future_scale=5.0)), origin)
    assert a is not None
    assert a.keys() == b.keys()
    for k in a:
        assert a[k] == b[k] or (pd.isna(a[k]) and pd.isna(b[k])), k


def test_history_needs_a_year():
    assert history_features(_frame(FakeHerdSource()), date(2016, 3, 7)) is None


def test_snapshot_leak_is_caught():
    with pytest.raises(LeakageError):
        load_snapshot(FakeHerdSource(leak="cells_on"), date(2017, 3, 6), CFG)


def test_table_rows_and_labels():
    src = FakeHerdSource()
    origins = _origins(date(2017, 1, 1), date(2017, 3, 1))
    snaps = load_snapshots(src, origins, CFG)
    meta, X = build_table(_frame(src), origins, SERIES, snaps, END)
    assert len(meta) == len(X) > 0
    assert set(meta["series"]) == set(SERIES)
    assert (pd.to_datetime(meta["period_end"]) <= pd.Timestamp(END)).all()
    assert (pd.to_datetime(meta["period_start"]) >= pd.to_datetime(meta["origin"])).all()
    assert {"due_cows_period", "fresh_cows_at_start", "milking_parity_1", "ly_ratio"} <= set(X.columns)
    # same features for every series at one origin x period
    one = X[(meta["origin"] == origins[0]) & (meta["horizon"] == 1) & (meta["grain"] == meta["grain"].iloc[0])]
    assert len(one.drop(columns="ly_ratio").drop_duplicates()) == 1


def test_training_mask_uses_finished_periods_only():
    src = FakeHerdSource()
    origins = _origins(date(2016, 9, 1), END)
    meta, _ = build_table(_frame(src), origins, (MILK,), None, END)
    refit = date(2017, 7, 1)
    m = training_mask(meta, refit)
    assert m.any()
    assert (pd.to_datetime(meta.loc[m, "period_end"]) <= pd.Timestamp(refit)).all()
    assert (pd.to_datetime(meta.loc[m, "origin"]) < pd.Timestamp(refit)).all()
    assert refit_date(date(2017, 8, 14), 3) == refit
    assert refit_date(date(2017, 7, 1), 3) == refit


def test_transform_round_trips():
    meta = pd.DataFrame({
        "kind": ["milk", "stock", "event"], "actual": [3000.0, 40.0, 4.0], "base": [100.0, 38.0, 2.0],
        "period_start": pd.to_datetime(["2017-01-01"] * 3), "period_end": pd.to_datetime(["2017-01-31"] * 3),
    })
    y = transform(meta)
    lgbm_y = y.copy()
    lgbm_y[2] = np.log(meta["actual"].iloc[2] / meta["base"].iloc[2])
    assert np.allclose(inverse(meta, lgbm_y, "ml_lgbm"), meta["actual"])
    ridge_y = y.copy()
    ridge_y[2] = np.log((4.0 + 0.5) / (2.0 + 0.5))
    assert np.allclose(inverse(meta, ridge_y, "ml_ridge"), meta["actual"])


def test_shap_groups_add_up():
    rng = np.random.default_rng(0)
    n = 400
    X = pd.DataFrame({"milk_r7_28": rng.normal(size=n), "due_cows_period": rng.normal(size=n),
                      "month_sin": rng.normal(size=n), "lead_days": rng.integers(0, 300, n).astype(float)})
    meta = pd.DataFrame({"kind": "milk", "base": 100.0, "origin": pd.Timestamp("2017-01-02"),
                         "period_start": pd.Timestamp("2017-02-01"), "period_end": pd.Timestamp("2017-03-01")},
                        index=X.index)
    y_true = 0.1 * X["milk_r7_28"] + 0.05 * X["due_cows_period"]
    meta["actual"] = 100.0 * 28 * np.exp(y_true)
    out, contrib = fit_predict(meta, X, meta, X, date(2017, 4, 1), SMALL, explain=True)
    groups = explain_groups(contrib)
    assert {"recent milk", "pregnancy pipeline", "season", "horizon", "baseline"} == set(groups.columns)
    raw = np.log(out["ml_lgbm"] / (100.0 * 28))
    assert np.allclose(groups.sum(axis=1), raw, atol=1e-6)


def test_event_series_without_any_event_falls_back_to_the_trailing_rate():
    """LightGBM's Poisson objective fails on all-zero labels; the forecast is then the base."""
    rng = np.random.default_rng(1)
    X = pd.DataFrame({"due_cows_period": rng.normal(size=100), "lead_days": rng.normal(size=100)})
    meta = pd.DataFrame({"kind": "event", "actual": 0.0, "base": 0.4,
                         "origin": pd.Timestamp("2016-10-03"), "period_start": pd.Timestamp("2016-11-01"),
                         "period_end": pd.Timestamp("2016-12-01")}, index=X.index)
    out, contrib = fit_predict(meta, X, meta, X, date(2017, 1, 1), SMALL, explain=True)
    assert contrib is None
    assert np.allclose(out["ml_lgbm"], 0.4)
    assert np.isfinite(out["ml_ridge"]).all()


def test_summary_counts_periods_without_events():
    """A day with no event and a forecast of 0.2 is an error of 0.2, not a skipped row."""
    e = pd.DataFrame({"series": "sales", "grain": "daily", "horizon": 1,
                      "origin": [date(2017, 1, 2), date(2017, 1, 9), date(2017, 1, 16)],
                      "model": "ml_lgbm", "actual": [0.0, 0.0, 1.0], "forecast": [0.2, 0.2, 0.6]})
    e["error"] = e["forecast"] - e["actual"]
    row = summary(e).iloc[0]
    assert row["n"] == 3
    assert row["bias_pct"] == pytest.approx(0.0)       # 1.0 forecast in total, 1 event
    assert row["accuracy"] == pytest.approx(1 - 0.8)   # |errors| 0.2 + 0.2 + 0.4 over 1 event
    assert row["within_10"] == 0.0                     # only the day with an event


def test_ridge_stays_inside_its_training_range():
    rng = np.random.default_rng(2)
    X = pd.DataFrame({"due_cows_period": rng.normal(size=200)})
    meta = pd.DataFrame({"kind": "stock", "base": 50.0, "origin": pd.Timestamp("2017-01-02"),
                         "period_start": pd.Timestamp("2017-02-01"), "period_end": pd.Timestamp("2017-03-01")},
                        index=X.index)
    meta["actual"] = 51.0 * np.exp(0.05 * X["due_cows_period"]) - 1
    far = pd.DataFrame({"due_cows_period": [1e6]})
    out, _ = fit_predict(meta, X, meta.iloc[:1], far, date(2017, 4, 1), SMALL)
    assert out["ml_ridge"][0] <= meta["actual"].max() + 1e-6


def _run(src):
    origins = {"monthly": [date(2017, 10, 1), date(2018, 1, 1), date(2018, 2, 1)],
               "weekly": [date(2017, 10, 2), date(2018, 1, 1)]}
    return run_ml_backtest(src, CFG, SMALL, origins, END, SERIES, benchmarks=True)


def test_backtest_runs_and_has_benchmarks():
    res = _run(FakeHerdSource())
    e = res.errors
    assert {"ml_lgbm", "ml_ridge", "persistence"} <= set(e["model"])
    assert set(e["grain"]) == {"monthly", "weekly", "daily"}
    ml = e[e["model"].str.startswith("ml_")]
    assert np.isfinite(ml["forecast"]).all() and (ml["forecast"] >= 0).all()
    assert {"lower", "upper", "covered", "error", "model_version"} <= set(e.columns)
    assert not {"kind", "base", "same_source"} & set(e.columns)
    assert len(res.importance) and "pregnancy pipeline" in res.importance.columns


def test_backtest_forecasts_ignore_data_after_the_origin():
    """Scaling every day from the cutoff changes nothing forecast before it."""
    a = _run(FakeHerdSource()).errors
    b = _run(FakeHerdSource(cutoff=CUTOFF, future_scale=5.0)).errors
    keys = ["origin", "grain", "horizon", "series", "model"]
    a = a[(a["model"].str.startswith("ml_")) & (pd.to_datetime(a["origin"]) < pd.Timestamp(CUTOFF))]
    b = b[(b["model"].str.startswith("ml_")) & (pd.to_datetime(b["origin"]) < pd.Timestamp(CUTOFF))]
    m = a.merge(b, on=keys, suffixes=("_a", "_b"))
    assert len(m) == len(a) > 0
    assert np.allclose(m["forecast_a"], m["forecast_b"])


def test_ablation_without_pipeline():
    res = run_ml_backtest(FakeHerdSource(), CFG, MLConfig(n_estimators=30, min_train=50, pipeline=False),
                          {"monthly": [date(2018, 1, 1)]}, END, (MILK,), benchmarks=False)
    assert set(res.errors["model"]) == {"ml_lgbm", "ml_ridge"}
    assert "pregnancy pipeline" not in res.importance.columns
    assert res.errors["model_version"].str.endswith("_nopipe").all()
