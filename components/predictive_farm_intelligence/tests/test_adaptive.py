"""Layer 1 adaptive correction on SYNTHETIC error tables."""
from datetime import date

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.adaptive import (
    AdaptiveConfig, adaptive_corrected, level_at,
)
from components.predictive_farm_intelligence.pfoi.error_tools import bias_corrected

SHIFT = date(2020, 1, 1)


def _errors(horizons=(1,), n=60, shift_to=0.8, noise=0.01, seed=0, skip=(), noise_by_h=None):
    """Monthly origins from 2017; actual = 100 until SHIFT, then 100 * shift_to."""
    rng = np.random.default_rng(seed)
    rows = []
    for o in pd.date_range("2017-01-01", periods=n, freq="MS"):
        if o.date() in skip:
            continue
        for h in horizons:
            s = o + pd.DateOffset(months=h - 1)
            e = s + pd.DateOffset(months=1)
            sd = (noise_by_h or {}).get(h, noise)
            a = 100.0 * (shift_to if s.date() >= SHIFT else 1.0) * (1 + rng.normal(0, sd))
            rows.append(dict(origin=o.date(), grain="monthly", horizon=h, period_start=s.date(),
                             period_end=e.date(), series="milking", model="herd_engine",
                             forecast=100.0, actual=a))
    df = pd.DataFrame(rows)
    df["error"] = df["forecast"] - df["actual"]
    return df


def _acc(rows):
    return 1 - (rows["forecast"] - rows["actual"]).abs().sum() / rows["actual"].sum()


def test_outcomes_after_the_origin_do_not_change_its_correction():
    e = _errors(horizons=(1, 3))
    origin = date(2019, 6, 1)
    a = adaptive_corrected(e, "herd_engine")
    e2 = e.copy()
    late = pd.to_datetime(e2["period_end"]).dt.date > origin
    e2.loc[late, "actual"] *= 3
    b = adaptive_corrected(e2, "herd_engine")
    pick = lambda d: d[d["origin"] == origin].sort_values("horizon")["forecast"].to_numpy()
    assert np.allclose(pick(a), pick(b))


def test_reacts_to_a_level_shift_faster_than_two_year_mean_correction():
    e = _errors()
    ad = adaptive_corrected(e, "herd_engine")
    bc = bias_corrected(e, base_model="herd_engine")
    win = lambda d: d[(pd.to_datetime(d["origin"]) >= "2020-03-01") & (pd.to_datetime(d["origin"]) < "2020-07-01")]
    assert _acc(win(ad)) > _acc(win(bc)) + 0.05
    assert _acc(win(ad)) > 0.95


def test_pooled_level_corrects_noisy_long_horizons_from_short_horizon_errors():
    # long-horizon errors are much noisier, so on their own they move the level slowly
    e = _errors(horizons=(1, 12), n=48, noise_by_h={1: 0.01, 12: 0.15})
    origin = date(2020, 4, 1)  # three finished post-shift months at both horizons
    pooled = adaptive_corrected(e, "herd_engine", cfg=AdaptiveConfig(pooled=True))
    per_h = adaptive_corrected(e, "herd_engine", cfg=AdaptiveConfig(pooled=False))
    f12 = lambda d: float(d[(d["origin"] == origin) & (d["horizon"] == 12)]["forecast"].iloc[0])
    assert f12(pooled) < 88 < f12(per_h)


def test_level_fades_towards_zero_after_a_long_gap():
    e = _errors(n=42)  # last finished error ends 2020-07-01
    ends = pd.to_datetime(e["period_end"]).to_numpy()
    y = (e["actual"] / e["forecast"] - 1).to_numpy()
    hz = e["horizon"].to_numpy()
    cfg = AdaptiveConfig(tau_days=180)
    near = level_at(ends, y, hz, np.datetime64("2020-07-01"), cfg)
    far = level_at(ends, y, hz, np.datetime64("2022-01-01"), cfg)
    assert near < -0.1 and abs(far) < abs(near) / 5
    no_tau = level_at(ends, y, hz, np.datetime64("2022-01-01"), AdaptiveConfig(tau_days=None))
    assert no_tau < -0.1


def test_no_correction_with_too_few_finished_errors():
    e = _errors(n=8)
    ad = adaptive_corrected(e, "herd_engine", cfg=AdaptiveConfig(min_obs=6))
    first = ad[pd.to_datetime(ad["origin"]) < "2017-07-01"]
    assert np.allclose(first["forecast"], 100.0)
    assert set(ad["model"]) == {"herd_engine_adaptive"}


def test_label_names_the_settings():
    assert AdaptiveConfig().label() == "pq0.1t365z3"
    assert AdaptiveConfig(pooled=False, tau_days=None, q30=0.5).label() == "hq0.5tnz3"
