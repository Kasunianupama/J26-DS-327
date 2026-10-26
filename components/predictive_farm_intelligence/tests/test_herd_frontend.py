"""Synthetic-only tests for the frontend outputs of the combined herd milk model (notebook 09).

Run on its own (PyTorch must not share a process with LightGBM on macOS):
    .venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_herd_frontend.py
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import herd_frontend as F
from components.predictive_farm_intelligence.pfoi import herd_outlook as o
from components.predictive_farm_intelligence.pfoi import herd_torch as h

needs_torch = pytest.mark.skipif("lightgbm" in sys.modules,
                                 reason="run test_herd_frontend.py in its own pytest process")


@pytest.fixture(scope="module")
def daily():
    return h.exclude_gap(h.synthetic_herd_daily(11), h.gap_for("clean"))


def test_record_status_current_stale_and_withheld(daily):
    assert F.record_status(daily)["status"] == "current"
    stale = daily.copy()
    stale.loc[stale.index > "2026-08-20", "ok"] = False
    r = F.record_status(stale)
    assert r["status"] == "stale" and r["staleness_days"] >= 11 and not r["milk_withheld"]
    gone = daily.copy()
    gone.loc[gone.index > "2026-07-15", "ok"] = False
    r = F.record_status(gone)
    assert r["status"] == "withheld" and r["milk_withheld"] and r["reason_text"]
    assert {c["check"] for c in r["checks"]} == {"freshness", "completeness", "plausibility",
                                                 "source_agreement"}
    rows = F.withheld_rows(pd.Timestamp("2026-09-01"))
    assert {r["grain"] for r in rows} == {"day", "week", "month"}


def test_pad_future_keeps_herd_and_leaves_milk_missing(daily):
    p = F.pad_future(daily, 10)
    future = p[p.index > daily.index.max()]
    assert len(future) == 10 and not future["ok"].any() and future["litres"].isna().all()
    assert (future["milking"] == daily["milking"].iloc[-1]).all()
    assert future["calvings"].isna().all()


def test_reconciled_path_adds_up_across_grains():
    origin = pd.Timestamp("2026-09-01")
    months = pd.date_range(origin, periods=24, freq="MS")
    monthly = pd.DataFrame({"period_start": months, "forecast": np.linspace(2500, 2700, 24)})
    short = pd.DataFrame({"grain": ["daily", "weekly"], "period_start": [origin, pd.Timestamp("2026-09-07")],
                          "period_end": [origin, pd.Timestamp("2026-09-13")], "forecast": [2600.0, 2550.0]})
    path = F.reconcile_path(origin, monthly, short)
    per = F.path_periods(path, origin)
    assert len(per["daily"]) == 365 and len(per["weekly"]) == 52 and len(per["monthly"]) == 24
    assert np.isclose(path["litres"].iloc[0], 2600.0)                    # daily one-step kept
    assert np.isclose(path.set_index("date").loc["2026-09-07":"2026-09-13", "litres"].mean(), 2550.0)
    m = per["monthly"]
    assert np.allclose(m["forecast"].iloc[1:], monthly["forecast"].iloc[1:] * m["days"].iloc[1:])
    assert np.isclose(m["forecast"].iloc[0], path.loc[path["month"] == origin, "litres"].sum())
    w = per["weekly"].iloc[3]
    assert np.isclose(w["forecast"], path.set_index("date").loc[w["period_start"]:w["period_end"], "litres"].sum())


def test_milk_rows_bounds_flags_and_contract():
    origin = pd.Timestamp("2026-09-01")
    monthly = pd.DataFrame({"period_start": pd.date_range(origin, periods=24, freq="MS"),
                            "forecast": 2500.0})
    per = F.path_periods(F.reconcile_path(origin, monthly, pd.DataFrame(
        columns=["grain", "period_start", "period_end", "forecast"])), origin)
    bands = pd.DataFrame({"horizon": range(1, 25), "lower_log": -0.05, "upper_log": 0.06})
    markers = pd.DataFrame({"marker": ["significant_drop", "untested_from"], "horizon": [6, 12],
                            "meaning": ["", ""]})
    rec = {"status": "current"}
    rows = F.milk_rows(per, origin, bands, {"daily": (-0.1, 0.1, 50), "weekly": (-0.05, 0.05, 20)},
                       markers, rec, "test-version", None)
    assert (rows["lower"] <= rows["forecast"]).all() and (rows["forecast"] <= rows["upper"]).all()
    m = rows[rows["grain"] == "monthly"].set_index("horizon")
    assert m.loc[1, "quality_flag"] == "high" and m.loc[6, "quality_flag"] == "moderate"
    assert m.loc[12, "quality_flag"] == "limited"
    assert m.loc[12, "status"] == "cannot be validated with current data"
    d = rows[rows["grain"] == "daily"].iloc[0]
    assert d["upper"] / d["forecast"] > np.exp(0.06)         # daily wider than monthly
    attr = pd.DataFrame({"origin_date": origin.date(), "target_period": origin.date(),
                         "grain": "monthly", "series": "herd_milk", "factor": "herd_size",
                         "contribution": 1.0, "kind": "forecast", "model_version": "v",
                         "core_version": None}, index=[0])
    c1o, c1a = F.c1_tables(rows, attr)
    assert set(c1o["series"]) == {"herd_milk"} and len(c1a) == 1


def test_past_attribution_is_exact(daily):
    past = F.past_attribution(daily, months=6)
    mth = daily.resample("MS").agg({"litres": "mean", "ok": "mean"})
    for tp, g in past.groupby("target_period"):
        t = pd.Timestamp(tp)
        prev = t - pd.DateOffset(months=1)
        assert np.isclose(g["contribution"].sum(), mth.loc[t, "litres"] - mth.loc[prev, "litres"])


def test_herd_path_errors_and_rows(daily):
    runs = o.month_starts("2025-06-01", "2026-09-01")
    paths = o.synthetic_engine_paths(daily, runs, horizon_days=200)
    err = F.herd_path_errors(daily, paths, max_h=6)
    assert set(err["series"]) == set(F.STOCK_SERIES) | set(F.EVENT_SERIES)
    bands = F.herd_bands(err, 6)
    rows = F.herd_rows(paths, pd.Timestamp("2026-09-01"), bands, {"status": "current"},
                       pd.DataFrame(columns=["marker", "horizon"]), "v", None, max_h=6)
    assert len(rows) == 6 * len(set(err["series"]))
    ok = rows.dropna(subset=["lower"])
    assert (ok["lower"] <= ok["forecast"] + 1e-9).all() and (ok["forecast"] <= ok["upper"] + 1e-9).all()


@needs_torch
def test_forecast_attribution_adds_up_exactly_with_a_network(daily):
    paths = o.MilkingPaths()
    origin = o.next_origin(daily)
    m = o.fit_outlook(daily, daily.index.max().date(), paths, [origin],
                      params={"max_epochs": 3, "min_epochs": 1}, ensemble=1, max_h=6,
                      use_ablation=False, use_quantile=False)
    assert "torch_mlp_horizon" in m.nets
    phi, out, ref = F.shapley_groups(m.nets["torch_mlp_horizon"], m.features)
    assert np.allclose(phi.sum(axis=1), out - ref)
    monthly = m.meta[["period_start"]].assign(forecast=m.predictions["torch_mlp_horizon"])
    per = F.path_periods(F.reconcile_path(origin, monthly, pd.DataFrame(
        columns=["grain", "period_start", "period_end", "forecast"])), origin)
    recent = 2500.0
    attr = F.outlook_attribution(m, "torch_mlp_horizon", origin, recent, per["monthly"])
    level = attr.groupby("target_period")["contribution"].sum().cumsum().to_numpy() + recent
    assert np.allclose(level, per["monthly"]["mean"].to_numpy())
    assert set(attr["factor"]) <= {"herd_size", "stage_mix", "parity_mix", "pregnancy_mix",
                                   "yield_level", "thi", "mastitis", "cow_model_correction",
                                   "residual"}


def test_partly_recorded_months_are_shown_as_estimates_not_scored(daily):
    d = daily.copy()
    month = (d.index >= "2021-03-01") & (d.index < "2021-04-01")
    d.loc[month & (d.index.day <= 10), "ok"] = False          # 10 of 31 days missing
    d.loc[~d["ok"], "litres"] = np.nan
    d = h.finish_daily(d)
    a = F.actual_rows(d)
    row = a[(a["series"] == "milk_litres") & (a["grain"] == "month") & (a["period"] == "2021-03-01")].iloc[0]
    assert not row["scoreable"] and row["value"] is not None and abs(row["coverage"] - 21 / 31) < 1e-3
    expected = d.loc[month, "litres"].mean() * 31
    assert np.isclose(row["value"], expected)
    d.loc[month & (d.index.day <= 20), "ok"] = False          # 20 of 31 missing: below half
    d = h.finish_daily(d)
    a = F.actual_rows(d)
    row = a[(a["series"] == "milk_litres") & (a["grain"] == "month") & (a["period"] == "2021-03-01")].iloc[0]
    assert row["value"] is None or pd.isna(row["value"])
