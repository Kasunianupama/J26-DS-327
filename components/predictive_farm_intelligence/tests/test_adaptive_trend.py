"""Damped-trend adaptive correction (pfoi-1.2.1-dev) on SYNTHETIC error tables."""
from dataclasses import asdict
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.adaptive import (
    AdaptiveConfig, TrendConfig, adaptive_corrected, damped_gain, level_at, level_trend_at,
)
from components.predictive_farm_intelligence.pfoi.hit_rate import hit_rates, keep_rule, year_table
from components.predictive_farm_intelligence.pfoi.nested_cv import choose_trend_by_year

CFG = AdaptiveConfig(q30=0.1, tau_days=365.0, z_reset=3.0, pooled=False)  # the pfoi-1.2.0-dev setting
GRID = [TrendConfig(p, q) for p in (0.8, 0.9, 0.95) for q in (0.01, 0.05)]


def _errors(slope=0.0, horizons=(1, 3, 6, 12), n=84, noise=0.02, seed=0, decline_months=24, shift=None):
    """Monthly origins 2017-2023; base forecast flat at 100. From 2020-01 the actual falls by
    ``slope`` per month for ``decline_months`` months, then stays flat (yield per cow drift).
    ``shift``: (date, factor) step change, for the break reset."""
    rng = np.random.default_rng(seed)
    rows = []
    for o in pd.date_range("2017-01-01", periods=n, freq="MS"):
        for h in horizons:
            s = o + pd.DateOffset(months=h - 1)
            e = s + pd.DateOffset(months=1)
            m = (s.year - 2020) * 12 + s.month - 1
            a = 100.0 * (1 - slope * min(max(m, 0), decline_months)) * (1 + rng.normal(0, noise))
            if shift and s.date() >= shift[0]:
                a *= shift[1]
            rows.append(dict(origin=o.date(), grain="monthly", horizon=h, period_start=s.date(),
                             period_end=e.date(), series="herd_milk", model="milk_baseline",
                             forecast=100.0, actual=a))
    df = pd.DataFrame(rows)
    df["error"] = df["forecast"] - df["actual"]
    return df


def _arrays(e):
    ends = pd.to_datetime(e["period_end"]).to_numpy()
    y = np.clip((e["actual"] / e["forecast"] - 1).to_numpy(), -0.9, 3.0)
    return ends, y, e["horizon"].to_numpy(dtype=int)


def _ape(d):
    return (d["forecast"] - d["actual"]).abs() / d["actual"]


def _by_year(d, f):
    return f(d).groupby(pd.to_datetime(d["origin"]).dt.year).mean()


# --- off setting reproduces today's milk_baseline_adaptive exactly -------------------------

@pytest.mark.parametrize("cfg", [CFG, AdaptiveConfig(), AdaptiveConfig(tau_days=None, q30=0.5)])
def test_phi_zero_filter_equals_the_plain_level_bit_for_bit(cfg):
    e = _errors(slope=0.01, shift=(date(2022, 6, 1), 0.7))  # includes break resets
    ends, y, hz = _arrays(e)
    for o in pd.date_range("2017-03-01", "2024-01-01", freq="MS").to_numpy():
        x, b = level_trend_at(ends, y, hz, o, cfg, TrendConfig(phi=0.0, q_trend=0.05))
        assert x == level_at(ends, y, hz, o, cfg) and b == 0.0


def test_trend_off_or_phi_zero_gives_identical_adaptive_rows():
    e = _errors(slope=0.01)
    today = adaptive_corrected(e, "milk_baseline", cfg=CFG)
    for trend in (None, TrendConfig(phi=0.0), TrendConfig(phi=0.0, q_trend=1.0)):
        again = adaptive_corrected(e, "milk_baseline", cfg=CFG, trend=trend)
        pd.testing.assert_frame_equal(today, again)
        assert set(again["model"]) == {"milk_baseline_adaptive"}


def test_phi_one_is_not_allowed_and_frozen_config_is_unchanged():
    with pytest.raises(ValueError):
        TrendConfig(phi=1.0)
    with pytest.raises(ValueError):
        TrendConfig(phi=-0.1)
    # the trend lives in its own config, so the pfoi-1.0.0 / 1.1.0 hashes keep their inputs
    assert set(asdict(CFG)) == {"q30", "tau_days", "z_reset", "pooled", "min_obs"}
    assert CFG.label() == "hq0.1t365z3"
    assert TrendConfig(0.9, 0.05).label() == "d0.9b0.05"


def test_damped_gain():
    assert damped_gain(0, 0.9) == 0 and damped_gain(300, 0.0) == 0
    assert damped_gain(30, 0.9) == pytest.approx(0.9)
    assert damped_gain(60, 0.9) == pytest.approx(0.9 + 0.81)
    assert damped_gain(1e6, 0.9) == pytest.approx(9.0)  # bounded: phi / (1 - phi)


