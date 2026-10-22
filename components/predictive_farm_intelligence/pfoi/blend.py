"""Layer 2: blend a structural forecast with persistence, weighted by past skill (Bates-Granger).

Why. Development errors of the adaptive milk model (pfoi-1.2.0-dev) show that at daily and
weekly range it is no better than carrying the last value forward, and clearly worse after the
Aug 2022 source break (weekly MAE ratio to persistence 1.3 to 1.7). The structural forecast
earns its keep at monthly range, where the recorded pregnancy pipeline carries information, so
monthly rows are left alone.

How. For each grain, series and horizon, the weight on the structural forecast at an origin is

    w = (1 / MAE_structural) / (1 / MAE_structural + 1 / MAE_persistence)

where both MAEs use only forecasts whose target period had **ended by the origin** (nothing
later is used), over all such finished forecasts. With fewer than ``min_obs`` finished pairs the
structural forecast is kept (w = 1). No parameter is tuned: the weights follow from the model's
own past errors, so a regime change shows up as soon as errors from it have finished.

The blended forecast is ``w x structural + (1 - w) x persistence``. Its intervals come from its
own past relative errors (``error_tools.add_intervals``), never from the structural model's.
Error tables have the backtest columns (origin, grain, horizon, period_start, period_end,
series, model, forecast, actual, ...); the persistence benchmark rows must be in the table.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_OBS = 8
BLEND_GRAINS = ("weekly", "daily")
KEYS = ["grain", "series", "horizon", "origin", "period_start"]


def persistence_blend(errors: pd.DataFrame, base_model: str = "milk_baseline_adaptive",
                      ref_model: str = "persistence", new_model: str | None = None,
                      grains: tuple[str, ...] = BLEND_GRAINS, min_obs: int = MIN_OBS) -> pd.DataFrame:
    """Rows of ``base_model`` in ``grains`` with forecasts replaced by the blend.

    Adds ``blend_w`` (weight on the structural forecast; 1.0 where history is too short).
    Rows without a persistence forecast for the same period are dropped (not scored)."""
    new_model = new_model or f"{base_model}_blend"
    base = errors[(errors["model"] == base_model) & errors["grain"].isin(grains)]
    ref = errors[errors["model"] == ref_model][KEYS + ["forecast"]].rename(columns={"forecast": "pers"})
    x = base.merge(ref, on=KEYS, how="inner")
    if not len(x):
        return base.iloc[0:0].assign(blend_w=pd.Series(dtype=float))
    x = x.copy()
    x["origin"] = pd.to_datetime(x["origin"])
    x["period_end"] = pd.to_datetime(x["period_end"])
    x["blend_w"] = 1.0
    for _, g in x.groupby(["grain", "series", "horizon"]):
        g = g.sort_values("origin")
        f = g["forecast"].to_numpy(dtype=float)
        p = g["pers"].to_numpy(dtype=float)
        a = g["actual"].to_numpy(dtype=float)
        ea, ep = np.abs(f - a), np.abs(p - a)
        ends, origins = g["period_end"].to_numpy(), g["origin"].to_numpy()
        w = np.ones(len(g))
        for i in range(len(g)):
            done = (ends <= origins[i]) & np.isfinite(ea) & np.isfinite(ep)
            if done.sum() < min_obs:
                continue
            ma, mp = max(ea[done].mean(), 1e-9), max(ep[done].mean(), 1e-9)
            w[i] = (1 / ma) / (1 / ma + 1 / mp)
        x.loc[g.index, "blend_w"] = w
    x["forecast"] = x["blend_w"] * x["forecast"] + (1 - x["blend_w"]) * x["pers"]
    x["error"] = x["forecast"] - x["actual"]
    x["model"] = new_model
    for col in ("lower", "upper", "covered"):
        if col in x.columns:
            x[col] = np.nan
    return x.drop(columns="pers").reset_index(drop=True)


def weights_at(errors: pd.DataFrame, origin, grain: str, series: str = "herd_milk",
               base_model: str = "milk_baseline_adaptive", ref_model: str = "persistence",
               min_obs: int = MIN_OBS) -> pd.DataFrame:
    """Blend weight on the structural forecast at ``origin``, per horizon the backtest scored.

    Same rule as ``persistence_blend`` (inverse past MAE, finished forecasts only), evaluated for a
    single forecast date, for the live outlook. Columns: horizon, w, n_finished. w = 1 with fewer than
    ``min_obs`` finished pairs."""
    origin = pd.Timestamp(origin)
    base = errors[(errors["model"] == base_model) & (errors["grain"] == grain) & (errors["series"] == series)]
    ref = errors[(errors["model"] == ref_model) & (errors["grain"] == grain) & (errors["series"] == series)]
    x = base.merge(ref[KEYS + ["forecast"]].rename(columns={"forecast": "pers"}), on=KEYS, how="inner")
    rows = []
    for h, g in x.groupby("horizon"):
        done = g[pd.to_datetime(g["period_end"]) <= origin]
        done = done[np.isfinite(done["forecast"]) & np.isfinite(done["pers"]) & np.isfinite(done["actual"])]
        w = 1.0
        if len(done) >= min_obs:
            ma = max((done["forecast"] - done["actual"]).abs().mean(), 1e-9)
            mp = max((done["pers"] - done["actual"]).abs().mean(), 1e-9)
            w = (1 / ma) / (1 / ma + 1 / mp)
        rows.append(dict(horizon=int(h), w=w, n_finished=len(done)))
    return pd.DataFrame(rows, columns=["horizon", "w", "n_finished"]).sort_values("horizon").reset_index(drop=True)


def interval_quantiles_at(blend_rows: pd.DataFrame, origin, grain: str, series: str = "herd_milk",
                          min_errors: int = 12, quantiles: tuple[float, float] = (0.05, 0.95)) -> pd.DataFrame:
    """5 % / 95 % quantiles of the blend's own finished relative errors (actual / forecast - 1) per
    horizon at ``origin`` (as ``error_tools.add_intervals`` does). Horizons with fewer than
    ``min_errors`` finished errors are left out."""
    origin = pd.Timestamp(origin)
    x = blend_rows[(blend_rows["grain"] == grain) & (blend_rows["series"] == series)]
    rows = []
    for h, g in x.groupby("horizon"):
        done = g[pd.to_datetime(g["period_end"]) <= origin]
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.where(done["forecast"] > 0, done["actual"] / done["forecast"] - 1.0, np.nan)
        rel = rel[np.isfinite(rel)]
        if len(rel) >= min_errors:
            ql, qh = np.quantile(rel, quantiles)
            rows.append(dict(horizon=int(h), q_low=float(ql), q_high=float(qh), n_errors=len(rel)))
    return pd.DataFrame(rows, columns=["horizon", "q_low", "q_high", "n_errors"])


# ---------------------------------------------------------------------------------------------
# Several partners (for example persistence and ETS): same rule, inverse past MAE over all models.

def _inverse_mae(mae: dict[str, float], usable: list[str]) -> dict[str, float]:
    """Weights proportional to 1 / MAE over ``usable`` models (all weight to the first if only it is)."""
    inv = {m: 1.0 / max(mae[m], 1e-9) for m in usable}
    total = sum(inv.values())
    return {m: inv[m] / total for m in usable}


def skill_blend(errors: pd.DataFrame, base_model: str = "milk_baseline_adaptive",
                partners: tuple[str, ...] = ("persistence",), new_model: str | None = None,
                grains: tuple[str, ...] = BLEND_GRAINS, min_obs: int = MIN_OBS) -> pd.DataFrame:
    """Rows of ``base_model`` in ``grains`` blended with ``partners``; weights proportional to 1 / MAE of
    each model's **finished** forecasts (target period ended by the origin), per grain, series and horizon.

    A partner with fewer than ``min_obs`` finished forecasts, or no forecast for a period, is left out of
    that row and the weights are renormalised; with no usable partner the base forecast is kept (weight 1).
    Adds ``blend_w`` (weight on the base) and ``w_<partner>`` columns; intervals are cleared."""
    new_model = new_model or f"{base_model}_blend"
    base = errors[(errors["model"] == base_model) & errors["grain"].isin(grains)]
    x = base.copy()
    for p in partners:
        pf = errors[errors["model"] == p][KEYS + ["forecast"]].rename(columns={"forecast": f"f_{p}"})
        x = x.merge(pf.drop_duplicates(KEYS), on=KEYS, how="left")
    x["origin"] = pd.to_datetime(x["origin"])
    x["period_end"] = pd.to_datetime(x["period_end"])
    names = [base_model, *partners]
    cols = ["forecast"] + [f"f_{p}" for p in partners]
    x["blend_w"] = 1.0
    for p in partners:
        x[f"w_{p}"] = 0.0
    new_fc = x["forecast"].to_numpy(dtype=float).copy()
    for _, g in x.groupby(["grain", "series", "horizon"]):
        g = g.sort_values("origin")
        f = g[cols].to_numpy(dtype=float)
        a = g["actual"].to_numpy(dtype=float)
        err = np.abs(f - a[:, None])
        ends, origins = g["period_end"].to_numpy(), g["origin"].to_numpy()
        for pos, idx in enumerate(g.index):
            done = (ends <= origins[pos]) & np.isfinite(err[:, 0])
            mae = {}
            for j, name in enumerate(names):
                ok = done & np.isfinite(err[:, j])
                if ok.sum() >= min_obs:
                    mae[name] = err[ok, j].mean()
            usable = [n for j, n in enumerate(names) if n in mae and np.isfinite(f[pos, j])]
            if base_model not in usable or len(usable) < 2:
                continue
            w = _inverse_mae(mae, usable)
            new_fc[x.index.get_loc(idx)] = sum(w[n] * f[pos, names.index(n)] for n in usable)
            x.loc[idx, "blend_w"] = w[base_model]
            for p in partners:
                x.loc[idx, f"w_{p}"] = w.get(p, 0.0)
    x["forecast"] = new_fc
    x["error"] = x["forecast"] - x["actual"]
    x["model"] = new_model
    for col in ("lower", "upper", "covered"):
        if col in x.columns:
            x[col] = np.nan
    return x.drop(columns=[f"f_{p}" for p in partners]).reset_index(drop=True)


def skill_weights_at(errors: pd.DataFrame, origin, grain: str, series: str = "herd_milk",
                     base_model: str = "milk_baseline_adaptive", partners: tuple[str, ...] = ("persistence",),
                     available: tuple[str, ...] | None = None, min_obs: int = MIN_OBS) -> pd.DataFrame:
    """The same weights for one forecast date, per horizon the backtest scored: columns horizon,
    ``w_<model>`` for the base and each partner, n_finished. ``available`` = partners that have a forecast
    at this date (default all); the others get weight 0 and the rest are renormalised."""
    origin = pd.Timestamp(origin)
    available = tuple(partners) if available is None else tuple(available)
    base = errors[(errors["model"] == base_model) & (errors["grain"] == grain) & (errors["series"] == series)]
    x = base[KEYS + ["forecast", "actual", "period_end"]].rename(columns={"forecast": base_model})
    for p in partners:
        pf = errors[(errors["model"] == p) & (errors["grain"] == grain) & (errors["series"] == series)]
        x = x.merge(pf[KEYS + ["forecast"]].rename(columns={"forecast": p}).drop_duplicates(KEYS), on=KEYS, how="left")
    names = [base_model, *partners]
    rows = []
    for h, g in x.groupby("horizon"):
        g = g[pd.to_datetime(g["period_end"]) <= origin]
        mae = {}
        for n in names:
            e = (g[n] - g["actual"]).abs()
            e = e[np.isfinite(e) & np.isfinite((g[base_model] - g["actual"]).abs())]
            if len(e) >= min_obs:
                mae[n] = float(e.mean())
        usable = [n for n in names if n in mae and (n == base_model or n in available)]
        row = {"horizon": int(h), "n_finished": int(np.isfinite((g[base_model] - g["actual"]).abs()).sum())}
        w = _inverse_mae(mae, usable) if base_model in usable and len(usable) > 1 else {base_model: 1.0}
        for n in names:
            row[f"w_{n}"] = w.get(n, 0.0)
        rows.append(row)
    cols = ["horizon", "n_finished"] + [f"w_{n}" for n in names]
    return pd.DataFrame(rows, columns=cols).sort_values("horizon").reset_index(drop=True)
