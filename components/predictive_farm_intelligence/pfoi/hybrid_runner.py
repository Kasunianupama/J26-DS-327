"""User-run PFOI 1.3 rolling research replay. Prints/saves aggregate reports only.

Real-data execution belongs to the user. Importing this module opens no connection,
loads no environment file and reads no real-data artifact. No publication or frozen
test command is supported. The forecast function also works with synthetic sources.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from pathlib import Path
import json
import hashlib
import sys

import numpy as np
import pandas as pd

from .hybrid import (VERSION, HybridConfig, abortion_posterior, change_forecast,
                     choose_weights, completed, coupled_hazard, dated, milk_context,
                     reconcile_milk, residual_interval)


def base_recipe(exit_model="state", break_reset=False):
    """Code-derived 1.2 reference: 1.1 preset + anchor-first, no rejected fast rates.

    The 1.2 label has no unique configuration in cli.py; record every setting rather
    than pretending the label identifies the user's latest published build.
    """
    from .freeze import V11_ENGINE, V11_MILK, V11_ADAPTIVE, V11_CORRECTED_HERD
    if exit_model not in ("state", "lactation"):
        raise ValueError("Unknown exit model")
    engine = replace(V11_ENGINE, milking_exit_model=exit_model)
    milk = replace(V11_MILK, k_mode="anchor_first")
    manifest = dict(reference="pfoi-1.2.0-dev code reference", engine=asdict(engine),
                    milk=asdict(milk), adaptive=asdict(V11_ADAPTIVE),
                    corrected_herd=list(V11_CORRECTED_HERD), break_reset=break_reset,
                    interval_reference="point forecasts only; new own-error intervals",
                    origin_schedule="monthly first day; daily/weekly scored from that path")
    return engine, milk, manifest


def history_frame(target, panel):
    """Trust eligibility uses only daily source/record checks, not future outcomes."""
    from .episodes import MAX_LITRES_PER_COW_DAY, VERIFIED_MIN_SHARE
    t, p = dated(target), dated(panel)
    h = t.join(p[["milking", "real_abortions"]], how="outer")
    h = h.rename(columns={"target_source": "source", "target_litres": "milk",
                          "real_abortions": "abortions"})
    delpro = h.source.eq("delpro")
    share_ok = h.identified_share.ge(VERIFIED_MIN_SHARE)
    plausible = h.milking.gt(0) & (h.milk/h.milking).le(MAX_LITRES_PER_COW_DAY)
    h["trusted"] = (h.is_scoreable.fillna(False).astype(bool) & h.data_gap.eq(0)
                    & (~delpro | (share_ok & plausible)))
    return h


def _part(daily, start, end):
    dates = pd.to_datetime(daily.date)
    return daily.loc[(dates >= pd.Timestamp(start)) & (dates < pd.Timestamp(end))]


def forecast_origin(run, history, milk_records, abortion_records, cfg):
    """Issue a coherent daily path without reading any current/future actuals.

    Returned pending records deliberately have actual=NaN. Scoring is a separate step.
    Herd outputs stay on a single cohort path (legacy additive stock biases are not
    applied); their effect is measured against the published-style base reference.
    """
    from .herd_engine import project
    from .periods import period_bounds

    origin = pd.Timestamp(run.origin)
    first_end = origin+pd.offsets.MonthBegin(1)
    posterior = abortion_posterior(history, origin, cfg)
    specialist = run.daily.copy()
    if posterior is not None:
        hazard = coupled_hazard(run.inputs.state, run.rates.abortion, posterior, 1.)
        proj = project(run.inputs.state, replace(run.rates, abortion=hazard), run.horizon_days,
                       milk_curve=run.setup.arrays)
        specialist = proj.daily.assign(herd_milk=run.setup.k*proj.daily.curve_litres)
    base_ab = float(_part(run.daily, origin, first_end).real_abortions.sum())
    spec_ab = float(_part(specialist, origin, first_end).real_abortions.sum())
    weights, gate_n = choose_weights(abortion_records, origin, ("base", "specialist"), cfg, "base")
    weight = weights["specialist"] if posterior is not None else 0.
    hazard = coupled_hazard(run.inputs.state, run.rates.abortion, posterior, weight)
    if weight > 0:
        proj = project(run.inputs.state, replace(run.rates, abortion=hazard), run.horizon_days,
                       milk_curve=run.setup.arrays)
        daily = proj.daily.assign(herd_milk=run.setup.k*proj.daily.curve_litres)
    else:
        daily = run.daily.copy()
    pending_ab = dict(origin=origin, period_start=origin, period_end=first_end, actual=np.nan,
                      base=base_ab, specialist=spec_ab if posterior is not None else np.nan,
                      fused=float(_part(daily, origin, first_end).real_abortions.sum()),
                      scale=1., weight=weight, gate_n=gate_n)
    months, pending_milk, decisions = {}, [], []
    for h in range(1, 13):
        start, end = period_bounds(run.origin, "monthly", h)
        part = _part(daily, start, end)
        days = (end-start).days
        if len(part) != days:
            continue
        context, reason = milk_context(history, origin, part, cfg)
        if run.milk_withheld or context is None:
            daily.loc[part.index, "herd_milk"] = np.nan
            decisions.append(dict(horizon=h, status=run.milk_withheld or reason, gate_n=0,
                train_n=0, route="withheld", abortion_weight=weight, abortion_gate_n=gate_n))
            continue
        prior = [r for r in milk_records if r["horizon"] == h and r["source"] == context["source"]]
        base = run.period_value("monthly", h, "herd_milk", False)
        values = dict(persistence=context["anchor"]*days, base=base,
                      coupled=run.output("monthly", "herd_milk", h, float(part.herd_milk.sum())))
        for name, feature in (("history_change", "history_x"), ("pipeline_change", "pipeline_x")):
            value = change_forecast(prior, context, origin, days, feature, cfg)
            if value is not None:
                values[name] = value
        names = tuple(n for n in ("persistence", "coupled", "history_change", "pipeline_change")
                      if n in values and np.isfinite(values[n]))
        w, n = choose_weights(prior, origin, names, cfg, "persistence")
        selected = sum(w[k]*values[k] for k in w)
        months[pd.Timestamp(start)] = selected
        pending_milk.append(dict(origin=origin, period_start=pd.Timestamp(start),
            period_end=pd.Timestamp(end), horizon=h, days=days, actual=np.nan,
            **context, **values, fused=selected, scale=context["anchor"]*days))
        route = "+".join(f"{name}:{value:g}" for name, value in w.items() if value > 0)
        decisions.append(dict(horizon=h, status="issued", gate_n=n,
            train_n=len(completed(prior, origin)), route=route,
            weights=w, abortion_weight=weight, abortion_gate_n=gate_n))
    path = reconcile_milk(daily, months)
    return path, pending_milk, pending_ab, decisions


def _actual(history, start, end, series, verified_milk=True):
    part = history.loc[(history.index >= pd.Timestamp(start)) & (history.index < pd.Timestamp(end))]
    if len(part) != (pd.Timestamp(end)-pd.Timestamp(start)).days:
        return np.nan, "missing"
    if series == "herd_milk":
        if (not part.is_scoreable.fillna(False).astype(bool).all()
                or part.source.isna().any() or part.source.nunique() != 1
                or not np.isfinite(part.milk).all() or (part.milk < 0).any()):
            return np.nan, "unscoreable"
        if verified_milk and not part.trusted.all():
            return np.nan, "unverified"
        return float(part.milk.sum()), "verified"
    col = {"real_abortions": "abortions"}.get(series, series)
    if col not in part or not np.isfinite(part[col]).all() or (part[col] < 0).any():
        return np.nan, "missing"
    return float(part[col].mean() if series in ("milking", "n_herd") else part[col].sum()), "recorded"


def evaluate(source, origins, end, engine, milk, base_errors, cfg, break_reset=False):
    """Monthly issuance, completed outcomes only, no frozen-test markers or writes."""
    from .data import DATA_START
    from .freeze import V11_ADAPTIVE, V11_CORRECTED_HERD
    from .outlook import run_model, build_output_layer
    from .milk_baseline import MilkHistory
    from .periods import HORIZONS, period_bounds

    target = source.target_daily(DATA_START, end)
    panel = source.panel_daily(DATA_START, end)
    history = history_frame(target, panel)
    extras = dated(panel).drop(columns=["milking", "real_abortions"])
    history = history.join(extras)
    validate_base_actuals(base_errors, history)
    hist = MilkHistory(source.milking_cowdays(DATA_START, end), target)
    milk_records, abortion_records, scores, decisions = [], [], [], []
    issued_records = {}  # own issued errors, one series/grain/horizon/source per key
    cache = {}
    for origin in origins:
        run = run_model(source, origin, engine, milk, hist=hist, cache=cache)
        breaks = None
        if break_reset:
            from .breaks import detect_breaks
            # Hand-labelled evaluation episodes never enter model inputs.
            before = history.loc[history.index < pd.Timestamp(origin)].reset_index()
            breaks = detect_breaks(before.rename(columns={"milk": "target_litres"}))
        run.layer = build_output_layer(base_errors, origin, V11_ADAPTIVE, V11_CORRECTED_HERD, breaks)
        path, pending, abortion, opts = forecast_origin(run, history, milk_records, abortion_records, cfg)
        decisions.extend(dict(origin=pd.Timestamp(origin), **opt) for opt in opts)
        # Predictions above are fixed before any current outcomes are attached below.
        for r in pending:
            r["actual"], _ = _actual(history, r["period_start"], r["period_end"], "herd_milk")
        abortion["actual"], _ = _actual(history, abortion["period_start"], abortion["period_end"], "real_abortions")
        milk_records.extend(pending)
        abortion_records.append(abortion)
        pending_by_h = {r["horizon"]: r for r in pending}
        for grain, horizons in HORIZONS.items():
            for h in horizons:
                start, stop = period_bounds(run.starts[grain], grain, h)
                for series in ("herd_milk", "milking", "n_herd", "calvings", "real_abortions"):
                    part = _part(path, start, stop)
                    actual, band = _actual(history, start, stop, series)
                    if len(part) != (stop-start).days:
                        continue
                    stock = series in ("milking", "n_herd")
                    values = part[series]
                    forecast = float(values.mean() if stock else values.sum(min_count=len(values)))
                    base = run.period_value(grain, h, series, stock)
                    past = history.loc[history.index < pd.Timestamp(origin)]
                    if series == "herd_milk":
                        ctx, _ = milk_context(history, origin, part, cfg)
                        persistence = ctx["anchor"]*(stop-start).days if ctx else np.nan
                        source_name = ctx["source"] if ctx else None
                        scale = persistence
                    elif stock:
                        persistence = float(past[series].iloc[-1]) if len(past) else np.nan
                        source_name, scale = None, 1.
                    else:
                        col = "abortions" if series == "real_abortions" else series
                        p = past.loc[past.index >= pd.Timestamp(origin)-pd.Timedelta(days=28), col]
                        persistence = float(p.mean()*(stop-start).days) if len(p) == 28 and p.notna().all() else np.nan
                        source_name, scale = None, 1.
                    key = (grain, h, series, source_name)
                    prior = issued_records.setdefault(key, [])
                    lo, hi, ni = residual_interval(prior, origin, forecast, scale, cfg) \
                        if np.isfinite(forecast) and np.isfinite(scale) and scale > 0 else (None, None, 0)
                    lo80, hi80, _ = residual_interval(prior, origin, forecast, scale, cfg, .8) \
                        if np.isfinite(forecast) and np.isfinite(scale) and scale > 0 else (None, None, 0)
                    record = dict(origin=pd.Timestamp(origin), period_start=pd.Timestamp(start),
                        period_end=pd.Timestamp(stop), fused=forecast, actual=actual, scale=scale)
                    prior.append(record)
                    common = dict(grain=grain, horizon=h, series=series, band=band,
                                  actual=actual, origin_year=origin.year)
                    candidates = {VERSION: forecast, "base_1_2_code_reference": base,
                                  "persistence": persistence}
                    if series == "herd_milk" and grain == "monthly" and h in pending_by_h:
                        r = pending_by_h[h]
                        candidates.update({k: r.get(k, np.nan) for k in
                                           ("coupled", "history_change", "pipeline_change")})
                    for model, value in candidates.items():
                        scores.append(dict(**common, model=model, forecast=value,
                            lower=lo if model == VERSION else None,
                            upper=hi if model == VERSION else None,
                            lower80=lo80 if model == VERSION else None,
                            upper80=hi80 if model == VERSION else None,
                            interval_n=ni if model == VERSION else 0,
                            # Internal keys allow exact pairing; never printed/saved as rows.
                            origin=pd.Timestamp(origin), period_start=pd.Timestamp(start)))
        print(f"Completed monthly origin {origin.isoformat()}", file=sys.stderr, flush=True)
    return pd.DataFrame(scores), pd.DataFrame(decisions)


def validate_base_actuals(errors, history):
    """Refuse correction histories scored against a different published data version."""
    if errors is None or errors.empty:
        return
    supported = ("herd_milk", "milking", "n_herd", "calvings", "real_abortions")
    rows = errors.loc[errors.series.isin(supported),
                      ["period_start", "period_end", "series", "actual"]].drop_duplicates()
    for r in rows.itertuples(index=False):
        actual, _ = _actual(history, r.period_start, r.period_end, r.series)
        if np.isfinite(actual) and (not np.isfinite(r.actual)
                or not np.isclose(actual, r.actual, rtol=1e-8, atol=1e-6)):
            raise ValueError("Base error actuals disagree with current aggregate history; "
                             "regenerate matching base errors before comparison")


def reports(scores, decisions):
    """Group metrics and exact paired skill; missing/withheld forecasts remain counted."""
    from .error_diagnostics import metrics, grouped
    from .episodes import add_recovery
    from .scorecard import poisson_deviance
    scores = scores.copy()
    for col in ("lower80", "upper80"):
        if col not in scores:
            scores[col] = np.nan
    groups = ["model", "series", "grain", "horizon", "band"]
    metric_rows = []
    for key, g in scores.groupby(groups, dropna=False):
        valid = np.isfinite(g.forecast) & np.isfinite(g.actual)
        ranged = valid & g.lower.notna() & g.upper.notna()
        coverage = ((g.loc[ranged, "actual"] >= g.loc[ranged, "lower"])
                    & (g.loc[ranged, "actual"] <= g.loc[ranged, "upper"]))
        ranged80 = valid & g.lower80.notna() & g.upper80.notna()
        coverage80 = ((g.loc[ranged80, "actual"] >= g.loc[ranged80, "lower80"])
                      & (g.loc[ranged80, "actual"] <= g.loc[ranged80, "upper80"]))
        relative_width = ((g.loc[ranged, "upper"]-g.loc[ranged, "lower"])
                          / g.loc[ranged, "forecast"].where(g.loc[ranged, "forecast"] > 0))
        metric_rows.append(dict(zip(groups, key), **metrics(g), scheduled=len(g),
            scoreable=int(np.isfinite(g.actual).sum()),
            issued=int(np.isfinite(g.forecast).sum()), interval_n=int(ranged.sum()),
            coverage80=coverage80.mean(), coverage90=coverage.mean(),
            width90=relative_width.mean(), width90_positive_forecast_n=int(relative_width.notna().sum()),
            mean_width=(g.loc[ranged, "upper"]-g.loc[ranged, "lower"]).mean()))
    pairs = []
    keys = ["origin", "period_start", "series", "grain", "horizon", "band"]
    for reference in ("persistence", "base_1_2_code_reference"):
        ref = scores[scores.model.eq(reference)]
        cand = scores[~scores.model.isin(("persistence", "base_1_2_code_reference"))]
        pair = cand.merge(ref[keys+["forecast", "actual"]], on=keys,
                          suffixes=("", "_ref"), validate="many_to_one")
        pair = pair[np.isfinite(pair.forecast) & np.isfinite(pair.forecast_ref) & np.isfinite(pair.actual)]
        if not np.allclose(pair.actual, pair.actual_ref):
            raise ValueError("Paired targets differ")
        for key, g in pair.groupby(groups, dropna=False):
            mae = float((g.forecast-g.actual).abs().mean())
            ref_mae = float((g.forecast_ref-g.actual).abs().mean())
            count = g.series.iloc[0] in ("real_abortions", "calvings")
            dc = poisson_deviance(g.actual.to_numpy(), g.forecast.to_numpy()) if count else np.nan
            dr = poisson_deviance(g.actual.to_numpy(), g.forecast_ref.to_numpy()) if count else np.nan
            pairs.append(dict(zip(groups, key), reference=reference, n=len(g), mae=mae,
                reference_mae=ref_mae, skill=1-mae/ref_mae if ref_mae > 0 else np.nan,
                deviance_ratio=dc/dr if dr > 0 else np.nan,
                interpretable=len(g) >= 12))
    decisions = decisions.copy()
    for col, default in (("route", "unavailable"), ("train_n", 0),
                         ("abortion_weight", 0.), ("abortion_gate_n", 0)):
        if col not in decisions:
            decisions[col] = default
    status = decisions.groupby(["horizon", "status", "route"]).agg(n=("status", "size"),
        min_gate_n=("gate_n", "min"), max_gate_n=("gate_n", "max"),
        min_train_n=("train_n", "min"), max_train_n=("train_n", "max"),
        mean_abortion_weight=("abortion_weight", "mean"),
        min_abortion_gate_n=("abortion_gate_n", "min")).reset_index()
    recovery = grouped(add_recovery(scores), groups+["last_break", "since_break"])
    by_year = grouped(scores, groups+["origin_year"]) if "origin_year" in scores else pd.DataFrame()
    return dict(metrics=pd.DataFrame(metric_rows), matched=pd.DataFrame(pairs),
                decisions=status, recovery=recovery, by_origin_year=by_year)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--block", required=True, choices=("development", "posthoc"))
    p.add_argument("--start", default="2017-01-01", type=pd.Timestamp)
    p.add_argument("--end", required=True, type=pd.Timestamp, help="Exclusive observation cutoff")
    p.add_argument("--backtests", default="logs/pfoi")
    p.add_argument("--exit-model", default="state", choices=("state", "lactation"))
    p.add_argument("--break-reset", action="store_true")
    p.add_argument("--out", required=True, help="New directory; refuses overwrite")
    a = p.parse_args(argv)
    if a.start >= a.end or a.start.day != 1 or a.start < pd.Timestamp("2017-01-01"):
        p.error("Start must be a month boundary before end")
    cutoff = pd.Timestamp("2024-01-01")
    if (a.block == "development" and a.end > cutoff) or (a.block == "posthoc" and a.start < cutoff):
        p.error("Development ends by 2024-01-01; posthoc starts on/after that date")
    if Path(a.out).exists():
        p.error("Output already exists; choose a new directory")
    engine, milk, manifest = base_recipe(a.exit_model, a.break_reset)
    tag = "w24_ck_kn_rk_lag90_hl6"+("_xl" if a.exit_model == "lactation" else "")
    # Explicit files, no glob selecting a different model. Check before connecting.
    parts, input_hashes = [], {}
    for grain in ("monthly", "weekly"):
        for family, name in (("herd", tag), ("milk", f"{milk.tag()}_{tag}")):
            suffixes = ("", "_posthoc") if a.block == "posthoc" else ("",)
            for suffix in suffixes:
                path = Path(a.backtests)/f"{family}_backtest_errors_{grain}_{name}{suffix}.csv"
                if not path.is_file():
                    p.error(f"Missing required base errors: {path.name}")
                x = pd.read_csv(path)
                dates = x[["origin", "period_end"]].apply(pd.to_datetime, errors="raise")
                if dates.isna().any().any() or (dates.period_end <= dates.origin).any():
                    p.error("Base errors have missing or invalid dates")
                if (not suffix and ((dates.period_end > cutoff).any() or (dates.origin >= cutoff).any())) \
                        or (suffix and (dates.origin < cutoff).any()):
                    p.error("Base errors cross their declared development/posthoc boundary")
                if x.duplicated(["origin", "period_start", "grain", "horizon", "series", "model"]).any():
                    p.error("Duplicate base errors")
                input_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
                parts.append(x)
    base_errors = pd.concat(parts, ignore_index=True)
    # User-only execution boundary. Tests supply an in-memory source to evaluate().
    from .data import SqlHerdSource
    source = SqlHerdSource.from_env(cell_table=engine.cell_table, conception_known=engine.conception_known)
    cfg = HybridConfig()
    # Replay development first for posthoc selection/interval history. No final-test marker.
    origins = list(pd.date_range("2017-01-01", a.end, freq="MS", inclusive="left").date)
    scores, decisions = evaluate(source, origins, a.end.date(), engine, milk, base_errors, cfg, a.break_reset)
    scored = scores.loc[scores.origin >= a.start]
    tables = reports(scored, decisions.loc[decisions.origin >= a.start])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    metadata = dict(version=VERSION, config_hash=cfg.identity(manifest), base=manifest,
        hybrid=asdict(cfg), block=a.block, start=str(a.start.date()), end_exclusive=str(a.end.date()),
        base_error_sha256=input_hashes, core_version=source.core_version(),
        status="research candidate; no measured improvement or calibration claimed",
        limitations=["Current ETL history may include retrospective revisions",
                     "Recorded abortion intensity is not pregnancy-exposure-adjusted risk",
                     "No causal, finance or individual-animal claim",
                     "Monthly issuance; weekly scores differ from weekly-origin backtests",
                     "Additive legacy stock corrections omitted to preserve cohort consistency",
                     "2024 onward is posthoc; needs prospective confirmation"])
    (out/"manifest.json").write_text(json.dumps(metadata, indent=2))
    # Herd-level forecast paths per forecast date (aggregates) for the per-date comparison charts.
    own = scored.loc[scored.model.eq(VERSION),
                     ["origin", "period_start", "grain", "horizon", "series", "forecast",
                      "lower", "upper", "actual"]]
    own.to_csv(out/"paths.csv", index=False)
    for name, table in tables.items():
        table.to_csv(out/f"{name}.csv", index=False)
        print(f"\n=== {name} ===\n{table.to_string(index=False)}")
    print(f"{VERSION}: aggregate reports only; nothing published. Hash {metadata['config_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