# --- no future errors ------------------------------------------------------------------------

def test_outcomes_after_the_origin_do_not_change_the_trend_correction():
    e = _errors(slope=0.01)
    origin = date(2021, 3, 1)
    t = TrendConfig(0.9, 0.05)
    a = adaptive_corrected(e, "milk_baseline", cfg=CFG, trend=t)
    e2 = e.copy()
    late = pd.to_datetime(e2["period_end"]).dt.date > origin
    e2.loc[late, "actual"] *= 3
    b = adaptive_corrected(e2, "milk_baseline", cfg=CFG, trend=t)
    pick = lambda d: d[d["origin"] == origin].sort_values("horizon")["forecast"].to_numpy()
    assert np.array_equal(pick(a), pick(b))


def test_year_choice_uses_only_periods_ended_before_that_year():
    e = _errors(slope=0.01)
    _, chosen_a, folds_a = choose_trend_by_year(e, "milk_baseline", CFG, GRID)
    e2 = e.copy()
    late = pd.to_datetime(e2["period_end"]) > pd.Timestamp("2021-01-01")
    e2.loc[late, "actual"] *= 0.5  # change everything that ended after 1 Jan 2021
    _, chosen_b, folds_b = choose_trend_by_year(e2, "milk_baseline", CFG, GRID)
    sel = lambda f: f[f["selected"]].set_index("fold_year")["candidate"]
    assert sel(folds_a)[[2017, 2018, 2019, 2020, 2021]].equals(sel(folds_b)[[2017, 2018, 2019, 2020, 2021]])
    early = lambda c: c[pd.to_datetime(c["origin"]) < "2021-01-01"].sort_values(["origin", "horizon"])
    assert np.array_equal(early(chosen_a)["forecast"].to_numpy(), early(chosen_b)["forecast"].to_numpy())


def test_first_year_has_no_earlier_periods_and_uses_off():
    off, chosen, folds = choose_trend_by_year(_errors(slope=0.01), "milk_baseline", CFG, GRID)
    assert folds[(folds["fold_year"] == 2017) & folds["selected"]]["candidate"].tolist() == ["off"]
    assert folds[folds["fold_year"] == 2017]["inner_score"].isna().all()
    assert len(chosen) == len(off)  # every development origin 2017-2023 is covered
    assert set(chosen["model"]) == {"milk_baseline_adaptive_trend"}
    assert set(chosen["trend_setting"]) <= {"off"} | {t.label() for t in GRID}


# --- a steady decline is followed, a flat series is not disturbed ---------------------------

def test_steady_yield_decline_is_followed():
    e = _errors(slope=0.01)  # -1 % a month through 2020-2021
    off = adaptive_corrected(e, "milk_baseline", cfg=CFG)
    tr = adaptive_corrected(e, "milk_baseline", cfg=CFG, trend=TrendConfig(0.9, 0.05))
    during = lambda d: d[pd.to_datetime(d["origin"]).dt.year.isin([2020, 2021])]
    assert _ape(during(tr)).mean() < 0.6 * _ape(during(off)).mean()
    # the plain level lags the decline (forecasts too high); the trend removes most of that bias
    bias = lambda d: float((d["forecast"] - d["actual"]).sum() / d["actual"].sum())
    assert bias(during(off)) > 0.05 and abs(bias(during(tr))) < bias(during(off)) / 3
    w10 = lambda d: _by_year(d, lambda x: _ape(x) <= 0.10)
    assert w10(tr)[2021] > w10(off)[2021] + 0.3


def test_flat_series_is_not_disturbed():
    e = _errors(slope=0.0)
    off = adaptive_corrected(e, "milk_baseline", cfg=CFG)
    tr = adaptive_corrected(e, "milk_baseline", cfg=CFG, trend=TrendConfig(0.9, 0.05))
    m = off.merge(tr, on=["origin", "horizon"], suffixes=("_off", "_tr"))
    rel = (m["forecast_tr"] / m["forecast_off"] - 1).abs()
    assert rel.mean() < 0.015  # measured about 1 % (noise 2 %)
    assert (_ape(tr) <= 0.10).mean() >= (_ape(off) <= 0.10).mean() - 0.01


def test_trend_overshoots_after_the_decline_stops():
    """Known cost, kept visible: the damped slope carries on for a while after the drift
    ends. This is why the keep rule checks every forecast year separately."""
    e = _errors(slope=0.01)
    off = adaptive_corrected(e, "milk_baseline", cfg=CFG)
    tr = adaptive_corrected(e, "milk_baseline", cfg=CFG, trend=TrendConfig(0.9, 0.05))
    w10 = lambda d: _by_year(d, lambda x: _ape(x) <= 0.10)
    assert w10(tr)[2022] < w10(off)[2022]


# --- hit rate by forecast year and the keep rule ----------------------------------------------

