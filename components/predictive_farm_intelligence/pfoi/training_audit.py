"""Aggregate-only training eligibility audit; no model fitting or file writes."""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .forecast_experiments import (
    CUTOFF, ExperimentConfig, KEYS, _target_frame, daily_frame, features,
    origin_grid, period_actual, period_bounds, read_structural,
)
from .periods import HORIZONS

STAGES = ("historical_origins", "completed", "scoreable", "within_window",
          "same_source", "usable_inputs", "structural_available")


def source_labels(values):
    """Do not print arbitrary database text; retain exact comparisons internally.

    Variant buckets are diagnostic only: no normalization changes training eligibility.
    Unknown labels get opaque codes so distinct sources remain distinguishable.
    """
    unique = sorted(set(str(v) for v in values if pd.notna(v)))
    result = {}
    unknown = 0
    for value in unique:
        if value in ("delpro", "shipment"):
            result[value] = value
        elif value.strip().lower() in ("delpro", "shipment"):
            result[value] = value.strip().lower() + "_case_or_space_variant"
        else:
            unknown += 1
            result[value] = f"other_source_{unknown}"
    return result


def catalog(frame, target, grain, horizon, cfg):
    rows = []
    first = frame.index.min()+pd.Timedelta(days=cfg.context)
    for origin in origin_grid(first, frame.index.max()+pd.Timedelta(days=1), grain):
        s, e = period_bounds(origin.date(), grain, horizon)
        act = period_actual(target, s, e)
        usable = features(frame, origin, pd.Timestamp(s), cfg) is not None
        rows.append(dict(origin=origin, period_start=pd.Timestamp(s), period_end=pd.Timestamp(e),
            grain=grain, horizon=horizon, scoreable=act is not None,
            source=act[1] if act is not None else None, usable=usable))
    return pd.DataFrame(rows, columns=KEYS+["scoreable", "source", "usable"])


