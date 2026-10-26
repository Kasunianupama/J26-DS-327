"""Synthetic-only tests for the herd-milk PyTorch model (notebook 07).

PyTorch crashes on macOS in a process where LightGBM has trained, so the fitting tests
skip themselves if LightGBM is already loaded. Run this file on its own:
    .venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_herd_torch.py
"""
from __future__ import annotations

import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import herd_torch as h

needs_torch = pytest.mark.skipif("lightgbm" in sys.modules,
                                 reason="run test_herd_torch.py in its own pytest process")


def _daily(seed=3):
    return h.exclude_gap(h.synthetic_herd_daily(seed), h.gap_for("clean"))


def test_loader_builds_herd_day_table_from_source():
    from components.predictive_farm_intelligence.tests.synthetic import FakeHerdSource

    src = FakeHerdSource()
    d = h.load_herd_daily(src, date(2020, 1, 1), date(2020, 7, 1))
    assert len(d) == 182 and d.index.is_unique
    for c in ("litres", "ok", "per_cow", "milking", "calvings", "dry_offs", "dim_0-60",
              "parity_1", "thi_mean"):
        assert c in d
    assert d["ok"].any()
    assert d.loc[~d["ok"], "litres"].isna().all()
    shares = d[[f"dim_{b}" for b in h.DIM_SHARES]].sum(axis=1)
    assert np.allclose(shares.dropna(), 1.0)
    assert not set(h.FORBIDDEN_COLUMNS) & set(d.columns)


def test_gap_removes_milk_but_keeps_movement():
    raw = h.synthetic_herd_daily(3)
    d = h.exclude_gap(raw, h.gap_for("clean"))
    inside = d.loc["2023-01-01":"2023-12-31"]
    assert not inside["ok"].any() and inside["litres"].isna().all()
    assert inside["calvings"].sum() == raw.loc["2023-01-01":"2023-12-31", "calvings"].sum()


def test_contract_checks_pass_and_catch_implausible_yield():
    d = _daily()
    assert h.herd_contract_checks(d)["passed"].all()
    bad = d.copy()
    day = bad.index[bad["ok"]][10]
    bad.loc[day, "litres"] = 20 * bad.loc[day, "milking"]
    bad = h.finish_daily(bad)
    checks = h.herd_contract_checks(bad).set_index("check")
    assert not checks.loc["litres per milking cow in (0, 18] L", "passed"]


@pytest.mark.parametrize("grain", h.GRAINS)
def test_features_and_base_use_only_days_before_the_origin(grain):
    d = _daily()
    origin = pd.Timestamp("2021-03-01")
    changed = d.copy()
    after = changed.index >= origin
    for c in ("litres", "milking", "calvings", "dry_offs", "thi_mean", "dim_0-60"):
        changed.loc[after, c] = changed.loc[after, c] * 1.7
    changed = h.finish_daily(changed)
    a = h.build_table(d, h.asof_features(d), grain, rolling=False)
    b = h.build_table(changed, h.asof_features(changed), grain, rolling=False)
    ia = np.flatnonzero(a.meta["origin"] == origin)
    ib = np.flatnonzero(b.meta["origin"] == origin)
    assert len(ia) == len(ib) == 1
    pd.testing.assert_series_equal(a.X.iloc[ia[0]], b.X.iloc[ib[0]])
    for col in ("base", "persistence", "milking_projected"):
        assert a.meta[col].iloc[ia[0]] == b.meta[col].iloc[ib[0]]
    assert a.meta["actual"].iloc[ia[0]] != b.meta["actual"].iloc[ib[0]]


def test_monthly_periods_are_calendar_months_and_training_windows_roll():
    d = _daily()
    asof = h.asof_features(d)
    sc = h.build_table(d, asof, "monthly", rolling=False)
    assert (sc.meta["origin"].dt.day == 1).all()
    assert (sc.meta["period_end"] + pd.Timedelta(days=1)).dt.day.eq(1).all()
    tr = h.build_table(d, asof, "monthly", rolling=True)
    assert (tr.meta["period_days"] == 30).all() and len(tr.meta) > 10 * len(sc.meta)


def test_recalibration_uses_only_periods_ended_before_origin():
    meta = pd.DataFrame({
        "origin": pd.date_range("2021-01-01", periods=6, freq="D"),
        "period_end": pd.date_range("2021-01-01", periods=6, freq="D"),
        "actual": [110.0, 110.0, 110.0, 110.0, 500.0, 500.0], "scored": True})
    pred = np.full(6, 100.0)
    out, factor = h.recalibrate(meta, pred, "daily")
    assert factor[0] == 1.0                      # nothing before the first origin
    assert np.isclose(factor[1], 1.1)            # only day 1 known
    assert np.isclose(factor[4], 1.1)            # day 5 (500) not yet known
    assert factor[5] == h.RECAL_BOUNDS[1]        # clipped once 500 enters


def test_blocks_never_mix_train_validation_and_test():
    meta = pd.DataFrame({"origin": pd.to_datetime(["2021-01-01", "2021-01-08", "2021-02-01",
                                                   "2021-03-01"]),
                         "period_end": pd.to_datetime(["2021-01-07", "2021-01-14", "2021-02-07",
                                                       "2021-03-07"])})
    labels = h.block_labels(meta, date(2021, 1, 10), date(2021, 2, 10))
    assert list(labels) == ["train", "straddle", "validation", "test"]


@needs_torch
def test_fit_scores_every_candidate_on_the_same_periods():
    d = _daily()
    split = h.chronological_split(pd.Series(d.index[d["ok"]]), (0.75, 0.05, 0.20))
    m = h.fit_herd_models(d, split.train_end, split.validation_end,
                          params={"max_epochs": 3, "min_epochs": 1},
                          options={"ensemble": 1}, min_coverage=0.8)
    for name in ("persistence", "herd_structural", "herd_kalman", "torch_mlp_small",
                 "torch_mlp_large", "torch_mlp_nomove", "torch_gru", "torch_q50",
                 "torch_mlp_small_recal"):
        assert set(m.predictions[name]) == set(h.GRAINS), name
    s = h.score_herd(m, ("validation",))
    assert set(s["grain"]) >= {"daily", "weekly"}
    per = s.groupby("grain")["periods"].nunique()
    assert (per == 1).all()
    pers = s[s["model"] == "persistence"]
    assert np.allclose(pers["skill_vs_persistence_pct"], 0.0)
    imp = h.movement_importance(m, block="validation")
    assert set(imp["family"]) == set(h.FEATURE_FAMILIES)
    assert len(h.interval_coverage(m, "validation"))
    pooled = h.pool_metrics([s, s.assign(block="other")])
    assert np.allclose(pooled.set_index(["grain", "model"])["accuracy_pct"],
                       s.set_index(["grain", "model"]).loc[pooled.set_index(["grain", "model"]).index,
                                                         "accuracy_pct"])