def _rates(rows):
    r = hit_rates(rows.assign(block="development", band="normal"))
    ry = hit_rates(rows.assign(block="development", band="normal"), by_year=True)
    return r, ry


def _cells(model, err_by_year, cells=(("weekly", 1), ("weekly", 13), ("monthly", 1), ("monthly", 3),
                                      ("monthly", 6), ("monthly", 12))):
    rows = []
    for (g, h) in cells:
        for year in range(2017, 2024):
            for i in range(10):
                p = err_by_year(year, g, h, i)
                rows.append(dict(origin=date(year, 1 + i, 1), grain=g, horizon=h, model=model,
                                 actual=100.0, forecast=100.0 * (1 + p)))
    return pd.DataFrame(rows)


def test_hit_rate_by_forecast_year():
    rows = _cells("m", lambda y, g, h, i: 0.2 if (y == 2021 and i < 5) else 0.0)
    _, ry = _rates(rows)
    t = year_table(ry, "m", block="development")
    assert t.loc[("monthly", 12), 2021] == pytest.approx(0.5)
    assert t.loc[("monthly", 12), 2019] == pytest.approx(1.0)
    assert list(t.columns) == list(range(2017, 2024))


def test_keep_rule_passes_and_fails_as_written():
    old = _cells("old", lambda y, g, h, i: 0.2 if (h in (13, 3, 6, 12) and i < 4) else 0.0)
    # better at the long horizons in every year, unchanged at week 1 / month 1
    good = _cells("new", lambda y, g, h, i: 0.2 if (h in (13, 3, 6, 12) and i < 2) else 0.0)
    r, ry = _rates(pd.concat([old, good]))
    checks, keep = keep_rule(r, ry, "old", "new")
    assert keep and checks["passed"].all()
    # same overall gain, but one year falls by more than 5 points
    bad_year = _cells("new", lambda y, g, h, i: (0.2 if i < 9 else 0.0) if y == 2022
                      else (0.2 if (h in (13, 3, 6, 12) and i < 1) else 0.0))
    r, ry = _rates(pd.concat([old, bad_year]))
    checks, keep = keep_rule(r, ry, "old", "new")
    assert not keep
    assert not checks.set_index("check").loc["year 2022 not worse by > 5%", "passed"]
    # month 1 falls
    worse_m1 = _cells("new", lambda y, g, h, i: 0.2 if ((h in (13, 3, 6, 12) and i < 2)
                                                        or (g, h) == ("monthly", 1) and i < 1) else 0.0)
    r, ry = _rates(pd.concat([old, worse_m1]))
    checks, keep = keep_rule(r, ry, "old", "new")
    assert not keep and not checks.set_index("check").loc["monthly h1 does not fall", "passed"]


def test_cli_adapt_trend_then_hit_rate_keep_rule(tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    tag = "synthetic_raw"
    e = _errors(slope=0.01)
    bench = e.assign(model="persistence")
    pd.concat([e, bench]).to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}.csv", index=False)
    pd.concat([e, bench]).iloc[0:0].to_csv(tmp_path / f"milk_backtest_errors_weekly_{tag}.csv", index=False)
    # the pfoi-1.2.0-dev reference file, for the exactness check
    adaptive_corrected(e, "milk_baseline", cfg=CFG).to_csv(
        tmp_path / f"milk_backtest_errors_monthly_{tag}_adhq0.1t365z3.csv", index=False)
    adaptive_corrected(e, "milk_baseline", cfg=CFG).iloc[0:0].to_csv(
        tmp_path / f"milk_backtest_errors_weekly_{tag}_adhq0.1t365z3.csv", index=False)
    assert cli.main(["adapt-trend", "--tag", tag, "--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    import re
    rel = float(re.search(r"336 of 336 rows matched, max relative difference ([0-9.e+-]+)", printed).group(1))
    assert rel < 1e-12  # identical up to CSV float rounding
    new = f"{tag}_adhq0.1t365z3_trnested"
    written = pd.read_csv(tmp_path / f"milk_backtest_errors_monthly_{new}.csv")
    assert set(written["model"]) == {"milk_baseline_adaptive", "milk_baseline_adaptive_trend", "persistence"}
    assert cli.main(["hit-rate", "--tag", new, "--quality", "off", "--out", str(tmp_path),
                     "--models", "milk_baseline_adaptive", "milk_baseline_adaptive_trend", "persistence",
                     "--keep-rule", "milk_baseline_adaptive", "milk_baseline_adaptive_trend"]) == 0
    printed = capsys.readouterr().out
    assert "by forecast year" in printed and "Verdict:" in printed
    assert (tmp_path / f"hit_rate_by_year_development_{new}.csv").exists()
    # tags that are not raw development backtests are refused
    assert cli.main(["adapt-trend", "--tag", tag + "_posthoc", "--out", str(tmp_path)]) == 1
