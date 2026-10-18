"""Command line for the herd engine. Run from the repository root, e.g.

    python -m components.predictive_farm_intelligence.pfoi.cli herd-rates --origin 2020-01-01
    python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain monthly

Database settings come from the root .env (APP_DB_* and APP_DB_PFOI_USER/PASSWORD). Output is aggregate only:
herd-level rates, totals and error metrics. Files go to logs/pfoi/ (gitignored).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from .backtest_herd import KEY_SERIES, development_origins, run_backtest, summarise
from .categories import STATE_TO_STOCK
from .config import EngineConfig
from .data import SqlHerdSource, load_origin_inputs
from .periods import HORIZONS
from .rates import conception_per_ai, estimate_rates, max_live_gestation, rate_summary


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
        table = pd.DataFrame({
            "mae_engine": eng["mae"],
            "mae_persistence": per["mae"],
            "ratio": eng["mae"] / per["mae"],
            "bias_engine": eng["bias"],
        }).round(2).unstack("horizon")
        print(f"\n{grain}: ratio < 1 means the engine beats persistence; "
              "bias > 0 means it forecasts too high")
        for col in ("ratio", "bias_engine"):
            print(f"\n{col}")
            print(table[col].to_string())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pfoi")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("herd-rates", help="rates and starting herd at one origin")
    p.add_argument("--origin", required=True, help="YYYY-MM-DD")
    p.add_argument("--window", default="24", choices=["12", "24", "36", "expanding"])
    p.set_defaults(func=_cmd_herd_rates)

    p = sub.add_parser("backtest-herd", help="rolling-origin backtest, development block")
    p.add_argument("--grain", default="both", choices=["monthly", "weekly", "both"])
    p.add_argument("--window", default="24", choices=["12", "24", "36", "expanding"])
    p.add_argument("--every", type=int, default=1, help="use every n-th origin")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_backtest)

    p = sub.add_parser("herd-report", help="ratio and bias tables from a finished backtest")
    p.add_argument("--window", default="24", choices=["12", "24", "36", "expanding"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
