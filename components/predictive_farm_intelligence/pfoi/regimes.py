"""Milk errors by recording regime, from saved backtest error files (no database, no writes).

The milk target is not one series. Shipments (to Jul 2022) and DelPro (from Aug 2022) measure
different things, and DelPro has a long data gap in 2024 (see docs/milk_model.md). A pooled MAE
hides which regime a model wins or loses in, so this report scores each regime on its own, with
its own n and bias, and counts how often a run had to fall back on a weaker level (flags).

T0 cells use origin source x target source, with shipment split at Aug 2020
by origin date and cross-source forecasts reported separately. Calendar boundaries
are descriptive until checked with origin-known daily inputs. See regime_cells.py.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .regime_cells import (
    BREAK_START, GAP_START, RESUME, SHIPMENT, SHIPMENT_EARLY, CROSS_BREAK,
    DELPRO_EARLY, GAP, DELPRO_LATE, REGIME_ORDER, assign_regime,
)

TEST_START = pd.Timestamp("2024-01-01")
SMALL_N = 10
KEYS = ["grain", "horizon", "origin", "period_start"]
FLAGS = ("source_switch", "no_same_source_k", "k_window", "no_window_k")


def _prepare(errors: pd.DataFrame) -> pd.DataFrame:
    need = {"model", "grain", "horizon", "origin", "period_start", "forecast", "actual", "source"}
    missing = need - set(errors.columns)
    if missing:
        raise ValueError(f"error file lacks columns: {sorted(missing)}")
    e = errors.copy()
    for col in ("origin", "period_start"):
        e[col] = pd.to_datetime(e[col], format="mixed")
    dup = int(e.duplicated(KEYS + ["model"]).sum())
    if dup:
        raise ValueError(
            f"{dup} forecasts appear more than once: the files mix configurations (for example "
            "several window tags) or overlap in time. Pass the error files of ONE run only "
            "(one tag; monthly and weekly files of the same run, plus its posthoc file if wanted). "
            "List them with: ls logs/pfoi | grep milk_backtest_errors")
    e["regime"] = assign_regime(e["period_start"], e["source"], e["origin"],
                                 e.get("origin_source"))
    e["error"] = e["forecast"] - e["actual"]
    return e


def regime_table(errors: pd.DataFrame, model: str = "milk_baseline",
                 reference: str = "persistence") -> pd.DataFrame:
    """Per regime x grain x horizon: n, MAE, bias (litres and % of actual), MAE ratio against
    ``reference`` on the periods both models forecast, and a small-n flag."""
    e = _prepare(errors)
    base = e[e["model"] == model]
    ref = e[e["model"] == reference]
    rows = []
    for (regime, grain, horizon), g in base.groupby(["regime", "grain", "horizon"]):
        r = ref[(ref["regime"] == regime) & (ref["grain"] == grain) & (ref["horizon"] == horizon)]
        common = g.merge(r[KEYS + ["error"]], on=KEYS, suffixes=("", "_ref"))
        total = g["actual"].sum()
        rows.append(dict(
            regime=regime, grain=grain, horizon=horizon, n=len(g),
            mae=g["error"].abs().mean(), bias=g["error"].mean(),
            bias_pct=100 * g["error"].sum() / total if total > 0 else np.nan,
            n_common=len(common),
            mae_ratio=(common["error"].abs().mean() / common["error_ref"].abs().mean()
                       if len(common) and common["error_ref"].abs().mean() > 0 else np.nan),
            small_n=len(g) < SMALL_N))
    out = pd.DataFrame(rows)
    if len(out):
        out["_o"] = out["regime"].map({k: i for i, k in enumerate(REGIME_ORDER)}).fillna(99)
        out = out.sort_values(["_o", "grain", "horizon"]).drop(columns="_o").reset_index(drop=True)
    return out


def matched_table(a: pd.DataFrame, b: pd.DataFrame, model: str = "milk_baseline",
                  model_b: str | None = None) -> pd.DataFrame:
    """Run A against run B (for example borrow-k on vs off) on the periods BOTH forecast, per
    regime x grain x horizon. A run that refuses to forecast some periods scores fewer, easier
    or harder ones, so a raw before/after comparison is not fair. Also shown: how many periods
    only A or only B forecast, and A's MAE on the periods B did not forecast (what B declined)."""
    ea, eb = _prepare(a), _prepare(b)
    ea, eb = ea[ea["model"] == model], eb[eb["model"] == (model_b or model)]
    both = ea.merge(eb[KEYS + ["error", "regime", "actual", "source"]], on=KEYS,
                    how="outer", suffixes=("_a", "_b"), indicator=True)
    common = both["_merge"] == "both"
    if ((both.loc[common, "regime_a"] != both.loc[common, "regime_b"]).any()
            or (both.loc[common, "source_a"] != both.loc[common, "source_b"]).any()
            or not np.allclose(both.loc[common, "actual_a"], both.loc[common, "actual_b"])):
        raise ValueError("matched runs disagree on regime, source or actual")
    both["regime"] = both["regime_a"].fillna(both["regime_b"])
    rows = []
    for (regime, grain, horizon), g in both.groupby(["regime", "grain", "horizon"]):
        m = g[g["_merge"] == "both"]
        only_a = g[g["_merge"] == "left_only"]
        rows.append(dict(
            regime=regime, grain=grain, horizon=horizon, n_both=len(m),
            mae_a=m["error_a"].abs().mean(), mae_b=m["error_b"].abs().mean(),
            bias_a=m["error_a"].mean(), bias_b=m["error_b"].mean(),
            bias_pct_a=100 * m["error_a"].sum() / m["actual_a"].sum() if m["actual_a"].sum() > 0 else np.nan,
            bias_pct_b=100 * m["error_b"].sum() / m["actual_b"].sum() if m["actual_b"].sum() > 0 else np.nan,
            only_a=len(only_a), mae_a_on_only_a=only_a["error_a"].abs().mean() if len(only_a) else np.nan,
            only_b=int((g["_merge"] == "right_only").sum()), small_n=len(m) < SMALL_N))
    out = pd.DataFrame(rows)
    if len(out):
        out["_o"] = out["regime"].map({k: i for i, k in enumerate(REGIME_ORDER)}).fillna(99)
        out = out.sort_values(["_o", "grain", "horizon"]).drop(columns="_o").reset_index(drop=True)
    return out


