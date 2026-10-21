"""Milk error split (pfoi/error_split.py) on SYNTHETIC backtest rows."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.error_split import join, summarise


def _pair(cow_err, yield_err, n=20, grain="monthly", horizon=6, band="normal"):
    """n periods: recorded 100 cows x 10 L x 30 days; forecasts off by the given ratios."""
    milk, herd = [], []
    for i in range(n):
        o = date(2018, 1, 1) + timedelta(days=31 * i)
        s, e = o + timedelta(days=150), o + timedelta(days=180)
        common = dict(block="development", grain=grain, horizon=horizon, origin=o, period_start=s, period_end=e)
        cows_f = 100 * (1 + cow_err(i))
        milk.append(dict(common, series="herd_milk", model="milk_baseline_adaptive", band=band,
                         forecast=cows_f * 10 * (1 + yield_err(i)) * 30, actual=100 * 10 * 30.0))
        herd.append(dict(common, series="milking", model="herd_engine", forecast=cows_f, actual=100.0))
    return pd.DataFrame(milk), pd.DataFrame(herd)


def test_parts_add_up_exactly():
    m, h = _pair(lambda i: 0.05 * np.sin(i), lambda i: -0.03 * np.cos(i))
    j = join(m, h, "milk_baseline_adaptive")
    assert len(j) == 20
    assert np.allclose(j["e_milk"], j["e_cows"] + j["e_yield"])
    assert np.allclose(j["yield_actual"], 10.0)


def test_ceilings_identify_the_part_to_fix():
    # cows 20 % too high, yield exact -> milk 20 % off; exact cows would fix every period
    m, h = _pair(lambda i: 0.20, lambda i: 0.0)
    s = summarise(join(m, h, "milk_baseline_adaptive")).iloc[0]
    assert s["within_10"] == 0.0 and s["within_10_if_cows_exact"] == 1.0
    assert s["within_10_if_yield_exact"] == 0.0
    assert s["cow_share_of_sq_error"] == pytest.approx(1.0)
    assert s["bias_cows_pct"] == pytest.approx(0.20)


def test_offsetting_errors_show_negative_correlation():
    m, h = _pair(lambda i: 0.1 * ((-1) ** i), lambda i: -0.08 * ((-1) ** i))
    s = summarise(join(m, h, "milk_baseline_adaptive")).iloc[0]
    assert s["corr_cows_yield"] < -0.9
    assert s["within_10"] == 1.0  # the two parts cancel


def test_unverified_periods_are_separate_and_other_models_ignored():
    m1, h1 = _pair(lambda i: 0.0, lambda i: 0.0, n=5)
    m2, h2 = _pair(lambda i: 0.0, lambda i: 0.5, n=5, band="unverified")
    m2["origin"] = m2["origin"].map(lambda d: d.replace(year=2021))
    h2["origin"] = h2["origin"].map(lambda d: d.replace(year=2021))
    m = pd.concat([m1, m2, m1.assign(model="persistence", forecast=1.0)])
    s = summarise(join(m, pd.concat([h1, h2]), "milk_baseline_adaptive")).set_index("trust")
    assert s.loc["trusted", "n"] == 5 and s.loc["unverified_or_gap", "n"] == 5
    assert s.loc["trusted", "within_10"] == 1.0


def test_cli_reads_tagged_files(tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    m, h = _pair(lambda i: 0.2, lambda i: 0.0)
    m.drop(columns="band").to_csv(tmp_path / "milk_backtest_errors_monthly_T.csv", index=False)
    h.to_csv(tmp_path / "herd_backtest_errors_monthly_H.csv", index=False)
    rc = cli.main(["milk-error-split", "--milk-tag", "T", "--herd-tag", "H", "--quality", "off",
                   "--out", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "within_10_if_cows_exact" in out and "cow_share_of_sq_error" in out


def test_patterns_find_a_seasonal_yield_error():
    from components.predictive_farm_intelligence.pfoi.error_split import patterns

    m, h = _pair(lambda i: 0.0, lambda i: 0.0, n=36)
    starts = pd.to_datetime(m["period_start"]).dt.month
    m["forecast"] = m["forecast"] * np.where(starts.isin([6, 7, 8]), 1.2, 1.0)  # too high in Jun-Aug
    pt = patterns(join(m, h, "milk_baseline_adaptive"))
    col = pt["month"]["monthly h6"]
    assert col.loc[[6, 7, 8]].round(6).eq(0.2).all() and col.drop([6, 7, 8]).abs().max() < 1e-9
    assert pt["year_n"]["monthly h6"].sum() == 36
