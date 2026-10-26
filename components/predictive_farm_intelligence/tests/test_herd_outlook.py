"""Synthetic-only tests for the two-year herd milk outlook (notebook 07, section 9).

Run on its own (PyTorch must not share a process with LightGBM on macOS):
    .venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_herd_outlook.py
"""
from __future__ import annotations

import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import herd_outlook as o
from components.predictive_farm_intelligence.pfoi import herd_torch as h

needs_torch = pytest.mark.skipif("lightgbm" in sys.modules,
                                 reason="run test_herd_outlook.py in its own pytest process")


def _daily(seed=5):
    return h.exclude_gap(h.synthetic_herd_daily(seed), h.gap_for("clean"))


def test_score_rows_are_calendar_months_up_to_24_ahead():
    d = _daily()
    t = o.horizon_table(d, h.asof_features(d), o.MilkingPaths(), "score",
                        origins=[pd.Timestamp("2021-03-01")])
    assert list(t.meta["horizon"]) == list(range(1, 25))
    assert t.meta["period_start"].iloc[0] == pd.Timestamp("2021-03-01")
    assert t.meta["period_start"].iloc[23] == pd.Timestamp("2023-02-01")
    assert (t.meta["period_end"] + pd.Timedelta(days=1)).dt.day.eq(1).all()


def test_origin_after_the_data_end_gives_a_future_path():
    d = _daily()
    origin = o.next_origin(d)
    assert origin == pd.Timestamp("2026-09-01")
    t = o.horizon_table(d, h.asof_features(d), o.MilkingPaths(), "score", origins=[origin])
    assert len(t.meta) == 24 and t.meta["actual"].isna().all()
    assert t.meta["has_base"].all()


@pytest.mark.parametrize("horizon", [1, 6, 24])
def test_inputs_use_only_days_before_the_origin(horizon):
    d = _daily()
    origin = pd.Timestamp("2021-06-01")
    changed = d.copy()
    after = changed.index >= origin
    for c in ("litres", "milking", "calvings", "dry_offs", "thi_mean"):
        changed.loc[after, c] = changed.loc[after, c] * 1.6
    changed = h.finish_daily(changed)
    a = o.horizon_table(d, h.asof_features(d), o.MilkingPaths(), "score", origins=[origin])
    b = o.horizon_table(changed, h.asof_features(changed), o.MilkingPaths(), "score",
                        origins=[origin])
    k = horizon - 1
    pd.testing.assert_series_equal(a.X.iloc[k], b.X.iloc[k])
    assert a.meta["base"].iloc[k] == b.meta["base"].iloc[k]


def test_engine_path_from_the_synthetic_source():
    from components.predictive_farm_intelligence.tests.synthetic import FakeHerdSource

    paths = o.engine_paths(FakeHerdSource(), [date(2020, 1, 1)], horizon_days=90)
    assert list(paths.runs) == [pd.Timestamp("2020-01-01")]
    f = paths.runs[pd.Timestamp("2020-01-01")]
    assert len(f) == 90 and (f["milking"] > 0).all()
    assert f["fresh"].between(0, 1).all()
    assert len(o.engine_path_summary(paths)) == 1


def test_engine_path_is_used_where_a_run_covers_the_month():
    d = _daily()
    days = pd.date_range("2021-01-01", periods=120)
    run = pd.DataFrame({"milking": np.linspace(300, 330, 120), "calvings": 1.0,
                        "dry_offs": 0.5, "fresh": 0.2}, index=days)
    paths = o.MilkingPaths("engine", {days[0]: run})
    t = o.horizon_table(d, h.asof_features(d), paths, "score", origins=[days[0]], max_h=6)
    covered = t.X["path_engine"].to_numpy() == 1
    assert covered[:3].all() and not covered[4:].any()   # 120 days cover months 1-3
    assert t.X["path_ratio"].iloc[1] > 1.0                # milking rises along the path
    assert np.isclose(t.X["path_fresh"].iloc[0], 0.2)


def test_bounds_widen_with_horizon_and_contain_the_forecast():
    rng = np.random.default_rng(0)
    rows = []
    for hz in range(1, 7):
        for _ in range(8):
            act = 1000.0
            rows.append({"model": "m", "horizon": hz, "actual": act,
                         "forecast": act * np.exp(rng.normal(0, 0.02 * hz))})
    bands = o.error_bands(pd.DataFrame(rows), "m")
    assert (np.diff(bands["upper_log"]) >= -1e-12).all()
    assert (np.diff(bands["lower_log"]) <= 1e-12).all()
    assert (bands["lower_log"] <= 0).all() and (bands["upper_log"] >= 0).all()
    assert set(bands.loc[bands["horizon"] <= 6, "status"]) == {"measured"}
    assert set(bands.loc[bands["horizon"] > 6, "status"]) == {"extrapolated"}


def test_markers_find_the_drop_the_85_rule_and_untested_horizons():
    acc = pd.DataFrame({"model": "m", "horizon": range(1, 25),
                        "periods": [10] * 8 + [1] * 16,
                        "accuracy_pct": [97, 97, 96, 95, 92, 90, 88, 86] + [np.nan] * 16,
                        "within_10pct": [100, 100, 90, 80, 70, 60, 50, 40] + [np.nan] * 16,
                        "skill_vs_persistence_pct": [20, 15, 10, 5, 2, -1, -3, -5] + [np.nan] * 16})
    mk = o.horizon_markers(acc, "m").set_index("marker")["horizon"].to_dict()
    assert mk == {"significant_drop": 7, "below_85pct_rule": 4,
                  "no_skill_vs_persistence": 6, "untested_from": 9}


@needs_torch
def test_fit_backtest_and_outlook_end_to_end():
    d = _daily()
    fk = {"params": {"max_epochs": 3, "min_epochs": 1}, "ensemble": 1}
    cuts = h.equal_day_cuts(d, date(2026, 8, 31), 3)
    errors = o.horizon_backtest(d, cuts, date(2026, 8, 31), o.MilkingPaths(), fk)
    assert set(errors["model"]) >= {"persistence", "herd_structural", "torch_mlp_horizon"}
    acc = o.horizon_accuracy(errors)
    assert set(acc["horizon"]) == set(range(1, 25))
    bands = o.error_bands(errors, "torch_mlp_horizon")
    markers = o.horizon_markers(acc, "torch_mlp_horizon")
    live = o.fit_outlook(d, d.index.max().date(), o.MilkingPaths(), [o.next_origin(d)], **fk)
    out = o.build_outlook(live, "torch_mlp_horizon", bands, markers)
    assert len(out) == 24 and (out["lower"] <= out["forecast"]).all()
    assert (out["forecast"] <= out["upper"]).all()
    assert out["forecast"].gt(0).all()


def test_choose_models_keeps_best_and_best_machine_learning():
    pooled = pd.DataFrame({"model": ["persistence", "herd_structural", "torch_q_horizon", "torch_mlp_horizon"],
                           "accuracy_pct": [99.0, 97.0, 95.0, 96.0]})
    c = o.choose_models(pooled)
    assert c == {"best": "herd_structural", "best_ml": "torch_mlp_horizon",
                 "models": ["herd_structural", "torch_mlp_horizon"]}
    c = o.choose_models(pooled.assign(accuracy_pct=[99.0, 90.0, 95.0, 96.0]))
    assert c["best"] == c["best_ml"] == "torch_mlp_horizon" and c["models"] == ["torch_mlp_horizon"]
