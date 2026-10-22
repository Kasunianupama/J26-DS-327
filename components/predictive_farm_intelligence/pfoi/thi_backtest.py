"""Rolling-origin back-test of the experimental THI forecasts (weather only, no animal data).

At each forecast date every model sees only complete weather up to ``origin - lag``,
exactly as on a real forecast day. Models compared on identical (origin, day) pairs:

* ``persistence``: the last known day's max THI, repeated;
* ``climatology``: median max THI of earlier years within +/-7 days of the date;
* ``v1``: seasonal curve plus a fixed seven-day fading adjustment (``forecast_thi``);
* ``v2``: recency-weighted seasonal curve plus learned daily changes (``forecast_thi_daily``).

Hot days use the herd's own knots (75th / 90th percentile of max THI known at the
origin), the same thresholds as the milk driver layer. Output is aggregate only:
MAE, RMSE, bias, skill against climatology, hit rate, false-alarm ratio, Brier score and
10-90% band coverage, by lead band. Tested on synthetic data; AI agents must not run it
against the real database.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .thi_forecast import DailyThiConfig, forecast_thi, forecast_thi_daily

MODELS = ("persistence", "climatology", "v1", "v2")
LEAD_BANDS = ((1, 3), (4, 7), (8, 14), (15, 30), (31, 90))
KNOTS = {"p75": 75.0, "p90": 90.0}
CLIM_HALFWIDTH = 7


def weekly_origins(start: date, end: date, step_days: int = 7) -> list[date]:
    """Mondays from ``start`` (inclusive) to ``end`` (exclusive), every ``step_days``."""
    d = start + timedelta(days=(7 - start.weekday()) % 7)
    out = []
    while d < end:
        out.append(d)
        d += timedelta(days=step_days)
    return out


def _complete(daily: pd.DataFrame) -> pd.Series:
    days = pd.to_datetime(daily["date"])
    values = pd.to_numeric(daily["thi_max"], errors="coerce")
    ok = daily["weather_is_complete"].astype("boolean").fillna(False) & np.isfinite(values)
    s = pd.Series(values[ok].to_numpy(), index=pd.DatetimeIndex(days[ok]))
    return s.groupby(level=0).mean().sort_index()


def _band(lead: int) -> str:
    for lo, hi in LEAD_BANDS:
        if lo <= lead <= hi:
            return f"{lo}-{hi}"
    return f">{LEAD_BANDS[-1][1]}"


def origin_rows(daily: pd.DataFrame, weather: pd.Series, origin: date, lag: int = 6,
                ahead: int = 90, score_until: date | None = None,
                cfg: DailyThiConfig = DailyThiConfig()) -> tuple[list[dict], dict]:
    """Forecast rows of all models at one origin, joined to the recorded outcome.

    ``weather`` is ``_complete(daily)``. Returns the rows and v2's learned persistence."""
    cutoff = pd.Timestamp(origin) - pd.Timedelta(days=max(1, lag))
    known = weather.loc[:cutoff]
    if len(known) < 365:
        return [], {}
    knots = {k: float(np.percentile(known, p)) for k, p in KNOTS.items()}
    v1 = forecast_thi(daily, origin, lag, ahead)
    v2 = forecast_thi_daily(daily, origin, lag, ahead, thresholds=knots, cfg=cfg)
    if v1["status"] != "experimental" or v2["status"] != "experimental":
        return [], {}
    v1p = {p["date"]: p for p in v1["predictions"]}
    doy = known.index.dayofyear.to_numpy()
    rows = []
    for p in v2["predictions"]:
        day = pd.Timestamp(p["date"])
        if score_until is not None and day >= pd.Timestamp(score_until):
            break
        if day not in weather.index or p["date"] not in v1p:
            continue
        dist = np.abs(doy - day.dayofyear)
        clim = known.to_numpy()[np.minimum(dist, 365 - dist) <= CLIM_HALFWIDTH]
        if len(clim) < 10:
            continue
        actual = float(weather.loc[day])
        lead = (day - pd.Timestamp(origin)).days + 1
        point = {"persistence": float(known.iloc[-1]), "climatology": float(np.median(clim)),
                 "v1": float(v1p[p["date"]]["thi_max"]), "v2": float(p["thi_max"])}
        band = {"climatology": tuple(np.percentile(clim, [10, 90])), "v2": (p["lower"], p["upper"])}
        for model in MODELS:
            row = {"origin": origin, "date": day.date(), "lead": lead, "band": _band(lead),
                   "model": model, "predicted": point[model], "actual": actual,
                   "lower": band.get(model, (np.nan, np.nan))[0],
                   "upper": band.get(model, (np.nan, np.nan))[1]}
            for k, t in knots.items():
                if model == "v2":
                    prob = p["p_above"][k]
                elif model == "climatology":
                    prob = float(np.mean(clim > t))
                else:  # point forecasts: hot or not
                    prob = float(point[model] > t)
                row[f"prob_{k}"], row[f"hot_{k}"] = prob, float(actual > t)
            rows.append(row)
    return rows, v2.get("persistence_by_lead", {})


