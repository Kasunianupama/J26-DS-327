"""Command line for the herd engine. Run from the repository root, e.g.

    python -m components.predictive_farm_intelligence.pfoi.cli herd-rates --origin 2020-01-01
    python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain monthly
    python -m components.predictive_farm_intelligence.pfoi.cli milk-curve --origin 2021-06-01
    python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both
    python -m components.predictive_farm_intelligence.pfoi.cli milk-report

Database settings come from the root .env (APP_DB_* and APP_DB_PFOI_USER/PASSWORD). Output is aggregate only:
herd-level rates, totals and error metrics. Files go to logs/pfoi/ (gitignored).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from .backtest_herd import KEY_SERIES, development_origins, run_backtest, summarise
from .categories import STATE_TO_STOCK
from .config import EngineConfig
from .data import (
    DATA_START, SNAPSHOT_METHODS, SqlHerdSource, frames_match, load_origin_inputs,
    prefetch_snapshots, snapshot_dates,
)
from .periods import HORIZONS
from .rates import conception_per_ai, estimate_rates, max_live_gestation, rate_summary
from .backtest_milk import common_periods, run_milk_backtest, summarise_milk
from .lactation_curve import curve_summary
from .milk_baseline import CURVE_MODES, K_MODES, MilkConfig, MilkHistory, anchor_k, prepare_milk


def _window(value: str) -> int | None:
    return None if value == "expanding" else int(value)


def _cmd_herd_rates(args: argparse.Namespace) -> int:
    cfg = EngineConfig(window_months=_window(args.window))
    source = SqlHerdSource.from_env()
    origin = date.fromisoformat(args.origin)
    inputs = load_origin_inputs(source, origin, cfg)
    rates = estimate_rates(inputs.rate_inputs, cfg)
    totals = inputs.state.state_totals()
    print(f"Origin {origin}  window={args.window} months  (herd-level aggregates)")
    print(pd.Series({STATE_TO_STOCK[k]: round(v, 1) for k, v in totals.items()}).to_string())
    print(f"conception_per_ai    {conception_per_ai(inputs.rate_inputs):.3f}")
    print(f"max_live_gestation   {max_live_gestation(inputs.rate_inputs.gestation)} days")
    print("\nAnnualised rates:")
    print(rate_summary(rates).round(4).to_string(index=False))
    for note in (*inputs.notes, *rates.notes):
        print("NOTE:", note)
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    cfg = EngineConfig(window_months=_window(args.window))
    source = SqlHerdSource.from_env()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    grains = ("monthly", "weekly") if args.grain == "both" else (args.grain,)
    summaries = []
    for grain in grains:
        origins = development_origins(grain, every=args.every)

        def progress(i: int, n: int, origin: date) -> None:
            if i % 10 == 0:
                print(f"  {grain}: origin {i + 1}/{n} ({origin})", file=sys.stderr)

        result = run_backtest(source, grain, cfg, origins=origins, progress=progress)
        tag = f"{grain}_w{args.window}"
        result.errors.to_csv(out / f"herd_backtest_errors_{tag}.csv", index=False)
        summary = summarise(result.errors)
        summary.to_csv(out / f"herd_backtest_summary_{tag}.csv", index=False)
        summaries.append(summary)
        if len(result.notes):
            print(f"\nFallback notes ({grain}, number of origins affected):")
            print(result.notes.to_string(index=False))

    summary = pd.concat(summaries, ignore_index=True)
    key = summary[summary["series"].isin(KEY_SERIES)]
    table = key.pivot_table(index=["grain", "series", "horizon"], columns="model",
                            values="mae").round(2)
    table["n_origins"] = (key[key["model"] == "herd_engine"]
                          .set_index(["grain", "series", "horizon"])["n"])
    print("\nMAE by horizon (development block, herd level):")
    print(table.to_string())
    print(f"\nFull tables written to {out}/ (gitignored). Horizons: {HORIZONS}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    out = Path(args.out)
    for grain in ("monthly", "weekly"):
        path = out / f"herd_backtest_summary_{grain}_w{args.window}.csv"
        if not path.exists():
            print(f"(no {path.name}; run backtest-herd first)")
            continue
        s = pd.read_csv(path)
        eng = s[s["model"] == "herd_engine"].set_index(["series", "horizon"])
        per = s[s["model"] == "persistence"].set_index(["series", "horizon"])
        cor = s[s["model"] == "herd_engine_corrected"].set_index(["series", "horizon"])
        table = pd.DataFrame({
            "mae_engine": eng["mae"],
            "mae_persistence": per["mae"],
            "ratio": eng["mae"] / per["mae"],
            "ratio_corrected": cor["mae"] / per["mae"],
            "bias_engine": eng["bias"],
            "bias_corrected": cor["bias"],
        }).round(2).unstack("horizon")
        print(f"\n{grain}: ratio < 1 means the model beats persistence; "
              "bias > 0 means it forecasts too high")
        for col in ("ratio", "ratio_corrected", "bias_engine", "bias_corrected"):
            print(f"\n{col}")
            print(table[col].to_string())
    return 0


def _milk_cfg(args: argparse.Namespace) -> MilkConfig:
    return MilkConfig(curve_mode=args.curve, pregnancy_factor=args.pregnancy_factor == "on",
                      generation_factor=args.generation_factor == "on", k_mode=args.k)


def _cmd_milk_curve(args: argparse.Namespace) -> int:
    source = SqlHerdSource.from_env()
    origin = date.fromisoformat(args.origin)
    mcfg = _milk_cfg(args)
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, origin),
                       target=source.target_daily(DATA_START, origin))
    setup = prepare_milk(source, origin, mcfg, hist)
    inputs = load_origin_inputs(source, origin, EngineConfig(window_months=_window(args.window)))
    anchor_k(setup, hist.target_before(origin), inputs.state, mcfg)
    print(f"Origin {origin}  curve source: {setup.curve.source}  ({mcfg.tag()})")
    print(curve_summary(setup.curve).round(4).to_string(index=False))
    if setup.curve.preg_factor:
        print("pregnancy factor (days pregnant >= band):", {k: round(v, 3) for k, v in setup.curve.preg_factor.items()})
    if mcfg.generation_factor:
        print("generation factor:", setup.curve.gen_factor.round(3).tolist())
    print(f"k = {setup.k:.3f} ({setup.k_source}); current target source: {setup.target_source}")
    for note in (*setup.notes, *setup.flags):
        print("NOTE:", note)
    return 0


def _cmd_backtest_milk(args: argparse.Namespace) -> int:
    cfg = EngineConfig(window_months=_window(args.window))
    mcfg = _milk_cfg(args)
    source = SqlHerdSource.from_env()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    origin_grains = ("monthly", "weekly") if args.grain == "both" else (args.grain,)
    jobs = args.jobs if args.jobs > 0 else max(1, (os.cpu_count() or 2) - 1)
    for og in origin_grains:
        origins = development_origins(og, every=args.every)

        def progress(i: int, n: int, origin: date) -> None:
            if i % 10 == 0:
                print(f"  {og}: origin {i + 1}/{n} ({origin})", file=sys.stderr)

        res = run_milk_backtest(source, og, cfg, mcfg, origins=origins, progress=progress,
                                jobs=jobs, source_factory=SqlHerdSource.from_env)
        tag = f"{og}_{mcfg.tag()}_w{args.window}"
        res.errors.to_csv(out / f"milk_backtest_errors_{tag}.csv", index=False)
        summarise_milk(res.errors).to_csv(out / f"milk_backtest_summary_{tag}.csv", index=False)
        summarise_milk(res.errors, by_source=True).to_csv(
            out / f"milk_backtest_summary_by_source_{tag}.csv", index=False)
        if len(res.notes):
            print(f"\nNotes ({og} origins, number of origins):")
            print(res.notes.to_string(index=False))
    print(f"\nDone. Run milk-report with the same options to see the H1 table. Files in {out}/.")
    return 0


def _cmd_check_snapshots(args: argparse.Namespace) -> int:
    """Batched vs per-origin snapshots on a sample of origins; prints counts only."""
    cfg = EngineConfig()
    source = SqlHerdSource.from_env()
    origins = development_origins(args.grain)[::args.every]
    snaps = prefetch_snapshots(source, origins, cfg)
    lag = cfg.pregnancy_check_lag_days
    checked, bad = 0, {}
    for o in origins:
        asof, ku = snapshot_dates(o, cfg)
        single = dict(cells_on=source.cells_on(asof), milking_clock=source.milking_clock(asof, ku),
                      dry_clock=source.dry_clock(asof, ku),
                      heifer_clock=source.heifer_clock(asof, ku, lag),
                      calf_sex_on=source.calf_sex_on(asof))
        for name, a in single.items():
            key = {"cells_on": (name, asof), "calf_sex_on": (name, asof),
                   "heifer_clock": (name, asof, ku, lag)}.get(name, (name, asof, ku))
            b = snaps[key]
            checked += 1
            if not frames_match(a, b):
                bad[name] = bad.get(name, 0) + 1
    print(f"origins: {len(origins)}, snapshot pairs checked: {checked}")
    for name in SNAPSHOT_METHODS:
        print(f"  {name}: mismatching origins = {bad.get(name, 0)}")
    return 1 if bad else 0


def _cmd_milk_report(args: argparse.Namespace) -> int:
    mcfg = _milk_cfg(args)
    out = Path(args.out)
    for og in ("monthly", "weekly"):
        path = out / f"milk_backtest_summary_{og}_{mcfg.tag()}_w{args.window}.csv"
        if not path.exists():
            print(f"(no {path.name}; run backtest-milk first)")
            continue
        s = pd.read_csv(path)
        for grain, g in s.groupby("grain", sort=False):
            mae = g.pivot_table(index="horizon", columns="model", values="mae")
            ratio = mae.div(mae["persistence"], axis=0) if "persistence" in mae else mae
            print(f"\n=== {grain} ({mcfg.tag()}, window {args.window}) — litres per period ===")
            print("MAE:")
            print(mae.round(0).to_string())
            print("MAE ratio vs persistence (< 1 = better):")
            print(ratio.round(2).to_string())
            for col, label in (("bias", "bias (forecast - actual)"), ("mape_pct", "MAPE %"),
                               ("coverage_pct", "90% interval coverage %"), ("n", "n periods scored")):
                print(f"{label}:")
                print(g.pivot_table(index="horizon", columns="model", values=col).round(1).to_string())
        _print_common_periods(out / f"milk_backtest_errors_{og}_{mcfg.tag()}_w{args.window}.csv")
    return 0


def _print_common_periods(path: Path) -> None:
    """H1 table on the same periods for every model (fair comparison)."""
    if not path.exists():
        return
    e = pd.read_csv(path)
    all_models = sorted(set(e["model"]))
    variants = [("all models", all_models)]
    if "sarima" in all_models:
        variants.append(("all models except SARIMA", [m for m in all_models if m != "sarima"]))
    for label, models in variants:
        s = summarise_milk(common_periods(e, models))
        if not len(s):
            continue
        for grain, g in s.groupby("grain", sort=False):
            mae = g.pivot_table(index="horizon", columns="model", values="mae")
            n = g.pivot_table(index="horizon", columns="model", values="n").iloc[:, 0]
            table = mae.div(mae["persistence"], axis=0).round(2)
            table["n_periods"] = n.astype(int)
            print(f"\n=== {grain}: COMMON PERIODS ({label}) — MAE ratio vs persistence ===")
            print(table.to_string(float_format=lambda v: f"{v:.2f}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pfoi")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("herd-rates", help="rates and starting herd at one origin")
    p.add_argument("--origin", required=True, help="YYYY-MM-DD")
    p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
    p.set_defaults(func=_cmd_herd_rates)

    p = sub.add_parser("backtest-herd", help="rolling-origin backtest, development block")
    p.add_argument("--grain", default="both", choices=["monthly", "weekly", "both"])
    p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
    p.add_argument("--every", type=int, default=1, help="use every n-th origin")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_backtest)

    p = sub.add_parser("herd-report", help="ratio and bias tables from a finished backtest")
    p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_report)

    def milk_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--curve", default="herd_fitted", choices=list(CURVE_MODES),
                       help="shape before 2020-09 (fitted_everywhere = sensitivity only)")
        p.add_argument("--pregnancy-factor", default="on", choices=["on", "off"])
        p.add_argument("--generation-factor", default="off", choices=["on", "off"])
        p.add_argument("--k", default="anchored", choices=list(K_MODES),
                       help="anchored = last 14 scoreable days; window = 12-month k")
        p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
        p.add_argument("--out", default="logs/pfoi")

    p = sub.add_parser("milk-curve", help="lactation curve and k at one origin")
    p.add_argument("--origin", required=True, help="YYYY-MM-DD")
    milk_opts(p)
    p.set_defaults(func=_cmd_milk_curve)

    p = sub.add_parser("backtest-milk", help="rolling-origin milk backtest, development block")
    p.add_argument("--grain", default="both", choices=["monthly", "weekly", "both"],
                   help="origin grain; weekly origins also score daily horizons")
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--jobs", type=int, default=1,
                   help="processes for scoring origins (0 = CPU cores - 1); each opens "
                        "its own read-only database connection")
    milk_opts(p)
    p.set_defaults(func=_cmd_backtest_milk)

    p = sub.add_parser("check-snapshots", help="batched vs per-origin snapshot queries (counts only)")
    p.add_argument("--grain", default="weekly", choices=["monthly", "weekly"])
    p.add_argument("--every", type=int, default=10, help="check every n-th origin")
    p.set_defaults(func=_cmd_check_snapshots)

    p = sub.add_parser("milk-report", help="H1 table from a finished milk backtest")
    milk_opts(p)
    p.set_defaults(func=_cmd_milk_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
