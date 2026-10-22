"""pfoi-1.2.1-dev gate confidence flag and gate-conditional intervals, on SYNTHETIC data."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.gate_intervals import (
    KEYS, attach_gate, build_121, interval_rule, interval_scores, mondrian_intervals,
)
from components.predictive_farm_intelligence.tests.test_gate import _daily, _errors, _unstable


@pytest.fixture(scope="module")
def case():
    e = _errors(_daily())
    milk = e[e["model"] == "milk_baseline_adaptive"].reset_index(drop=True)
    probs = milk[KEYS].copy()
    probs = probs[pd.to_datetime(probs["origin"]).dt.year >= 2019]
    probs["p_logistic"] = [0.9 if _unstable(o) else 0.1 for o in probs["origin"]]
    return milk, probs


def test_point_forecasts_are_unchanged_and_version_is_set(case):
    milk, probs = case
    out = build_121(milk, probs)
    m = out.merge(milk[KEYS + ["forecast"]], on=KEYS, suffixes=("", "_120"))
    np.testing.assert_array_equal(m["forecast"].to_numpy(), m["forecast_120"].to_numpy())
    assert set(out["model_version"]) == {"pfoi-1.2.1-dev"}


def test_flag_falls_back_to_the_origin_mean_and_stays_missing_without_a_gate(case):
    milk, probs = case
    p = probs[~((probs["grain"] == "weekly") & (probs["horizon"] == 13))]
    r = attach_gate(milk, p).set_index(KEYS)
    row = milk[(milk["grain"] == "weekly") & (milk["horizon"] == 13)
               & (pd.to_datetime(milk["origin"]).dt.year == 2021)].iloc[0]
    k = (row["grain"], int(row["horizon"]), row["origin"], row["period_start"])
    assert np.isfinite(r.loc[k, "p_gate"])                   # from the other weekly horizons
    early = r[pd.to_datetime(r.index.get_level_values("origin")).year < 2019]
    assert early["confidence"].isna().all() and early["p_gate"].isna().all()


def test_intervals_use_only_errors_finished_before_the_forecast_date(case):
    milk, probs = case
    a = mondrian_intervals(attach_gate(milk.assign(series="herd_milk"), probs))
    origin = date(2021, 6, 7)
    m2 = milk.copy()
    later = pd.to_datetime(m2["period_end"]).dt.date > origin
    m2.loc[later, "actual"] *= 2
    b = mondrian_intervals(attach_gate(m2.assign(series="herd_milk"), probs))
    sel = lambda f: f[f["origin"] == origin].set_index(KEYS).sort_index()  # noqa: E731
    for c in ("lo_0.9", "hi_0.9", "plo_0.9", "phi_0.9"):
        np.testing.assert_allclose(sel(a)[c].to_numpy(dtype=float), sel(b)[c].to_numpy(dtype=float))


def test_gate_conditional_ranges_fit_each_regime_better_than_pooled(case):
    milk, probs = case
    out = build_121(milk, probs)
    s = interval_scores(out, by=("confidence",)).set_index("confidence")
    # unstable forecasts err about 15 %, stable ones about 3 %: pooled ranges under-cover the first
    # and are too wide for the second; ranges calibrated per flag fit both
    assert abs(s.loc["low", "cov90_gate"] - 0.9) < abs(s.loc["low", "cov90_pooled"] - 0.9)
    assert s.loc["normal", "width90_gate"] < s.loc["normal", "width90_pooled"]
    assert s.loc["normal", "cov90_gate"] >= 0.85
    # cold start: until 19 earlier low-confidence errors exist, those rows fall back to the pooled
    # range, so low-confidence coverage stays just under 0.80 here (0.795) even with a perfect gate;
    # the pre-registered rule is applied unchanged to the real run
    checks, _ = interval_rule(s.reset_index())
    c = checks.set_index("check")
    assert c.loc["low: coverage closer to 0.90 than pooled", "passed"]
    assert c.loc["normal: width at most 10% above pooled", "passed"]
    assert 0.75 < c.loc["low: coverage >= 0.8", "value"] < 0.85
    assert "origin" not in s.columns


def test_interval_rule_fails_when_low_confidence_coverage_is_poor():
    s = pd.DataFrame([dict(confidence="low", cov90_gate=0.70, cov90_pooled=0.60, width90_gate=0.4, width90_pooled=0.3),
                      dict(confidence="normal", cov90_gate=0.9, cov90_pooled=0.95, width90_gate=0.1, width90_pooled=0.12),
                      dict(confidence="all", cov90_gate=0.86, cov90_pooled=0.9, width90_gate=0.2, width90_pooled=0.2)])
    checks, keep = interval_rule(s)
    assert not keep
    assert not checks.set_index("check").loc["low: coverage >= 0.8", "passed"]
