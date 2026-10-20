"""User-run aggregate diagnostics of saved development forecasts; no training or writes."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .episodes import add_bands, add_recovery
from .scorecard import BENCHMARKS

KEYS = ["origin", "period_start", "period_end", "grain", "horizon"]


def load_tag(folder, family, tag):
    if not re.fullmatch(r"[A-Za-z0-9_.]+", tag) or tag.endswith("_test"):
        raise ValueError("A development tag is required")
    paths = [Path(folder) / f"{family}_backtest_errors_{g}_{tag}.csv"
             for g in ("monthly", "weekly")]
    if not all(p.is_file() for p in paths):
        raise ValueError(f"Both monthly and weekly {family} files are required")
    rows = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    for col in ("origin", "period_start", "period_end"):
        rows[col] = pd.to_datetime(rows[col], errors="raise")
        if rows[col].isna().any():
            raise ValueError("Missing forecast dates")
    cutoff = pd.Timestamp("2024-01-01")
    if (rows.origin.ge(cutoff).any() or rows.period_end.gt(cutoff).any()
            or rows.period_end.le(rows.origin).any()):
        raise ValueError("Development forecasts only, with completed outcomes by 2024-01-01")
    if rows.duplicated(KEYS + ["series", "model"]).any():
        raise ValueError("Duplicate forecast keys")
    return rows


def metrics(g):
    valid = np.isfinite(g.forecast) & np.isfinite(g.actual) & g.actual.ge(0)
    x = g[valid]
    err = x.forecast - x.actual
    total = x.actual.sum()
    ape = err.abs() / x.actual.where(x.actual.gt(0))
    return dict(n=len(x), excluded=len(g)-len(x), mae=err.abs().mean(),
                rmse=np.sqrt((err**2).mean()),
                wape_pct=100*err.abs().sum()/total if total > 0 else np.nan,
                bias_pct=100*err.sum()/total if total > 0 else np.nan,
                p90_ape_pct=100*ape.quantile(.9),
                positive_actual_n=int(ape.notna().sum()),
                misses_over_20pct=100*ape.dropna().gt(.2).mean())


def grouped(rows, groups):
    return pd.DataFrame([dict(zip(groups, key if isinstance(key, tuple) else (key,)), **metrics(g))
                         for key, g in rows.groupby(groups, dropna=False)])


def benchmark_pairs(base, all_rows):
    """Each benchmark gets its own matched sample; expose absent fits explicitly."""
    result = []
    for (grain, horizon), g in base.groupby(["grain", "horizon"]):
        for name in BENCHMARKS:
            b = all_rows[(all_rows.model == name) & (all_rows.series == "herd_milk")]
            matched = g.merge(b[KEYS + ["forecast", "actual"]], on=KEYS,
                              suffixes=("", "_benchmark"), validate="one_to_one")
            if not np.allclose(matched.actual, matched.actual_benchmark, equal_nan=True):
                raise ValueError("Benchmark and model actuals disagree")
            matched = matched[np.isfinite(matched.forecast) & np.isfinite(matched.forecast_benchmark)
                              & np.isfinite(matched.actual) & matched.actual.ge(0)]
            for label in ("current", name):
                x = matched.copy()
                if label != "current":
                    x["forecast"] = x.forecast_benchmark
                result.append(dict(grain=grain, horizon=horizon, comparison=name, model=label,
                                   available_current=len(g), missing_pair=len(g)-len(x), **metrics(x)))
    return pd.DataFrame(result)


def paired_counts(milk, herd):
    """Aligned cow-count errors, not a causal or per-cow yield decomposition."""
    h = herd[(herd.series == "milking") & (herd.model == "herd_engine")]
    m = milk.merge(h[KEYS + ["forecast", "actual"]], on=KEYS,
                   suffixes=("", "_cows"), validate="one_to_one")
    rows = []
    for (grain, horizon), g in m.groupby(["grain", "horizon"]):
        valid = (np.isfinite(g.forecast) & np.isfinite(g.actual) & g.actual.gt(0)
                 & np.isfinite(g.forecast_cows) & np.isfinite(g.actual_cows) & g.actual_cows.gt(0))
        x = g[valid]
        milk_error = x.forecast/x.actual-1
        cow_error = x.forecast_cows/x.actual_cows-1
        corr = milk_error.corr(cow_error) if len(x) > 2 and milk_error.std() > 0 and cow_error.std() > 0 else np.nan
        rows.append(dict(grain=grain, horizon=horizon, matched_n=len(x),
                         mean_milk_error_pct=100*milk_error.mean(),
                         mean_cow_error_pct=100*cow_error.mean(),
                         cow_mae=(x.forecast_cows-x.actual_cows).abs().mean(),
                         error_correlation=corr))
    return pd.DataFrame(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--model", default="milk_baseline_adaptive")
    parser.add_argument("--herd-tag", required=True, help="Uncorrected herd tag underlying this milk model")
    parser.add_argument("--out", default="logs/pfoi_1_1_clean")
    parser.add_argument("--quality", choices=["on", "off"], default="off")
    args = parser.parse_args(argv)
    errors = load_tag(args.out, "milk", args.tag)
    herd = load_tag(args.out, "herd", args.herd_tag)
    base = errors[(errors.model == args.model) & (errors.series == "herd_milk")].copy()
    if base.empty:
        raise ValueError("Requested milk model has no forecasts")
    if args.quality == "on":
        from .selection_report import load_quality
        base = add_bands(base, load_quality())
        print("=== quality counts before filtering ===")
        print(base.groupby(["grain", "horizon", "band"]).size().rename("n").to_string())
        base = base[base.band.isin(["normal", "degraded"])].copy()
    base = add_recovery(base)
    base["origin_year"] = base.origin.dt.year
    base["target_year"] = base.period_start.dt.year
    for label, groups in (
        ("errors by forecast issue year", ["grain", "horizon", "origin_year"]),
        ("errors by target year", ["grain", "horizon", "target_year"]),
        ("errors by latest known break at issue date", ["grain", "horizon", "last_break", "since_break"]),
    ):
        print(f"\n=== {label} (MAE/RMSE in litres) ===")
        print(grouped(base, groups).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\n=== pairwise statistical benchmarks, matched periods (litres) ===")
    print(benchmark_pairs(base, errors).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    for year_field in ("origin_year", "target_year"):
        yearly = [benchmark_pairs(part, errors).assign(**{year_field: year})
                  for year, part in base.groupby(year_field)]
        print(f"\n=== matched benchmarks by {year_field} (litres) ===")
        if yearly:
            print(pd.concat(yearly, ignore_index=True).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\n=== milk versus underlying mean milking-cow count errors ===")
    print(paired_counts(base, herd).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("Cow counts are full-period daily means. Milk can exclude unscoreable days.")
    print("These associations do not separate causal yield and count contributions. Exact decomposition needs aligned cow-days and daily milk projections.")
    print("Break buckets describe the latest known break at issuance; overlapping episodes are not causal comparisons.")
    print("Each benchmark pair may cover different periods; compare within pairs. No model or database was updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
