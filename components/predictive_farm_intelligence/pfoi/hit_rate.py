"""Hit rate: share of forecasts within +-5 % and +-10 % of the recorded value (1.2.1-dev #1).

The user's target (2026-10-21) is about 85 % of forecasts within 5-10 % of what was recorded.
This measures it on finished backtest error tables (columns block, grain, horizon, model,
forecast, actual; optional ``band`` from ``episodes.add_bands``), per block x grain x horizon
x model x trust group. Trusted = record-quality band normal or degraded (docs/targets.md);
unverified and gap periods are reported separately, because no model can forecast a
recording artefact. Nothing is re-run; herd-level aggregates only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .episodes import VERIFIED_BANDS

THRESHOLDS = (0.05, 0.10)
TARGET_SHARE = 0.85
TARGET_WITHIN = 0.10
TRUSTED, UNTRUSTED, ALL = "trusted", "unverified_or_gap", "all"


def trust_group(errors: pd.DataFrame) -> pd.Series:
    if "band" not in errors:
        return pd.Series(ALL, index=errors.index)
    return errors["band"].isin(VERIFIED_BANDS).map({True: TRUSTED, False: UNTRUSTED})


def hit_rates(errors: pd.DataFrame, thresholds=THRESHOLDS, by_year: bool = False) -> pd.DataFrame:
    """One row per block x grain x horizon x model x trust (x forecast year, the year of the
    origin, with ``by_year``): n, within_5, within_10, median absolute % error, WAPE, bias %
    and whether within_10 reaches the 85 % target."""
    e = errors[errors["actual"] > 0].copy()
    if "block" not in e:
        e["block"] = "all"
    e["trust"] = trust_group(e)
    e["ape"] = (e["forecast"] - e["actual"]).abs() / e["actual"]
    e["err"] = e["forecast"] - e["actual"]
    keys = ["block", "grain", "horizon", "model", "trust"]
    if by_year:
        e["year"] = pd.to_datetime(e["origin"]).dt.year
        keys.append("year")
    rows = []
    for k, g in e.groupby(keys, sort=True):
        row = dict(zip(keys, k), n=len(g))
        for t in thresholds:
            row[f"within_{round(t * 100)}"] = float((g["ape"] <= t + 1e-9).mean())
        row["median_ape"] = float(g["ape"].median())
        row["wape"] = float(g["err"].abs().sum() / g["actual"].sum())
        row["bias_pct"] = float(g["err"].sum() / g["actual"].sum())
        row["meets_target"] = bool(row[f"within_{round(TARGET_WITHIN * 100)}"] >= TARGET_SHARE)
        rows.append(row)
    return pd.DataFrame(rows)


GRAIN_ORDER = {"daily": 0, "weekly": 1, "monthly": 2}


def table(rates: pd.DataFrame, value: str = "within_10", trust: str = TRUSTED,
          block: str | None = None) -> pd.DataFrame:
    """Grain x horizon rows, model columns: ``value`` (with n of the first model) for printing."""
    r = rates[rates["trust"].isin([trust, ALL])]
    if block is not None:
        r = r[r["block"] == block]
    if not len(r):
        return pd.DataFrame()
    t = r.pivot_table(index=["grain", "horizon"], columns="model", values=value, aggfunc="first")
    n = r.groupby(["grain", "horizon"])["n"].max().rename("n")
    t = t.join(n)
    order = sorted(t.index, key=lambda gh: (GRAIN_ORDER.get(gh[0], 9), gh[1]))
    return t.loc[order].replace({np.nan: None})


def year_table(rates_y: pd.DataFrame, model: str, value: str = "within_10", trust: str = TRUSTED,
               block: str | None = None) -> pd.DataFrame:
    """Grain x horizon rows, forecast-year columns, for one model (from ``by_year`` rates)."""
    r = rates_y[(rates_y["model"] == model) & rates_y["trust"].isin([trust, ALL])]
    if block is not None:
        r = r[r["block"] == block]
    if not len(r):
        return pd.DataFrame()
    t = r.pivot_table(index=["grain", "horizon"], columns="year", values=value, aggfunc="first")
    order = sorted(t.index, key=lambda gh: (GRAIN_ORDER.get(gh[0], 9), gh[1]))
    return t.loc[order]


# Keep rule for the 1.2.1-dev damped trend, fixed before any real run (handoff 2026-10-22):
# development origins 2017-2023, trusted periods, share within +-10 %.
KEEP_RISE = (("weekly", 13), ("monthly", 3), ("monthly", 6), ("monthly", 12))   # must rise
KEEP_HOLD = (("weekly", 1), ("monthly", 1))                                       # must not fall
KEEP_MAX_YEAR_DROP = 0.05  # no forecast year worse by more than 5 percentage points
KEEP_YEARS = tuple(range(2017, 2024))


def keep_rule(rates: pd.DataFrame, rates_y: pd.DataFrame, old: str, new: str,
              trust: str = TRUSTED, block: str = "development"):
    """Verdict of the fixed keep rule for ``new`` against ``old``.

    A year's share is the mean over horizons of within_10 for that forecast year (each
    grain x horizon scored by both models counts once), so every horizon weighs the same.
    Returns (checks table, keep: bool)."""
    rows = []
    r = rates[rates["trust"].isin([trust, ALL]) & (rates["block"] == block)]
    w = r.pivot_table(index=["grain", "horizon"], columns="model", values="within_10", aggfunc="first")
    for cells, rule in ((KEEP_RISE, "rises"), (KEEP_HOLD, "does not fall")):
        for g, h in cells:
            o = w.at[(g, h), old] if (g, h) in w.index and old in w else np.nan
            n = w.at[(g, h), new] if (g, h) in w.index and new in w else np.nan
            ok = (n > o) if rule == "rises" else (n >= o)
            rows.append(dict(check=f"{g} h{h} {rule}", old=o, new=n, change=n - o,
                             passed=bool(ok) if np.isfinite(o) and np.isfinite(n) else False))
    y = rates_y[rates_y["trust"].isin([trust, ALL]) & (rates_y["block"] == block)
                & rates_y["year"].isin(KEEP_YEARS)]
    wy = y.pivot_table(index=["year", "grain", "horizon"], columns="model", values="within_10", aggfunc="first")
    if old in wy and new in wy:
        wy = wy[[old, new]].dropna().groupby(level="year").mean()
        for year, (o, n) in wy.iterrows():
            rows.append(dict(check=f"year {year} not worse by > {KEEP_MAX_YEAR_DROP:.0%}", old=o, new=n,
                             change=n - o, passed=bool(n - o >= -KEEP_MAX_YEAR_DROP - 1e-12)))
    else:
        rows.append(dict(check="years", old=np.nan, new=np.nan, change=np.nan, passed=False))
    t = pd.DataFrame(rows)
    return t, bool(len(t) and t["passed"].all())
