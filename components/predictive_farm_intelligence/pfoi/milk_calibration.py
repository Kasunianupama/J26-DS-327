"""Experimental past-only MAE calibration for long-horizon herd milk forecasts.

For each monthly horizon >= 3, choose a multiplier minimising exponentially
weighted absolute litre errors on completed forecasts. This is the weighted median
of actual / forecast with weights forecast * recency_weight. No correction is
applied before six usable outcomes, after a long gap, or to short horizons.

Version 1 fixes the settings before the real-data comparison. It is a research
candidate, not a change to the frozen model or evidence of real-data improvement.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import pandas as pd

MODEL = "milk_baseline_calibrated"
SUFFIX = "maecalv1"
KEYS = ["origin", "period_start", "grain", "series", "horizon"]


@dataclass(frozen=True)
class CalibrationConfig:
    half_life_days: float = 365.0
    max_age_days: int = 1095
    min_periods: int = 6
    min_monthly_horizon: int = 3
    lower: float = 0.5
    upper: float = 1.5


def weighted_median(values, weights) -> float:
    order = np.argsort(values, kind="stable")
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    return float(v[np.searchsorted(np.cumsum(w), w.sum() / 2, side="left")])


def calibrated_milk(errors: pd.DataFrame, base_model: str,
                    cfg: CalibrationConfig = CalibrationConfig()) -> pd.DataFrame:
    """Preserve every base forecast; fit only from outcomes known at its origin.

    k_source identifies the calibration source known at issuance. The current row's
    'source' is a future target label and must never determine its correction.
    Historical target sources and quality bands are usable only after period_end.
    """
    if (cfg.half_life_days <= 0 or cfg.max_age_days <= 0 or cfg.min_periods < 1
            or cfg.min_monthly_horizon < 1 or not 0 < cfg.lower <= 1 <= cfg.upper):
        raise ValueError("Invalid calibration settings")
    base = errors.loc[errors["model"] == base_model].copy().reset_index(drop=True)
    if base.empty:
        raise ValueError("No forecasts found for the requested base model")
    required = set(KEYS + ["period_end", "actual", "forecast", "k_source", "source"])
    if not required.issubset(base.columns):
        raise ValueError("Calibration needs dated forecasts and source metadata")
    if base.duplicated(KEYS).any():
        raise ValueError("Duplicate base forecast keys")
    for col in ("origin", "period_start", "period_end"):
        base[col] = pd.to_datetime(base[col])
        if base[col].isna().any():
            raise ValueError("Forecast dates must be present")
    if (base["period_end"] <= base["origin"]).any():
        raise ValueError("Forecast outcomes must end after their issue date")
    forecasts = base["forecast"].to_numpy(dtype=float)
    if (~np.isfinite(forecasts) | (forecasts < 0)).any():
        raise ValueError("Base forecasts must be finite and nonnegative")
    base["calibration_factor"] = 1.0
    base["calibration_n"] = 0
    known_source = base["k_source"].fillna("").astype(str).str.removeprefix("anchored:")
    flags = base["flags"].fillna("").astype(str) if "flags" in base else pd.Series("", index=base.index)
    eligible = (base["series"].eq("herd_milk") & base["grain"].eq("monthly")
                & base["horizon"].ge(cfg.min_monthly_horizon))
    for _, group in base[eligible].groupby(["series", "grain", "horizon"], sort=False):
        for idx in group.index:
            origin, source = base.at[idx, "origin"], known_source.at[idx]
            if source not in ("shipment", "delpro") or "source_switch" in flags.at[idx]:
                continue
            history = group[(group["period_end"] <= origin)
                            & (group["period_end"] >= origin - pd.Timedelta(days=cfg.max_age_days))]
            # Filter only completed outcomes; never inspect the current target source/band.
            history = history[(known_source.loc[history.index] == source)
                              & history["source"].eq(source)
                              & ~flags.loc[history.index].str.contains("source_switch", regex=False)]
            if "band" in history:
                history = history[history["band"].isin(["normal", "degraded"])]
            history = history[np.isfinite(history["actual"]) & history["actual"].ge(0)
                              & history["forecast"].gt(0)]
            n = history[["period_start", "period_end"]].drop_duplicates().shape[0]
            base.at[idx, "calibration_n"] = n
            if n < cfg.min_periods or forecasts[idx] == 0:
                continue
            age = (origin - history["period_end"]).dt.days.to_numpy()
            weights = history["forecast"].to_numpy() * np.exp2(-age / cfg.half_life_days)
            ratio = history["actual"].to_numpy() / history["forecast"].to_numpy()
            factor = weighted_median(ratio, weights)
            base.at[idx, "calibration_factor"] = np.clip(factor, cfg.lower, cfg.upper)
    base["forecast"] = forecasts * base["calibration_factor"]
    base["error"] = base["forecast"] - base["actual"]
    base["model"] = MODEL
    # Old intervals refer to a different forecast and must be recalibrated later.
    stale = [c for c in base if c in ("lower", "upper", "covered", "origin_band")
             or re.fullmatch(r"(lower|upper|covered)(80|90)", c)]
    return base.drop(columns=stale)


def comparison(base: pd.DataFrame, revised: pd.DataFrame) -> pd.DataFrame:
    """Matched-period error magnitudes against actuals, never individual forecasts."""
    joined = base.merge(revised[KEYS + ["forecast"]], on=KEYS, suffixes=("", "_new"),
                        validate="one_to_one")
    if len(joined) != len(base) or len(joined) != len(revised):
        raise ValueError("Comparison requires identical forecast periods")
    if "band" in joined:
        joined = joined[joined["band"].isin(["normal", "degraded"])]
    rows = []
    for (grain, horizon), g in joined.groupby(["grain", "horizon"]):
        for label, col in (("existing", "forecast"), ("calibrated", "forecast_new")):
            err = g[col] - g["actual"]
            absolute = err.abs()
            total = g["actual"].sum()
            ape = absolute / g["actual"].where(g["actual"] > 0)
            rows.append(dict(grain=grain, horizon=horizon, candidate=label, n=len(g),
                             mae_litres=absolute.mean(), rmse_litres=np.sqrt((err ** 2).mean()),
                             wape_pct=100 * absolute.sum() / total if total > 0 else np.nan,
                             bias_pct=100 * err.sum() / total if total > 0 else np.nan,
                             p90_ape_pct=100 * ape.quantile(.9), n_positive_actual=int(ape.notna().sum()),
                             misses_over_20pct=100 * (ape.dropna() > .2).mean()))
    return pd.DataFrame(rows)


def run_command(args) -> int:
    """User-run on local aggregate backtests; optional read-only quality lookup."""
    from .episodes import add_bands
    from .scorecard import BENCHMARKS

    if (not re.fullmatch(r"[A-Za-z0-9_.]+", args.tag) or args.tag.endswith("_test")
            or SUFFIX in args.tag):
        raise ValueError("Use a development base tag, not a test or calibrated tag")
    out = Path(args.out)
    paths = [out / f"milk_backtest_errors_{g}_{args.tag}.csv" for g in ("monthly", "weekly")]
    if not all(p.is_file() for p in paths):
        raise ValueError("Both monthly and weekly base backtests must finish first")
    errors = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    for col in ("origin", "period_start", "period_end"):
        errors[col] = pd.to_datetime(errors[col])
    cutoff = pd.Timestamp("2024-01-01")
    if errors["origin"].ge(cutoff).any() or errors["period_end"].gt(cutoff).any():
        raise ValueError("Only development outcomes ending by 2024-01-01 are allowed")
    if args.quality == "on":
        from .selection_report import load_quality
        errors = add_bands(errors, load_quality())
    elif "band" in errors:
        errors = errors.drop(columns="band")
    revised = calibrated_milk(errors, args.base)
    base = errors[errors["model"] == args.base]
    print("EXPERIMENTAL: matched development forecasts against actual milk; litres per period.")
    print("Training/scoring quality: " + ("normal + degraded" if args.quality == "on" else "scoreable only"))
    print(comparison(base, revised).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    stats = revised.assign(adjusted=~np.isclose(revised["calibration_factor"], 1.0))
    print("\n=== calibration use (counts and mean multiplier) ===")
    print(stats.groupby(["grain", "horizon"]).agg(
        n=("forecast", "size"), adjusted=("adjusted", "sum"),
        mean_multiplier=("calibration_factor", "mean")).to_string())
    tag = f"{args.tag}_{SUFFIX}_{'qon' if args.quality == 'on' else 'qoff'}"
    both = pd.concat([revised, errors[errors["model"].isin(BENCHMARKS)]], ignore_index=True)
    file_grain = both["grain"].where(both["grain"].eq("monthly"), "weekly")
    for grain, part in both.groupby(file_grain):
        part.to_csv(out / f"milk_backtest_errors_{grain}_{tag}.csv", index=False)
    print(f"\nSaved development candidate: {tag}")
    print("Real-data improvement is unconfirmed until these errors and nested validation are reviewed.")
    return 0
