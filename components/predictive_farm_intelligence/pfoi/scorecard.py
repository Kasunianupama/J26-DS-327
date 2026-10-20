"""Scorecard: every backtested series against the agreed targets (docs/targets.md).

Works on backtest error tables (columns origin, grain, horizon, period_start,
period_end, series, model, forecast, actual, error) and returns one herd-level row per
block x grain x series x horizon x candidate model. Nothing is re-run and no data is
read here; intervals are rebuilt with ``error_tools.add_intervals`` so 80 % and 90 %
coverage use the same past-errors-only rule as the backtests.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .episodes import VERIFIED_BANDS
from .error_tools import add_intervals

MIN_PERIODS = 12
BENCH_MIN_SHARE = 0.5
COVERAGE_BANDS = {80: (0.75, 0.85), 90: (0.85, 0.95)}
INTERVALS = {80: (0.10, 0.90), 90: (0.05, 0.95)}
CONFIRM_DROP = 0.05

CANDIDATES = ("milk_baseline", "milk_baseline_corrected", "herd_engine", "herd_engine_corrected")
PRIMARY = ("milk_baseline", "herd_engine")
BENCHMARKS = ("persistence", "seasonal_naive", "ets", "sarima")


@dataclass(frozen=True)
class Target:
    accuracy: float
    min_skill: float | None = None
    max_abs_bias: float | None = None
    max_width90: float | None = None


def _t(acc: dict[int, float], skill: dict[int, float] | float | None = None,
       bias: float | None = None, width: dict[int, float] | None = None) -> dict[int, Target]:
    out = {}
    for h, a in acc.items():
        s = skill.get(h) if isinstance(skill, dict) else skill
        out[h] = Target(a, s, bias, (width or {}).get(h))
    return out


# (series, grain) -> horizon -> Target. Same numbers as docs/targets.md.
# A skill condition "> 0" is stored as a tiny positive minimum.
_POS = 1e-9
TARGETS: dict[tuple[str, str], dict[int, Target]] = {
    ("herd_milk", "monthly"): _t({1: .92, 3: .90, 6: .88, 12: .85}, _POS, .03, {3: .30}),
    ("herd_milk", "weekly"): _t({1: .93, 4: .90, 13: .87}, {4: _POS, 13: _POS}),
    ("herd_milk", "daily"): _t({1: .95, 7: .92, 14: .90}, -0.05),
    ("milking", "monthly"): _t({1: .97, 3: .95, 6: .92, 12: .88}, {3: _POS, 6: _POS, 12: _POS}),
    ("n_herd", "monthly"): _t({1: .98, 3: .96, 6: .94, 12: .90}, {6: _POS, 12: _POS}),
    ("calvings", "monthly"): _t({1: .80, 3: .80, 6: .75, 12: .65}, {3: .20, 6: .20}),
    ("dry_offs", "monthly"): _t({1: .75, 3: .70, 6: .70, 12: .65}, _POS),
}
# Small-count events: no accuracy target; calibrated 80 % interval and deviance ratio < 1.
COUNT_SERIES = ("real_abortions", "deaths", "culls", "sales")
COUNT_GRAIN = "monthly"
# Recovery targets (agreed 2026-10-19): (series, grain, horizon, months since break) ->
# minimum accuracy, judged like the other targets (verified periods, n >= MIN_PERIODS).
RECOVERY_TARGETS = {("herd_milk", "weekly", 4, "0-2 months"): 0.90}


def poisson_deviance(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Mean Poisson deviance; forecasts are floored at 0.1 so zero forecasts stay finite."""
    y = np.asarray(actual, dtype=float)
    mu = np.maximum(np.asarray(forecast, dtype=float), 0.1)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(y > 0, y * np.log(y / mu), 0.0)
    return float(np.mean(2 * (term - (y - mu))))


