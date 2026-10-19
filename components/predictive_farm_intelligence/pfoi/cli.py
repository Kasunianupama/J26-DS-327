"""Command line for the herd engine. Run from the repository root, e.g.

    python -m components.predictive_farm_intelligence.pfoi.cli herd-rates --origin 2020-01-01
    python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain monthly
    python -m components.predictive_farm_intelligence.pfoi.cli milk-curve --origin 2021-06-01
    python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both
    python -m components.predictive_farm_intelligence.pfoi.cli milk-report
    python -m components.predictive_farm_intelligence.pfoi.cli explain-milk --origin 2023-06-01
    python -m components.predictive_farm_intelligence.pfoi.cli explain-herd --origin 2023-06-01
    python -m components.predictive_farm_intelligence.pfoi.cli explain-generation --origin 2023-06-01

Database settings come from the root .env (APP_DB_* and APP_DB_PFOI_USER/PASSWORD). Output is aggregate only:
herd-level rates, totals and error metrics. Files go to logs/pfoi/ (gitignored).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from .backtest_herd import KEY_SERIES, TEST_START, development_origins, run_backtest, summarise
from .categories import STATE_TO_STOCK
from .config import EngineConfig
from .parallel import resolve_jobs
from .data import (
    DATA_START, SNAPSHOT_METHODS, SqlHerdSource, add_months, check_before, frames_match,
    load_origin_inputs, month_start, prefetch_snapshots, snapshot_dates,
)
from .periods import HORIZONS
from .rates import conception_per_ai, estimate_rates, max_live_gestation, rate_summary
from .backtest_milk import common_periods, run_milk_backtest, summarise_milk
from .attribution import (
    calving_split, expected_mastitis, explain_forecast_milk, explain_past_milk,
    generation_composition, herd_flows, mastitis_rates, starting_mix,
)
from .herd_engine import project
from .milk_baseline import monthly_target
from .lactation_curve import curve_summary
from .milk_baseline import CURVE_MODES, K_MODES, MilkConfig, MilkHistory, anchor_k, prepare_milk


def _window(value: str) -> int | None:
    return None if value == "expanding" else int(value)


def _engine_cfg(args: argparse.Namespace) -> EngineConfig:
    return EngineConfig(window_months=_window(args.window),
                        conception_cut=getattr(args, "conception_cut", "origin"),
                        cell_table=getattr(args, "cell_table", "day_cell"),
                        conception_known=getattr(args, "conception_known", "lag"),
                        pregnancy_check_lag_days=getattr(args, "pregnancy_lag", 35))


def _source(args: argparse.Namespace) -> SqlHerdSource:
    return SqlHerdSource.from_env(cell_table=getattr(args, "cell_table", "day_cell"),
                                  conception_known=getattr(args, "conception_known", "lag"))


def _source_factory(args: argparse.Namespace):
    """Picklable factory for worker processes, reading the same cell table."""
    from functools import partial
    return partial(SqlHerdSource.from_env, cell_table=getattr(args, "cell_table", "day_cell"),
                   conception_known=getattr(args, "conception_known", "lag"))


def _wtag(args: argparse.Namespace) -> str:
    """Window part of output file names; ``_ck`` marks conception_cut=known."""
    ck = "_ck" if getattr(args, "conception_cut", "origin") == "known" else ""
    kn = "_kn" if getattr(args, "cell_table", "day_cell") == "day_cell_known" else ""
    rk = "_rk" if getattr(args, "conception_known", "lag") == "recorded" else ""
    lag = getattr(args, "pregnancy_lag", 35)
    lg = f"_lag{lag}" if lag != 35 else ""
    return f"w{args.window}{ck}{kn}{rk}{lg}"


def _bt(args: argparse.Namespace) -> str:
    """File-name suffix for the final test block."""
    return "_test" if getattr(args, "block", "development") == "test" else ""


def _block_setup(args, grain: str, name: str, cfg, mcfg=None):
    """Origins, score_until, marker and prior errors for the chosen block."""
    from .freeze import (
        DATA_END, FROZEN_ENGINE, FROZEN_MILK, config_hash, final_test_origins, guard_final_test,
    )
    if args.block == "development":
        return development_origins(grain, every=args.every), TEST_START, None, False, None
    if cfg != FROZEN_ENGINE or (mcfg is not None and mcfg != FROZEN_MILK):
        raise SystemExit("the final test block runs only on the frozen configuration "
                         f"(model {config_hash()}); drop the non-default options")
    marker, rerun = guard_final_test(Path(args.out), f"{name}_{grain}", args.force)
    prior_path = Path(args.out) / (f"herd_backtest_errors_{grain}_{_wtag(args)}.csv" if mcfg is None
                                   else f"milk_backtest_errors_{grain}_{mcfg.tag()}_{_wtag(args)}.csv")
    prior = pd.read_csv(prior_path) if prior_path.exists() else None
    if prior is None:
        print(f"NOTE: {prior_path.name} not found: corrections and intervals start without "
              "development errors", file=sys.stderr)
    if rerun:
        print("WARNING: final test block is being RE-RUN (--force); this will be reported.",
              file=sys.stderr)
    return final_test_origins(grain, every=args.every), DATA_END, marker, rerun, prior


def _cmd_herd_rates(args: argparse.Namespace) -> int:
    cfg = _engine_cfg(args)
    source = _source(args)
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
    cfg = _engine_cfg(args)
    source = _source(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    grains = ("monthly", "weekly") if args.grain == "both" else (args.grain,)
    summaries = []
    for grain in grains:
        origins, score_until, marker, rerun, prior = _block_setup(args, grain, "herd", cfg)

        def progress(i: int, n: int, origin: date) -> None:
            if i % 10 == 0:
                print(f"  {grain}: origin {i + 1}/{n} ({origin})", file=sys.stderr)

        result = run_backtest(source, grain, cfg, origins=origins, progress=progress,
                              score_until=score_until, block=args.block, prior_errors=prior,
                              jobs=resolve_jobs(args.jobs), source_factory=_source_factory(args))
        tag = f"{grain}_{_wtag(args)}{_bt(args)}"
        result.errors.to_csv(out / f"herd_backtest_errors_{tag}.csv", index=False)
        summary = summarise(result.errors)
        summary.to_csv(out / f"herd_backtest_summary_{tag}.csv", index=False)
        summaries.append(summary)
        if marker is not None:
            from .freeze import record_final_test
            record_final_test(marker, rerun, [f"herd_backtest_summary_{tag}.csv"], len(origins))
        if len(result.notes):
            print(f"\nFallback notes ({grain}, number of origins affected):")
            print(result.notes.to_string(index=False))

    summary = pd.concat(summaries, ignore_index=True)
    key = summary[summary["series"].isin(KEY_SERIES)]
    table = key.pivot_table(index=["grain", "series", "horizon"], columns="model",
                            values="mae").round(2)
    table["n_origins"] = (key[key["model"] == "herd_engine"]
                          .set_index(["grain", "series", "horizon"])["n"])
    print(f"\nMAE by horizon ({args.block} block, herd level):")
    print(table.to_string())
    print(f"\nFull tables written to {out}/ (gitignored). Horizons: {HORIZONS}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    out = Path(args.out)
    for grain in ("monthly", "weekly"):
        path = out / f"herd_backtest_summary_{grain}_{_wtag(args)}{_bt(args)}.csv"
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
    source = _source(args)
    origin = date.fromisoformat(args.origin)
    mcfg = _milk_cfg(args)
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, origin),
                       target=source.target_daily(DATA_START, origin))
    setup = prepare_milk(source, origin, mcfg, hist)
    inputs = load_origin_inputs(source, origin, _engine_cfg(args))
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
    cfg = _engine_cfg(args)
    mcfg = _milk_cfg(args)
    source = _source(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    origin_grains = ("monthly", "weekly") if args.grain == "both" else (args.grain,)
    jobs = resolve_jobs(args.jobs)
    for og in origin_grains:
        origins, score_until, marker, rerun, prior = _block_setup(args, og, "milk", cfg, mcfg)

        def progress(i: int, n: int, origin: date) -> None:
            if i % 10 == 0:
                print(f"  {og}: origin {i + 1}/{n} ({origin})", file=sys.stderr)

        res = run_milk_backtest(source, og, cfg, mcfg, origins=origins, progress=progress,
                                jobs=jobs, source_factory=_source_factory(args),
                                score_until=score_until, block=args.block, prior_errors=prior)
        tag = f"{og}_{mcfg.tag()}_{_wtag(args)}{_bt(args)}"
        res.errors.to_csv(out / f"milk_backtest_errors_{tag}.csv", index=False)
        summarise_milk(res.errors).to_csv(out / f"milk_backtest_summary_{tag}.csv", index=False)
        summarise_milk(res.errors, by_source=True).to_csv(
            out / f"milk_backtest_summary_by_source_{tag}.csv", index=False)
        if marker is not None:
            from .freeze import record_final_test
            record_final_test(marker, rerun, [f"milk_backtest_summary_{tag}.csv"], len(origins))
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
        path = out / f"milk_backtest_summary_{og}_{mcfg.tag()}_{_wtag(args)}{_bt(args)}.csv"
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
        _print_common_periods(out / f"milk_backtest_errors_{og}_{mcfg.tag()}_{_wtag(args)}{_bt(args)}.csv")
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


def _cmd_scorecard(args: argparse.Namespace) -> int:
    """Targets table (docs/targets.md) from finished backtests; nothing is re-run."""
    from .episodes import add_bands, add_recovery, daily_quality
    from .freeze import DATA_END
    from .scorecard import confirm, group_scores, prepare, recovery_verdicts, scorecard

    mcfg = _milk_cfg(args)
    out = Path(args.out)
    blocks = ("development", "test") if args.block == "both" else (args.block,)
    frames = []
    for block in blocks:
        suffix = "_test" if block == "test" else ""
        for g in ("monthly", "weekly"):
            for path in (out / f"milk_backtest_errors_{g}_{mcfg.tag()}_{_wtag(args)}{suffix}.csv",
                         out / f"herd_backtest_errors_{g}_{_wtag(args)}{suffix}.csv"):
                if path.exists():
                    frames.append(pd.read_csv(path).assign(block=block))
                else:
                    print(f"NOTE: {path.name} not found", file=sys.stderr)
    if not frames:
        print("no backtest error files found; run backtest-herd and backtest-milk first")
        return 1
    errors = pd.concat(frames, ignore_index=True)
    q = None
    if args.quality == "on":  # herd-level daily aggregates: identified share, gaps, cows
        source = SqlHerdSource.from_env()
        q = daily_quality(source.target_daily(DATA_START, DATA_END),
                          source.panel_daily(DATA_START, DATA_END))
        errors = add_bands(errors, q)
    errors = prepare(add_recovery(errors), method=args.intervals, quality=q)
    card = scorecard(errors)
    iv = "" if args.intervals == "empirical" else f"_{args.intervals}"
    name = f"scorecard_{args.block}_{mcfg.tag()}_{_wtag(args)}{iv}.csv"
    card.to_csv(out / name, index=False)

    pd.set_option("display.width", 200)
    show = card[card["target"] != "no target"]
    cols = ["n", "accuracy", "target_accuracy", "skill", "best_benchmark", "bias_pct",
            "coverage80", "coverage90", "width90", "deviance_ratio", "target", "calibrated", "reasons"]
    for block, b in show.groupby("block", sort=False):
        print(f"\n=== {block} block: targets (docs/targets.md), herd-level aggregates ===")
        print(b.set_index(["grain", "series", "horizon", "model"])[cols]
              .to_string(float_format=lambda v: f"{v:.3f}"))
        prim = b[b["model"].isin(["milk_baseline", "herd_engine"])]
        print(f"rows met (target and calibrated): {int(prim['met'].sum())} of {len(prim)}; "
              f"not interpretable: {int((prim['target'] == 'not interpretable').sum())}")
    if len(blocks) == 2:
        c = confirm(card)
        if len(c):
            print("\n=== development vs test accuracy (confirmed = test >= development - 5 points) ===")
            print(c.set_index(["grain", "series", "horizon", "model"])
                  .to_string(float_format=lambda v: f"{v:.3f}"))
    other = card[(card["target"] == "no target") & card["model"].isin(["milk_baseline", "herd_engine"])]
    if len(other):
        print("\n=== other series and horizons (no target): accuracy and skill ===")
        print(other.pivot_table(index=["block", "grain", "series"], columns="horizon",
                                values=["accuracy", "skill"]).round(3).to_string())
    key = ["herd_milk", "milking", "n_herd", "calvings"]
    views = [("since_break", "accuracy by months from the latest break to the origin")]
    if "band" in errors.columns:
        views.insert(0, ("band", "accuracy by record-quality band (targets use normal + degraded)"))
    for by, label in views:
        g = group_scores(errors, by)
        g = g[g["series"].isin(key)]
        if not len(g):
            continue
        g.to_csv(out / name.replace("scorecard_", f"scorecard_{by}_"), index=False)
        print(f"\n=== {label}; n in brackets ===")
        g["cell"] = [f"{a:.3f} ({n})" if pd.notna(a) else f"- ({n})"
                     for a, n in zip(g["accuracy"], g["n"])]
        print(g.pivot_table(index=["block", "grain", "series", "horizon"], columns=by,
                            values="cell", aggfunc="first").fillna("").to_string())
    rec = recovery_verdicts(errors)
    print("\n=== recovery targets (verified periods after a break) ===")
    print(rec.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"\nFull table: {out / name} (gitignored)")
    return 0


ADAPT_FAMILIES = {
    # family: (file pattern, base model, series used by the targets, grains)
    "herd": (r"herd_backtest_errors_(monthly|weekly)_(.+)\.csv$", "herd_engine",
             ("milking", "n_herd", "calvings", "dry_offs"), ("monthly",)),
    "milk": (r"milk_backtest_errors_(monthly|weekly)_(.+)\.csv$", "milk_baseline",
             ("herd_milk",), ("monthly", "weekly", "daily")),
}
BENCHMARK_MODELS = ("persistence", "seasonal_naive", "ets", "sarima")


def _cmd_calibrate_milk(args: argparse.Namespace) -> int:
    from .milk_calibration import run_command
    return run_command(args)


def _cmd_adapt(args: argparse.Namespace) -> int:
    """Layer 1: add adaptive-level variants of development backtests as new candidates."""
    import re

    from .adaptive import AdaptiveConfig, adaptive_corrected
    from .episodes import add_recovery

    out = Path(args.out)
    variants = [AdaptiveConfig(pooled=p, q30=q, tau_days=args.tau or None)
                for p in (True, False) for q in args.q30]
    report = []
    for fam in (("herd", "milk") if args.family == "both" else (args.family,)):
        pattern, base, series, grains = ADAPT_FAMILIES[fam]
        rx = re.compile(pattern)
        files: dict[str, list[Path]] = {}
        for path in sorted(out.glob("*_backtest_errors_*.csv")):
            m = rx.match(path.name)
            tag = m.group(2) if m else ""
            if not m or tag.endswith("_test") or "_ad" in tag:
                continue
            if args.tags and tag not in args.tags:
                continue
            files.setdefault(tag, []).append(path)
        for tag, paths in files.items():
            e = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
            e = e[e["series"].isin(series) & e["grain"].isin(grains)]
            if not e["model"].eq(base).any():
                continue
            bench = e[e["model"].isin(BENCHMARK_MODELS)]
            report.append(e[e["model"].isin([base, f"{base}_corrected"])].assign(candidate=lambda d: tag + "/" + d["model"]))
            for cfg in variants:
                ad = adaptive_corrected(e, base, cfg=cfg)
                new_tag = f"{tag}_ad{cfg.label()}"
                both = pd.concat([ad, bench], ignore_index=True)
                # weekly-origin files also hold the daily horizons, as the backtests write them
                file_grain = both["grain"].where(both["grain"] == "monthly", "weekly")
                for g, part in both.groupby(file_grain):
                    part.to_csv(out / f"{fam}_backtest_errors_{g}_{new_tag}.csv", index=False)
                report.append(ad.assign(candidate=f"{new_tag}/{base}_adaptive"))
                print(f"{fam}: wrote {new_tag}", file=sys.stderr)
    if not report:
        print(f"no development error files found in {out}")
        return 1
    r = add_recovery(pd.concat(report, ignore_index=True))
    r["error"] = r["forecast"] - r["actual"]
    r["recent"] =r["since_break"].isin(["0-2 months", "3-5 months"])
    key = [("herd_milk", "weekly", 4), ("herd_milk", "monthly", 3),
           ("milking", "monthly", 3), ("n_herd", "monthly", 6), ("calvings", "monthly", 3)]
    rows = []
    for (s, g, h) in key:
        sub = r[(r["series"] == s) & (r["grain"] == g) & (r["horizon"] == h)]
        for cand, c in sub.groupby("candidate"):
            acc = lambda d: 1 - d["error"].abs().sum() / d["actual"].sum() if len(d) else float("nan")
            rows.append(dict(target=f"{s} {g} h{h}", candidate=cand, n=len(c),
                             all=acc(c), after_break_0_5m=acc(c[c["recent"]]),
                             n_after=int(c["recent"].sum())))
    t = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\n=== development accuracy, all origins and 0-5 months after a break (E1, E5a) ===")
    print(t.set_index(["target", "candidate"]).to_string(float_format=lambda v: f"{v:.3f}"))
    print("\nNext: nested-cv picks among all candidates year by year.")
    return 0


def _cmd_drivers(args: argparse.Namespace) -> int:
    """Layer 2: driver layer on one development milk backtest (raw or adaptive)."""
    from .drivers import DriverConfig, driver_layer
    from .freeze import DATA_END

    out = Path(args.out)
    paths = [out / f"milk_backtest_errors_{g}_{args.tag}.csv" for g in ("monthly", "weekly")]
    paths = [p for p in paths if p.exists()]
    if not paths or args.tag.endswith("_test"):
        print(f"no development milk files for tag {args.tag!r} in {out}")
        return 1
    e = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    daily = SqlHerdSource.from_env().driver_daily(DATA_START, DATA_END)
    cfg = DriverConfig(groups=tuple(args.groups))
    res = driver_layer(e, daily, args.base, cfg=cfg)
    bench = e[e["model"].isin(BENCHMARK_MODELS)]
    both = pd.concat([res.errors, bench], ignore_index=True)
    file_grain = both["grain"].where(both["grain"] == "monthly", "weekly")
    new_tag = f"{args.tag}_dr"
    for g, part in both.groupby(file_grain):
        part.to_csv(out / f"milk_backtest_errors_{g}_{new_tag}.csv", index=False)
    res.coefficients.to_csv(out / f"drivers_coefficients_{new_tag}.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"\n=== feature registry ({args.tag}, base {args.base}): forecast dates per status ===")
    print(res.registry.to_string())
    last = res.coefficients[res.coefficients["origin"] == res.coefficients["origin"].max()]
    if len(last):
        print("\n=== coefficients at the last forecast date (log-ratio per standard deviation) ===")
        print(last.pivot_table(index="feature", columns=["grain", "horizon"], values="coef")
              .round(4).to_string())
    base = e[e["model"] == args.base]
    acc = lambda d: 1 - (d["forecast"] - d["actual"]).abs().sum() / d["actual"].sum()
    rows = []
    for (g, h), b in base[base["series"] == "herd_milk"].groupby(["grain", "horizon"]):
        d = res.errors[(res.errors["grain"] == g) & (res.errors["horizon"] == h)]
        rows.append(dict(grain=g, horizon=h, n=len(b), base=acc(b), drivers=acc(d)))
    print("\n=== development accuracy, herd milk ===")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"\nWrote candidate {new_tag}; nested-cv compares it with the others.")
    return 0


def _cmd_scenarios(args: argparse.Namespace) -> int:
    """Layer 3: episode library, responses "like last time", optional outlook scenarios."""
    from .freeze import DATA_END
    from .scenarios import (
        apply_scenario, detect_episodes, episode_response, narrative, summarize_response,
    )

    out = Path(args.out)
    frames = []
    for suffix in ("", "_test"):
        for g in ("monthly", "weekly"):
            p = out / f"milk_backtest_errors_{g}_{args.tag}{suffix}.csv"
            if p.exists():
                frames.append(pd.read_csv(p))
    if not frames:
        print(f"no milk backtest files for tag {args.tag!r} in {out}")
        return 1
    errors = pd.concat(frames, ignore_index=True)
    daily = SqlHerdSource.from_env().driver_daily(DATA_START, DATA_END)
    episodes = detect_episodes(daily)
    episodes.to_csv(out / "scenario_episodes.csv", index=False)
    pd.set_option("display.width", 200)
    print("=== episode library (herd-level; start months) ===")
    for kind, g in episodes.groupby("kind"):
        months = ", ".join(sorted({f"{d:%Y-%m}" for d in g["start"]}))
        print(f"{kind:18s} {len(g):3d}  {months}")
    resp = episode_response(errors, episodes, args.model)
    summary = summarize_response(resp)
    summary.to_csv(out / f"scenario_response_{args.tag}.csv", index=False)
    print(f"\n=== response of {args.model} (excess relative error after onset) ===")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    print()
    for kind in summary["kind"].unique():
        for grain, h in (("weekly", 4), ("monthly", 3)):
            print("-", narrative(summary, kind, grain, h))
    if args.outlook:
        path = Path(args.outlook)
        base = pd.read_csv(path)
        base = base[base["series"] == "herd_milk"]
        res = pd.concat([apply_scenario(base, summary, k) for k in summary["kind"].unique()],
                        ignore_index=True)
        dest = out / f"scenarios_{path.stem}.csv"
        res.to_csv(dest, index=False)
        m = res[res["grain"] == "monthly"]
        if len(m):
            print("\n=== monthly herd milk under each scenario (litres) ===")
            print(m.pivot_table(index="target_period", columns="scenario", values="scenario_forecast")
                  .round(0).to_string())
        print(f"written {dest}")
    print("\nResponses are what happened after earlier episodes in this herd, not proven causes.")
    return 0


def _cmd_nested_cv(args: argparse.Namespace) -> int:
    """Nested, purged validation over every development backtest found in --out."""
    import re

    from .nested_cv import default_objectives, nested_select

    out = Path(args.out)
    families = {
        "herd": (re.compile(r"herd_backtest_errors_(monthly|weekly)_(.+)\.csv$"),
                 ("herd_engine", "herd_engine_corrected", "herd_engine_adaptive"),
                 ("milking", "n_herd", "calvings", "dry_offs")),
        "milk": (re.compile(r"milk_backtest_errors_(monthly|weekly)_(.+)\.csv$"),
                 ("milk_baseline", "milk_baseline_corrected", "milk_baseline_adaptive",
                  "milk_baseline_drivers", "milk_baseline_adaptive_drivers", "milk_baseline_calibrated"),
                 ("herd_milk",)),
    }
    pd.set_option("display.width", 200)
    for fam in (("herd", "milk") if args.family == "both" else (args.family,)):
        pattern, models, series = families[fam]
        frames: dict[str, list[pd.DataFrame]] = {}
        for path in sorted(out.glob("*_backtest_errors_*.csv")):
            m = pattern.match(path.name)
            if not m or m.group(2).endswith("_test"):
                continue
            frames.setdefault(m.group(2), []).append(pd.read_csv(path))
        cands = {}
        for tag, parts in frames.items():
            e = pd.concat(parts, ignore_index=True)
            for model in models:
                rows = e[e["model"] == model]
                if len(rows):
                    cands[f"{tag}/{model}"] = rows
        if len(cands) < 2:
            print(f"{fam}: fewer than two candidates in {out} (run more development backtests)")
            continue
        res = nested_select(cands, default_objectives(series))
        res.folds.to_csv(out / f"nested_cv_{fam}_folds.csv", index=False)
        res.summary.to_csv(out / f"nested_cv_{fam}_summary.csv", index=False)
        print(f"\n=== {fam}: inner score (mean WAPE on periods ended before the fold; * = selected) ===")
        f = res.folds.assign(cell=[f"{s:.4f}{'*' if sel else ''}" if pd.notna(s) else "-"
                                   for s, sel in zip(res.folds["inner_score"], res.folds["selected"])])
        print(f.pivot(index="candidate", columns="fold_year", values="cell").to_string())
        print(f"\n=== {fam}: accuracy on fold years 2019-2023 (nested = chosen year by year) ===")
        print(res.summary.set_index(["series", "grain", "horizon"])
              .to_string(float_format=lambda v: f"{v:.3f}"))
    return 0


def _explain_setup(args: argparse.Namespace):
    cfg = _engine_cfg(args)
    mcfg = _milk_cfg(args)
    source = _source(args)
    origin = date.fromisoformat(args.origin)
    if origin.day != 1:
        raise SystemExit("--origin must be the first day of a month")
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, origin),
                       target=source.target_daily(DATA_START, origin))
    setup = prepare_milk(source, origin, mcfg, hist)
    inputs = load_origin_inputs(source, origin, cfg)
    anchor_k(setup, hist.target_before(origin), inputs.state, mcfg)
    rates = estimate_rates(inputs.rate_inputs, cfg)
    return mcfg, source, origin, hist, setup, inputs, rates


def _save(frame: pd.DataFrame, out: Path, name: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / name, index=False)


def _cmd_explain_milk(args: argparse.Namespace) -> int:
    mcfg, source, origin, hist, setup, inputs, rates = _explain_setup(args)
    tm = monthly_target(hist.target_before(origin))
    tm = tm[tm["share"] >= 0.8]
    actual = pd.DataFrame({"litres_per_day": tm["litres"] / tm["ok_days"], "source": tm["source"]})
    cowdays = hist.cowdays_before(month_start(origin), origin)
    past = explain_past_milk(cowdays, actual, setup.curve, origin, months=args.past_months)
    H = (add_months(origin, 12) - origin).days
    proj = project(inputs.state, rates, H, milk_curve=setup.arrays, record_milk_mix=True)
    last = starting_mix(inputs.state, origin)
    fut = explain_forecast_milk(proj.milk_mix, list(pd.to_datetime(proj.daily["date"]).dt.date),
                                setup.k, setup.curve, last, origin)
    both = pd.concat([past, fut], ignore_index=True)
    _save(both, Path(args.out), f"explain_milk_{origin:%Y%m}_{mcfg.tag()}.csv")
    for kind, g in both.groupby("kind", sort=False):
        table = g.pivot_table(index="target_period", columns="factor", values="contribution", sort=False)
        print(f"\n=== {kind} months: change in herd milk (litres/day) by factor; origin {origin} ===")
        print(table.round(0).to_string())
    print("\nFactors sum exactly to the model change; 'residual' = actual change - model change "
          f"(heat, health, feed, recording). Curve: {setup.curve.source}, k = {setup.k:.3f}")
    return 0


def _cmd_explain_herd(args: argparse.Namespace) -> int:
    mcfg, source, origin, hist, setup, inputs, rates = _explain_setup(args)
    H = (add_months(origin, 12) - origin).days
    proj = project(inputs.state, rates, H)
    flows = herd_flows(proj.daily, origin)
    split = calving_split(inputs.state, rates, H, origin)
    health = check_before(source.health_months(DATA_START, month_start(origin)), origin, "health_months")
    md = check_before(source.exposure(DATA_START, month_start(origin)), origin, "exposure")
    md = md[md["state"] == "milking"].groupby("month")["animal_days"].sum()
    mast = expected_mastitis(proj.daily, mastitis_rates(health, md, origin), origin)
    _save(pd.concat([flows, split, mast], ignore_index=True), Path(args.out),
          f"explain_herd_{origin:%Y%m}.csv")
    for state in ("milking", "dry_pregnant", "heifer_pregnant", "calf"):
        t = flows[flows["series"] == state].pivot_table(index="target_period", columns="factor",
                                                         values="contribution")
        t["net_change"] = t.sum(axis=1)
        print(f"\n=== {state}: monthly flows (animals), origin {origin} ===")
        print(t.round(1).to_string())
    print("\n=== calvings: determined (pregnancies at origin) vs rate-driven (new conceptions) ===")
    print(split.pivot_table(index="target_period", columns="factor", values="contribution").round(1).to_string())
    if len(mast):
        print("\n=== expected mastitis episodes (low confidence; recording gap since 2023) ===")
        print(mast.pivot_table(index="target_period", columns="factor", values="contribution").round(1).to_string())
    return 0


def _cmd_explain_generation(args: argparse.Namespace) -> int:
    mcfg, source, origin, hist, setup, inputs, rates = _explain_setup(args)
    H = (add_months(origin, 12) - origin).days
    proj = project(inputs.state, rates, H, record_cells=True)
    comp = generation_composition(proj.cells)
    _save(comp, Path(args.out), f"explain_generation_{origin:%Y%m}.csv")
    t = comp.pivot_table(index="month", columns=["group", "generation_group"], values="mean_animals")
    print(f"=== projected mean animals by generation, origin {origin} ===")
    print(t.iloc[[0, 2, 5, 8, 11]].round(0).to_string() if len(t) >= 12 else t.round(0).to_string())
    print("\n=== fertility by generation within calving period (descriptive associations only) ===")
    print(source.generation_fertility().to_string(index=False))
    return 0


def _load_backtests(out: Path) -> dict[tuple[str, str], pd.DataFrame | None]:
    """Backtest error files of the frozen configuration, by (kind, block)."""
    names = {"milk": "milk_backtest_errors_{g}_herd_fitted_p1_g0_ka_w12{b}.csv",
             "herd": "herd_backtest_errors_{g}_w12{b}.csv"}
    found = {}
    for kind, pattern in names.items():
        for block, suffix in (("development", ""), ("test", "_test")):
            frames = []
            for g in ("monthly", "weekly"):
                path = out / pattern.format(g=g, b=suffix)
                if path.exists():
                    frames.append(pd.read_csv(path))
                else:
                    print(f"NOTE: {path.name} not found", file=sys.stderr)
            found[(kind, block)] = pd.concat(frames, ignore_index=True) if frames else None
    return found


def _cmd_build_outlook(args: argparse.Namespace) -> int:
    import json

    from sqlalchemy import create_engine

    from .config import DatabaseSettings
    from .freeze import DATA_END, config_hash
    from .outlook import build_outlook, run_frozen, write_outlook, write_run_document
    from .page_run import build_page_run

    source = SqlHerdSource.from_env()
    origin = date.fromisoformat(args.origin)
    out = Path(args.out)
    backtests = _load_backtests(out)
    present = [e for e in backtests.values() if e is not None]
    errors = pd.concat(present, ignore_index=True) if present else None
    core_version = source.core_version()
    run = run_frozen(source, origin)
    outlook, attribution, history = build_outlook(source, origin, errors, core_version, run=run)
    document = build_page_run(source, run, attribution, backtests, core_version, realised_until=DATA_END)
    dest = out / "outlook"
    for name, frame in (("outlook", outlook), ("attribution", attribution), ("history", history)):
        _save(frame, dest, f"{name}_{origin:%Y%m}.csv")
    (dest / f"run_{origin:%Y%m}.json").write_text(json.dumps(document, indent=1))
    m = outlook[(outlook["grain"] == "monthly") & (outlook["series"] == "herd_milk")]
    print(f"Outlook {origin}  model {outlook['model_version'].iloc[0]} (config {config_hash()}), "
          f"core_version {core_version}, quality: {outlook['quality_flag'].iloc[0]}")
    print(m[["target_period", "forecast", "lower", "upper"]].round(0).to_string(index=False))
    print(f"rows: outlook {len(outlook)}, attribution {len(attribution)}, history {len(history)}; "
          f"page document: {len(document['outlook'])} forecasts, {len(document['backtest'])} backtest rows; "
          f"files in {dest}/")
    real = pd.DataFrame(document["realised"])
    if len(real):  # counts only: realised periods per grain, and how many can be scored
        print("realised outcomes (periods, scoreable) by grain: " + ", ".join(
            f"{g} {len(x)}/{int(x['scoreable'].sum())}" for g, x in real.groupby("grain")))
    else:
        print("realised outcomes: none (no complete forecast period before the last data day)")
    if args.write:
        engine = create_engine(DatabaseSettings.from_env().url)
        counts = write_outlook(engine, outlook, attribution, history)
        write_run_document(engine, document)
        print("written to c1_output:", counts, "+ run_document")
    else:
        print("not written to the database (add --write after checking the numbers)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pfoi")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("herd-rates", help="rates and starting herd at one origin")
    p.add_argument("--origin", required=True, help="YYYY-MM-DD")
    p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
    p.add_argument("--conception-cut", default="origin", choices=["origin", "known"],
                   help="known = heifer/dry conception rates only from months confirmable at the origin")
    p.add_argument("--cell-table", default="day_cell", choices=["day_cell", "day_cell_known"],
                   help="day_cell_known = pregnancies only once confirmed (no hindsight)")
    p.add_argument("--conception-known", default="lag", choices=["lag", "recorded"],
                   help="recorded = a conception counts once its pregnancy check is recorded")
    p.add_argument("--pregnancy-lag", type=int, default=35,
                   help="days after which conceptions count in the rate window (90 suits 'recorded')")
    p.set_defaults(func=_cmd_herd_rates)

    def jobs_opt(p: argparse.ArgumentParser) -> None:
        p.add_argument("--jobs", type=int, default=1,
                       help="processes for scoring origins (0 = CPU cores - 1); each opens "
                            "its own read-only database connection")

    def block_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--block", default="development", choices=["development", "test"],
                       help="test = final test block, frozen model, run once")
        p.add_argument("--force", action="store_true", help="re-run the final test (reported)")

    p = sub.add_parser("backtest-herd", help="rolling-origin backtest (development or test block)")
    p.add_argument("--grain", default="both", choices=["monthly", "weekly", "both"])
    p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
    p.add_argument("--conception-cut", default="origin", choices=["origin", "known"],
                   help="known = heifer/dry conception rates only from months confirmable at the origin")
    p.add_argument("--cell-table", default="day_cell", choices=["day_cell", "day_cell_known"],
                   help="day_cell_known = pregnancies only once confirmed (no hindsight)")
    p.add_argument("--conception-known", default="lag", choices=["lag", "recorded"],
                   help="recorded = a conception counts once its pregnancy check is recorded")
    p.add_argument("--pregnancy-lag", type=int, default=35,
                   help="days after which conceptions count in the rate window (90 suits 'recorded')")
    p.add_argument("--every", type=int, default=1, help="use every n-th origin")
    p.add_argument("--out", default="logs/pfoi")
    jobs_opt(p)
    block_opts(p)
    p.set_defaults(func=_cmd_backtest)

    p = sub.add_parser("herd-report", help="ratio and bias tables from a finished backtest")
    p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
    p.add_argument("--conception-cut", default="origin", choices=["origin", "known"],
                   help="known = heifer/dry conception rates only from months confirmable at the origin")
    p.add_argument("--cell-table", default="day_cell", choices=["day_cell", "day_cell_known"],
                   help="day_cell_known = pregnancies only once confirmed (no hindsight)")
    p.add_argument("--conception-known", default="lag", choices=["lag", "recorded"],
                   help="recorded = a conception counts once its pregnancy check is recorded")
    p.add_argument("--pregnancy-lag", type=int, default=35,
                   help="days after which conceptions count in the rate window (90 suits 'recorded')")
    p.add_argument("--out", default="logs/pfoi")
    p.add_argument("--block", default="development", choices=["development", "test"])
    p.set_defaults(func=_cmd_report)

    def milk_opts(p: argparse.ArgumentParser, blocks=("development", "test"),
                  block_default: str = "development") -> None:
        p.add_argument("--curve", default="herd_fitted", choices=list(CURVE_MODES),
                       help="shape before 2020-09 (fitted_everywhere = sensitivity only)")
        p.add_argument("--pregnancy-factor", default="on", choices=["on", "off"])
        p.add_argument("--generation-factor", default="off", choices=["on", "off"])
        p.add_argument("--k", default="anchored", choices=list(K_MODES),
                       help="anchored = last 14 scoreable days; window = 12-month k")
        p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
        p.add_argument("--conception-cut", default="origin", choices=["origin", "known"],
                       help="known = heifer/dry conception rates only from months confirmable at the origin")
        p.add_argument("--cell-table", default="day_cell", choices=["day_cell", "day_cell_known"],
                       help="day_cell_known = pregnancies only once confirmed (no hindsight)")
        p.add_argument("--conception-known", default="lag", choices=["lag", "recorded"],
                       help="recorded = a conception counts once its pregnancy check is recorded")
        p.add_argument("--pregnancy-lag", type=int, default=35,
                       help="days after which conceptions count in the rate window (90 suits 'recorded')")
        p.add_argument("--out", default="logs/pfoi")
        p.add_argument("--block", default=block_default, choices=list(blocks))
        p.add_argument("--force", action="store_true", help="re-run the final test (reported)")

    p = sub.add_parser("milk-curve", help="lactation curve and k at one origin")
    p.add_argument("--origin", required=True, help="YYYY-MM-DD")
    milk_opts(p)
    p.set_defaults(func=_cmd_milk_curve)

    p = sub.add_parser("backtest-milk", help="rolling-origin milk backtest, development block")
    p.add_argument("--grain", default="both", choices=["monthly", "weekly", "both"],
                   help="origin grain; weekly origins also score daily horizons")
    p.add_argument("--every", type=int, default=1)
    jobs_opt(p)
    milk_opts(p)
    p.set_defaults(func=_cmd_backtest_milk)

    p = sub.add_parser("check-snapshots", help="batched vs per-origin snapshot queries (counts only)")
    p.add_argument("--grain", default="weekly", choices=["monthly", "weekly"])
    p.add_argument("--every", type=int, default=10, help="check every n-th origin")
    p.set_defaults(func=_cmd_check_snapshots)

    p = sub.add_parser("milk-report", help="H1 table from a finished milk backtest")
    milk_opts(p)
    p.set_defaults(func=_cmd_milk_report)

    p = sub.add_parser("adapt", help="Layer 1: adaptive-level variants of development backtests")
    p.add_argument("--family", default="both", choices=["herd", "milk", "both"])
    p.add_argument("--tags", nargs="*", default=None,
                   help="backtest tags to adapt (e.g. w36_ck); default: every development tag")
    p.add_argument("--q30", nargs="*", type=float, default=[0.1, 0.5],
                   help="level variance added per 30 days, as a share of the error variance")
    p.add_argument("--tau", type=float, default=365.0, help="days for the level to fade (0 = never)")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_adapt)

    p = sub.add_parser("calibrate-milk", help="Experimental past-only monthly MAE calibration")
    p.add_argument("--tag", required=True)
    p.add_argument("--base", default="milk_baseline_adaptive",
                   choices=["milk_baseline", "milk_baseline_corrected", "milk_baseline_adaptive"])
    p.add_argument("--quality", default="off", choices=["on", "off"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_calibrate_milk)

    p = sub.add_parser("drivers", help="Layer 2: driver layer (heat, rain, health, sensors)")
    p.add_argument("--tag", required=True,
                   help="milk backtest tag, e.g. herd_fitted_p1_g0_ka_w12_ck or ..._adpq0.1t365z3")
    p.add_argument("--base", default="milk_baseline",
                   choices=["milk_baseline", "milk_baseline_adaptive"])
    p.add_argument("--groups", nargs="*", default=["weather", "health", "sensor", "quality", "season"],
                   choices=["weather", "health", "sensor", "quality", "season"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_drivers)

    p = sub.add_parser("scenarios", help="Layer 3: scenarios like earlier heat, drought, disease")
    p.add_argument("--tag", required=True, help="milk backtest tag (its _test files are added if present)")
    p.add_argument("--model", default="milk_baseline")
    p.add_argument("--outlook", default=None,
                   help="outlook CSV to apply scenarios to, e.g. logs/pfoi/outlook/outlook_202608.csv")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_scenarios)

    p = sub.add_parser("nested-cv", help="choose options year by year on past periods only (L9)")
    p.add_argument("--family", default="both", choices=["herd", "milk", "both"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_nested_cv)

    p = sub.add_parser("scorecard", help="accuracy, skill and calibration vs the agreed targets")
    milk_opts(p, blocks=("development", "test", "both"), block_default="both")
    p.add_argument("--intervals", default="empirical", choices=["empirical", "aci"],
                   help="aci = recency-weighted adaptive conformal intervals scaled by record quality")
    p.add_argument("--quality", default="on", choices=["on", "off"],
                   help="on = read daily herd-level record quality to split scores by band")
    p.set_defaults(func=_cmd_scorecard)

    for name, func, help_ in (
        ("explain-milk", _cmd_explain_milk, "Shapley split of past and forecast milk changes"),
        ("explain-herd", _cmd_explain_herd, "herd flows, calving split, expected mastitis"),
        ("explain-generation", _cmd_explain_generation, "generation composition and fertility"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--origin", required=True, help="first day of a month, YYYY-MM-01")
        p.add_argument("--past-months", type=int, default=12)
        milk_opts(p)
        p.set_defaults(func=func)

    p = sub.add_parser("build-outlook", help="frozen-model outlook at one origin (CSV; --write to c1_output)")
    p.add_argument("--origin", default="2026-08-01")
    p.add_argument("--out", default="logs/pfoi")
    p.add_argument("--write", action="store_true", help="replace this origin's rows in c1_output")
    p.set_defaults(func=_cmd_build_outlook)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
