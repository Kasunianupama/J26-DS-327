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
from .ml_features import DEFAULT_SERIES as DEFAULT_ML_SERIES


def _window(value: str) -> int | None:
    return None if value == "expanding" else int(value)


def _half_life(value: str | None) -> float | None:
    return None if value in (None, "none") else float(value)


def _apply_preset(args: argparse.Namespace) -> None:
    """Fill the engine options from a named version preset (in place)."""
    if getattr(args, "preset", None) not in ("pfoi-1.1", "pfoi-1.1.1", "candidate"):
        return
    from .freeze import CANDIDATE_ENGINE as c
    args.window = "expanding" if c.window_months is None else str(c.window_months)
    args.conception_cut, args.cell_table = c.conception_cut, c.cell_table
    args.conception_known, args.pregnancy_lag = c.conception_known, c.pregnancy_check_lag_days
    args.half_life = "none" if c.rate_half_life_months is None else f"{c.rate_half_life_months:g}"


def _engine_cfg(args: argparse.Namespace) -> EngineConfig:
    _apply_preset(args)
    return EngineConfig(window_months=_window(args.window),
                        rate_half_life_months=_half_life(getattr(args, "half_life", None)),
                        conception_cut=getattr(args, "conception_cut", "origin"),
                        cell_table=getattr(args, "cell_table", "day_cell"),
                        conception_known=getattr(args, "conception_known", "lag"),
                        pregnancy_check_lag_days=getattr(args, "pregnancy_lag", 35),
                        conception_dim_shape=getattr(args, "conception_shape", "off") == "on",
                        fast_half_life_months=_half_life(getattr(args, "fast_half_life", None)),
                        milking_exit_model=getattr(args, "exit_model", "state"))


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
    hl = _half_life(getattr(args, "half_life", None))
    hl_tag = f"_hl{hl:g}" if hl is not None else ""
    cs = "_cs" if getattr(args, "conception_shape", "off") == "on" else ""
    fhl = _half_life(getattr(args, "fast_half_life", None))
    fh = f"_fhl{fhl:g}" if fhl is not None else ""
    xl = "_xl" if getattr(args, "exit_model", "state") == "lactation" else ""
    return f"w{args.window}{ck}{kn}{rk}{lg}{hl_tag}{cs}{fh}{xl}"


def _bt(args: argparse.Namespace) -> str:
    """File-name suffix for the final test block or a post-hoc replay of 2024-26."""
    return {"test": "_test", "posthoc": "_posthoc"}.get(getattr(args, "block", "development"), "")


def _block_setup(args, grain: str, name: str, cfg, mcfg=None):
    """Origins, score_until, marker and prior errors for the chosen block."""
    from .freeze import (
        DATA_END, FROZEN_ENGINE, FROZEN_MILK, config_hash, final_test_origins, guard_final_test,
    )
    if args.block == "development":
        return development_origins(grain, every=args.every), TEST_START, None, False, None
    if args.block == "posthoc":
        # 2024-26 has been looked at, so a new version's scores there are post-hoc: no
        # run-once marker, files tagged _posthoc. The frozen model keeps its own test run.
        if cfg == FROZEN_ENGINE and (mcfg is None or mcfg == FROZEN_MILK):
            raise SystemExit("pfoi-1.0.0 is scored on the test block (run once); "
                             "posthoc is for new versions")
        prior_path = Path(args.out) / (
            f"herd_backtest_errors_{grain}_{_wtag(args)}.csv" if mcfg is None
            else f"milk_backtest_errors_{grain}_{mcfg.tag()}_{_wtag(args)}.csv")
        prior = pd.read_csv(prior_path) if prior_path.exists() else None
        if prior is None:
            print(f"NOTE: {prior_path.name} not found: run the development block first so "
                  "corrections and intervals can use its errors", file=sys.stderr)
        print("POST-HOC: 2024-26 scores of a non-frozen version; report them as post-hoc.",
              file=sys.stderr)
        return final_test_origins(grain, every=args.every), DATA_END, None, False, prior
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
                      generation_factor=args.generation_factor == "on", k_mode=args.k,
                      anchor_gate=getattr(args, "anchor_gate", "off") == "on",
                      borrow_other_source_k=getattr(args, "borrow_k", "on") == "on")


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
    factory = _source_factory(args)
    target_tag = ""
    if getattr(args, "target", "record") == "delpro":
        from .delpro_target import DelProFactory, DelProTargetSource
        if args.block != "development":
            print("--target delpro is a development-block experiment only")
            return 1
        source, factory, target_tag = DelProTargetSource(source), DelProFactory(factory), "_tdp"
        print("DelPro-only target: litres from milk_delpro_total (from 2020-08), verified days only; "
              "origins before DelPro records are withheld and counted.", file=sys.stderr)
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
                                jobs=jobs, source_factory=factory,
                                score_until=score_until, block=args.block, prior_errors=prior)
        if target_tag and len(res.errors):
            res.errors["target_definition"] = "delpro_only"
        tag = f"{og}_{mcfg.tag()}_{_wtag(args)}{target_tag}{_bt(args)}"
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