def flag_table(errors: pd.DataFrame, model: str = "milk_baseline") -> pd.DataFrame:
    """Share (%) of scored forecasts per regime that carried each fallback flag. Needs the
    ``flags`` column that backtest-milk writes."""
    if "flags" not in errors.columns:
        return pd.DataFrame()
    e = _prepare(errors)
    e = e[e["model"] == model]
    flags = e["flags"].fillna("").astype(str)
    out = pd.DataFrame({"regime": e["regime"]})
    for f in FLAGS:
        out[f] = flags.str.split(";").map(lambda parts, f=f: f in parts)
    g = out.groupby("regime")
    res = (100 * g[list(FLAGS)].mean()).round(1)
    res.insert(0, "n", g.size())
    return res.reset_index()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", help="milk_backtest_errors_*.csv (development and/or posthoc)")
    p.add_argument("--model", default="milk_baseline")
    p.add_argument("--reference", default="persistence")
    p.add_argument("--model-b", default=None,
                   help="compare --model (A) with this model (B) on the same periods, from the same "
                        "files (for example milk_baseline_adaptive_blend)")
    p.add_argument("--against", nargs="+", default=None, metavar="FILE",
                   help="error files of a second run (for example --borrow-k off): compare it with "
                        "the first on the periods both forecast")
    p.add_argument("--block", choices=("development", "posthoc"), default="development",
                   help="filter by issuance date; later targets remain descriptive")
    p.add_argument("--source-basis", choices=("timeline", "calibration"), default="timeline",
                   help="calibration reproduces Appendix F's k_source proxy; borrowed k is not issuance source")
    args = p.parse_args(argv)

    def load(names):
        paths = [Path(f) for f in names]
        bad = [str(f) for f in paths if not f.is_file()]
        if bad:
            raise ValueError(f"not found: {bad}")
        frame = pd.concat([pd.read_csv(f) for f in paths], ignore_index=True)
        origins = pd.to_datetime(frame["origin"], format="mixed")
        mask = ((origins >= "2017-01-01") & (origins < TEST_START)
                if args.block == "development" else origins >= TEST_START)
        if args.block == "development":
            mask &= pd.to_datetime(frame["period_start"], format="mixed") < TEST_START
            if "period_end" in frame:
                mask &= pd.to_datetime(frame["period_end"], format="mixed") <= TEST_START
        frame = frame.loc[mask].copy()
        if args.source_basis == "calibration":
            if "k_source" not in frame:
                raise ValueError("calibration-source sensitivity requires k_source")
            frame["origin_source"] = frame["k_source"].astype("string").str.removeprefix("anchored:")
        return frame

    errors = load(args.files)
    print(f"Block: {args.block}. Calendar cells are descriptive, not detected breaks.")
    if args.source_basis == "calibration":
        print("APPENDIX F SENSITIVITY: origin source is the k_source proxy, including borrowed levels.")
    if "origin_source" not in errors:
        print("Origin source inferred from the documented Aug 2022 timeline; k_source may be borrowed.")
    if args.block == "posthoc":
        print("POST-HOC ONLY: do not use these results to choose a model.")
    if pd.to_datetime(errors["period_start"]).ge(TEST_START).any():
        print("Targets from 2024 onward are descriptive only, including those issued in development.")
    if args.against or args.model_b:
        other = load(args.against) if args.against else errors
        print(f"=== A = {args.model} (first files) vs B = {args.model_b or args.model} "
              f"({'--against files' if args.against else 'same files'}), periods both forecast; "
              "only_a = periods B did not forecast, with A's MAE on them ===")
        print(matched_table(errors, other, args.model, args.model_b).to_string(
            index=False, float_format=lambda x: f"{x:,.2f}"))
        print("\nNo database was opened and nothing was written.")
        return 0
    if pd.to_datetime(errors["period_start"]).ge(TEST_START).any():
        print("NOTE: these files include periods from 2024-01-01 (post-hoc / test block). "
              "Treat those rows as descriptive, not as development results.\n")
    table = regime_table(errors, args.model, args.reference)
    print(f"=== {args.model} by regime (MAE and bias in litres per period; "
          f"mae_ratio < 1 beats {args.reference} on the same periods) ===")
    print(table.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\nsmall_n = fewer than {SMALL_N} periods: do not read the ratio. Overlapping horizons "
          "from neighbouring origins are not independent samples.")
    flags = flag_table(errors, args.model)
    if len(flags):
        print("\n=== share of forecasts (%) that fell back on a weaker level, by regime ===")
        print(flags.to_string(index=False))
    print("\nNo database was opened and nothing was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
