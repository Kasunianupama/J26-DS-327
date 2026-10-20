"""Honest intervals (ACI + quality bands) on SYNTHETIC error tables."""
from datetime import date

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.episodes import NORMAL, UNVERIFIED
from components.predictive_farm_intelligence.pfoi.error_tools import add_intervals
from components.predictive_farm_intelligence.pfoi.intervals import (
    aci_intervals, weighted_quantile,
)


def _weekly(n=400, sd=0.05, sd_after=None, after=date(2021, 1, 1), seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for o in pd.date_range("2016-01-04", periods=n, freq="W-MON"):
        s = (o.date() >= after and sd_after) or sd
        a = 100.0 * np.exp(rng.normal(0, s))
        rows.append(dict(origin=o.date(), grain="weekly", horizon=1, period_start=o.date(),
                         period_end=(o + pd.Timedelta(days=7)).date(), series="herd_milk",
                         model="milk_baseline", forecast=100.0, actual=a))
    return pd.DataFrame(rows)


def test_weighted_quantile_matches_plain_quantile_with_equal_weights():
    x = np.arange(101, dtype=float)
    assert abs(weighted_quantile(x, np.ones(101), 0.9) - np.quantile(x, 0.9)) < 1.0


def test_outcomes_after_the_origin_do_not_change_its_interval():
    e = _weekly()
    origin = date(2019, 6, 3)
    a = aci_intervals(e)
    e2 = e.copy()
    e2.loc[pd.to_datetime(e2["period_end"]).dt.date > origin, "actual"] *= 5
    b = aci_intervals(e2)
    row = lambda d: d[d["origin"] == origin][["lower80", "upper80", "lower90", "upper90"]].to_numpy()
    assert np.allclose(row(a), row(b))


def test_coverage_is_near_target_on_stationary_errors():
    out = aci_intervals(_weekly(n=500))
    assert abs(out["covered80"].mean() - 0.80) < 0.05
    assert abs(out["covered90"].mean() - 0.90) < 0.04


def test_keeps_coverage_after_the_noise_doubles_better_than_old_quantiles():
    e = _weekly(n=500, sd=0.03, sd_after=0.09)
    new = aci_intervals(e)
    old = add_intervals(e, quantiles=(0.05, 0.95))
    late = lambda d: d[pd.to_datetime(d["origin"]) >= "2021-01-01"]
    assert late(new)["covered90"].mean() > late(old)["covered"].mean() + 0.10
    assert late(new)["covered90"].mean() > 0.80


def test_intervals_widen_in_a_poor_record_band():
    e = _weekly(n=400, sd=0.03)
    rng = np.random.default_rng(1)
    bad = set(e["origin"].iloc[::3])  # every third origin had unverified records ...
    e.loc[e["origin"].isin(bad), "actual"] = 100.0 * np.exp(rng.normal(0, 0.09, len(bad)))  # ... and 3x the spread
    bands = {o: (UNVERIFIED if o in bad else NORMAL) for o in e["origin"]}
    out = aci_intervals(e, band_at_origin=bands)
    late = out[pd.to_datetime(out["origin"]) >= "2019-01-01"]
    width = (late["upper90"] - late["lower90"])
    ratio = width[late["origin_band"] == UNVERIFIED].mean() / width[late["origin_band"] == NORMAL].mean()
    assert ratio > 2.0
    assert late.loc[late["origin_band"] == UNVERIFIED, "covered90"].mean() > 0.8


def test_no_interval_before_enough_finished_errors():
    out = aci_intervals(_weekly(n=30), min_errors=12)
    assert out["lower80"].iloc[:12].isna().all()
    assert out["lower80"].iloc[-1] == out["lower80"].iloc[-1]  # set once history exists