def with_intervals(errors: pd.DataFrame, method: str = "empirical",
                   quality: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add lower/upper/covered for 80 % and 90 % from past errors only.

    ``empirical`` (pfoi-1.0.0): quantiles of all past relative errors. ``aci``: recency
    weighted, adaptive conformal, scaled by the record-quality band at the origin
    (``intervals.aci_intervals``; bands need the daily ``quality`` frame).
    """
    base = errors.drop(columns=[c for c in ("lower", "upper", "covered") if c in errors.columns])
    base = base.reset_index(drop=True)
    for col in ("origin", "period_start", "period_end"):
        base[col] = pd.to_datetime(base[col]).dt.date
    if method == "aci":
        from .intervals import aci_intervals, origin_bands
        bands = origin_bands(base["origin"], quality) if quality is not None else None
        return aci_intervals(base, band_at_origin=bands)
    if method != "empirical":
        raise ValueError(f"unknown interval method {method!r}")
    for level, q in INTERVALS.items():
        iv = add_intervals(base[["origin", "grain", "horizon", "period_end", "series", "model",
                                 "forecast", "actual"]], quantiles=q)
        base[f"lower{level}"] = iv["lower"].to_numpy()
        base[f"upper{level}"] = iv["upper"].to_numpy()
        base[f"covered{level}"] = iv["covered"].to_numpy()
    return base


def prepare(errors: pd.DataFrame, method: str = "empirical",
            quality: pd.DataFrame | None = None) -> pd.DataFrame:
    """Block column, 80/90 % intervals (if missing) and error = forecast - actual."""
    e = errors.copy()
    if "block" not in e.columns:
        e["block"] = "development"
    e = with_intervals(e, method, quality) if "covered80" not in e.columns else e
    e["error"] = e["forecast"] - e["actual"]
    return e


def group_scores(errors: pd.DataFrame, by: str, models=PRIMARY) -> pd.DataFrame:
    """n, accuracy, bias and coverage of ``models`` per block x grain x series x horizon x
    ``by`` (e.g. ``band`` or ``since_break``)."""
    e = prepare(errors)
    e = e[e["model"].isin(models)]
    rows = []
    keys = ["block", "grain", "series", "horizon", "model", by]
    for k, g in e.groupby(keys, sort=True, dropna=False):
        tot = g["actual"].sum()
        rows.append(dict(zip(keys, k), n=len(g),
                         accuracy=1 - g["error"].abs().sum() / tot if tot > 0 else np.nan,
                         bias_pct=g["error"].sum() / tot if tot > 0 else np.nan,
                         coverage90=float(g["covered90"].mean()) if g["covered90"].notna().any() else np.nan))
    return pd.DataFrame(rows)


def _best_benchmark(cand: pd.DataFrame, group: pd.DataFrame) -> tuple[str | None, float, int]:
    """(benchmark, skill, n common periods) for the toughest benchmark: the one with the
    lowest MAE relative to the candidate on the periods the two share."""
    keys = ["origin", "period_start"]
    best = (None, np.nan, 0)
    best_ratio = -np.inf  # toughest benchmark = highest model/benchmark MAE ratio
    for bench in BENCHMARKS:
        b = group[group["model"] == bench]
        if not len(b):
            continue
        m = cand[keys + ["error"]].merge(b[keys + ["error"]], on=keys, suffixes=("_c", "_b"))
        if len(m) < max(MIN_PERIODS, BENCH_MIN_SHARE * len(cand)):
            continue
        mae_b = m["error_b"].abs().mean()
        if mae_b <= 0:
            continue
        ratio = m["error_c"].abs().mean() / mae_b
        if ratio > best_ratio:
            best_ratio, best = ratio, (bench, 1 - ratio, len(m))
    return best


def _deviance_ratio(cand: pd.DataFrame, group: pd.DataFrame) -> float:
    keys = ["origin", "period_start"]
    p = group[group["model"] == "persistence"]
    m = cand[keys + ["actual", "forecast"]].merge(p[keys + ["forecast"]], on=keys,
                                                  suffixes=("", "_p"))
    if len(m) < MIN_PERIODS:
        return np.nan
    dp = poisson_deviance(m["actual"].to_numpy(), m["forecast_p"].to_numpy())
    dc = poisson_deviance(m["actual"].to_numpy(), m["forecast"].to_numpy())
    return dc / dp if dp > 0 else np.nan


def _calibrated(cov80: float, cov90: float) -> bool | None:
    if np.isnan(cov80) or np.isnan(cov90):
        return None
    (l8, h8), (l9, h9) = COVERAGE_BANDS[80], COVERAGE_BANDS[90]
    return bool(l8 <= cov80 <= h8 and l9 <= cov90 <= h9)


def _verdict(row: dict, target: Target | None, count: bool) -> tuple[str, str]:
    """(target verdict, reasons) for one row."""
    if target is None and not count:
        return "no target", ""
    if row["n"] < MIN_PERIODS:
        return "not interpretable", f"n < {MIN_PERIODS}"
    if count:
        reasons = []
        cal80 = row["coverage80"]
        lo, hi = COVERAGE_BANDS[80]
        if np.isnan(cal80) or not lo <= cal80 <= hi:
            reasons.append("80% coverage outside 75-85%")
        if not row["deviance_ratio"] < 1:
            reasons.append("deviance ratio >= 1")
        return ("met" if not reasons else "missed"), "; ".join(reasons)
    if target is None:
        return "no target", ""
    reasons = []
    if not row["accuracy"] >= target.accuracy:
        reasons.append(f"accuracy < {target.accuracy:.0%}")
    if target.min_skill is not None and not row["skill"] >= target.min_skill:
        reasons.append("skill below condition" if not np.isnan(row["skill"])
                       else "no usable benchmark")
    if target.max_abs_bias is not None and not abs(row["bias_pct"]) <= target.max_abs_bias:
        reasons.append(f"|bias| > {target.max_abs_bias:.0%}")
    if target.max_width90 is not None and not row["width90"] <= target.max_width90:
        reasons.append(f"width90 > {target.max_width90:.2f}")
    return ("met" if not reasons else "missed"), "; ".join(reasons)


def scorecard(errors: pd.DataFrame) -> pd.DataFrame:
    """One row per block x grain x series x horizon x candidate model.

    ``errors`` may hold several blocks in a ``block`` column (development first): all
    blocks share one interval history, so test-block intervals may use development
    errors, as in the backtests. With a ``band`` column (``episodes.add_bands``), only
    verified periods (normal and degraded records) are judged; other bands are reported
    by ``group_scores``. Intervals always use the full error history.
    """
    if not len(errors):
        return pd.DataFrame()
    e = prepare(errors)
    if "band" in e.columns:
        e = e[e["band"].isin(VERIFIED_BANDS)]
    rows = []
    for (block, grain, series, horizon), group in e.groupby(["block", "grain", "series", "horizon"],
                                                             sort=True):
        target = TARGETS.get((series, grain), {}).get(int(horizon))
        count = series in COUNT_SERIES and grain == COUNT_GRAIN
        for model in CANDIDATES:
            cand = group[group["model"] == model]
            if not len(cand):
                continue
            tot = cand["actual"].sum()
            bench, skill, n_common = _best_benchmark(cand, group)
            width = ((cand["upper90"] - cand["lower90"]) / cand["forecast"]).where(cand["forecast"] > 0)
            row = dict(
                block=block, grain=grain, series=series, horizon=int(horizon), model=model,
                n=len(cand),
                accuracy=1 - cand["error"].abs().sum() / tot if tot > 0 else np.nan,
                skill=skill, best_benchmark=bench, n_common=n_common,
                bias_pct=cand["error"].sum() / tot if tot > 0 else np.nan,
                coverage80=float(cand["covered80"].mean()) if cand["covered80"].notna().any() else np.nan,
                coverage90=float(cand["covered90"].mean()) if cand["covered90"].notna().any() else np.nan,
                n_coverage=int(cand["covered90"].notna().sum()),
                width90=float(width.mean()) if width.notna().any() else np.nan,
                deviance_ratio=_deviance_ratio(cand, group) if count else np.nan,
                target_accuracy=target.accuracy if target else np.nan,
            )
            primary = model in PRIMARY
            verdict, why = _verdict(row, target if primary else None, count and primary)
            cal = _calibrated(row["coverage80"], row["coverage90"])
            row.update(
                target=verdict, reasons=why,
                calibrated={True: "yes", False: "no", None: "n/a"}[cal],
                met=(verdict == "met" and (cal is True or count)),
            )
            rows.append(row)
    return pd.DataFrame(rows)


def confirm(card: pd.DataFrame, drop: float = CONFIRM_DROP) -> pd.DataFrame:
    """Development vs test accuracy per target row; confirmed if test >= dev - ``drop``."""
    keys = ["grain", "series", "horizon", "model"]
    dev = card[card["block"] == "development"].set_index(keys)
    test = card[card["block"] == "test"].set_index(keys)
    both = dev[["accuracy", "n", "target"]].join(test[["accuracy", "n"]], how="inner",
                                                rsuffix="_test")
    both = both[both["target"] != "no target"]
    interp = both["n_test"] >= MIN_PERIODS
    both["confirmed"] = np.where(~interp, "not interpretable",
                                 np.where(both["accuracy_test"] >= both["accuracy"] - drop, "yes", "no"))
    return both.reset_index()


def recovery_verdicts(errors: pd.DataFrame) -> pd.DataFrame:
    """One row per block x recovery target: n, accuracy and verdict. ``errors`` needs
    ``since_break`` (``episodes.add_recovery``); with a ``band`` column only verified
    periods count."""
    e = errors[errors["band"].isin(VERIFIED_BANDS)] if "band" in errors.columns else errors
    g = group_scores(e, "since_break")
    rows = []
    for (series, grain, horizon, bucket), target in RECOVERY_TARGETS.items():
        sel = g[(g["series"] == series) & (g["grain"] == grain) & (g["horizon"] == horizon)
                & (g["since_break"] == bucket)]
        for block in sorted(set(e["block"])) if "block" in e.columns else ["development"]:
            r = sel[sel["block"] == block]
            n = int(r["n"].iloc[0]) if len(r) else 0
            acc = float(r["accuracy"].iloc[0]) if len(r) else np.nan
            verdict = ("not interpretable" if n < MIN_PERIODS
                       else "met" if acc >= target else "missed")
            rows.append(dict(block=block, series=series, grain=grain, horizon=horizon,
                             since_break=bucket, n=n, accuracy=acc, target_accuracy=target,
                             target=verdict))
    return pd.DataFrame(rows)
