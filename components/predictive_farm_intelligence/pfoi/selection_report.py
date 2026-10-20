"""Aggregate-only selection diagnostics from saved development backtests.

By default no database is used. --quality on loads development quality aggregates
when the user runs it locally; never run that option as an AI agent.
Each selected forecast keeps intervals calibrated on that candidate's own past
errors, including its pre-2019 history, rather than mixing candidate histories.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re

import pandas as pd

from .episodes import add_bands, add_recovery, daily_quality
from .nested_cv import default_objectives, nested_select
from .scorecard import BENCHMARKS, prepare, recovery_verdicts, scorecard

CUTOFF = date(2024, 1, 1)
FAMILIES = {
    "milk": (("milk_baseline", "milk_baseline_corrected", "milk_baseline_adaptive",
              "milk_baseline_drivers", "milk_baseline_adaptive_drivers", "milk_baseline_calibrated"), ("herd_milk",)),
    "herd": (("herd_engine", "herd_engine_corrected", "herd_engine_adaptive"),
             ("milking", "n_herd", "calvings", "dry_offs")),
}
KEYS = ["origin", "period_start", "grain", "series", "horizon"]
COLUMNS = KEYS + ["period_end", "model", "forecast", "actual"]


def load_saved(folder: Path, family: str):
    """Only development error files; no environment settings or connection creation."""
    models, series = FAMILIES[family]
    pattern = re.compile(rf"{family}_backtest_errors_(monthly|weekly)_(.+)\.csv$")
    tags = {}
    for path in sorted(folder.glob(f"{family}_backtest_errors_*.csv")):
        match = pattern.fullmatch(path.name)
        if not match or match.group(2).endswith("_test"):
            continue
        f = pd.read_csv(path, usecols=COLUMNS)
        for col in ("origin", "period_start", "period_end"):
            f[col] = pd.to_datetime(f[col]).dt.date
        if (f["origin"] >= CUTOFF).any() or (f["period_end"] > CUTOFF).any():
            raise ValueError("Non-development dates found; selection report stopped")
        f = f[f["series"].isin(series)].copy()
        f["error"] = f["forecast"] - f["actual"]
        tags.setdefault(match.group(2), []).append(f)
    candidates, benchmarks = {}, []
    for tag, parts in tags.items():
        f = pd.concat(parts, ignore_index=True)
        benchmarks.append(f[f["model"].isin(BENCHMARKS)])
        for model in models:
            rows = f[f["model"] == model].copy()
            if not rows.empty:
                if rows.duplicated(KEYS).any():
                    raise ValueError("Duplicate candidate forecast keys; report stopped")
                candidates[f"{tag}/{model}"] = rows
    if len(candidates) < 2:
        raise ValueError("At least two saved development candidates are required")
    bench = pd.concat(benchmarks, ignore_index=True)
    # Benchmarks are repeated in variant files; never count those copies twice.
    bkeys = KEYS + ["model"]
    if not bench.empty:
        conflict = bench.groupby(bkeys)[["forecast", "actual"]].nunique(dropna=False)
        if (conflict > 1).any().any():
            raise ValueError("Conflicting benchmark copies; report stopped")
    return candidates, bench.drop_duplicates(bkeys)


def load_quality():
    """User-run, read-only quality inputs, confined to the development period."""
    from .data import DATA_START, SqlHerdSource

    source = SqlHerdSource.from_env()
    return daily_quality(source.target_daily(DATA_START, CUTOFF),
                         source.panel_daily(DATA_START, CUTOFF))


def _scoring_errors(policy, benchmarks, family, method, quality):
    policy = policy.copy()
    # Primary names let the existing scorecard apply the agreed target conditions.
    policy["model"] = "milk_baseline" if family == "milk" else "herd_engine"
    bench = prepare(benchmarks, method=method, quality=quality) if not benchmarks.empty else benchmarks
    errors = pd.concat([policy, bench], ignore_index=True)
    if quality is not None:
        errors = add_bands(errors, quality)
    return add_recovery(errors)


def fixed_scorecard(candidates, benchmarks, ranking, family, method, quality=None):
    """Descriptive development score of the winner; not independent validation."""
    winner = ranking.loc[ranking["selected"], "candidate"].iloc[0]
    full = prepare(candidates[winner], method=method, quality=quality)
    # Match the nested evaluation years; earlier history still calibrates intervals.
    full = full[pd.to_datetime(full["origin"]).dt.year.between(2019, 2023)]
    errors = _scoring_errors(full, benchmarks, family, method, quality)
    return winner, scorecard(errors)


def evaluate(candidates, benchmarks, family: str, method: str, quality=None):
    objectives = default_objectives(FAMILIES[family][1])
    nested = nested_select(candidates, objectives)
    if nested.summary["n"].eq(0).any():
        raise ValueError("Some nested objectives have zero coverage; repair coverage first")
    ranking = nested_select(candidates, objectives, fold_years=(2024,)).folds
    ranking = ranking.sort_values("inner_score", na_position="last")
    if not ranking["selected"].any():
        raise ValueError("Insufficient finished development outcomes for final selection")
    selected = nested.selected_rows
    calibrated = []
    for name in selected["candidate"].unique():
        # Calibrate on all of this candidate's history before selecting outer rows.
        full = prepare(candidates[name], method=method, quality=quality)
        wanted = selected.loc[selected["candidate"] == name, KEYS]
        calibrated.append(full.merge(wanted, on=KEYS, how="inner", validate="one_to_one"))
    policy = pd.concat(calibrated, ignore_index=True)
    errors = _scoring_errors(policy, benchmarks, family, method, quality)
    card = scorecard(errors)
    recovery = recovery_verdicts(errors) if family == "milk" else pd.DataFrame()
    return nested, ranking, card, recovery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("logs/pfoi_1_1_clean"))
    parser.add_argument("--family", choices=["milk", "herd", "both"], default="both")
    parser.add_argument("--intervals", choices=["empirical", "aci"], default="aci")
    parser.add_argument("--quality", choices=["off", "on"], default="off",
                        help="on: user-run read-only database quality check, development only")
    args = parser.parse_args(argv)
    quality = load_quality() if args.quality == "on" else None
    if quality is None:
        print("PROVISIONAL: all saved scoreable periods; no record-quality filtering;")
        print("ACI has no quality scaling. Not directly comparable to quality-filtered scorecards.")
    else:
        print("Quality-aware: scorecards judge normal + degraded periods; ACI uses origin quality.")
        print("Selection rankings remain based on the original common-period WAPE objective.")
    print("Nested scores evaluate year-by-year selection, not one fixed deployment model.")
    print("Final ranking uses only outcomes ended by 2024-01-01; it does not freeze a model.")
    families = ("milk", "herd") if args.family == "both" else (args.family,)
    for family in families:
        candidates, benchmarks = load_saved(args.out, family)
        nested, ranking, card, recovery = evaluate(candidates, benchmarks, family, args.intervals, quality)
        print(f"\n=== {family}: choices by validation year ===")
        print(nested.folds.loc[nested.folds["selected"],
                               ["fold_year", "candidate", "inner_score", "n_objectives"]]
              .to_string(index=False))
        print(f"\n=== {family}: final development ranking (lower WAPE is better) ===")
        print(ranking[["candidate", "inner_score", "n_objectives", "selected"]]
              .to_string(index=False, float_format=lambda v: f"{v:.4f}"))
        print(f"\n=== {family}: nested-policy scorecard, 2019-2023, {args.intervals} ===")
        cols = ["series", "grain", "horizon", "n", "accuracy", "target_accuracy", "skill",
                "best_benchmark", "bias_pct", "n_coverage", "coverage80", "coverage90",
                "width90", "target", "calibrated", "reasons"]
        print(card[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
        print(f"Target and calibrated: {int(card['met'].sum())} / {len(card)}")
        winner, fixed = fixed_scorecard(candidates, benchmarks, ranking, family, args.intervals, quality)
        print(f"\n=== {family}: selected fixed configuration: {winner} ===")
        print("DESCRIPTIVE 2019-2023: selected using overlapping development outcomes;")
        print("these scores are not independent validation of the fixed configuration.")
        print(fixed[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
        if not recovery.empty:
            label = "normal + degraded" if quality is not None else "no record-quality filtering"
            print(f"\n=== nested-policy recovery ({label}) ===")
            print(recovery.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
