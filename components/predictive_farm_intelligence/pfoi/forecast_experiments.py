"""Experimental rolling milk forecasts, user-run on local herd-level aggregates.

Separate development/post-hoc reports. Never changes frozen models or final-test
markers. Only aggregate metrics are printed/saved, not individual forecast rows.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd

from .backtest_milk import _target_frame, period_actual, benchmark_forecasts
from .episodes import add_bands, add_recovery, daily_quality
from .error_diagnostics import KEYS, grouped
from .periods import HORIZONS, period_bounds

MODELS = ("ridge", "boosted", "tcn", "tcn_residual")
CUTOFF = pd.Timestamp("2024-01-01")
RAW_TAG = "herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90"
ADAPTIVE_TAG = RAW_TAG + "_adhq0.1t365z3"


@dataclass(frozen=True)
class ExperimentConfig:
    context: int = 84
    min_train: int = 24
    train_years: int = 5
    epochs: int = 60
    seed: int = 17


def origin_grid(start, end, grain):
    return pd.date_range(start, end, freq="MS" if grain == "monthly" else "W-MON", inclusive="left")


def daily_frame(target, panel):
    """No future fill. Missing observations are zero placeholders with explicit masks."""
    t, p = target.copy(), panel.copy()
    if t.empty:
        raise ValueError("No target history available")
    t["date"], p["date"] = pd.to_datetime(t.date), pd.to_datetime(p.date)
    if t.date.duplicated().any() or p.date.duplicated().any():
        raise ValueError("Daily aggregate dates must be unique")
    f = t.merge(p[["date", "milking"]], on="date", how="left").set_index("date").sort_index()
    f = f.reindex(pd.date_range(f.index.min(), f.index.max(), freq="D"))
    f["milk"] = f.target_litres.where(f.is_scoreable.fillna(False).astype(bool))
    f["milk"] = f.milk.where(np.isfinite(f.milk) & f.milk.ge(0))
    f["milking"] = f.milking.where(np.isfinite(f.milking) & f.milking.ge(0))
    return f


def features(frame, origin, start, cfg):
    days = pd.date_range(origin-pd.Timedelta(days=cfg.context), periods=cfg.context, freq="D")
    history = frame.reindex(days)  # always strictly before origin
    if history.milk.iloc[-28:].notna().sum() < 7:
        return None
    milk_scale = max(float(history.milk.iloc[-28:].mean()), 1.)
    cows_scale = max(float(history.milking.iloc[-28:].mean()), 1.)
    if not np.isfinite(cows_scale):
        cows_scale = 1.
    seq = np.column_stack([
        history.milk.fillna(0)/milk_scale, history.milking.fillna(0)/cows_scale,
        history.milk.isna().astype(float), history.milking.isna().astype(float),
        history.target_source.eq("delpro").astype(float),
    ]).astype(np.float32)
    static = np.array([np.log1p(milk_scale), np.log1p(cows_scale),
                       np.sin(2*np.pi*start.month/12), np.cos(2*np.pi*start.month/12),
                       np.sin(2*np.pi*start.dayofweek/7), np.cos(2*np.pi*start.dayofweek/7)], dtype=np.float32)
    return seq, static


def examples(frame, target, grain, horizon, cfg):
    """Historical labels are kept separate; callers enforce completion before fitting."""
    rows, seqs, statics = [], [], []
    start = frame.index.min() + pd.Timedelta(days=cfg.context)
    for origin in origin_grid(start, frame.index.max()+pd.Timedelta(days=1), grain):
        s, e = period_bounds(origin.date(), grain, horizon)
        feat = features(frame, origin, pd.Timestamp(s), cfg)
        act = period_actual(target, s, e)
        if feat is None or act is None:
            continue
        rows.append(dict(origin=origin, period_start=pd.Timestamp(s), period_end=pd.Timestamp(e),
                         grain=grain, horizon=horizon, series="herd_milk", actual=act[0],
                         source=act[1], days=(e-s).days))
        seqs.append(feat[0]); statics.append(feat[1])
    return pd.DataFrame(rows), np.asarray(seqs), np.asarray(statics)


def fit_predict(name, seq, static, y, query_seq, query_static, cfg):
    """Training transforms see training rows only. Fixed settings, no random validation split."""
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    x = np.concatenate([seq.reshape(len(seq), -1), static], axis=1)
    q = np.concatenate([query_seq.reshape(1, -1), query_static.reshape(1, -1)], axis=1)
    if name in ("ridge", "boosted"):
        if name == "ridge":
            from sklearn.linear_model import Ridge
            estimator = Ridge(alpha=100.)
        else:
            from sklearn.ensemble import HistGradientBoostingRegressor
            estimator = HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=7,
                min_samples_leaf=10, l2_regularization=10., early_stopping=False, random_state=cfg.seed)
        estimator.fit(scaler.fit_transform(x), y)
        return float(estimator.predict(scaler.transform(q))[0])
    import torch
    from torch import nn
    torch.manual_seed(cfg.seed)
    # CPU, one thread: reproducible small experiments; no GPU dependency.
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        class CausalConv(nn.Module):
            def __init__(self, cin, cout, dilation):
                super().__init__()
                self.pad = 2*dilation
                self.conv = nn.Conv1d(cin, cout, 3, dilation=dilation)
            def forward(self, value):
                return self.conv(torch.nn.functional.pad(value, (self.pad, 0)))
        class Network(nn.Module):
            def __init__(self):
                super().__init__()
                self.sequence = nn.Sequential(CausalConv(seq.shape[2], 16, 1), nn.ReLU(),
                    CausalConv(16, 16, 2), nn.ReLU(), CausalConv(16, 16, 4), nn.ReLU(),
                    CausalConv(16, 16, 8), nn.ReLU(), CausalConv(16, 16, 16), nn.ReLU())
                self.output = nn.Linear(16+static.shape[1], 1)
            def forward(self, values, fixed):
                return self.output(torch.cat([self.sequence(values)[:, :, -1], fixed], dim=1)).squeeze(1)
        sm = seq.mean(axis=(0, 1)); ss = np.maximum(seq.std(axis=(0, 1)), 1e-6)
        xs = torch.tensor(((seq-sm)/ss).transpose(0, 2, 1), dtype=torch.float32)
        xt = torch.tensor(scaler.fit_transform(static), dtype=torch.float32)
        ym, ys = float(np.mean(y)), max(float(np.std(y)), 1.)
        yt = torch.tensor((y-ym)/ys, dtype=torch.float32)
        network = Network()
        optimizer = torch.optim.AdamW(network.parameters(), lr=.003, weight_decay=.01)
        for _ in range(cfg.epochs):
            optimizer.zero_grad()
            loss = nn.functional.smooth_l1_loss(network(xs, xt), yt)
            loss.backward()
            nn.utils.clip_grad_norm_(network.parameters(), 1.)
            optimizer.step()
        network.eval()
        with torch.no_grad():
            qs = torch.tensor(((query_seq-sm)/ss).T[None], dtype=torch.float32)
            qt = torch.tensor(scaler.transform(query_static[None]), dtype=torch.float32)
            return float(network(qs, qt).item()*ys+ym)
    finally:
        torch.set_num_threads(previous_threads)


def rolling(frame, target, grain, horizon, start, end, models, cfg, structural=None):
    rows, seq, static = examples(frame, target, grain, horizon, cfg)
    if rows.empty:
        return pd.DataFrame(), []
    rows["structural"] = np.nan
    if structural is not None and not structural.empty:
        lookup = structural.set_index(KEYS).forecast
        rows["structural"] = [lookup.get(tuple(r[k] for k in KEYS), np.nan) for _, r in rows.iterrows()]
        check = rows.merge(structural[KEYS+["actual"]], on=KEYS, suffixes=("", "_saved"), validate="one_to_one")
        if not np.allclose(check.actual, check.actual_saved, rtol=1e-8, atol=1e-6, equal_nan=True):
            raise ValueError("Saved structural actuals differ from current targets; reconcile data versions")
    output, coverage = [], []
    queries = rows.index[(rows.origin >= start) & (rows.origin < end) & (rows.period_end <= end)]
    for idx in queries:
        row = rows.loc[idx]
        known = ((rows.period_end <= row.origin) & (rows.origin < row.origin)
                 & (rows.origin >= row.origin-pd.DateOffset(years=cfg.train_years)))
        # Restrict labels to the milk source known just before issuance.
        past = frame.loc[frame.index < row.origin, "target_source"].dropna()
        if not past.empty:
            known &= rows.source.eq(past.iloc[-1])
        for name in models:
            usable = known.copy()
            if name == "tcn_residual":
                usable &= rows.structural.notna()
            n = int(usable.sum())
            status = "ok"
            if name == "tcn_residual" and not np.isfinite(row.structural):
                status = "missing_structural_forecast"
            elif n < cfg.min_train:
                status = "insufficient_completed_training"
            coverage.append(dict(origin_year=row.origin.year, grain=grain, horizon=horizon,
                                 model=name, status=status, n_train=n))
            if status != "ok":
                continue
            y = rows.loc[usable, "actual"].to_numpy()/rows.loc[usable, "days"].to_numpy()
            if name == "tcn_residual":
                y -= rows.loc[usable, "structural"].to_numpy()/rows.loc[usable, "days"].to_numpy()
            value = fit_predict(name, seq[usable], static[usable], y, seq[idx], static[idx], cfg)*row.days
            if name == "tcn_residual":
                value += row.structural
            if not np.isfinite(value):
                raise ValueError("Non-finite prediction; experiment stopped")
            output.append(dict(row, model=name, forecast=max(0., value)))
        if np.isfinite(row.structural):
            output.append(dict(row, model="current_structural", forecast=row.structural))
        for name, _, value in benchmark_forecasts(target, row.origin.date(), grain, (horizon,)):
            output.append(dict(row, model=name, forecast=value))
    return pd.DataFrame(output), coverage


def read_structural(folder, tag, model, end):
    """Read only explicitly named saved aggregates, never create or rerun test artifacts."""
    if not re.fullmatch(r"[A-Za-z0-9_.]+", tag) or tag.endswith("_test"):
        raise ValueError("Pass the base tag without a test suffix")
    parts = []
    for grain in ("monthly", "weekly"):
        for suffix in ("", "_test") if end > CUTOFF else ("",):
            path = Path(folder)/f"milk_backtest_errors_{grain}_{tag}{suffix}.csv"
            if path.is_file():
                part = pd.read_csv(path)
                part = part[(part.model == model) & (part.series == "herd_milk")].copy()
                for col in ("origin", "period_start", "period_end"):
                    part[col] = pd.to_datetime(part[col], errors="raise")
                parts.append(part)
    if not parts:
        raise ValueError("No saved structural forecasts for the requested tag")
    result = pd.concat(parts, ignore_index=True)
    if result.duplicated(KEYS).any():
        raise ValueError("Duplicate structural forecasts")
    return result


def matched_reports(errors, models):
    """Year-specific paired comparisons; different pairs may have different coverage."""
    records = []
    for (year, grain, horizon), group in errors.groupby(["target_year", "grain", "horizon"]):
        for candidate in models:
            a = group[group.model == candidate]
            for reference in ("current_structural", "persistence", "seasonal_naive", "ets", "sarima"):
                b = group[group.model == reference]
                pair = a.merge(b[KEYS+["forecast", "actual"]], on=KEYS, suffixes=("", "_ref"), validate="one_to_one")
                if not np.allclose(pair.actual, pair.actual_ref, equal_nan=True):
                    raise ValueError("Matched actuals disagree")
                from .error_diagnostics import metrics
                for label in (candidate, reference):
                    scored = pair.copy()
                    if label == reference:
                        scored["forecast"] = scored.forecast_ref
                    records.append(dict(target_year=year, grain=grain, horizon=horizon,
                        candidate=candidate, reference=reference, scored_model=label,
                        candidate_available=len(a), reference_available=len(b), **metrics(scored)))
    return pd.DataFrame(records)


def target_coverage(target, grains, start, end, available_end):
    records = []
    for grain in grains:
        for horizon in HORIZONS[grain]:
            for origin in origin_grid(start, min(end, available_end), grain):
                s, e = period_bounds(origin.date(), grain, horizon)
                status = "scoreable"
                if pd.Timestamp(e) > min(end, available_end):
                    status = "target_not_complete_within_cutoff"
                elif period_actual(target, s, e) is None:
                    status = "missing_unscoreable_or_mixed_source"
                records.append(dict(origin_year=origin.year, grain=grain, horizon=horizon, status=status))
    return pd.DataFrame(records).groupby(["origin_year", "grain", "horizon", "status"]).size().rename("n").reset_index()


def generate_structural(source, saved, grains, end):
    """Explicit post-hoc replay of the current candidate; no marker or database writes."""
    from .adaptive import AdaptiveConfig, adaptive_corrected
    from .backtest_milk import run_milk_backtest
    from .config import EngineConfig
    from .milk_baseline import MilkConfig
    from .error_diagnostics import load_tag
    prior = load_tag(saved, "milk", RAW_TAG)
    prior = prior[prior.model == "milk_baseline"].copy()
    if prior.empty:
        raise ValueError("The current candidate's raw development history is required")
    cfg = EngineConfig(window_months=12, conception_cut="known", cell_table="day_cell_known",
                       conception_known="recorded", pregnancy_check_lag_days=90)
    parts = [prior]
    origin_grains = sorted({"monthly" if g == "monthly" else "weekly" for g in grains})
    for grain in origin_grains:
        origins = list(origin_grid(CUTOFF, end, grain).date)
        if not origins:
            continue
        print(f"Regenerating POSTHOC structural {grain} forecasts ({len(origins)} origins)", file=sys.stderr, flush=True)
        result = run_milk_backtest(source, grain, cfg, MilkConfig(), origins=origins,
            score_until=end.date(), block="posthoc", jobs=1,
            progress=lambda i, n, o: print(f"structural: {i}/{n}", file=sys.stderr, flush=True) if i % 10 == 0 else None)
        if not result.errors.empty:
            parts.append(result.errors[result.errors.model == "milk_baseline"])
    all_raw = pd.concat(parts, ignore_index=True)
    for col in ("origin", "period_start", "period_end"):
        all_raw[col] = pd.to_datetime(all_raw[col])
    return adaptive_corrected(all_raw, "milk_baseline", cfg=AdaptiveConfig(pooled=False, q30=.1, tau_days=365))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", required=True, choices=["development", "posthoc"])
    parser.add_argument("--start", required=True, type=pd.Timestamp)
    parser.add_argument("--end", required=True, type=pd.Timestamp, help="Exclusive end of scored data")
    parser.add_argument("--grain", choices=["monthly", "weekly", "daily", "both"], default="monthly")
    parser.add_argument("--models", nargs="+", choices=MODELS, default=["ridge", "boosted"])
    parser.add_argument("--structural-tag")
    parser.add_argument("--structural-model", default="milk_baseline_adaptive")
    parser.add_argument("--generate-structural", action="store_true",
                        help="Explicit posthoc replay of the fixed current candidate; can take hours")
    parser.add_argument("--saved", default="logs/pfoi_1_1_clean")
    parser.add_argument("--out", required=True, help="New experiment directory; refuses overwrite")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args(argv)
    if args.start >= args.end or (args.block == "development" and args.end > CUTOFF) or (args.block == "posthoc" and args.start < CUTOFF):
        parser.error("Use development before 2024; posthoc origins start on/after 2024-01-01")
    if args.epochs < 1:
        parser.error("epochs must be positive")
    if "tcn_residual" in args.models and not args.structural_tag:
        parser.error("tcn_residual requires --structural-tag")
    if args.generate_structural and (args.block != "posthoc" or args.structural_tag != ADAPTIVE_TAG
                                    or args.structural_model != "milk_baseline_adaptive"):
        parser.error("Structural regeneration requires posthoc and the fixed current adaptive tag/model")
    if Path(args.out).exists():
        parser.error("Output directory already exists; choose a new experiment name")
    # Import optional dependencies before any real-data access.
    import sklearn
    if any(m.startswith("tcn") for m in args.models):
        import torch
    from .data import SqlHerdSource, DATA_START
    source = SqlHerdSource.from_env()  # USER ONLY; synthetic tests never invoke this loader
    target = source.target_daily(DATA_START, args.end.date())
    panel = source.panel_daily(DATA_START, args.end.date())
    frame, t = daily_frame(target, panel), _target_frame(target)
    cfg = ExperimentConfig(epochs=args.epochs, seed=args.seed)
    grains = ("monthly", "weekly", "daily") if args.grain == "both" else (args.grain,)
    available_end = min(args.end, pd.Timestamp(target.date.max()) + pd.Timedelta(days=1))
    if available_end <= args.start:
        raise ValueError("No target data available after the requested start")
    if args.generate_structural:
        structural = generate_structural(source, args.saved, grains, available_end)
    else:
        structural = read_structural(args.saved, args.structural_tag, args.structural_model, args.end) if args.structural_tag else None
    outputs, coverage = [], []
    print(f"{args.block.upper()} RESEARCH: rolling refits using completed outcomes; no deployment.", flush=True)
    for grain in grains:
        for horizon in HORIZONS[grain]:
            print(f"Running {grain} h{horizon}", file=sys.stderr, flush=True)
            rows, counts = rolling(frame, t, grain, horizon, args.start, args.end, args.models, cfg, structural)
            outputs.append(rows); coverage.extend(counts)
    nonempty = [x for x in outputs if not x.empty]
    if not nonempty:
        raise ValueError("No completed scoreable forecasts in this period")
    errors = pd.concat(nonempty, ignore_index=True)
    errors = add_bands(errors, daily_quality(target, panel))
    quality_counts = errors.groupby(["model", "grain", "horizon", "band"]).size().rename("n").reset_index()
    errors = errors[errors.band.isin(["normal", "degraded"])].copy()
    errors["target_year"], errors["origin_year"] = errors.period_start.dt.year, errors.origin.dt.year
    errors = add_recovery(errors)
    tables = {
        "target_coverage": target_coverage(t, grains, args.start, args.end, available_end),
        "quality": quality_counts,
        "by_target_year": grouped(errors, ["model", "grain", "horizon", "target_year"]),
        "by_origin_year": grouped(errors, ["model", "grain", "horizon", "origin_year"]),
        "recovery": grouped(errors, ["model", "grain", "horizon", "last_break", "since_break"]),
        "matched": matched_reports(errors, args.models),
        "training_coverage": pd.DataFrame(coverage).groupby(["model", "grain", "horizon", "origin_year", "status"]).agg(
            n=("n_train", "size"), min_train=("n_train", "min"), max_train=("n_train", "max")).reset_index(),
    }
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        print(f"\n=== {name} ===\n" + table.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
        table.to_csv(out/f"{name}.csv", index=False)
    metadata = dict(block=args.block, start=str(args.start.date()), end_exclusive=str(args.end.date()),
        last_available_target_date=str(pd.to_datetime(target.date).max().date()), models=args.models,
        config=vars(cfg), sklearn=sklearn.__version__, structural_tag=args.structural_tag,
        structural_model=args.structural_model, grain=args.grain, generated_structural=args.generate_structural,
        evaluation="rolling refit; posthoc is not an untouched holdout",
        numpy=np.__version__, pandas=pd.__version__,
        limitation="Uses current published aggregate history; cannot undo retrospective ETL revisions")
    if any(m.startswith("tcn") for m in args.models):
        metadata["torch"] = torch.__version__
    (out/"experiment.json").write_text(json.dumps(metadata, indent=2))
    print("Saved aggregate reports and configuration only. Missing completed targets are not predictions scored as zero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