def run_thi_backtest(daily: pd.DataFrame, origins: list[date], lag: int = 6, ahead: int = 90,
                     score_until: date | None = None,
                     cfg: DailyThiConfig = DailyThiConfig()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All forecast rows and the per-origin v2 persistence (both kept local, never printed)."""
    weather = _complete(daily)
    rows, pers = [], []
    for origin in origins:
        r, p = origin_rows(daily, weather, origin, lag, ahead, score_until, cfg)
        rows += r
        if r:
            pers.append({"origin": origin, **{f"after_{k}_days": v for k, v in p.items()}})
    return pd.DataFrame(rows), pd.DataFrame(pers)


def _scale_for(g: pd.DataFrame, target: float) -> float:
    """Factor on the band's distances from the prediction that would cover ``target``."""
    p, a = g["predicted"].to_numpy(), g["actual"].to_numpy()
    lo, hi = p - g["lower"].to_numpy(), g["upper"].to_numpy() - p
    cover = lambda s: np.mean((a >= p - s * lo) & (a <= p + s * hi))  # noqa: E731
    a_s, b_s = 0.1, 10.0
    if cover(b_s) < target:
        return np.nan
    for _ in range(40):
        mid = (a_s + b_s) / 2
        a_s, b_s = (mid, b_s) if cover(mid) < target else (a_s, mid)
    return b_s


def summarise(rows: pd.DataFrame) -> pd.DataFrame:
    """Aggregate accuracy by model and lead band (only pairs every model forecast)."""
    if rows.empty:
        return pd.DataFrame()
    n_models = rows.groupby(["origin", "date"])["model"].transform("nunique")
    rows = rows[n_models == rows["model"].nunique()].copy()
    rows["error"] = rows["predicted"] - rows["actual"]
    clim_mae = rows[rows["model"] == "climatology"].groupby("band")["error"].apply(lambda e: e.abs().mean())
    out = []
    for (band, model), g in rows.groupby(["band", "model"], sort=False):
        e = g["error"]
        r = {"lead_days": band, "model": model, "n": len(g),
             "mae": e.abs().mean(), "rmse": float(np.sqrt((e ** 2).mean())), "bias": e.mean(),
             "skill_vs_clim": 1 - e.abs().mean() / clim_mae[band]}
        for k in KNOTS:
            hot, prob = g[f"hot_{k}"], g[f"prob_{k}"]
            said = prob >= 0.5
            r[f"hot_share_{k}"] = hot.mean()
            r[f"hit_rate_{k}"] = (said & (hot == 1)).sum() / max(1, (hot == 1).sum())
            r[f"false_alarm_{k}"] = (said & (hot == 0)).sum() / said.sum() if said.any() else np.nan
            r[f"brier_{k}"] = ((prob - hot) ** 2).mean()
        has = g["lower"].notna()
        r["band_cover_10_90"] = (((g["actual"] >= g["lower"]) & (g["actual"] <= g["upper"]))[has].mean()
                                 if has.any() else np.nan)
        r["band_scale_for_80"] = _scale_for(g[has], 0.8) if has.any() else np.nan
        out.append(r)
    order = {f"{lo}-{hi}": i for i, (lo, hi) in enumerate(LEAD_BANDS)}
    t = pd.DataFrame(out)
    t["_b"], t["_m"] = t["lead_days"].map(order), t["model"].map({m: i for i, m in enumerate(MODELS)})
    return t.sort_values(["_b", "_m"]).drop(columns=["_b", "_m"]).reset_index(drop=True)