def _cmd_neural(args: argparse.Namespace) -> int:
    """Neural milk model on the two-stage split (pfoi/neural.py); herd-level aggregates only."""
    from . import neural as N

    cfg, mcfg = _engine_cfg(args), _milk_cfg(args)
    source = _source(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print("Loading herd-level daily inputs ...", file=sys.stderr)
    f = N.daily_frame(source)
    cache = out / f"neural_engine_paths_{mcfg.tag()}_{_wtag(args)}.csv"
    if cache.exists() and not args.rebuild_engine:
        paths = pd.read_csv(cache, parse_dates=["run", "date"])
        paths["run"], paths["date"] = paths["run"].dt.date, paths["date"].dt.date
        print(f"Engine paths from {cache}", file=sys.stderr)
    else:
        runs = N.mondays(N.STAGES[0].train_start, N.STAGES[-1].test_end)

        def progress(i: int, n: int, origin: date) -> None:
            if i % 20 == 0:
                print(f"  engine run {i + 1}/{n} ({origin})", file=sys.stderr)

        paths = N.engine_paths(source, runs, cfg, mcfg, jobs=resolve_jobs(args.jobs),
                               source_factory=_source_factory(args), progress=progress)
        paths.to_csv(cache, index=False)
    seeds = tuple(range(args.seeds))
    res = N.run_neural(f, paths, seeds=seeds, max_epochs=args.epochs, patience=args.patience)
    tag = f"{mcfg.tag()}_{_wtag(args)}_s{args.seeds}"
    res.errors.assign(model_version="pfoi-neural-dev").to_csv(out / f"neural_errors_{tag}.csv", index=False)
    res.summary.to_csv(out / f"neural_summary_{tag}.csv", index=False)
    res.fits.to_csv(out / f"neural_fits_{tag}.csv", index=False)
    res.counts.to_csv(out / f"neural_counts_{tag}.csv", index=False)
    res.paths.to_csv(out / f"neural_paths_{tag}.csv", index=False)
    import torch
    for (stage, variant), (nets, _) in res.nets.items():
        torch.save([n.state_dict() for n in nets], out / f"neural_weights_{stage}_{variant}_{tag}.pt")
    pd.set_option("display.width", 160)
    print("\nSplit (samples = daily origins; target_days = scored days; engine_share = origins with an engine path):")
    print(res.counts.round(3).to_string(index=False))
    print("\nTraining (mean over seeds; L1 of log litres, about a relative error):")
    print(res.fits.groupby(["stage", "model"])[["epochs", "best_epoch", "train_l1", "val_l1"]]
          .mean().round(4).to_string())
    if len(res.errors):
        r = res.errors.assign(ratio=res.errors["forecast"] / res.errors["actual"])
        print("\nSanity: forecast / actual on test periods (p05, median, p95; 1 = exact):")
        print(r.groupby(["stage", "model", "grain"])["ratio"].quantile([0.05, 0.5, 0.95]).unstack()
              .round(3).to_string())
    print("\nTest accuracy on identical periods (litres; ratio < 1 beats persistence):")
    if len(res.summary):
        print(res.summary.round({"mae": 1, "bias": 1, "ratio_to_persistence": 3}).to_string(index=False))
    print("\nNote: stage-2 test 2024-01 onward was viewed in earlier post-hoc replays; report it as "
          "previously viewed. 2023 was in the earlier development block.")
    print(f"Files in {out}/ (weights stay local; logs/ is not committed).")
    return 0


def _cmd_neural_outlook(args: argparse.Namespace) -> int:
    """Neural and persistence page documents from built ones, for compare-runs; files only."""
    from .neural_outlook import run

    return run(args.out, args.source, args.neural_dir, args.origins)


def _cmd_hit_rate(args: argparse.Namespace) -> int:
    """Share of forecasts within +-5 % / +-10 % of the record (target: 85 % within 10 %)."""
    from .episodes import add_bands, daily_quality
    from .freeze import DATA_END
    from .hit_rate import TARGET_SHARE, hit_rates, keep_rule, table, year_table

    out = Path(args.out)
    frames = []
    if args.files:
        for f in args.files:
            frames.append(pd.read_csv(f).assign(block=args.block_name or Path(f).stem))
    else:
        blocks = {"both": ("development", "posthoc")}.get(args.block, (args.block,))
        for block in blocks:
            suffix = {"posthoc": "_posthoc"}.get(block, "")
            for g in ("monthly", "weekly"):
                path = out / f"milk_backtest_errors_{g}_{args.tag}{suffix}.csv"
                if path.exists():
                    frames.append(pd.read_csv(path).assign(block=block))
                else:
                    print(f"NOTE: {path.name} not found", file=sys.stderr)
    if not frames:
        print("no error files found; pass --tag of a finished milk backtest or --files")
        return 1
    errors = pd.concat(frames, ignore_index=True)
    if "series" in errors:
        errors = errors[errors["series"] == "herd_milk"]
    if args.models:
        errors = errors[errors["model"].isin(args.models)]
    if args.quality == "on":  # herd-level daily aggregates: identified share, gaps, cows
        source = SqlHerdSource.from_env()
        q = daily_quality(source.target_daily(DATA_START, DATA_END),
                          source.panel_daily(DATA_START, DATA_END))
        errors = add_bands(errors, q)
    else:
        errors = errors.drop(columns="band", errors="ignore")
    rates = hit_rates(errors)
    name = f"hit_rate_{args.block if not args.files else 'files'}_{args.tag}.csv"
    rates.to_csv(out / name, index=False)
    pd.set_option("display.width", 220)
    trust = "trusted" if args.quality == "on" else "all"
    for block in rates["block"].unique():
        for value, what in (("within_10", "share within +-10 %"), ("within_5", "share within +-5 %"),
                            ("wape", "WAPE (mean absolute error / recorded)")):
            t = table(rates, value, trust, block)
            if len(t):
                print(f"\n[{block}] {what}, {trust} periods (n = periods of the largest model):")
                print(t.round(3).to_string())
    rates_y = hit_rates(errors, by_year=True) if "origin" in errors else None
    if rates_y is not None:
        name_y = name.replace("hit_rate_", "hit_rate_by_year_", 1)
        rates_y.to_csv(out / name_y, index=False)
        for block in rates_y["block"].unique():
            for model in rates_y["model"].unique():
                t = year_table(rates_y, model, "within_10", trust, block)
                if len(t):
                    print(f"\n[{block}] {model}: share within +-10 % by forecast year (year of the "
                          f"forecast date), {trust} periods:")
                    print(t.round(3).to_string())
                    n = year_table(rates_y, model, "n", trust, block)
                    print("n forecasts:")
                    print(n.fillna(0).astype(int).to_string())
    met = rates[(rates["trust"] == trust)]
    print(f"\nTarget: {TARGET_SHARE:.0%} of forecasts within +-10 %. Met in "
          f"{int(met['meets_target'].sum())} of {len(met)} block x grain x horizon x model cells.")
    if args.quality == "on":
        u = rates[rates["trust"] == "unverified_or_gap"]
        print(f"Unverified/gap periods reported separately in {name}: {int(u['n'].sum())} forecasts.")
    if args.keep_rule and rates_y is not None:
        old, new = args.keep_rule
        checks, keep = keep_rule(rates, rates_y, old, new, trust)
        print(f"\nKeep rule ({new} vs {old}; development, {trust} periods, share within +-10 %; a year's "
              "share = mean over its horizons):")
        print(checks.round(3).to_string(index=False))
        print(f"Verdict: {'KEEP' if keep else 'DROP (record as tested and dropped; code kept, off)'}")
    print(f"File: {out / name}")
    return 0


def _cmd_milk_error_split(args: argparse.Namespace) -> int:
    """Milk error = cow-count part + yield-per-cow part, with 'one part perfect' ceilings."""
    from .episodes import add_bands, daily_quality
    from .error_split import join, show, summarise
    from .freeze import DATA_END

    out = Path(args.out)
    blocks = {"both": ("development", "posthoc")}.get(args.block, (args.block,))
    milk, herd = [], []
    for block in blocks:
        suffix = {"posthoc": "_posthoc"}.get(block, "")
        for g in ("monthly", "weekly"):
            for kind, tag, bucket in (("milk", args.milk_tag, milk), ("herd", args.herd_tag, herd)):
                path = out / f"{kind}_backtest_errors_{g}_{tag}{suffix}.csv"
                if path.exists():
                    bucket.append(pd.read_csv(path).assign(block=block))
                else:
                    print(f"NOTE: {path.name} not found", file=sys.stderr)
    if not milk or not herd:
        print("need both milk and herd backtest error files (check --milk-tag / --herd-tag)")
        return 1
    milk_e = pd.concat(milk, ignore_index=True)
    if args.quality == "on":
        source = SqlHerdSource.from_env()
        q = daily_quality(source.target_daily(DATA_START, DATA_END),
                          source.panel_daily(DATA_START, DATA_END))
        milk_e = add_bands(milk_e, q)
    j = join(milk_e, pd.concat(herd, ignore_index=True), args.milk_model)
    if not len(j):
        print("no periods in common between the milk and herd files")
        return 1
    summary = summarise(j)
    name = f"milk_error_split_{args.block}_{args.milk_tag}.csv"
    summary.to_csv(out / name, index=False)
    pd.set_option("display.width", 240)
    trust = "trusted" if args.quality == "on" else "all"
    t = show(summary, trust)
    print(f"\nMilk error split ({args.milk_model}; {trust} periods). within_10 = share of milk forecasts "
          "within +-10 %; the two ceilings use hindsight (diagnostic only):")
    print(t[["n", "within_10", "within_10_if_cows_exact", "within_10_if_yield_exact"]].round(3).to_string())
    print("\nSize of each part (mean absolute %, bias %), share of squared error from cows, and the "
          "cow-yield correlation (negative = the level k already offsets cow errors):")
    print(t[["mean_abs_cows_pct", "mean_abs_yield_pct", "bias_cows_pct", "bias_yield_pct",
             "cow_share_of_sq_error", "corr_cows_yield"]].round(3).to_string())
    from .error_split import patterns
    pt = patterns(j)
    for key, what in (("month", "calendar month of the target period"), ("year", "year of the forecast date")):
        print(f"\nYield-per-cow error by {what} (mean %, + = forecast too high; trusted periods):")
        print(pt[key].round(3).to_string())
        print("n periods:")
        print(pt[f"{key}_n"].fillna(0).astype(int).to_string())
    print(f"\nFile: {out / name}")
    return 0


def _cmd_backtest_ml(args: argparse.Namespace) -> int:
    """Direct ML forecaster (LightGBM + ridge), rolling origin; herd-level aggregates only."""
    from .backtest_herd import check_block
    from .freeze import DATA_END, final_test_origins
    from .ml_direct import MLConfig, run_ml_backtest, summary

    cfg = EngineConfig(cell_table=args.cell_table, conception_known=args.conception_known,
                       pregnancy_check_lag_days=args.pregnancy_lag)
    mcfg = MLConfig(refit_months=args.refit_months, half_life_days=args.half_life_days,
                    pipeline=args.pipeline == "on")
    grains = ("monthly", "weekly") if args.grain == "both" else (args.grain,)
    if args.block == "development":
        origins = {g: development_origins(g, every=args.every) for g in grains}
        score_until = TEST_START
    else:  # 2024-26 replay of a new model: post-hoc, never the run-once final test
        origins = {g: final_test_origins(g, every=args.every) for g in grains}
        score_until = DATA_END
    for g, o in origins.items():
        check_block(o, score_until, args.block)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = SqlHerdSource.from_env(cell_table=args.cell_table, conception_known=args.conception_known)
    res = run_ml_backtest(source, cfg, mcfg, origins, score_until, tuple(args.series),
                          benchmarks=args.benchmarks == "on",
                          progress=lambda msg: print(f"  {msg}", file=sys.stderr))
    if not len(res.errors):
        print("no forecasts were scored")
        return 1
    tag = f"{mcfg.tag()}{_bt(args)}"
    for g in ("monthly", "weekly", "daily"):
        part = res.errors[res.errors["grain"] == g]
        if not len(part):
            continue
        name = "weekly" if g == "daily" else g  # daily rows go with the weekly origins, as in backtest-milk
        path = out / f"ml_backtest_errors_{name}_{tag}.csv"
        part.to_csv(path, mode="a" if g == "daily" and path.exists() else "w",
                    header=not (g == "daily" and path.exists()), index=False)
    table = summary(res.errors)
    table.to_csv(out / f"ml_backtest_summary_{tag}.csv", index=False)
    res.importance.to_csv(out / f"ml_importance_{tag}.csv", index=False)
    pd.set_option("display.width", 220)
    for metric in ("accuracy", "within_10", "skill_vs_persistence", "bias_pct"):
        t = table.pivot_table(index=["series", "grain", "horizon"], columns="model", values=metric)
        print(f"\n[{args.block}] {metric} (herd-level aggregates):")
        print(t.round(3).to_string())
    print("\nMean |SHAP| by feature group (model scale, ml_lgbm):")
    print(res.importance.round(4).to_string(index=False))
    if len(res.notes):
        print("\nNotes (number of forecasts):")
        print(res.notes.to_string(index=False))
    print(f"\nFiles in {out}/ (tag {tag}). Milk hit rate with the quality split:\n"
          f"  hit-rate --files {out}/ml_backtest_errors_monthly_{tag}.csv "
          f"{out}/ml_backtest_errors_weekly_{tag}.csv")
    return 0


def _cmd_ml_report(args: argparse.Namespace) -> int:
    """Re-print the backtest-ml tables from its saved error files (nothing is re-run)."""
    from .ml_direct import summary

    out = Path(args.out)
    frames = [pd.read_csv(out / f"ml_backtest_errors_{g}_{args.tag}.csv")
              for g in ("monthly", "weekly") if (out / f"ml_backtest_errors_{g}_{args.tag}.csv").exists()]
    if not frames:
        print(f"no ml_backtest_errors_*_{args.tag}.csv in {out}")
        return 1
    errors = pd.concat(frames, ignore_index=True)
    if args.series:
        errors = errors[errors["series"].isin(args.series)]
    table = summary(errors)
    table.to_csv(out / f"ml_backtest_summary_{args.tag}.csv", index=False)
    pd.set_option("display.width", 220)
    pd.set_option("display.float_format", lambda v: f"{v:.3f}")
    for metric in args.metrics:
        t = table.pivot_table(index=["series", "grain", "horizon"], columns="model", values=metric)
        print(f"\n{metric} (herd-level aggregates):")
        print(t.to_string())
    return 0


def _cmd_ml_charts(args: argparse.Namespace) -> int:
    """PNG charts: pfoi-1.4.0-dev (ML) vs pfoi-1.2.0-dev vs persistence, matched periods."""
    from .ml_charts import draw, load

    ml_dir, pfoi_dir = Path(args.ml_dir), Path(args.pfoi_dir)
    pick = lambda d, pattern: [p for g in ("monthly", "weekly")  # noqa: E731
                               for p in [d / pattern.format(g=g)] if p.exists()]
    ml = pick(ml_dir, f"ml_backtest_errors_{{g}}_{args.ml_tag}.csv")
    milk = pick(pfoi_dir, f"milk_backtest_errors_{{g}}_{args.milk_tag}.csv")
    herd = pick(pfoi_dir, f"herd_backtest_errors_{{g}}_{args.herd_tag}.csv")
    for name, files in (("ML", ml), ("1.2.0-dev milk", milk), ("1.2.0-dev herd", herd)):
        print(f"{name}: {len(files)} file(s)")
    if not ml or not milk:
        print("need the backtest-ml files and the pfoi-1.2.0-dev milk files")
        return 1
    e = load(ml, milk, herd, args.milk_model, args.herd_model)
    imp_path = ml_dir / f"ml_importance_{args.ml_tag}.csv"
    imp = pd.read_csv(imp_path) if imp_path.exists() else None
    out = Path(args.out)
    for p in draw(e, out, imp):
        print(f"wrote {p}")
    print(f"matched forecasts per model: {len(e) // 3}")
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
    # posthoc is scored with the development block, so its intervals use the development
    # errors as their history (as the test block does)
    blocks = {"both": ("development", "test"),
              "posthoc": ("development", "posthoc")}.get(args.block, (args.block,))
    frames = []
    for block in blocks:
        suffix = {"test": "_test", "posthoc": "_posthoc"}.get(block, "")
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
    interval_quality = q if getattr(args, "interval_quality", "on") == "on" else None
    errors = prepare(add_recovery(errors), method=args.intervals, quality=interval_quality)
    card = scorecard(errors)
    iv = "" if args.intervals == "empirical" else f"_{args.intervals}"
    quality_tag = "_quality_off" if args.quality == "off" else ""
    interval_quality_tag = "_interval_quality_off" if getattr(args, "interval_quality", "on") == "off" else ""
    name = f"scorecard_{args.block}_{mcfg.tag()}_{_wtag(args)}{iv}{quality_tag}{interval_quality_tag}.csv"
    card.to_csv(out / name, index=False)

    pd.set_option("display.width", 200)
    show = card[card["target"] != "no target"]
    cols = ["n", "n_coverage", "accuracy", "target_accuracy", "skill", "best_benchmark", "bias_pct",
            "coverage80", "coverage90", "width90", "deviance_ratio", "target", "calibrated", "reasons"]
    for block, b in show.groupby("block", sort=False):
        print(f"\n=== {block} block: targets (docs/targets.md), herd-level aggregates ===")
        print(b.set_index(["grain", "series", "horizon", "model"])[cols]
              .to_string(float_format=lambda v: f"{v:.3f}"))
        prim = b[b["model"].isin(["milk_baseline", "herd_engine"])]
        print(f"rows met (target and calibrated): {int(prim['met'].sum())} of {len(prim)}; "
              f"not interpretable: {int((prim['target'] == 'not interpretable').sum())}")
    if blocks == ("development", "test"):
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


# Tag endings of files that are not development backtests. Model selection (adapt,
# drivers, nested-cv) must never read them: 2024-26 errors would leak into the choice.
# Oracle driver runs use the actual weather of the target period (analysis only, M5).
NOT_DEVELOPMENT = ("_test", "_posthoc", "_oracle")
# Tag part of configurations without hindsight in pregnancy states (leakage audit L2, L3):
# conception cut "known", cell table day_cell_known, conceptions known when recorded.
HONEST_TAG = "_ck_kn_rk"

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
            if not m or tag.endswith(NOT_DEVELOPMENT) or "_ad" in tag:
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


TREND_RAW_TAG = "herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6"


def _cmd_adapt_trend(args: argparse.Namespace) -> int:
    """pfoi-1.2.1-dev: damped-trend adaptive milk correction, settings chosen year by year."""
    from .adaptive import TrendConfig
    from .freeze import V11_ADAPTIVE
    from .nested_cv import choose_trend_by_year

    out = Path(args.out)
    tag = args.tag
    if tag.endswith(NOT_DEVELOPMENT) or "_ad" in tag:
        print(f"{tag}: give the raw development milk tag (no _test/_posthoc/_oracle, no _ad...)")
        return 1
    paths = [out / f"milk_backtest_errors_{g}_{tag}.csv" for g in ("monthly", "weekly")]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        print(f"not found: {', '.join(missing)}")
        return 1
    e = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    e = e[e["series"] == "herd_milk"]
    cfg = V11_ADAPTIVE  # the pfoi-1.2.0-dev correction: per horizon, q30 0.1, tau 365, z 3
    grid = [TrendConfig(phi=ph, q_trend=q) for ph in args.phi for q in args.q_trend]
    off, chosen, folds = choose_trend_by_year(e, "milk_baseline", cfg, grid, metric=args.metric)
    new_tag = f"{tag}_ad{cfg.label()}_trnested"
    bench = e[e["model"].isin(BENCHMARK_MODELS)]
    both = pd.concat([off, chosen, bench], ignore_index=True)
    file_grain = both["grain"].where(both["grain"] == "monthly", "weekly")
    for g, part in both.groupby(file_grain):
        part.to_csv(out / f"milk_backtest_errors_{g}_{new_tag}.csv", index=False)
    pd.set_option("display.width", 200)
    f = folds.assign(cell=[f"{v:.4f}{'*' if sel else ''}" if pd.notna(v) else "-"
                           for v, sel in zip(folds["inner_score"], folds["selected"])])
    print(f"Inner score by forecast year ({args.metric} on periods ended before 1 Jan of the year; "
          "* = used for that year; no score = 'off'):")
    print(f.pivot(index="candidate", columns="fold_year", values="cell").to_string())
    if len(chosen):
        print("\nSetting used by forecast year (number of forecasts):")
        yr = pd.to_datetime(chosen["origin"]).dt.year
        print(chosen.groupby([yr.rename("year"), "trend_setting"]).size().unstack(fill_value=0).to_string())
    # Exactness check against the pfoi-1.2.0-dev files (aggregates only)
    ref_paths = [out / f"milk_backtest_errors_{g}_{tag}_ad{cfg.label()}.csv" for g in ("monthly", "weekly")]
    if all(p.exists() for p in ref_paths):
        ref = pd.concat([pd.read_csv(p) for p in ref_paths], ignore_index=True)
        ref = ref[(ref["model"] == "milk_baseline_adaptive") & (ref["series"] == "herd_milk")]
        k = ["origin", "grain", "horizon", "period_start"]
        mine = off.assign(origin=off["origin"].astype(str), period_start=off["period_start"].astype(str))
        m = ref.assign(origin=ref["origin"].astype(str), period_start=ref["period_start"].astype(str)) \
            .merge(mine, on=k, suffixes=("_ref", "_new"))
        rel = ((m["forecast_new"] - m["forecast_ref"]).abs() / m["forecast_ref"].abs()).max() if len(m) else float("nan")
        print(f"\nCheck: trend off vs pfoi-1.2.0-dev milk_baseline_adaptive: {len(m)} of {len(ref)} rows "
              f"matched, max relative difference {rel:.2e} (expected 0 up to CSV float rounding, < 1e-12)")
    print(f"\nWrote milk_backtest_errors_{{monthly,weekly}}_{new_tag}.csv with milk_baseline_adaptive "
          "(trend off), milk_baseline_adaptive_trend (chosen year by year) and the benchmarks.")
    return 0


def _cmd_blend(args: argparse.Namespace) -> int:
    """Layer 2: persistence blend of one development milk backtest (daily and weekly rows).

    Reads the files of ``--tag`` (monthly and weekly), keeps every row, adds the blended model
    ``<base>_blend`` with its own 5-95 % intervals and writes both files under ``<tag>_bl``."""
    from .blend import persistence_blend
    from .error_tools import add_intervals

    out = Path(args.out)
    if args.tag.endswith(NOT_DEVELOPMENT) or args.tag.endswith("_bl"):
        print(f"{args.tag!r} is not a development tag of a model to blend")
        return 2
    paths = {g: out / f"milk_backtest_errors_{g}_{args.tag}.csv" for g in ("monthly", "weekly")}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        print(f"missing: {missing}")
        return 1
    frames = {g: pd.read_csv(p) for g, p in paths.items()}
    e = pd.concat(frames.values(), ignore_index=True)
    if not e["model"].eq(args.base).any():
        print(f"model {args.base!r} not in {args.tag}; models: {sorted(e['model'].unique())}")
        return 1
    blend = persistence_blend(e, base_model=args.base, min_obs=args.min_obs)
    if not len(blend):
        print("no blendable rows (needs persistence rows for the same periods)")
        return 1
    new_model = blend["model"].iloc[0]
    scored = add_intervals(pd.concat([e[e["model"] == args.base], blend], ignore_index=True))
    blend = scored[scored["model"] == new_model].copy()
    for col in ("origin", "period_start", "period_end"):  # same plain dates as the backtest files
        blend[col] = pd.to_datetime(blend[col]).dt.strftime("%Y-%m-%d")
    new_tag = f"{args.tag}_bl"
    for g, part in frames.items():
        grains = {"monthly": ("monthly",), "weekly": ("weekly", "daily")}[g]
        rows = pd.concat([part, blend[blend["grain"].isin(grains)]], ignore_index=True)
        rows.to_csv(out / f"milk_backtest_errors_{g}_{new_tag}.csv", index=False)
    w = blend.groupby(["grain", "horizon"])["blend_w"].agg(["size", "mean", "min", "max"]).round(2)
    print(f"wrote milk_backtest_errors_{{monthly,weekly}}_{new_tag}.csv (model {new_model}).")
    print("Weight on the structural forecast (1 = structural only; rows with too little history = 1):")
    print(w.to_string())
    print("\nScore it by regime, against the structural model on the same periods:")
    print(f"  python -m components.predictive_farm_intelligence.pfoi.regimes "
          f"{out}/milk_backtest_errors_*_{new_tag}.csv --model {args.base} --model-b {new_model}")
    return 0


DRIVER_GROUPS = {"weather": "W", "health": "H", "sensor": "S", "quality": "Q", "season": "C",
                 "recent": "R"}


def _cmd_drivers(args: argparse.Namespace) -> int:
    """Layer 2: driver layer on one development milk backtest (raw or adaptive)."""
    from .drivers import DriverConfig, driver_layer
    from .freeze import DATA_END

    out = Path(args.out)
    paths = [out / f"milk_backtest_errors_{g}_{args.tag}.csv" for g in ("monthly", "weekly")]
    paths = [p for p in paths if p.exists()]
    if not paths or args.tag.endswith(NOT_DEVELOPMENT):
        print(f"no development milk files for tag {args.tag!r} in {out}")
        return 1
    e = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    src = SqlHerdSource.from_env()
    daily = src.driver_daily(DATA_START, DATA_END)
    if "sensor" in args.groups or "quality" in args.groups:  # M6 session-sensor summaries
        daily = daily.merge(src.sensor_daily(DATA_START, DATA_END), on="date", how="left")
    cfg = DriverConfig(groups=tuple(args.groups), weather_lag_days=args.weather_lag,
                       thi_knot_pct=args.thi_knot, oracle=args.oracle)
    new_model = f"{args.base}_drivers" + ("_oracle" if cfg.oracle else "")
    res = driver_layer(e, daily, args.base, new_model=new_model, cfg=cfg)
    bench = e[e["model"].isin(BENCHMARK_MODELS)]
    both = pd.concat([res.errors, bench], ignore_index=True)
    file_grain = both["grain"].where(both["grain"] == "monthly", "weekly")
    groups = "" if set(args.groups) == set(DRIVER_GROUPS) else "_g" + "".join(
        DRIVER_GROUPS[g] for g in DRIVER_GROUPS if g in args.groups)
    new_tag = f"{args.tag}_dr_{cfg.label().replace('_oracle', '')}{groups}" + ("_oracle" if cfg.oracle else "")
    if cfg.oracle:
        print("ORACLE RUN: uses the actual weather of each target period. Analysis only; "
              "never an operational forecast and never offered to model selection.")
    for g, part in both.groupby(file_grain):
        part.to_csv(out / f"milk_backtest_errors_{g}_{new_tag}.csv", index=False)
    res.coefficients.to_csv(out / f"drivers_coefficients_{new_tag}.csv", index=False)
    res.registry.to_csv(out / f"drivers_registry_{new_tag}.csv")
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


def _cmd_gate_audit(args: argparse.Namespace) -> int:
    """G1: can unstable positions be recognised at the forecast date? (go/no-go, aggregates)"""
    from .episodes import add_bands, daily_quality
    from .freeze import DATA_END
    from .gate import GateConfig, run_gate_audit

    out = Path(args.out)
    if args.tag.endswith(NOT_DEVELOPMENT) or (args.alt_tag and args.alt_tag.endswith(NOT_DEVELOPMENT)):
        print("development tags only (no _test/_posthoc/_oracle): the test block is never used")
        return 1
    frames = []
    for tag in [args.tag] + ([args.alt_tag] if args.alt_tag else []):
        for g in ("monthly", "weekly"):
            path = out / f"milk_backtest_errors_{g}_{tag}.csv"
            if path.exists():
                frames.append(pd.read_csv(path))
            else:
                print(f"NOTE: {path.name} not found", file=sys.stderr)
    if not frames:
        print("no error files found")
        return 1
    e = pd.concat(frames, ignore_index=True)
    e = e[(e["series"] == "herd_milk") & (pd.to_datetime(e["origin"]) < pd.Timestamp(TEST_START))]
    if args.base not in set(e["model"]):
        print(f"model {args.base!r} not in the files")
        return 1
    src = SqlHerdSource.from_env()
    target = src.target_daily(DATA_START, DATA_END)
    panel = src.panel_daily(DATA_START, DATA_END)
    e = add_bands(e, daily_quality(target, panel))
    daily = (src.driver_daily(DATA_START, DATA_END)
             .merge(target[["date", "target_source", "data_gap"]], on="date", how="left")
             .merge(panel[["date", "n_herd"]], on="date", how="left"))
    daily = daily[pd.to_datetime(daily["date"]) < pd.Timestamp(TEST_START)]
    cfg = GateConfig(markov=not args.no_markov, threshold=args.threshold)
    alts = tuple(a for a in args.alts if a in set(e["model"]))
    audit = run_gate_audit(e, daily, args.base, alternatives=alts, cfg=cfg)
    name = f"{args.tag}_{args.base}"
    audit.folds.to_csv(out / f"gate_folds_{name}.csv", index=False)
    pd.concat([audit.scores_by_year.assign(by="fold_year"), audit.scores_by_cell.assign(by="cell")]) \
        .to_csv(out / f"gate_scores_{name}.csv", index=False)
    audit.features.to_csv(out / f"gate_features_{name}.csv", index=False)
    audit.switch.to_csv(out / f"gate_switch_{name}.csv", index=False)
    audit.auc_target.to_csv(out / f"gate_auc_target_{name}.csv", index=False)
    audit.predictions.to_csv(out / f"gate_probs_{name}.csv", index=False)  # herd-level, for G2
    pd.set_option("display.width", 220)
    print(f"Gate audit G1, development origins only, trusted periods as labels; base {args.base}, "
          f"misses = outside +-10 %. Markov feature {'on' if cfg.markov else 'off'}.")
    print("\n=== folds: labels ended before 1 Jan of the fold year ===")
    print(audit.folds.to_string(index=False))
    print("\n=== gate scores by fold year (brier_skill > 0 = better than the horizon's usual miss rate; "
          "auc = within grain x horizon, 0.5 = no skill) ===")
    print(audit.scores_by_year.round(3).to_string(index=False))
    print("\n=== gate scores by grain x horizon (all fold years) ===")
    print(audit.scores_by_cell.round(3).to_string(index=False))
    print("\n=== single signals: AUC within grain x horizon (descriptive) ===")
    print(audit.features.round(3).to_string(index=False))
    if len(audit.switch):
        print(f"\n=== switching check (gate lgbm, p > {cfg.threshold}; alternatives {', '.join(alts)}; "
              "persistence excluded). Ceiling = hindsight best-of, NOT a forecast ===")
        print(audit.switch.round(3).to_string(index=False))
    if len(audit.auc_target):
        print("\n=== AUC target 0.80 (user, 2026-10-22), within each grain x horizon, all fold years; "
              "interval = 5-95 % bootstrap over origin months; long = week 13, months 6 and 12 ===")
        print(audit.auc_target.round(3).to_string(index=False))
    print("\n=== pre-registered G1 rule: brier_skill > 0 and auc >= 0.65 over 2019-2023, "
          "brier_skill > 0 in >= 3 fold years ===")
    print(audit.verdict.round(3).to_string(index=False))
    print(f"\nVerdict: {'GO (build specialists, step G2)' if audit.go else 'NO-GO (instability not recognisable from these signals; switch path)'}")
    return 0


def _milk_files(out: Path, tag: str) -> pd.DataFrame | None:
    frames = []
    for g in ("monthly", "weekly"):
        path = out / f"milk_backtest_errors_{g}_{tag}.csv"
        if path.exists():
            frames.append(pd.read_csv(path))
        else:
            print(f"NOTE: {path.name} not found", file=sys.stderr)
    if not frames:
        return None
    e = pd.concat(frames, ignore_index=True)
    return e[(e["series"] == "herd_milk") & (pd.to_datetime(e["origin"]) < pd.Timestamp(TEST_START))]


def _write_grain_files(rows: pd.DataFrame, out: Path, tag: str) -> None:
    file_grain = rows["grain"].where(rows["grain"] == "monthly", "weekly")
    for g, part in rows.groupby(file_grain):
        part.to_csv(out / f"milk_backtest_errors_{g}_{tag}.csv", index=False)


def _cmd_specialist_a(args: argparse.Namespace) -> int:
    """G2 Track A: fast re-level specialist S1, used only where the G1 gate says unstable."""
    from .episodes import add_bands, daily_quality
    from .freeze import DATA_END
    from .specialists import (TRACK_A_CELLS, fast_relevel, gated_switch, matched_hits, track_a_rule)

    out = Path(args.out)
    base_e, raw_e = _milk_files(out, args.tag), _milk_files(out, args.raw_tag)
    probs_path = out / f"gate_probs_{args.tag}_{args.base}.csv"
    if base_e is None or raw_e is None or not probs_path.exists():
        print(f"need the base and raw milk files and {probs_path.name} (run gate-audit first)")
        return 1
    src = SqlHerdSource.from_env()
    q = daily_quality(src.target_daily(DATA_START, DATA_END), src.panel_daily(DATA_START, DATA_END))
    raw = add_bands(raw_e[raw_e["model"] == "milk_baseline"], q)
    base = base_e[base_e["model"] == args.base]
    probs = pd.read_csv(probs_path)
    s1 = fast_relevel(raw)
    gated = gated_switch(base, s1, probs, gate=args.gate, threshold=args.threshold)
    hits = matched_hits({args.base: base, "gated_s1": gated}, keys_from=probs)
    hits_y = matched_hits({args.base: base, "gated_s1": gated}, keys_from=probs, by_year=True)
    hits_s1 = matched_hits({args.base: base, "s1_relevel": s1}, keys_from=probs)
    checks, keep = track_a_rule(hits, hits_y, args.base, "gated_s1")
    new_tag = f"{args.tag}_gs1"
    _write_grain_files(pd.concat([base, s1, gated.drop(columns="switched")], ignore_index=True), out, new_tag)
    pd.set_option("display.width", 220)
    a_cells = set(TRACK_A_CELLS)
    is_a = lambda t: [(g, int(h)) in a_cells for g, h in zip(t["grain"], t["horizon"])]  # noqa: E731
    print(f"G2 Track A: S1 re-level (raw structural x level of its own finished <=14-day errors, last 14 "
          f"days, trusted), used where the {args.gate} gate p > {args.threshold}; development fold years "
          "2019-2023, periods the gate scored (trusted).")
    g2 = gated.copy()
    g2["year"] = pd.to_datetime(g2["origin"]).dt.year
    print("\n=== share of forecasts switched to S1, by year (Track A cells) ===")
    print(g2[is_a(g2)].groupby("year")["switched"].mean().round(3).to_string())
    print("\n=== share within +-10 %: 1.2.0-dev vs gated S1 (same periods) ===")
    print(hits.pivot_table(index=["grain", "horizon"], columns="model", values="within_10").round(3)
          .assign(n=hits.groupby(["grain", "horizon"])["n"].max()).to_string())
    print("\n=== S1 alone, ungated (descriptive; periods where S1 had a level) ===")
    print(hits_s1.pivot_table(index=["grain", "horizon"], columns="model", values="within_10").round(3)
          .assign(n=hits_s1.groupby(["grain", "horizon"])["n"].max()).to_string())
    hy = hits_y[is_a(hits_y)]
    print("\n=== by forecast year, mean over Track A cells ===")
    print(hy.groupby(["year", "model"])["within_10"].mean().unstack().round(3).to_string())
    print("\n=== pre-registered Track A rule ===")
    print(checks.round(3).to_string(index=False))
    print(f"Verdict: {'KEEP gated S1 for Track A cells' if keep else 'DROP (record as tested; code kept, off)'}")
    print(f"Wrote milk_backtest_errors_{{monthly,weekly}}_{new_tag}.csv")
    return 0


def _specialist_b_tuned(args, base: pd.DataFrame, herd: pd.DataFrame, daily: pd.DataFrame) -> int:
    from .episodes import VERIFIED_BANDS
    from .specialists import (DEV_END, TRACK_B_CELLS, chronos2_pipeline, matched_hits, predictor_from,
                              track_b_rule, weekly_series)
    from .tuning import tuned_track_b

    pipe = chronos2_pipeline(args.model, args.device)
    predictors = {"median": predictor_from(pipe, "median"), "mean": predictor_from(pipe, "mean")}
    trusted = base[base["band"].isin(VERIFIED_BANDS)]
    weekly = weekly_series(daily[pd.to_datetime(daily["date"]) < pd.Timestamp(DEV_END)])
    rows, choice, hind = tuned_track_b(trusted, herd, weekly, predictors)
    out = Path(args.out)
    choice.to_csv(out / f"tune_track_b_choice_{args.tag}.csv", index=False)
    hind.to_csv(out / f"tune_track_b_hindsight_{args.tag}.csv", index=False)
    pd.set_option("display.width", 220)
    print("Nested tuning of Chronos-2 settings (context source current/all, 520/260/104 weeks, median/mean), "
          "chosen per fold year 2019-2023 on long-horizon forecasts dated in the last 20 % of the inner span.")
    print("\n=== chosen setting per fold year (validation = mean share within +-10 % over long cells) ===")
    print(choice.round(3).to_string(index=False))
    print("\n=== each fixed setting over 2019-2023 (hindsight, NOT a result; shows tuning optimism) ===")
    print(hind.round(3).to_string(index=False))
    if not len(rows):
        print("no tuned forecasts")
        return 0
    pair = {args.base: trusted, "chronos2_tuned": rows}
    hits, hits_y = matched_hits(pair), matched_hits(pair, by_year=True)
    checks, keep = track_b_rule(hits, hits_y, args.base, "chronos2_tuned")
    print("\n=== share within +-10 %, 1.2.0-dev vs tuned Chronos-2 (fold years 2019-2023, matched) ===")
    print(hits.pivot_table(index=["grain", "horizon"], columns="model", values="within_10").round(3)
          .assign(n=hits.groupby(["grain", "horizon"])["n"].max()).to_string())
    long = set(TRACK_B_CELLS)
    hy = hits_y[[(g, int(h)) in long for g, h in zip(hits_y["grain"], hits_y["horizon"])]]
    print("\n=== by forecast year, mean over week 13, month 6, month 12 ===")
    print(hy.groupby(["year", "model"])["within_10"].mean().unstack().round(3).to_string())
    print("\n=== pre-registered Track B rule (unchanged; fold years 2019-2023) ===")
    print(checks.round(3).to_string(index=False))
    print(f"Verdict: {'KEEP for long horizons' if keep else 'DROP (record as tested; code kept, off)'}")
    return 0


def _cmd_specialist_b(args: argparse.Namespace) -> int:
    """G2 Track B: zero-shot Chronos-2 yield per cow x engine milking cows, all periods."""
    from .episodes import add_bands, daily_quality
    from .freeze import DATA_END
    from .specialists import TRACK_B_CELLS, chronos2_predictor, run_track_b

    out = Path(args.out)
    base_e = _milk_files(out, args.tag)
    herd_paths = [out / f"herd_backtest_errors_{g}_{args.herd_tag}.csv" for g in ("monthly", "weekly")]
    missing = [p.name for p in herd_paths if not p.exists()]
    if base_e is None or missing:
        print(f"need the base milk files and {', '.join(missing) or 'herd files'}")
        return 1
    herd = pd.concat([pd.read_csv(p) for p in herd_paths], ignore_index=True)
    src = SqlHerdSource.from_env()
    target = src.target_daily(DATA_START, DATA_END)
    panel = src.panel_daily(DATA_START, DATA_END)
    base = add_bands(base_e[base_e["model"] == args.base], daily_quality(target, panel))
    daily = target.merge(panel[["date", "milking"]], on="date", how="left")
    print(f"Loading {args.model} locally (weights from Hugging Face on first use; no farm data is sent).")
    if args.tune:
        return _specialist_b_tuned(args, base, herd, daily)
    predictor = chronos2_predictor(args.model, args.device)
    res = run_track_b(base, herd, daily, predictor, base_model=args.base)
    new_tag = f"{args.tag}_chronos2"
    if len(res.rows):
        _write_grain_files(pd.concat([base, res.rows], ignore_index=True), out, new_tag)
    pd.set_option("display.width", 220)
    print("G2 Track B: zero-shot Chronos-2 on weekly litres per recorded milking cow (trusted days, current "
          "source, weeks ended before the forecast date) x engine-projected milking cows; development "
          "origins 2017-2023, trusted periods matched with 1.2.0-dev.")
    print("\n=== coverage: trusted base periods and forecasts issued ===")
    print(res.coverage.to_string(index=False))
    if len(res.hits):
        print("\n=== share within +-10 % (each candidate matched with 1.2.0-dev on its own periods) ===")
        print(res.hits.pivot_table(index=["grain", "horizon"], columns="model", values="within_10").round(3)
              .assign(n=res.hits.groupby(["grain", "horizon"])["n"].max()).to_string())
        long = set(TRACK_B_CELLS)
        hy = res.hits_y[[(g, int(h)) in long for g, h in zip(res.hits_y["grain"], res.hits_y["horizon"])]]
        print("\n=== by forecast year, mean over week 13, month 6, month 12 ===")
        print(hy.groupby(["year", "model"])["within_10"].mean().unstack().round(3).to_string())
        print("n periods:")
        print(hy.groupby(["year", "model"])["n"].sum().unstack().fillna(0).astype(int).to_string())
    print("\n=== pre-registered Track B rule (chronos2_ypc_x_engine vs 1.2.0-dev) ===")
    print(res.checks.round(3).to_string(index=False) if len(res.checks) else "no forecasts to score")
    print(f"Verdict: {'KEEP for long horizons' if res.keep else 'DROP (record as tested; code kept, off)'}")
    return 0


def _gate_inputs(args: argparse.Namespace):
    """Development milk errors (base + raw tags) with quality bands, and herd-level daily inputs."""
    from .episodes import add_bands, daily_quality
    from .freeze import DATA_END

    out = Path(args.out)
    frames = [f for f in (_milk_files(out, args.tag), _milk_files(out, args.raw_tag)) if f is not None]
    if not frames:
        return None, None
    e = pd.concat(frames, ignore_index=True)
    src = SqlHerdSource.from_env()
    target = src.target_daily(DATA_START, DATA_END)
    panel = src.panel_daily(DATA_START, DATA_END)
    e = add_bands(e, daily_quality(target, panel))
    daily = (src.driver_daily(DATA_START, DATA_END)
             .merge(target[["date", "target_source", "data_gap"]], on="date", how="left")
             .merge(panel[["date", "n_herd"]], on="date", how="left"))
    return e, daily[pd.to_datetime(daily["date"]) < pd.Timestamp(TEST_START)]


def _cmd_tune_gate(args: argparse.Namespace) -> int:
    """Nested tuning of the gate and of the Track A switch (S1 window, gate threshold)."""
    from .gate import GateConfig, GateFeatures, auc_target_table, label_rows
    from .specialists import TRACK_A_CELLS, matched_hits, track_a_rule
    from .tuning import tuned_gate, tuned_gate_scores, tuned_track_a

    out = Path(args.out)
    e, daily = _gate_inputs(args)
    if e is None or args.base not in set(e["model"]):
        print("no development milk files with the base model")
        return 1
    labels = label_rows(e, args.base)
    X = GateFeatures(daily, labels, GateConfig(markov=not args.no_markov)).matrix(labels)
    tg = tuned_gate(labels, X)
    g1_path = out / f"gate_probs_{args.tag}_{args.base}.csv"
    g1 = pd.read_csv(g1_path) if g1_path.exists() else None
    scores = tuned_gate_scores(tg.predictions, g1)
    auc_t = auc_target_table(tg.predictions, gates=("tuned",))
    raw = e[e["model"] == "milk_baseline"]
    rows, choice, grid = tuned_track_a(raw, tg)
    base_rows = tg.predictions.assign(model=args.base)
    tuned_rows = rows.assign(model="gated_s1_tuned")
    hits = matched_hits({args.base: base_rows, "gated_s1_tuned": tuned_rows})
    hits_y = matched_hits({args.base: base_rows, "gated_s1_tuned": tuned_rows}, by_year=True)
    checks, keep = track_a_rule(hits, hits_y, args.base, "gated_s1_tuned")
    name = f"{args.tag}_{args.base}"
    tg.folds.to_csv(out / f"tune_gate_folds_{name}.csv", index=False)
    tg.grid_scores.to_csv(out / f"tune_gate_grid_{name}.csv", index=False)
    scores.to_csv(out / f"tune_gate_scores_{name}.csv", index=False)
    choice.to_csv(out / f"tune_track_a_choice_{name}.csv", index=False)
    grid.to_csv(out / f"tune_track_a_grid_{name}.csv", index=False)
    tg.predictions.to_csv(out / f"gate_probs_tuned_{name}.csv", index=False)
    pd.set_option("display.width", 220)
    print("Nested tuning (fold years 2019-2023): each year's settings chosen on an inner chronological "
          "80:20 split of labels ended by 1 Jan, embargo = grain's longest horizon (14 d / 91 d / 365 d); "
          "the year itself is never used for selection.")
    print("\n=== gate: chosen setting per fold year (validation Brier, lower is better) ===")
    print(tg.folds.round(4).to_string(index=False))
    print("\n=== gate: outer scores, tuned vs G1 fixed gates (same forecasts) ===")
    print(scores.round(3).to_string(index=False))
    print("\n=== tuned gate: AUC target 0.80 per grain x horizon ===")
    print(auc_t.round(3).to_string(index=False))
    print("\n=== Track A: S1 window and gate threshold chosen per fold year ===")
    print(choice.round(3).to_string(index=False))
    cells = set(TRACK_A_CELLS)
    print("\n=== Track A: share within +-10 %, 1.2.0-dev vs tuned gated S1 ===")
    ha = hits[[(g, int(h)) in cells for g, h in zip(hits["grain"], hits["horizon"])]]
    print(ha.pivot_table(index=["grain", "horizon"], columns="model", values="within_10").round(3)
          .assign(n=ha.groupby(["grain", "horizon"])["n"].max()).to_string())
    hy = hits_y[[(g, int(h)) in cells for g, h in zip(hits_y["grain"], hits_y["horizon"])]]
    print("\n=== Track A by forecast year (mean over Track A cells) ===")
    print(hy.groupby(["year", "model"])["within_10"].mean().unstack().round(3).to_string())
    print("\n=== pre-registered Track A rule (unchanged) ===")
    print(checks.round(3).to_string(index=False))
    print(f"Verdict: {'KEEP tuned gated S1 for Track A cells' if keep else 'DROP (record as tested; code kept, off)'}")
    return 0


def _cmd_compare_target(args: argparse.Namespace) -> int:
    """Recorded target (shipment, then DelPro) vs DelPro-only target, same model and origins."""
    from .delpro_target import DELPRO_START, delpro_target, target_rule
    from .episodes import VERIFIED_BANDS, add_bands, daily_quality
    from .freeze import DATA_END
    from .specialists import matched_hits

    out = Path(args.out)
    rec, dp = _milk_files(out, args.tag_record), _milk_files(out, args.tag_delpro)
    if rec is None or dp is None:
        print("need both milk error file sets (run backtest-milk --target delpro and adapt first)")
        return 1
    start = pd.Timestamp(args.start)
    pick = lambda e: e[(e["model"] == args.model) & (pd.to_datetime(e["origin"]) >= start)]  # noqa: E731
    rec, dp = pick(rec), pick(dp)
    src = SqlHerdSource.from_env()
    panel = src.panel_daily(DATA_START, DATA_END)
    rec = add_bands(rec, daily_quality(src.target_daily(DATA_START, DATA_END), panel))
    dp = add_bands(dp, daily_quality(delpro_target(src.delpro_daily(DATA_START, DATA_END)), panel))
    rec, dp = rec[rec["band"].isin(VERIFIED_BANDS)], dp[dp["band"].isin(VERIFIED_BANDS)]
    own = pd.concat([matched_hits({"record_target": rec}), matched_hits({"delpro_target": dp})], ignore_index=True)
    pair = {"record_target": rec, "delpro_target": dp}
    hits, hits_y = matched_hits(pair), matched_hits(pair, by_year=True)
    pd.set_option("display.width", 220)
    if not len(hits):
        print(f"no periods trusted under both targets (record {len(rec)}, DelPro {len(dp)} trusted rows)")
        return 0
    checks, keep = target_rule(hits, hits_y, "record_target", "delpro_target")
    print(f"Model {args.model}, development origins from {start.date()} (DelPro starts {DELPRO_START}); "
          "each target's own trusted periods. Different measures: this compares how well each can be "
          "forecast, not two forecasts of one quantity.")
    print("\n=== each target on its own trusted periods: share within +-10 % ===")
    print(own.pivot_table(index=["grain", "horizon"], columns="model", values=["within_10", "n"]).round(3).to_string())
    print("\n=== periods trusted under both targets ===")
    print(hits.pivot_table(index=["grain", "horizon"], columns="model", values="within_10").round(3)
          .assign(n=hits.groupby(["grain", "horizon"])["n"].max()).to_string())
    print("\n=== by forecast year (periods trusted under both), mean over week 13, month 6, month 12 ===")
    long = hits_y[[(g, int(h)) in {("weekly", 13), ("monthly", 6), ("monthly", 12)}
                   for g, h in zip(hits_y["grain"], hits_y["horizon"])]]
    print(long.groupby(["year", "model"])["within_10"].mean().unstack().round(3).to_string())
    print("n periods:")
    print(long.groupby(["year", "model"])["n"].sum().unstack().fillna(0).astype(int).to_string())
    print("\n=== pre-registered rule (DelPro-only target vs recorded target) ===")
    print(checks.round(3).to_string(index=False))
    print(f"Verdict: {'DelPro-only target is better forecastable at long horizons' if keep else 'not shown better (record as tested)'}")
    return 0


def _cmd_gate_outlook(args: argparse.Namespace) -> int:
    """pfoi-1.2.1-dev page documents from built 1.2.0-dev documents (files only, for compare-runs)."""
    from .episodes import add_bands, daily_quality
    from .freeze import DATA_END
    from .gate_outlook import run

    out = Path(args.out)
    frames = []
    for suffix in ("", "_posthoc"):
        for g in ("monthly", "weekly"):
            path = out / f"milk_backtest_errors_{g}_{args.tag}{suffix}.csv"
            if path.exists():
                frames.append(pd.read_csv(path))
    if not frames:
        print(f"no milk error files for {args.tag}")
        return 1
    e = pd.concat(frames, ignore_index=True)
    e = e[(e["series"] == "herd_milk") & (e["model"] == "milk_baseline_adaptive")]
    src = SqlHerdSource.from_env()
    target = src.target_daily(DATA_START, DATA_END)
    panel = src.panel_daily(DATA_START, DATA_END)
    e = add_bands(e, daily_quality(target, panel))
    daily = (src.driver_daily(DATA_START, DATA_END)
             .merge(target[["date", "target_source", "data_gap"]], on="date", how="left")
             .merge(panel[["date", "n_herd"]], on="date", how="left"))
    print("Forecast dates from 2024 use 2024-26 outcomes that ended before them (post-test development, "
          "descriptive only).", file=sys.stderr)
    rc = run(out, args.source, e, daily, args.origins, markov=not args.no_markov)
    if rc == 0 and args.write:
        import json

        from sqlalchemy import create_engine

        from .config import DatabaseSettings
        from .gate_intervals import VERSION
        from .outlook import write_run_document

        engine = create_engine(DatabaseSettings.from_env().url)
        files = sorted((out / "outlook" / VERSION).glob("run_*.json"))
        if args.origins:
            wanted = {date.fromisoformat(o).strftime("%Y%m") for o in args.origins}
            files = [f for f in files if f.stem.split("_")[1] in wanted]
        for f in files:
            write_run_document(engine, json.loads(f.read_text()))
        print(f"written to c1_output.run_document: {len(files)} {VERSION} documents (the page shows the newest "
              "build per forecast date)")
    return rc


def _cmd_gate_intervals(args: argparse.Namespace) -> int:
    """pfoi-1.2.1-dev on the development backtest: ranges by confidence, pre-registered rule."""
    from .episodes import VERIFIED_BANDS, add_bands, daily_quality
    from .freeze import DATA_END
    from .gate_intervals import build_121, interval_rule, interval_scores

    out = Path(args.out)
    milk = _milk_files(out, args.tag)
    probs_path = out / f"gate_probs_{args.tag}_{args.base}.csv"
    if milk is None or not probs_path.exists():
        print(f"need the milk files and {probs_path.name} (run gate-audit first)")
        return 1
    src = SqlHerdSource.from_env()
    milk = add_bands(milk[milk["model"] == args.base],
                     daily_quality(src.target_daily(DATA_START, DATA_END), src.panel_daily(DATA_START, DATA_END)))
    milk = milk[milk["band"].isin(VERIFIED_BANDS)]
    herd_paths = [out / f"herd_backtest_errors_{g}_{args.herd_tag}.csv" for g in ("monthly", "weekly")]
    herd = pd.concat([pd.read_csv(p) for p in herd_paths if p.exists()], ignore_index=True) \
        if any(p.exists() for p in herd_paths) else None
    if herd is not None:
        herd = herd[(herd["model"] == "herd_engine") & herd["series"].isin(["milking", "n_herd"])
                    & (pd.to_datetime(herd["origin"]) < pd.Timestamp(TEST_START))]
    rows = build_121(milk, pd.read_csv(probs_path), herd)
    rows.drop(columns=[c for c in ("band",) if c in rows]).to_csv(
        out / f"milk_backtest_errors_gate121_{args.tag}.csv", index=False)
    m = rows[rows["series"] == "herd_milk"]
    s_milk = interval_scores(m, by=("confidence",))
    s_grain = interval_scores(m, by=("grain", "confidence"))
    s_herd = interval_scores(rows[rows["series"] != "herd_milk"], by=("series", "confidence"))
    yr = m.assign(year=pd.to_datetime(m["origin"]).dt.year)
    s_year = interval_scores(yr, by=("year",))
    checks, keep = interval_rule(s_milk)
    pd.set_option("display.width", 220)
    print("pfoi-1.2.1-dev = 1.2.0-dev forecasts (unchanged) + gate confidence + gate-conditional ranges; "
          "development forecast years 2020-2023 (ranges need earlier flagged errors), trusted milk periods.")
    for title, t in (("milk by confidence", s_milk), ("milk by grain and confidence", s_grain),
                     ("milk by forecast year", s_year), ("herd stocks (reported, not ruled on)", s_herd)):
        print(f"\n=== {title}: coverage and mean relative width, gate-conditional vs pooled ===")
        print(t.round(3).to_string(index=False))
    print("\n=== pre-registered 1.2.1-dev rule (90 % range) ===")
    print(checks.round(3).to_string(index=False))
    print(f"Verdict: {'KEEP pfoi-1.2.1-dev ranges and flag' if keep else 'DROP (record as tested; code kept, off)'}")
    return 0


def _cmd_thi_backtest(args: argparse.Namespace) -> int:
    """Experimental THI forecasts (v1, v2) vs persistence and climatology, aggregates only."""
    from .freeze import DATA_END
    from .thi_backtest import run_thi_backtest, summarise, weekly_origins

    if args.block == "development":
        start, end = date(2017, 1, 1), TEST_START
    else:
        start, end = TEST_START, DATA_END
        print("TEST BLOCK: run once, after the THI model options are fixed on development.")
    origins = weekly_origins(start, end, args.step)
    daily = SqlHerdSource.from_env().driver_daily(DATA_START, DATA_END)
    rows, pers = run_thi_backtest(daily, origins, args.weather_lag, args.ahead, score_until=end)
    if rows.empty:
        print("no forecast dates with enough complete weather")
        return 1
    table = summarise(rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{args.block}_w{args.weather_lag}"
    table.to_csv(out / f"thi_backtest_summary_{tag}.csv", index=False)
    pd.set_option("display.width", 220)
    fmt = lambda v: f"{v:.3f}"  # noqa: E731
    print(f"\n=== THI forecast accuracy, {args.block} block, weather lag {args.weather_lag} days, "
          f"{rows['origin'].nunique()} forecast dates ===")
    print(table[["lead_days", "model", "n", "mae", "rmse", "bias", "skill_vs_clim",
                 "band_cover_10_90", "band_scale_for_80"]].to_string(index=False, float_format=fmt))
    for k in ("p75", "p90"):
        print(f"\n=== hot days above the herd {k} knot (probability >= 0.5 counts as 'predicted hot') ===")
        print(table[["lead_days", "model", f"hot_share_{k}", f"hit_rate_{k}", f"false_alarm_{k}",
                     f"brier_{k}"]].to_string(index=False, float_format=fmt))
    if len(pers):
        print("\n=== v2 learned persistence: share of a one-day anomaly left after N days "
              "(median and 10-90% range over forecast dates) ===")
        q = pers.drop(columns="origin").quantile([0.1, 0.5, 0.9]).T
        q.columns = ["p10", "median", "p90"]
        print(q.to_string(float_format=fmt))
    print(f"\nWrote {out / f'thi_backtest_summary_{tag}.csv'} (aggregates only).")
    return 0


def _cmd_repro_timing(args: argparse.Namespace) -> int:
    """M7: reproductive timing from the record (censored, competing exits) vs the engine."""
    from .freeze import DATA_END
    from .repro_timing import compare_engine, repro_table

    cfg = _engine_cfg(args)
    source = _source(args)
    asof = date.fromisoformat(args.asof) if args.asof else DATA_END
    steps = source.repro_steps(asof)
    out = Path(args.out) / "repro"
    out.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    print(f"Reproductive timing, lactations that started before {asof} (herd-level counts only).")
    print("Open or pregnant cows at that date are censored, not failures; leaving the herd is "
          "its own outcome; 'first_ai' is the first RECORDED service.")
    for by in (("period",), ("period", "parity_group")):
        t = repro_table(steps, by)
        name = "_".join(by)
        t.to_csv(out / f"repro_timing_by_{name}.csv", index=False)
        print(f"\n=== by {', '.join(by)} ===")
        print(t.round(3).to_string(index=False))
    origin = month_start(asof)
    inputs = load_origin_inputs(source, origin, cfg)
    rates = estimate_rates(inputs.rate_inputs, cfg)
    period = "2015-2019" if origin < date(2020, 1, 1) else "2020-2022" if origin < date(2023, 1, 1) else "2023-2026"
    rec = steps[steps["period"] == period]
    rows = [compare_engine(rec, rates, p) for p in ("1", "2", "3+")]
    cmp_ = pd.concat([r for r in rows if len(r)], ignore_index=True) if any(len(r) for r in rows) else pd.DataFrame()
    cmp_.to_csv(out / f"repro_engine_vs_record_{origin:%Y%m}.csv", index=False)
    print(f"\n=== share conceived by day in milk: record (calvings {period}) vs engine rates at {origin} ===")
    print("(engine: " + ("conception shaped by days in milk" if cfg.conception_dim_shape
                         else "one conception rate per DIM band") + ")")
    print(cmp_.round(3).to_string(index=False) if len(cmp_) else "(no data)")
    print(f"\nFiles in {out}/. Associations in this herd only.")
    return 0


def _cmd_generation_outcomes(args: argparse.Namespace) -> int:
    """M8: separate outcomes by generation within calving period (descriptive)."""
    from .freeze import DATA_END
    from .generation_outcomes import NOTE, generation_outcomes

    source = _source(args)
    asof = date.fromisoformat(args.asof) if args.asof else DATA_END
    t = generation_outcomes(source.generation_yield(asof), source.generation_days(asof),
                            source.repro_steps(asof), source.generation_alarms(asof))
    out = Path(args.out) / "generation"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "generation_outcomes.csv", index=False)
    pd.set_option("display.width", 220)
    print(f"Outcomes by generation before {asof} (herd-level aggregates). {NOTE}")
    wide = t.pivot_table(index=["outcome", "period"], columns="generation_group", values="value")
    n = t.pivot_table(index=["outcome", "period"], columns="generation_group", values="n")
    print("\n=== value ===")
    print(wide.round(3).to_string())
    print("\n=== n (cow-days or lactations) ===")
    print(n.round(0).to_string())
    print(f"\nFiles in {out}/.")
    return 0


def _cmd_evidence_ladder(args: argparse.Namespace) -> int:
    """Evidence ladder (F7): each rung on exactly the periods all rungs forecast."""
    from .evidence import Rung, ladder, parse_rung, status_of_tag
    from .freeze import DATA_END

    out = Path(args.out)
    frames, rungs = {}, []
    specs = [parse_rung(r) for r in args.rung]
    base_tag = specs[0][1]
    for label, tag, model in [("persistence", base_tag, "persistence")] + specs:
        paths = [out / f"milk_backtest_errors_{g}_{tag}.csv" for g in ("weekly", "monthly")]
        parts = [pd.read_csv(p) for p in paths if p.exists()]
        if not parts:
            print(f"no milk backtest files for tag {tag!r} in {out}")
            return 1
        e = pd.concat(parts, ignore_index=True)
        e = e[(e["model"] == model) & (e["grain"] == args.grain)]
        if not len(e):
            print(f"tag {tag!r} has no {args.grain} rows for model {model!r}")
            return 1
        frames[label] = e
        rungs.append(Rung(label, model, status_of_tag(tag)))
    thi = SqlHerdSource.from_env().driver_daily(DATA_START, DATA_END)[["date", "thi_mean"]] \
        if args.heat_band == "on" else None
    t = ladder(frames, rungs, thi_daily=thi)
    dest = out / "evidence"
    dest.mkdir(parents=True, exist_ok=True)
    name = f"evidence_ladder_{args.grain}" + (f"_{args.name}" if args.name else "")
    t.to_csv(dest / f"{name}.csv", index=False)
    from .evidence import plot_ladder
    for band in sorted(set(t["band"])):
        plot_ladder(t, dest / f"{name}_{band}.png", band=band)
    pd.set_option("display.width", 220)
    print(f"Evidence ladder, {args.grain}: every rung on the same periods; ratio < 1 beats persistence.")
    print("Oracle rungs use actual future weather: analysis only, never a result.")
    for band, g in t.groupby("band", sort=False):
        print(f"\n=== band: {band} ===")
        print(g.drop(columns="band").round(3).to_string(index=False))
    print(f"\nFiles: {dest}/{name}.csv and one chart per band ({name}_<band>.png)")
    return 0


def _cmd_break_reset(args: argparse.Namespace) -> int:
    """PP1 1a: the correction layer with and without the break reset, on saved errors."""
    from .break_eval import compare, verdict, with_reset
    from .breaks import detect_breaks
    from .freeze import DATA_END, V11_ADAPTIVE

    out = Path(args.out)
    suffix = "_posthoc" if args.block == "posthoc" else ""

    def load(kind: str, tag: str, sfx: str) -> pd.DataFrame | None:
        frames = [pd.read_csv(p) for g in ("monthly", "weekly")
                  for p in [out / f"{kind}_backtest_errors_{g}_{tag}{sfx}.csv"] if p.exists()]
        return pd.concat(frames, ignore_index=True) if frames else None

    herd = load("herd", args.herd_tag, "")
    milk = load("milk", args.milk_tag, "")
    if args.block == "posthoc":  # development errors are the past of the 2024-26 forecast dates
        herd = pd.concat([x for x in (herd, load("herd", args.herd_tag, suffix)) if x is not None], ignore_index=True)
        milk = pd.concat([x for x in (milk, load("milk", args.milk_tag, suffix)) if x is not None], ignore_index=True)
    if herd is None and milk is None:
        print(f"no error files for {args.herd_tag!r} / {args.milk_tag!r} in {out}")
        return 1
    src = SqlHerdSource.from_env()
    end = DATA_END if args.block == "posthoc" else TEST_START
    daily = src.panel_daily(DATA_START, end)[["date", "n_herd"]].merge(
        src.target_daily(DATA_START, end)[["date", "is_scoreable", "target_litres"]], on="date", how="left")
    breaks = detect_breaks(daily)
    rows = with_reset(herd, milk, breaks, V11_ADAPTIVE)
    t = compare(rows, breaks, score_from=TEST_START if args.block == "posthoc" else None)
    _save(t, out, f"break_reset_comparison_{args.milk_tag}{suffix}.csv")
    pd.set_option("display.width", 220)
    print(f"Breaks detected (herd size +/-10 % over 90 days, or milk back after 28+ days): "
          f"{len(breaks)}; years: " + ", ".join(sorted({str(b.year) for b in breaks})))
    label = "POST-TEST DEVELOPMENT (2024-26 already inspected)" if args.block == "posthoc" else "development"
    print(f"\n=== correction layer with and without the break reset ({label}) ===")
    print(t.round(3).to_string(index=False))
    if args.block == "development":
        keep, reasons = verdict(t)
        print("\nKeep rule: " + ("PASSED" if keep else "FAILED") + ("" if keep else " - " + "; ".join(reasons)))
        for kind, tag, model_new in (("herd", args.herd_tag, "herd_engine_corrected_br"),
                                     ("milk", args.milk_tag, "milk_baseline_adaptive_br")):
            src_e = herd if kind == "herd" else milk
            if src_e is None:
                continue
            bench = src_e[src_e["model"].isin(BENCHMARK_MODELS + (("herd_engine",) if kind == "herd" else ("milk_baseline",)))]
            both = pd.concat([rows[rows["model"] == model_new], bench], ignore_index=True)
            file_grain = both["grain"].where(both["grain"] == "monthly", "weekly")
            for g, part in both.groupby(file_grain):
                part.to_csv(out / f"{kind}_backtest_errors_{g}_{tag}_br.csv", index=False)
        print(f"Wrote candidates {args.herd_tag}_br and {args.milk_tag}_br (models *_br).")
    return 0


def _cmd_scenarios(args: argparse.Namespace) -> int:
    """Layer 3: episode library, responses "like last time", optional outlook scenarios."""
    from .freeze import DATA_END
    from .scenarios import (
        apply_scenario, detect_episodes, episode_response, narrative, summarize_response,
    )

    out = Path(args.out)
    frames = []
    for suffix in ("", "_test", "_posthoc"):  # the library describes the past, not a claim
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
    summary = summarize_response(resp).assign(series="herd_milk")
    if args.herd_tag:  # 1c: herd numbers after earlier episodes (incl. the 2024 removal)
        hf = [pd.read_csv(p) for suffix in ("", "_test", "_posthoc") for g in ("monthly", "weekly")
              for p in [out / f"herd_backtest_errors_{g}_{args.herd_tag}{suffix}.csv"] if p.exists()]
        if hf:
            he = pd.concat(hf, ignore_index=True)
            for series in ("milking", "n_herd"):
                hs = summarize_response(episode_response(he, episodes, "herd_engine", series=series))
                summary = pd.concat([summary, hs.assign(series=series)], ignore_index=True)
    summary.to_csv(out / f"scenario_response_{args.tag}.csv", index=False)
    print(f"\n=== response (excess relative error after onset), by series ===")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
    print()
    for series, label in (("herd_milk", "herd milk"), ("milking", "milking cows"), ("n_herd", "total herd")):
        ss = summary[summary["series"] == series]
        for kind in ss["kind"].unique():
            for grain, h in (("weekly", 4), ("monthly", 3)):
                if ((ss["kind"] == kind) & (ss["grain"] == grain)).any():
                    print("-", narrative(ss, kind, grain, h, series_label=label))
    if args.outlook:
        path = Path(args.outlook)
        base = pd.read_csv(path)
        base = base[base["series"] == "herd_milk"]
        milk_summary = summary[summary["series"] == "herd_milk"].drop(columns="series")
        res = pd.concat([apply_scenario(base, milk_summary, k) for k in milk_summary["kind"].unique()],
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
        hindsight = set()
        for path in sorted(out.glob("*_backtest_errors_*.csv")):
            m = pattern.match(path.name)
            if not m or m.group(2).endswith(NOT_DEVELOPMENT):
                continue
            if not args.include_hindsight and HONEST_TAG not in m.group(2):
                hindsight.add(m.group(2))
                continue
            frames.setdefault(m.group(2), []).append(pd.read_csv(path))
        if hindsight:
            print(f"{fam}: {len(hindsight)} tags left out (pregnancy states with hindsight, "
                  f"no '{HONEST_TAG}'); --include-hindsight adds them")
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


def _load_backtests(out: Path, herd_tag: str = "w12", milk_tag: str = "herd_fitted_p1_g0_ka_w12",
                    later: tuple[str, str] = ("test", "_test")) -> dict[tuple[str, str], pd.DataFrame | None]:
    """Backtest error files of one configuration (default: the frozen one), by (kind, block).
    ``later`` = the 2024-26 block: the frozen test, or a new version's post-hoc replay."""
    names = {"milk": f"milk_backtest_errors_{{g}}_{milk_tag}{{b}}.csv",
             "herd": f"herd_backtest_errors_{{g}}_{herd_tag}{{b}}.csv"}
    found = {}
    for kind, pattern in names.items():
        for block, suffix in (("development", ""), later):
            frames = []
            for g in ("monthly", "weekly"):
                path = out / pattern.format(g=g, b=suffix)
                if path.exists():
                    frames.append(pd.read_csv(path))
                else:
                    print(f"NOTE: {path.name} not found", file=sys.stderr)
            found[(kind, block)] = pd.concat(frames, ignore_index=True) if frames else None
    return found


def _path_name(wtag: str, suffix: str = "") -> str:
    return f"path_backtest_errors_{wtag}{suffix}.csv"


def _load_path_backtests(out: Path, wtag: str) -> dict[tuple[str, str], pd.DataFrame | None]:
    found = {}
    for block, suffix in (("development", ""), ("posthoc", "_posthoc")):
        path = out / _path_name(wtag, suffix)
        if path.exists():
            found[("path", block)] = pd.read_csv(path)
        else:
            print(f"NOTE: {path.name} not found (run backtest-path): no daily/weekly ranges "
                  f"from the {block} block", file=sys.stderr)
    return found


def _cmd_backtest_path(args: argparse.Namespace) -> int:
    """pfoi-1.1.1 path backtest; prints aggregates only."""
    from .backtest_herd import development_origins as dev_origins
    from .freeze import DATA_END, V11_ADAPTIVE, V11_CORRECTED_HERD, V11_MILK, final_test_origins
    from .path_backtest import run_path_backtest, summarise_path

    cfg, mcfg = _engine_cfg(args), V11_MILK
    out = Path(args.out)
    bt_dir = Path(args.backtests) if args.backtests else out
    wtag = _wtag(args)
    later = ("posthoc", "_posthoc")
    backtests = _load_backtests(bt_dir, wtag, f"{mcfg.tag()}_{wtag}", later=later)
    blocks = ("development",) if args.block == "development" else ("development", "posthoc")
    present = [e for (_, b), e in backtests.items() if e is not None and b in blocks]
    if not present:
        raise SystemExit("no pfoi-1.1 backtest errors found: the correction layer needs them")
    errors = pd.concat(present, ignore_index=True)
    if args.block == "development":
        origins, until, prior, suffix = dev_origins("monthly", every=args.every), TEST_START, None, ""
    else:
        prior_path = out / _path_name(wtag)
        if not prior_path.exists():
            raise SystemExit(f"{prior_path.name} not found: run the development block first")
        origins, until, suffix = final_test_origins("monthly", every=args.every), DATA_END, "_posthoc"
        prior = pd.read_csv(prior_path)
        print("POST-HOC: 2024-26 scores of pfoi-1.1.1; report them as post-hoc.", file=sys.stderr)

    def progress(i: int, n: int, origin: date) -> None:
        if i % 6 == 0:
            print(f"  origin {i + 1}/{n} ({origin})", file=sys.stderr)

    e = run_path_backtest(_source(args), origins, errors, cfg, mcfg, V11_ADAPTIVE, V11_CORRECTED_HERD,
                          score_until=until, block=args.block, prior=prior, progress=progress)
    _save(e, out, _path_name(wtag, suffix))
    s = summarise_path(e)
    if not len(s):
        print("no scored periods")
        return 0
    key = s[s["series"].isin(["milk_litres", "milking", "total_herd", "calvings"])]
    pd.set_option("display.width", 200)
    for sid, g in key.groupby("series"):
        print(f"\n{sid} ({args.block}): n, MAE, MAPE %, bias, 90 % coverage % by grain x horizon x model")
        print(g.drop(columns="series").round(3).to_string(index=False))
    print(f"\n{len(e)} rows ({len(origins)} forecast dates) in {out / _path_name(wtag, suffix)} (gitignored)")
    return 0


def _cmd_build_outlook(args: argparse.Namespace) -> int:
    """One or more forecast dates (``--origin`` takes several); returns the worst exit code."""
    import copy

    origins = args.origin if isinstance(args.origin, list) else [args.origin]
    codes = []
    for o in origins:
        if len(origins) > 1:
            print(f"\n=== forecast date {o} ===")
        one = copy.copy(args)
        one.origin = o
        codes.append(_build_outlook_one(one))
    if len(origins) > 1:
        print(f"\n{sum(c == 0 for c in codes)}/{len(codes)} forecast dates built"
              + ("; the others had no clean milk months to anchor k" if any(codes) else ""))
    return max(codes)


def _cmd_freeze_info(args: argparse.Namespace) -> int:
    """Frozen versions, their configuration hashes and what each one publishes."""
    from .freeze import (
        V11_FROZEN_ON, V11_VERSION, V111_FROZEN_ON, V111_RECONCILIATION, V111_VERSION, config_hash,
        v11_config_hash, v111_config_hash,
    )
    from . import MODEL_VERSION

    rows = [(MODEL_VERSION, "2026-10-19", config_hash(), "default of every command; run-once final test"),
            (V11_VERSION, V11_FROZEN_ON.isoformat(), v11_config_hash(),
             "--preset pfoi-1.1: recency-weighted rates + correction layer; 14 days, 13 weeks, 12 months"),
            (V111_VERSION, V111_FROZEN_ON.isoformat(), v111_config_hash(),
             f"--preset pfoi-1.1.1: pfoi-1.1.0 for 12 months at every grain ({V111_RECONCILIATION})")]
    for version, frozen, h, what in rows:
        print(f"{version:12s} frozen {frozen}  config {h}  {what}")
    return 0


PP1_DEV_VERSION = "pfoi-1.2.0-dev"


def _pp1_dev(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "k", None) or getattr(args, "intervals", "empirical") == "aci"
                or getattr(args, "staleness", None) or getattr(args, "anchor_gate", "off") == "on"
                or getattr(args, "fast_half_life", "none") not in (None, "none")
                or getattr(args, "exit_model", "state") != "state"
                or getattr(args, "break_reset", "off") == "on"
                or getattr(args, "persistence_blend", "off") == "on")


def _load_evidence(folder: Path) -> dict:
    """Newest outage-simulation, evidence-ladder and driver-registry tables in ``folder``
    (aggregates written by outage_sim, evidence-ladder and drivers); missing ones are left out."""
    from .evidence import latest

    out = {}
    p = latest((folder / "outage_sim").glob("outage_outage_cost_*.csv"))
    if p:
        out["outage"] = pd.read_csv(p)
    # development ladders only (files named evidence_ladder_<grain>.csv); named ones such as
    # _posthoc are comparisons for the report, not page evidence
    ladders = [pd.read_csv(x) for x in sorted((folder / "evidence").glob("evidence_ladder_*.csv"))
               if x.stem.count("_") == 2]
    if ladders:
        out["ladder"] = pd.concat(ladders, ignore_index=True)
    p = latest(folder.glob("scenario_response_*.csv"))
    if p:
        out["scenarios"] = pd.read_csv(p)
    p = latest(folder.glob("drivers_registry_*.csv"))
    if p:
        reg = pd.read_csv(p)
        out["registry"] = reg.rename(columns={reg.columns[0]: "feature"})
    print("evidence tables: " + (", ".join(sorted(out)) or "none found") + f" (in {folder})")
    return out


def _pp1_interval_opts(args: argparse.Namespace, source, run) -> dict:
    """Interval options of a PP1 development build (docs/pp1_plan.md M4)."""
    from .episodes import daily_quality
    from .intervals import StalenessScale
    from .record_status import staleness_days

    origin = run.origin
    target = run.hist.target_before(origin)
    quality = None
    if args.intervals == "aci":
        quality = daily_quality(source.target_daily(DATA_START, origin),
                                source.panel_daily(DATA_START, origin))
    return {"aci": args.intervals == "aci", "quality": quality,
            "stale_days": staleness_days(target, origin),
            "scale": StalenessScale.from_csv(args.staleness)}


def _build_outlook_one(args: argparse.Namespace) -> int:
    import json

    from sqlalchemy import create_engine

    from .config import DatabaseSettings
    from .adaptive import adaptive_corrected
    from .freeze import (
        DATA_END, V11_ADAPTIVE, V11_CORRECTED_HERD, V11_MILK, V11_VERSION, V111_VERSION, config_hash,
        v11_config_hash, v111_config_hash,
    )
    from .outlook import (
        build_outlook, build_output_layer, run_frozen, run_model, write_outlook, write_run_document,
    )
    from .page_run import build_page_run

    origin = date.fromisoformat(args.origin)
    out = Path(args.out)
    bt_dir = Path(args.backtests) if args.backtests else out  # where the backtest errors are
    dev = _pp1_dev(args)
    if getattr(args, "persistence_blend", "off") == "on" and (
            args.preset not in ("pfoi-1.1", "candidate")
            or getattr(args, "break_reset", "off") == "on"):
        print("--persistence-blend on requires --preset pfoi-1.1 and --break-reset off")
        return 2
    if dev and not args.preset:
        print("--k, --intervals aci and --staleness need --preset pfoi-1.1 or pfoi-1.1.1")
        return 2
    if args.preset:  # pfoi-1.1.0 (frozen 2026-10-20): engine, then the correction layer
        cfg, mcfg = _engine_cfg(args), V11_MILK
        if args.k or args.anchor_gate == "on":
            from dataclasses import replace as _replace
            mcfg = _replace(V11_MILK, k_mode=args.k or V11_MILK.k_mode,
                            anchor_gate=args.anchor_gate == "on")
        source = _source(args)
        backtests = _load_backtests(bt_dir, _wtag(args), f"{mcfg.tag()}_{_wtag(args)}",
                                    later=("posthoc", "_posthoc"))
        v111 = args.preset == "pfoi-1.1.1"
        if v111:  # the reconciled path's own errors: daily and weekly ranges and scores
            backtests.update(_load_path_backtests(bt_dir, _wtag(args)))
        present = [e for e in backtests.values() if e is not None]
        errors = pd.concat(present, ignore_index=True) if present else None
        breaks = None
        if getattr(args, "break_reset", "off") == "on":  # PP1 1a: breaks visible before the date
            from .breaks import detect_breaks
            src0 = _source(args)
            daily = src0.panel_daily(DATA_START, origin)[["date", "n_herd"]].merge(
                src0.target_daily(DATA_START, origin)[["date", "is_scoreable", "target_litres"]],
                on="date", how="left")
            breaks = detect_breaks(daily)
            print(f"break reset: {len(breaks)} breaks before {origin}; latest "
                  f"{max(breaks) if breaks else 'none'}")
        if errors is not None:  # the adaptive milk model's own errors, for its intervals
            errors = pd.concat([errors, adaptive_corrected(errors, "milk_baseline", cfg=V11_ADAPTIVE,
                                                           breaks=breaks)], ignore_index=True)
        try:
            run = run_model(source, origin, cfg, mcfg)
        except ValueError as err:  # e.g. no clean milk months to anchor k after the outage
            print(f"{origin}: no outlook ({err}). Pick a later forecast date with clean milk records"
                  " (or use --k anchor_first).")
            return 2
        if run.milk_withheld:
            print(f"{origin}: milk forecast withheld ({run.milk_withheld}); herd forecast kept.")
        run.layer = build_output_layer(errors, origin, V11_ADAPTIVE, V11_CORRECTED_HERD, breaks=breaks)
        print(f"correction layer: {len(run.layer.herd_bias)} herd bias terms, "
              f"{len(run.layer.milk_level)} milk levels (from errors ended by {origin})")
        if v111:  # same model; 12 months at every grain, days reconciled to the months
            run.reconciled, run.version = True, V111_VERSION
        chash = v111_config_hash() if v111 else v11_config_hash()
        if dev:  # PP1 development options: never published under a frozen version name
            run.version, chash = PP1_DEV_VERSION, "dev"
            run.interval_opts = _pp1_interval_opts(args, source, run)
            print(f"{PP1_DEV_VERSION}: development build (not frozen); options: k={mcfg.k_mode}, "
                  f"intervals={args.intervals}, staleness scale: {run.interval_opts['scale'].source}")
        if getattr(args, "persistence_blend", "off") == "on":
            from .live_persistence import attach_live_persistence
            errors = attach_live_persistence(run, errors)
            print("Persistence-only blend enabled; audit in page document; adoption not confirmed.")
            audit = run.layer.persistence.audit()
            summary = []
            for grain, rows in audit["grains"].items():
                w = [r["weight"] for r in rows]
                n = [r["n_finished"] for r in rows]
                summary.append(dict(grain=grain, horizons=len(rows), weight_min=min(w),
                                    weight_mean=sum(w) / len(w), weight_max=max(w),
                                    finished_min=min(n), finished_max=max(n),
                                    persistence=rows[0]["persistence"],
                                    reference_age_days=audit["reference_age_days"]))
            print(pd.DataFrame(summary).round(3).to_string(index=False))
        dest = out / "outlook" / run.version
    else:
        source = SqlHerdSource.from_env()
        backtests = _load_backtests(bt_dir)
        present = [e for e in backtests.values() if e is not None]
        errors = pd.concat(present, ignore_index=True) if present else None
        try:
            run = run_frozen(source, origin)
        except ValueError as err:
            print(f"{origin}: no outlook ({err}). Pick a later forecast date with clean milk records.")
            return 2
        dest = out / "outlook"
        chash = config_hash()
    core_version = source.core_version()
    outlook, attribution, history = build_outlook(source, origin, errors, core_version, run=run)
    evidence = _load_evidence(Path(args.evidence) if args.evidence else bt_dir) if dev else None
    document = build_page_run(source, run, attribution, backtests, core_version, realised_until=DATA_END,
                              evidence=evidence, interval_errors=errors)
    for name, frame in (("outlook", outlook), ("attribution", attribution), ("history", history)):
        _save(frame, dest, f"{name}_{origin:%Y%m}.csv")
    (dest / f"run_{origin:%Y%m}.json").write_text(json.dumps(document, indent=1))
    m = outlook[(outlook["grain"] == "monthly") & (outlook["series"] == "herd_milk")]
    print(f"Outlook {origin}  model {outlook['model_version'].iloc[0]} (config {chash}), "
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


def _cmd_compare_runs(args: argparse.Namespace) -> int:
    """Score and plot both models at each forecast date; prints aggregates only."""
    import json

    from . import MODEL_VERSION
    from .compare_runs import plot, score

    out = Path(args.out)
    dest = out / "compare"
    dest.mkdir(parents=True, exist_ok=True)
    # pfoi-1.0.0 documents sit in outlook/, later versions in outlook/<version>/
    folder = lambda v: out / "outlook" if v == MODEL_VERSION else out / "outlook" / v  # noqa: E731
    default = args.base == MODEL_VERSION and args.candidate == "pfoi-1.1.0" and args.grain == "month"
    if getattr(args, "also", None):
        return _compare_many(args, out, dest, folder)
    tables = []
    for o in args.origins:
        origin = date.fromisoformat(o)
        paths = (folder(args.base) / f"run_{origin:%Y%m}.json",
                 folder(args.candidate) / f"run_{origin:%Y%m}.json")
        missing = [p for p in paths if not p.exists()]
        if missing:
            print(f"{origin}: missing {', '.join(str(p) for p in missing)} (run build-outlook first)")
            continue
        frozen, cand = (json.loads(p.read_text()) for p in paths)
        name = (f"compare_{origin:%Y%m}.png" if default
                else f"compare_{args.grain}_{origin:%Y%m}_{args.base}_vs_{args.candidate}.png")
        plot(frozen, cand, origin, dest / name, grain=args.grain,
             labels=(frozen.get("model_version", "frozen"), cand.get("model_version", "candidate")))
        tables.append(score(frozen, cand, grain=args.grain).assign(origin=f"{origin:%Y-%m}"))
    if not tables:
        return 1
    t = pd.concat(tables, ignore_index=True).set_index(["origin", "series"])
    pd.set_option("display.width", 200)
    print(f"\nRecorded {args.grain}s after each forecast date that both versions forecast "
          f"({args.base} vs {args.candidate}; n_months = number of periods); "
          "MAE and bias: forecast - recorded; change_pct < 0 = candidate better;\n"
          "cover90 blank = that run has no 5-95 % range (no past errors); layer_candidate = "
          "mean correction-layer amount in the candidate's forecast")
    print(t.round(2).to_string())
    print(f"\nCharts in {dest}/ (gitignored)")
    return 0


def _compare_many(args: argparse.Namespace, out: Path, dest: Path, folder) -> int:
    """compare-runs with extra versions (``--also``): one chart per forecast date, all versions drawn
    together with the recorded outcome; scores on the periods every version forecast."""
    import json

    from .compare_runs import SERIES, plot_versions, score_versions

    versions = [args.base, args.candidate, *args.also]
    series = tuple(args.series) if args.series else ("milk_litres",)
    unknown = [s for s in series if s not in SERIES]
    if unknown:
        print(f"unknown series {unknown}; choose from {list(SERIES)}")
        return 2
    tables = []
    for o in args.origins:
        origin = date.fromisoformat(o)
        paths = [folder(v) / f"run_{origin:%Y%m}.json" for v in versions]
        missing = [p for p in paths if not p.exists()]
        if missing:
            print(f"{origin}: missing {', '.join(str(p) for p in missing)} (run build-outlook / blend-outlook first)")
            continue
        docs = [(json.loads(p.read_text()).get("model_version", v), json.loads(p.read_text()))
                for v, p in zip(versions, paths)]
        name = f"compare_{args.grain}_{origin:%Y%m}_" + "_vs_".join(versions) + ".png"
        plot_versions(docs, origin, dest / name, series=series, grain=args.grain)
        tables.append(score_versions(docs, series=series, grain=args.grain).assign(origin=f"{origin:%Y-%m}"))
    if not tables:
        return 1
    t = pd.concat(tables, ignore_index=True).set_index(["origin", "series", "version"])
    pd.set_option("display.width", 200)
    print(f"\nRecorded {args.grain}s after each forecast date that ALL of {', '.join(versions)} forecast "
          "(n_periods); MAE and bias = forecast - recorded; cover90 blank = no 5-95 % range")
    print(t.round(2).to_string())
    print(f"\nCharts in {dest}/ (gitignored). Nothing was written to the database.")
    return 0


def _cmd_blend_outlook(args: argparse.Namespace) -> int:
    """Derive <version>-blend documents (daily and weekly milk blended with persistence); files only."""
    from .blend_outlook import run

    return run(args.out, args.source, args.origins, tag=args.tag, min_obs=args.min_obs)


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
    p.add_argument("--half-life", default="none",
                   help="recency weighting of the rate window in months (none = pfoi-1.0.0)")
    p.add_argument("--conception-shape", default="off", choices=["on", "off"],
                   help="M7: cow conception rate shaped by days in milk within each band")
    p.add_argument("--fast-half-life", default="none",
                   help="1b: half-life (months) for abortions, losses, exits and conceptions")
    p.add_argument("--exit-model", default="state", choices=["state", "lactation"],
                   help="lactation = milking-cow exits by parity x DIM band x pregnancy")
    p.add_argument("--preset", default=None, choices=["pfoi-1.1", "candidate"],
                   help="pfoi-1.1 (alias candidate) = the pfoi-1.1.0 engine settings (overrides window, "
                        "conception and half-life options)")
    p.set_defaults(func=_cmd_herd_rates)

    def jobs_opt(p: argparse.ArgumentParser) -> None:
        p.add_argument("--jobs", type=int, default=1,
                       help="processes for scoring origins (0 = CPU cores - 1); each opens "
                            "its own read-only database connection")

    def block_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--block", default="development", choices=["development", "test", "posthoc"],
                       help="test = final test block, frozen model, run once; "
                            "posthoc = 2024-26 replay of a new version (not a test)")
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
    p.add_argument("--half-life", default="none",
                   help="recency weighting of the rate window in months (none = pfoi-1.0.0)")
    p.add_argument("--conception-shape", default="off", choices=["on", "off"],
                   help="M7: cow conception rate shaped by days in milk within each band")
    p.add_argument("--fast-half-life", default="none",
                   help="1b: half-life (months) for abortions, losses, exits and conceptions")
    p.add_argument("--exit-model", default="state", choices=["state", "lactation"],
                   help="lactation = milking-cow exits by parity x DIM band x pregnancy")
    p.add_argument("--preset", default=None, choices=["pfoi-1.1", "candidate"],
                   help="pfoi-1.1 (alias candidate) = the pfoi-1.1.0 engine settings (overrides window, "
                        "conception and half-life options)")
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
    p.add_argument("--half-life", default="none",
                   help="recency weighting of the rate window in months (none = pfoi-1.0.0)")
    p.add_argument("--conception-shape", default="off", choices=["on", "off"],
                   help="M7: cow conception rate shaped by days in milk within each band")
    p.add_argument("--fast-half-life", default="none",
                   help="1b: half-life (months) for abortions, losses, exits and conceptions")
    p.add_argument("--exit-model", default="state", choices=["state", "lactation"],
                   help="lactation = milking-cow exits by parity x DIM band x pregnancy")
    p.add_argument("--preset", default=None, choices=["pfoi-1.1", "candidate"],
                   help="pfoi-1.1 (alias candidate) = the pfoi-1.1.0 engine settings (overrides window, "
                        "conception and half-life options)")
    p.add_argument("--out", default="logs/pfoi")
    p.add_argument("--block", default="development", choices=["development", "test", "posthoc"])
    p.set_defaults(func=_cmd_report)

    def milk_opts(p: argparse.ArgumentParser, blocks=("development", "test"),
                  block_default: str = "development") -> None:
        p.add_argument("--curve", default="herd_fitted", choices=list(CURVE_MODES),
                       help="shape before 2020-09 (fitted_everywhere = sensitivity only)")
        p.add_argument("--pregnancy-factor", default="on", choices=["on", "off"])
        p.add_argument("--generation-factor", default="off", choices=["on", "off"])
        p.add_argument("--k", default="anchored", choices=list(K_MODES),
                       help="anchored = last 14 scoreable days; window = 12-month k; "
                            "anchor_first = anchored without needing the 12-month k (M1)")
        p.add_argument("--anchor-gate", default="off", choices=["on", "off"],
                       help="on = anchor only on verified days (M3; identified share >= 0.2, "
                            "<= 20 L per milking cow)")
        p.add_argument("--borrow-k", default="on", choices=["on", "off"],
                       help="off = never use the other record source's 12-month k (shipment vs "
                            "DelPro); level from recent same-source days or the milk forecast is "
                            "withheld (tag suffix s)")
        p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
        p.add_argument("--conception-cut", default="origin", choices=["origin", "known"],
                       help="known = heifer/dry conception rates only from months confirmable at the origin")
        p.add_argument("--cell-table", default="day_cell", choices=["day_cell", "day_cell_known"],
                       help="day_cell_known = pregnancies only once confirmed (no hindsight)")
        p.add_argument("--conception-known", default="lag", choices=["lag", "recorded"],
                       help="recorded = a conception counts once its pregnancy check is recorded")
        p.add_argument("--pregnancy-lag", type=int, default=35,
                       help="days after which conceptions count in the rate window (90 suits 'recorded')")
        p.add_argument("--half-life", default="none",
                       help="recency weighting of the rate window in months (none = pfoi-1.0.0)")
        p.add_argument("--conception-shape", default="off", choices=["on", "off"],
                       help="M7: cow conception rate shaped by days in milk within each band")
        p.add_argument("--fast-half-life", default="none",
                       help="1b: half-life (months) for abortions, losses, exits and conceptions")
        p.add_argument("--exit-model", default="state", choices=["state", "lactation"],
                       help="lactation = milking-cow exits by parity x DIM band x pregnancy")
        p.add_argument("--preset", default=None, choices=["pfoi-1.1", "candidate"],
                       help="pfoi-1.1 (alias candidate) = the pfoi-1.1.0 engine settings (overrides window, "
                            "conception and half-life options)")
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
    milk_opts(p, blocks=("development", "test", "posthoc"))
    p.add_argument("--target", default="record", choices=["record", "delpro"],
                   help="delpro = score and calibrate on DelPro litres only (from 2020-08; tag suffix _tdp)")
    p.set_defaults(func=_cmd_backtest_milk)

    p = sub.add_parser("neural", help="GRU milk model on the two-stage split (train 2015-17, test "
                                      "2018-19; fine-tune 2020-22, test 2023 on)")
    p.add_argument("--seeds", type=int, default=5, help="ensemble size")
    p.add_argument("--epochs", type=int, default=200, help="maximum epochs per seed")
    p.add_argument("--patience", type=int, default=20, help="early stopping on validation")
    p.add_argument("--rebuild-engine", action="store_true", help="recompute the cached engine paths")
    jobs_opt(p)
    milk_opts(p, blocks=("development",))
    p.set_defaults(func=_cmd_neural, out="logs/pfoi_neural", preset="pfoi-1.1", k="anchor_first")

    p = sub.add_parser("neural-outlook", help="page documents for the neural model and persistence "
                                              "(copies of built ones, milk replaced) for compare-runs")
    p.add_argument("--source", default="pfoi-1.2.0-dev", help="built version to copy (its folder in outlook/)")
    p.add_argument("--neural-dir", default="logs/pfoi_neural", help="where the neural command wrote its files")
    p.add_argument("--origins", nargs="*", default=None, help="forecast dates (default: every built one)")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_neural_outlook)

    p = sub.add_parser("hit-rate", help="share of milk forecasts within +-5 %% / +-10 %% of the record, "
                                        "trusted periods vs unverified (target 85 %% within 10 %%)")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3",
                   help="milk backtest tag (default: the pfoi-1.2.0-dev development errors)")
    p.add_argument("--block", default="development", choices=["development", "posthoc", "both"])
    p.add_argument("--files", nargs="*", default=None, help="explicit error files instead of --tag")
    p.add_argument("--block-name", default=None,
                   help="one block name for every --files file (e.g. development), so models from "
                        "different files are compared and --keep-rule works across them")
    p.add_argument("--models", nargs="*", default=None,
                   help="models to score (default: all in the files, e.g. milk_baseline_adaptive persistence)")
    p.add_argument("--quality", default="on", choices=["on", "off"],
                   help="on = split trusted vs unverified periods (reads daily herd-level aggregates)")
    p.add_argument("--keep-rule", nargs=2, metavar=("OLD", "NEW"), default=None,
                   help="apply the fixed 1.2.1-dev keep rule to model NEW against OLD")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_hit_rate)

    p = sub.add_parser("milk-error-split", help="milk error = cow-count part + yield-per-cow part, "
                                                "with hit-rate ceilings if either part were exact")
    p.add_argument("--milk-tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3")
    p.add_argument("--herd-tag", default="w24_ck_kn_rk_lag90_hl6",
                   help="herd backtest tag with the same engine settings as the milk run")
    p.add_argument("--milk-model", default="milk_baseline_adaptive")
    p.add_argument("--block", default="development", choices=["development", "posthoc", "both"])
    p.add_argument("--quality", default="on", choices=["on", "off"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_milk_error_split)

    p = sub.add_parser("backtest-ml", help="direct ML forecaster (LightGBM + ridge, pooled horizons), "
                                           "rolling origin, development or post-hoc 2024-26")
    p.add_argument("--grain", default="both", choices=["monthly", "weekly", "both"],
                   help="origin grain; weekly origins also score daily horizons")
    p.add_argument("--block", default="development", choices=["development", "posthoc"])
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--series", nargs="+", default=list(DEFAULT_ML_SERIES))
    p.add_argument("--refit-months", type=int, default=3)
    p.add_argument("--half-life-days", type=float, default=730.0)
    p.add_argument("--pipeline", default="on", choices=["on", "off"],
                   help="off = no composition / pregnancy-pipeline features (ablation, tag _nopipe)")
    p.add_argument("--benchmarks", default="on", choices=["on", "off"])
    p.add_argument("--cell-table", default="day_cell_known", choices=["day_cell", "day_cell_known"])
    p.add_argument("--conception-known", default="recorded", choices=["lag", "recorded"])
    p.add_argument("--pregnancy-lag", type=int, default=90)
    p.add_argument("--out", default="logs/pfoi/ml")
    p.set_defaults(func=_cmd_backtest_ml)

    p = sub.add_parser("ml-report", help="re-print backtest-ml tables from its saved error files")
    p.add_argument("--tag", default="ml_r3_hl730")
    p.add_argument("--series", nargs="*", default=None, help="e.g. herd_milk milking calvings")
    p.add_argument("--metrics", nargs="+", default=["accuracy", "within_10", "skill_vs_persistence", "bias_pct"],
                   choices=["n", "accuracy", "within_10", "skill_vs_persistence", "bias_pct"])
    p.add_argument("--out", default="logs/pfoi/ml")
    p.set_defaults(func=_cmd_ml_report)

    p = sub.add_parser("ml-charts", help="PNG charts: pfoi-1.4.0-dev (ML) vs pfoi-1.2.0-dev vs persistence")
    p.add_argument("--ml-tag", default="ml_r3_hl730")
    p.add_argument("--milk-tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3",
                   help="pfoi-1.2.0-dev milk backtest tag")
    p.add_argument("--herd-tag", default="w24_ck_kn_rk_lag90_hl6", help="pfoi-1.2.0-dev herd backtest tag")
    p.add_argument("--milk-model", default="milk_baseline_adaptive")
    p.add_argument("--herd-model", default="herd_engine")
    p.add_argument("--ml-dir", default="logs/pfoi/ml")
    p.add_argument("--pfoi-dir", default="logs/pfoi")
    p.add_argument("--out", default="logs/pfoi/compare/pfoi_1_4")
    p.set_defaults(func=_cmd_ml_charts)

    p = sub.add_parser("check-snapshots", help="batched vs per-origin snapshot queries (counts only)")
    p.add_argument("--grain", default="weekly", choices=["monthly", "weekly"])
    p.add_argument("--every", type=int, default=10, help="check every n-th origin")
    p.set_defaults(func=_cmd_check_snapshots)

    p = sub.add_parser("milk-report", help="H1 table from a finished milk backtest")
    milk_opts(p, blocks=("development", "test", "posthoc"))
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

    p = sub.add_parser("adapt-trend", help="1.2.1-dev: damped-trend adaptive milk correction, "
                                           "settings chosen year by year on earlier years only")
    p.add_argument("--tag", default=TREND_RAW_TAG, help="raw development milk backtest tag")
    p.add_argument("--phi", nargs="*", type=float, default=[0.8, 0.9, 0.95],
                   help="slope damping per 30 days, each in (0, 1)")
    p.add_argument("--q-trend", nargs="*", type=float, default=[0.01, 0.05],
                   help="slope variance added per 30 days, as a share of the error variance")
    p.add_argument("--metric", default="miss10", choices=["miss10", "wape"],
                   help="inner score: share outside +-10 %% (default) or WAPE")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_adapt_trend)

    p = sub.add_parser("blend", help="Layer 2: blend an adaptive milk backtest with persistence "
                                     "(daily and weekly rows, weights from finished past errors)")
    p.add_argument("--tag", required=True, help="development tag of the milk backtest to blend")
    p.add_argument("--base", default="milk_baseline_adaptive", help="model to blend")
    p.add_argument("--min-obs", type=int, default=8, help="finished forecasts needed before blending")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_blend)

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
    p.add_argument("--groups", nargs="*",
                   default=["weather", "health", "sensor", "quality", "season", "recent"],
                   choices=["weather", "health", "sensor", "quality", "season", "recent"])
    p.add_argument("--weather-lag", type=int, default=6,
                   help="last weather day used = forecast date minus this (ERA5 is ~5 days late)")
    p.add_argument("--thi-knot", type=float, default=75.0, choices=[75.0, 90.0],
                   help="herd-relative heat knot: percentile of past daily max THI")
    p.add_argument("--oracle", action="store_true",
                   help="ANALYSIS ONLY: add the actual THI of each target period")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_drivers)

    p = sub.add_parser("gate-audit", help="G1: are 1.2.0-dev's later misses recognisable at the forecast "
                                          "date? forward-chained gates, aggregates only")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3",
                   help="development milk backtest tag holding the base model (default: pfoi-1.2.0-dev)")
    p.add_argument("--alt-tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6",
                   help="extra tag for alternatives (default: the raw structural milk_baseline)")
    p.add_argument("--base", default="milk_baseline_adaptive")
    p.add_argument("--alts", nargs="*", default=["milk_baseline", "ets", "sarima", "seasonal_naive"],
                   help="existing alternatives for the switching check (persistence is never allowed)")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--no-markov", action="store_true", help="skip the Markov-switching feature (faster)")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_gate_audit)

    p = sub.add_parser("specialist-a", help="G2 Track A: S1 re-level used where the G1 gate says unstable "
                                            "(day 1 to month 3), pre-registered keep rule")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3")
    p.add_argument("--raw-tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6")
    p.add_argument("--base", default="milk_baseline_adaptive")
    p.add_argument("--gate", default="logistic", choices=["logistic", "lgbm"])
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_specialist_a)

    p = sub.add_parser("specialist-b", help="G2 Track B: zero-shot Chronos-2 yield per cow x engine cows "
                                            "(week 13, months 6-12), pre-registered keep rule")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3")
    p.add_argument("--herd-tag", default="w24_ck_kn_rk_lag90_hl6")
    p.add_argument("--base", default="milk_baseline_adaptive")
    p.add_argument("--model", default="amazon/chronos-2")
    p.add_argument("--device", default="cpu")
    p.add_argument("--tune", action="store_true",
                   help="nested year-by-year choice of context source, length and point forecast")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_specialist_b)

    p = sub.add_parser("tune-gate", help="nested tuning of the gate (logistic / LightGBM settings) and the "
                                         "Track A switch (S1 window, threshold); fold years 2019-2023")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3")
    p.add_argument("--raw-tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6")
    p.add_argument("--base", default="milk_baseline_adaptive")
    p.add_argument("--no-markov", action="store_true")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_tune_gate)

    p = sub.add_parser("compare-target", help="recorded milk target vs DelPro-only target (same model, "
                                              "origins from 2020-08), pre-registered rule")
    p.add_argument("--tag-record", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3")
    p.add_argument("--tag-delpro", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_tdp_adhq0.1t365z3")
    p.add_argument("--model", default="milk_baseline_adaptive")
    p.add_argument("--start", default="2020-08-01")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_compare_target)

    p = sub.add_parser("gate-outlook", help="pfoi-1.2.1-dev documents: 1.2.0-dev forecasts with gate confidence "
                                            "and gate-conditional milk ranges (files only, for compare-runs)")
    p.add_argument("--source", default="pfoi-1.2.0-dev", help="built version to copy (its folder in outlook/)")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3")
    p.add_argument("--origins", nargs="*", default=None, help="forecast dates (default: every built one)")
    p.add_argument("--no-markov", action="store_true")
    p.add_argument("--write", action="store_true",
                   help="also write the documents to c1_output.run_document (role farmx_model), for the page")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_gate_outlook)

    p = sub.add_parser("gate-intervals", help="pfoi-1.2.1-dev backtest check: gate-conditional vs pooled ranges, "
                                              "coverage and width by confidence, pre-registered rule")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3")
    p.add_argument("--base", default="milk_baseline_adaptive")
    p.add_argument("--herd-tag", default="w24_ck_kn_rk_lag90_hl6")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_gate_intervals)

    p = sub.add_parser("thi-backtest", help="experimental THI forecasts v1/v2 vs persistence and "
                                            "climatology (weather only, aggregates)")
    p.add_argument("--block", default="development", choices=["development", "test"])
    p.add_argument("--weather-lag", type=int, default=6,
                   help="last weather day used = forecast date minus this (ERA5 is ~5 days late)")
    p.add_argument("--ahead", type=int, default=90, help="days forecast at each date")
    p.add_argument("--step", type=int, default=7, help="days between forecast dates")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_thi_backtest)

    p = sub.add_parser("repro-timing", help="M7: reproductive timing (record vs engine), aggregates only")
    p.add_argument("--asof", default=None, help="YYYY-MM-DD (default: the data end)")
    p.add_argument("--window", default="12", choices=["12", "24", "36", "expanding"])
    p.add_argument("--conception-cut", default="origin", choices=["origin", "known"])
    p.add_argument("--cell-table", default="day_cell", choices=["day_cell", "day_cell_known"])
    p.add_argument("--conception-known", default="lag", choices=["lag", "recorded"])
    p.add_argument("--pregnancy-lag", type=int, default=35)
    p.add_argument("--half-life", default="none")
    p.add_argument("--conception-shape", default="off", choices=["on", "off"])
    p.add_argument("--fast-half-life", default="none")
    p.add_argument("--exit-model", default="state", choices=["state", "lactation"])
    p.add_argument("--preset", default=None, choices=["pfoi-1.1", "candidate"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_repro_timing)

    p = sub.add_parser("break-reset", help="PP1 1a: correction layer with and without the break reset")
    p.add_argument("--herd-tag", required=True, help="herd backtest tag, e.g. w24_ck_kn_rk_lag90_hl6")
    p.add_argument("--milk-tag", required=True, help="milk backtest tag, e.g. herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6")
    p.add_argument("--block", default="development", choices=["development", "posthoc"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_break_reset)

    p = sub.add_parser("evidence-ladder", help="F7: compare model additions on identical periods")
    p.add_argument("--rung", action="append", required=True,
                   help="label=tag:model, in ladder order, e.g. current=<tag>:milk_baseline_adaptive")
    p.add_argument("--grain", default="weekly", choices=["daily", "weekly", "monthly"])
    p.add_argument("--name", default=None,
                   help="suffix for the output files, e.g. posthoc (keeps the development ladder)")
    p.add_argument("--heat-band", default="on", choices=["on", "off"],
                   help="on = also score periods with THI above the past 90th percentile")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_evidence_ladder)

    p = sub.add_parser("generation-outcomes", help="M8: separate outcomes by generation (descriptive)")
    p.add_argument("--asof", default=None, help="YYYY-MM-DD (default: the data end)")
    p.add_argument("--cell-table", default="day_cell_known", choices=["day_cell", "day_cell_known"])
    p.add_argument("--conception-known", default="recorded", choices=["lag", "recorded"])
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_generation_outcomes)

    p = sub.add_parser("scenarios", help="Layer 3: scenarios like earlier heat, drought, disease")
    p.add_argument("--tag", required=True, help="milk backtest tag (its _test files are added if present)")
    p.add_argument("--model", default="milk_baseline")
    p.add_argument("--herd-tag", default=None,
                   help="1c: also measure milking cows and total herd after episodes (herd backtest tag)")
    p.add_argument("--outlook", default=None,
                   help="outlook CSV to apply scenarios to, e.g. logs/pfoi/outlook/outlook_202608.csv")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_scenarios)

    p = sub.add_parser("nested-cv", help="choose options year by year on past periods only (L9)")
    p.add_argument("--family", default="both", choices=["herd", "milk", "both"])
    p.add_argument("--include-hindsight", action="store_true",
                   help="also offer configurations whose pregnancy states use hindsight "
                        "(day_cell, conception cut 'origin'); off by default (leakage audit L3)")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_nested_cv)

    p = sub.add_parser("scorecard", help="accuracy, skill and calibration vs the agreed targets")
    milk_opts(p, blocks=("development", "test", "both", "posthoc"), block_default="both")
    p.add_argument("--intervals", default="empirical", choices=["empirical", "aci"],
                   help="aci = recency-weighted adaptive conformal intervals scaled by record quality")
    p.add_argument("--quality", default="on", choices=["on", "off"],
                   help="on = read daily herd-level record quality to split scores by band")
    p.add_argument("--interval-quality", default="on", choices=["on", "off"],
                   help="off = disable ACI quality scaling while retaining --quality scoring bands; "
                        "matched-period diagnostic, not a change to the published model")
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

    p = sub.add_parser("build-outlook", help="frozen-model outlook at one or more forecast dates "
                                             "(CSV; --write to c1_output)")
    from .freeze import LEGACY_OUTPUT_VALUES
    p.add_argument("--persistence-blend", choices=["off", "on"],
                   default=LEGACY_OUTPUT_VALUES["persistence_blend"],
                   help="T1: opt-in persistence-only milk blend; requires unreconciled pfoi-1.1")
    p.add_argument("--origin", nargs="+", default=["2026-08-01"],
                   help="YYYY-MM-01 forecast date(s); several are built one after another")
    p.add_argument("--out", default="logs/pfoi")
    p.add_argument("--write", action="store_true", help="replace this origin's rows in c1_output")
    p.add_argument("--backtests", default=None,
                   help="folder with the backtest error files for ranges and corrections "
                        "(default: --out; e.g. logs/pfoi_ref for pfoi-1.0.0)")
    p.add_argument("--preset", default=None, choices=["pfoi-1.1", "pfoi-1.1.1", "candidate"],
                   help="pfoi-1.1 (alias candidate) = frozen pfoi-1.1.0 with its correction layer, "
                        "files in <out>/outlook/pfoi-1.1.0/; pfoi-1.1.1 = the same model published "
                        "for 12 months at every grain (days reconciled to the corrected months; "
                        "run backtest-path first); --write publishes it next to the others")
    p.add_argument("--k", default=None, choices=list(K_MODES),
                   help="PP1 development: anchor_first = level from trusted recent days, 12-month "
                        "k only as fallback, milk withheld when neither exists (needs --preset)")
    p.add_argument("--fast-half-life", default="none",
                   help="PP1 development (1b): half-life for abortions, losses, exits and conceptions")
    p.add_argument("--exit-model", default="state", choices=["state", "lactation"],
                   help="PP1 development: milking-cow exits by parity x DIM band x pregnancy")
    p.add_argument("--break-reset", default="off", choices=["on", "off"],
                   help="PP1 development (1a): corrections ignore errors from before the latest "
                        "break detected at the forecast date")
    p.add_argument("--anchor-gate", default="off", choices=["on", "off"],
                   help="PP1 development: anchor the milk level only on verified days (M3)")
    p.add_argument("--intervals", default="empirical", choices=["empirical", "aci"],
                   help="PP1 development: aci = adaptive conformal milk ranges scaled by record quality")
    p.add_argument("--evidence", default=None,
                   help="PP1 development: folder with outage_sim/, evidence/ and drivers_registry_* "
                        "tables for the page (default: the backtest folder)")
    p.add_argument("--staleness", default=None,
                   help="PP1 development: outage_staleness_*.csv from outage_sim (development); "
                        "milk ranges widen with days since the last trusted milk day")
    p.set_defaults(func=_cmd_build_outlook)

    p = sub.add_parser("backtest-path", help="pfoi-1.1.1: score the reconciled days and weeks up to "
                                             "12 months ahead at monthly forecast dates")
    p.add_argument("--block", default="development", choices=["development", "posthoc"])
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--out", default="logs/pfoi")
    p.add_argument("--backtests", default=None,
                   help="folder with the pfoi-1.1 milk and herd backtest errors (default: --out)")
    p.set_defaults(func=_cmd_backtest_path, preset="pfoi-1.1.1")

    p = sub.add_parser("freeze-info", help="frozen versions and their configuration hashes")
    p.set_defaults(func=_cmd_freeze_info)

    p = sub.add_parser("compare-runs", help="two versions at forecast dates (from build-outlook files)")
    p.add_argument("--origins", nargs="+", required=True, help="YYYY-MM-01 forecast dates")
    p.add_argument("--base", default="pfoi-1.0.0", choices=["pfoi-1.0.0", "pfoi-1.1.0", "pfoi-1.1.1", PP1_DEV_VERSION])
    p.add_argument("--candidate", default="pfoi-1.1.0", choices=["pfoi-1.1.0", "pfoi-1.1.1", PP1_DEV_VERSION,
                                                               "pfoi-1.2.0-dev-persistence"],
                   help=f"{PP1_DEV_VERSION} = development build (build-outlook with --k / --intervals aci)")
    p.add_argument("--grain", default="month", choices=["month", "week", "day"],
                   help="day / week: the pfoi-1.1.1 daily and weekly path (earlier versions: 14 days, 13 weeks)")
    p.add_argument("--also", nargs="*", default=None, metavar="VERSION",
                   help="extra versions drawn on the same chart (for example pfoi-1.2.0-dev-blend from "
                        "blend-outlook); scores use the periods every version forecast")
    p.add_argument("--series", nargs="*", default=None,
                   help="with --also: series to draw (default milk_litres, the only one the blend changes)")
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_compare_runs)

    p = sub.add_parser("blend-outlook", help="preview the persistence blend on built outlook documents "
                                             "(files only, no database)")
    p.add_argument("--source", default=PP1_DEV_VERSION, help="built version to derive <version>-blend from")
    p.add_argument("--origins", nargs="*", default=None, help="forecast dates (default: every built one)")
    p.add_argument("--tag", default="herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6",
                   help="raw milk backtest tag the weights are learned from")
    p.add_argument("--min-obs", type=int, default=8)
    p.add_argument("--out", default="logs/pfoi")
    p.set_defaults(func=_cmd_blend_outlook)

    args = parser.parse_args(argv)
    _apply_preset(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