def audit(target, panel, start, end, grains=("monthly",), cfg=ExperimentConfig(), structural=None):
    # Confine the audit to the requested data cutoff even when synthetic/mock loaders return more.
    target = target[pd.to_datetime(target.date) < end].copy()
    panel = panel[pd.to_datetime(panel.date) < end].copy()
    frame, t = daily_frame(target, panel), _target_frame(target)
    labels = source_labels(frame.target_source)
    def label(value):
        return "missing" if pd.isna(value) else labels[str(value)]
    days = pd.DataFrame(dict(year=frame.index.year,
        source=frame.target_source.map(label), days=1,
        scoreable_days=frame.milk.notna().astype(int),
        missing_cow_count_days=frame.milking.isna().astype(int)))
    inventory = days.groupby(["year", "source"], dropna=False)[
        ["days", "scoreable_days", "missing_cow_count_days"]].sum().reset_index()
    structural_keys = set()
    if structural is not None:
        structural_keys = set(structural.loc[np.isfinite(structural.forecast), KEYS].itertuples(index=False, name=None))
    details, histories = [], []
    for grain in grains:
        for horizon in HORIZONS[grain]:
            c = catalog(frame, t, grain, horizon, cfg)
            c["structural"] = [tuple(row) in structural_keys for row in c[KEYS].itertuples(index=False, name=None)]
            for origin in origin_grid(max(start, frame.index.min()), min(end, frame.index.max()+pd.Timedelta(days=1)), grain):
                s, e = period_bounds(origin.date(), grain, horizon)
                prior_source = frame.loc[frame.index < origin, "target_source"].dropna()
                current = prior_source.iloc[-1] if len(prior_source) else None
                last_valid = frame.loc[(frame.index < origin) & frame.milk.notna(), "target_source"].dropna()
                valid_source = last_valid.iloc[-1] if len(last_valid) else None
                feat = features(frame, origin, pd.Timestamp(s), cfg)
                act = period_actual(t, s, e)
                query_status = "runner_query"
                if pd.Timestamp(e) > min(end, frame.index.max()+pd.Timedelta(days=1)):
                    query_status = "target_incomplete"
                elif act is None:
                    query_status = "target_unscoreable"
                elif feat is None:
                    query_status = "query_inputs_unusable"
                elif origin < frame.index.min()+pd.Timedelta(days=cfg.context):
                    query_status = "before_context_start"
                # Cumulative funnel, algebraically identical to runner's eligibility mask.
                masks = {}
                masks["historical_origins"] = c.origin < origin
                masks["completed"] = masks["historical_origins"] & (c.period_end <= origin)
                masks["scoreable"] = masks["completed"] & c.scoreable
                masks["within_window"] = masks["scoreable"] & (c.origin >= origin-pd.DateOffset(years=cfg.train_years))
                masks["same_source"] = masks["within_window"] & (c.source.eq(current) if current is not None else True)
                masks["usable_inputs"] = masks["same_source"] & c.usable
                masks["structural_available"] = masks["usable_inputs"] & c.structural
                counts = {name: int(mask.sum()) for name, mask in masks.items()}
                key = (origin, pd.Timestamp(s), pd.Timestamp(e), grain, horizon)
                details.append(dict(origin_year=origin.year, grain=grain, horizon=horizon,
                    source=label(current), last_scoreable_source=label(valid_source),
                    query_status=query_status, **counts,
                    below_minimum=int(counts["usable_inputs"] < cfg.min_train),
                    residual_below_minimum=int(counts["structural_available"] < cfg.min_train),
                    query_structural_missing=int(key not in structural_keys),
                    no_source_filter=int(current is None)))
                if query_status == "runner_query":
                    for source, group in c[masks["within_window"]].groupby("source"):
                        histories.append(dict(origin_year=origin.year, grain=grain, horizon=horizon,
                            current_source=label(current), historical_source=label(source),
                            example_exposures=len(group), usable_exposures=int(group.usable.sum()),
                            matched_exposures=int(group.source.eq(current).sum()) if current is not None else len(group)))
    detail = pd.DataFrame(details)
    if detail.empty:
        raise ValueError("No forecast origins within the requested data range")
    keys = ["origin_year", "grain", "horizon", "source"]
    query_counts = detail.groupby(keys+["last_scoreable_source", "query_status"]).size().rename("n_origins").reset_index()
    runners = detail[detail.query_status.eq("runner_query")]
    funnel_rows = []
    for key, g in runners.groupby(keys):
        for stage in STAGES:
            if stage == "structural_available" and structural is None:
                continue
            funnel_rows.append(dict(zip(keys, key), stage=stage, n_origins=len(g),
                                   min_examples=int(g[stage].min()), mean_examples=g[stage].mean(),
                                   max_examples=int(g[stage].max())))
    status = runners.groupby(keys).agg(n_origins=("below_minimum", "size"),
        below_24=("below_minimum", "sum"), residual_below_24=("residual_below_minimum", "sum"),
        query_structural_missing=("query_structural_missing", "sum"),
        no_source_filter=("no_source_filter", "sum")).reset_index()
    if structural is None:
        status = status.drop(columns=["residual_below_24", "query_structural_missing"])
    history = pd.DataFrame(histories)
    if not history.empty:
        history = history.groupby(["origin_year", "grain", "horizon", "current_source", "historical_source"])[
            ["example_exposures", "usable_exposures", "matched_exposures"]].sum().reset_index()
    return {"source_inventory": inventory, "query_coverage": query_counts,
            "eligibility_funnel": pd.DataFrame(funnel_rows), "minimum_training": status,
            "historical_source_mix": history}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=pd.Timestamp, default=pd.Timestamp("2019-01-01"))
    parser.add_argument("--end", type=pd.Timestamp, default=CUTOFF)
    parser.add_argument("--grain", choices=["monthly", "weekly", "daily", "both"], default="monthly")
    parser.add_argument("--structural-tag")
    parser.add_argument("--structural-model", default="milk_baseline_adaptive")
    parser.add_argument("--saved", default="logs/pfoi_1_1_clean")
    args = parser.parse_args(argv)
    if args.start >= args.end or args.end > CUTOFF:
        parser.error("This audit is development-only: start < end <= 2024-01-01")
    from .data import DATA_START, SqlHerdSource
    structural = read_structural(args.saved, args.structural_tag, args.structural_model, args.end) if args.structural_tag else None
    source = SqlHerdSource.from_env()  # user-run only; tests mock this loader
    target = source.target_daily(DATA_START, args.end.date())
    panel = source.panel_daily(DATA_START, args.end.date())
    grains = ("monthly", "weekly", "daily") if args.grain == "both" else (args.grain,)
    tables = audit(target, panel, args.start, args.end, grains=grains, structural=structural)
    print("DEVELOPMENT TRAINING AUDIT: unchanged five-year window and 24-example minimum; no fitting or writes.")
    for name, table in tables.items():
        print(f"\n=== {name} ===")
        print(table.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print("Funnel counts are min/mean/max examples per eligible forecast origin, not independent observations.")
    print("Historical source exposures count the same example again when reused by a later forecast.")
    print("Source matching remains exact; case/space variants are labelled for diagnosis only. Other source text is hidden.")
    print("Compare source with last_scoreable_source to detect the effect of labels on unusable days.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
