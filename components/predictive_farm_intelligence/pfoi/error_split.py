"""Milk error split into cow-count and yield-per-cow parts, with ceilings (1.2.1-dev step 2).

Milk over a period = milking cows (daily mean) x days x litres per cow-day, so for every
scored period, exactly:

    log(forecast / recorded milk) = log(forecast / recorded cows) + log(forecast / recorded yield)

Milk forecasts come from a milk backtest, cow forecasts from the herd backtest of the same
engine settings, at the same forecast dates and periods. Ceilings answer "what if one part
were perfect": the milk hit rate with the recorded cow count (only yield error left) and
with the recorded yield per cow (only cow error left). These are diagnostics with hindsight,
never forecasts. Herd-level aggregates only; nothing is re-run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .hit_rate import TRUSTED, trust_group

KEYS = ["block", "grain", "horizon", "origin", "period_start"]


def _norm(e: pd.DataFrame) -> pd.DataFrame:
    e = e.copy()
    for c in ("origin", "period_start", "period_end"):
        e[c] = pd.to_datetime(e[c]).dt.date
    if "block" not in e:
        e["block"] = "all"
    return e


def join(milk: pd.DataFrame, herd: pd.DataFrame, milk_model: str,
         herd_model: str = "herd_engine") -> pd.DataFrame:
    """One row per period both backtests scored, with the three log errors."""
    m = _norm(milk[(milk["model"] == milk_model) & (milk.get("series", "herd_milk") == "herd_milk")])
    h = _norm(herd[(herd["model"] == herd_model) & (herd["series"] == "milking")])
    cols = [*KEYS, "period_end", "forecast", "actual"]
    j = m[cols + (["band"] if "band" in m else [])].merge(
        h[[*KEYS, "forecast", "actual"]], on=KEYS, suffixes=("_milk", "_cows"))
    j = j[(j["actual_milk"] > 0) & (j["forecast_milk"] > 0) & (j["actual_cows"] > 0) & (j["forecast_cows"] > 0)]
    days = np.array([(e - s).days for s, e in zip(j["period_start"], j["period_end"])], dtype=float)
    j = j.assign(days=days)
    j["e_milk"] = np.log(j["forecast_milk"] / j["actual_milk"])
    j["e_cows"] = np.log(j["forecast_cows"] / j["actual_cows"])
    j["e_yield"] = j["e_milk"] - j["e_cows"]
    j["yield_forecast"] = j["forecast_milk"] / (j["forecast_cows"] * j["days"])
    j["yield_actual"] = j["actual_milk"] / (j["actual_cows"] * j["days"])
    return j


def _within(log_err: pd.Series, tol: float) -> float:
    return float((np.abs(np.expm1(log_err)) <= tol + 1e-9).mean())


def summarise(j: pd.DataFrame, tol: float = 0.10) -> pd.DataFrame:
    """Per block x grain x horizon x trust: hit rate now and with each part perfect, the size of
    each part, how much of the squared error is cows, and the cow-yield error correlation
    (negative = the level k already absorbs part of the cow error)."""
    j = j.assign(trust=trust_group(j))
    rows = []
    for (b, g, h, t), d in j.groupby(["block", "grain", "horizon", "trust"], sort=True):
        ec, ey = d["e_cows"], d["e_yield"]
        sq = (ec ** 2).mean() + (ey ** 2).mean()
        rows.append(dict(
            block=b, grain=g, horizon=h, trust=t, n=len(d),
            within_10=_within(d["e_milk"], tol),
            within_10_if_cows_exact=_within(ey, tol),
            within_10_if_yield_exact=_within(ec, tol),
            mean_abs_cows_pct=float(np.abs(np.expm1(ec)).mean()),
            mean_abs_yield_pct=float(np.abs(np.expm1(ey)).mean()),
            bias_cows_pct=float(np.expm1(ec.mean())), bias_yield_pct=float(np.expm1(ey.mean())),
            cow_share_of_sq_error=float((ec ** 2).mean() / sq) if sq > 0 else np.nan,
            corr_cows_yield=float(np.corrcoef(ec, ey)[0, 1]) if len(d) > 2 and ec.std() > 0 and ey.std() > 0 else np.nan,
        ))
    out = pd.DataFrame(rows)
    order = {"daily": 0, "weekly": 1, "monthly": 2}
    return out.sort_values(["block", "trust", "grain", "horizon"],
                           key=lambda s: s.map(order) if s.name == "grain" else s).reset_index(drop=True)


def show(summary: pd.DataFrame, trust: str = TRUSTED) -> pd.DataFrame:
    s = summary[summary["trust"].isin([trust, "all"])]
    return s.drop(columns=["trust"]).set_index(["block", "grain", "horizon"])


PATTERN_CELLS = (("weekly", 13), ("monthly", 3), ("monthly", 6), ("monthly", 12))


def patterns(j: pd.DataFrame, cells=PATTERN_CELLS) -> dict[str, pd.DataFrame]:
    """Mean yield-per-cow error (%) of trusted periods by calendar month of the target
    (seasonality) and by year of the forecast date (drift), for the long horizons.
    Columns are '<grain> h<horizon>'; each value is a mean over n periods (n in brackets table)."""
    t = j[trust_group(j).isin([TRUSTED, "all"])].copy()
    t["month"] = [s.month for s in t["period_start"]]
    t["year"] = [o.year for o in t["origin"]]
    out = {}
    for key in ("month", "year"):
        mean, n = {}, {}
        for g, h in cells:
            d = t[(t["grain"] == g) & (t["horizon"] == h)]
            col = f"{g} h{h}"
            mean[col] = d.groupby(key)["e_yield"].mean().map(np.expm1)
            n[col] = d.groupby(key)["e_yield"].size()
        out[key] = pd.DataFrame(mean)
        out[f"{key}_n"] = pd.DataFrame(n)
    return out
