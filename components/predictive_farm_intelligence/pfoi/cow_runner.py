"""Terminal runner for the individual-cow yield model (pfoi-cow-yield-1.6.0-dev).

Runs the same protocol as notebook 05 from the command line: recording gap excluded,
75/5/20 chronological split by cow-days, time-series tuning inside training, validation
selection (with recalibrated and blended candidates), frozen final test and an optional
yearly refit. It prints aggregate tables and writes aggregate CSVs only. It never writes
outlook files, ``c1_output`` or any other database table.

The comparison table scores **every** candidate (persistence, Wood, EBM, Ridge, random
forest, MLP, LightGBM, their recalibrated versions and the blend) on the same test rows.
Those test scores are for comparison only: the winners were chosen on validation before
the test was scored, and the comparison never changes them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .cow_accuracy import (COW_MODEL_NAME, COW_MODEL_VERSION, COW_TEST_NAME,
                           EXPERIMENT_VERSION, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE,
                           RECORDING_GAP, TEST_END, add_blend_candidate, apply_blend_spec,
                           blend_weights_table, chronological_split, exclude_recording_gap,
                           expanding_backtest, fit_accuracy_models, score_models,
                           score_performance_windows, select_validation_winners, winner_map)
from .cow_diagnostics import error_breakdown, herd_level_accuracy, noise_floor
from .cow_tuning import build_folds, tune_residual_model

COMPARE_COLUMNS = ["grain", "model", "selected", "periods", "accuracy_pct", "within_10pct",
                   "mae_per_cow_day", "bias_pct", "skill_vs_persistence_pct", "r2"]


@dataclass
class CowRunSettings:
    tag: str = "default"
    exclude_gap: bool = True
    split: tuple[float, float, float] = (0.75, 0.05, 0.20)
    tune: bool = True
    trials_lgbm: int = 30
    trials_rf: int = 8
    include_ebm: bool = True
    min_source_records: int = 100
    yearly_refit: bool = False
    n_jobs: int = -1
    parallel_grains: bool = True
    parallel_folds: int = 3
    seed: int = 17
    window_blocks: int = 0  # >0: also run the equal-record window study with this many blocks
    verbose: bool = True


@dataclass
class CowRunResult:
    settings: CowRunSettings
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)


def _log(settings: CowRunSettings, message: str) -> None:
    if settings.verbose:
        print(f"[cow-yield] {message}", flush=True)


def run_cow_yield(raw: pd.DataFrame, events: dict, settings: CowRunSettings) -> CowRunResult:
    """Run the full protocol on an in-memory frame; returns aggregate tables only."""
    started = time.perf_counter()
    s = settings
    result = CowRunResult(settings=s)
    t = result.tables

    gap = RECORDING_GAP if s.exclude_gap else None
    before = len(raw)
    raw = exclude_recording_gap(raw, gap)
    _log(s, f"recording gap {gap}: removed {before - len(raw):,} of {before:,} cow-days")
    split = chronological_split(raw["date"], s.split)
    t["split"] = split.summary
    _log(s, f"split train<= {split.train_end}, validation<= {split.validation_end}, "
            f"test from {split.test_start}")

    lgbm_params, rf_params = {}, {}
    if s.tune:
        folds = build_folds(raw, split.train_end, events=events,
                            min_source_records=s.min_source_records, verbose=s.verbose)
        lgbm_params, t["tuning_lgbm"] = tune_residual_model(
            folds, "lgbm", n_trials=s.trials_lgbm, seed=s.seed, n_jobs=s.n_jobs,
            verbose=s.verbose)
        if s.trials_rf > 0:
            rf_params, t["tuning_rf"] = tune_residual_model(
                folds, "rf", n_trials=s.trials_rf, seed=s.seed, n_jobs=s.n_jobs,
                verbose=s.verbose)
        del folds
    t["settings"] = pd.DataFrame([
        {"setting": "lgbm", "value": str(lgbm_params or "default")},
        {"setting": "random_forest", "value": str(rf_params or "default")},
    ])
    common = dict(include_ebm=s.include_ebm,
                  lgbm_kwargs={**lgbm_params, "random_state": s.seed}, rf_kwargs=rf_params,
                  ebm_kwargs={"outer_bags": 8, "interactions": 3, "random_state": s.seed},
                  evaluation_mode="walk_forward", events=events,
                  min_source_records=s.min_source_records, n_jobs=s.n_jobs,
                  parallel_grains=s.parallel_grains, verbose=s.verbose)

    _log(s, "validation fit")
    vm = fit_accuracy_models(raw, train_end=split.train_end,
                             validation_end=split.validation_end, **common)
    vmet, _ = score_models(vm, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE, blocks=("validation",))
    best = (vmet[vmet["model"] != "persistence_last_yield"].sort_values("wape_pct")
            .groupby("grain")["model"].first().to_dict())
    blend = add_blend_candidate(vm, best, block="validation")
    t["blend_weights"] = blend_weights_table(blend)
    vmet, _ = score_models(vm, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE, blocks=("validation",))
    winners = select_validation_winners(vmet, metric="wape_pct")
    selected = winner_map(winners)
    t["validation_all"] = vmet.sort_values(["grain", "wape_pct"]).reset_index(drop=True)
    t["winners"] = winners

    _log(s, "final refit (training + validation), frozen weights for the test")
    fm = fit_accuracy_models(raw, train_end=split.validation_end,
                             validation_end=split.validation_end, **common)
    apply_blend_spec(fm, blend)
    test_all, perf_all = score_models(fm, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE,
                                      blocks=("test",))
    test_all["selected"] = [g in selected.get(m, set())
                            for m, g in zip(test_all["model"], test_all["grain"])]
    t["test_all_candidates"] = test_all.sort_values(["grain", "wape_pct"]).reset_index(drop=True)
    windows = {"test_all": (split.test_start, TEST_END)}
    windows.update({f"test_{y}": (max(date(y, 1, 1), split.test_start),
                                  min(date(y, 12, 31), TEST_END))
                    for y in range(split.test_start.year, TEST_END.year + 1)})
    sel_perf = {m: {g: f for g, f in grains.items() if g in selected.get(m, set())}
                for m, grains in perf_all.items() if m in selected}
    t["test_selected_by_year"] = score_performance_windows(sel_perf, windows)
    t["herd_level"] = herd_level_accuracy(sel_perf)

    daily_model = next(m for m, g in selected.items() if "daily" in g)
    for label, models, block in (("validation", vm, "validation"), ("test", fm, "test")):
        t[f"breakdown_{label}"] = error_breakdown(
            models.frame, models.predictions[daily_model], block=block,
            naive=models.predictions["persistence_last_yield"])
    t["noise_floor"] = noise_floor(fm.frame)

    if s.yearly_refit:
        _log(s, "yearly expanding-window refit")
        bt, folds_tbl = expanding_backtest(
            raw, selected, test_start=split.test_start, events=events,
            min_source_records=s.min_source_records, include_ebm=False,
            lgbm_kwargs=common["lgbm_kwargs"], rf_kwargs=rf_params, n_jobs=s.n_jobs,
            parallel_folds=s.parallel_folds, blend_spec=blend, verbose=s.verbose)
        _, bperf = score_models(bt, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE, blocks=("test",),
                                selected=selected)
        t["yearly_refit_folds"] = folds_tbl
        t["yearly_refit_by_year"] = score_performance_windows(bperf, windows)
    if s.window_blocks > 1:
        _log(s, f"window study: {s.window_blocks} equal-record blocks")
        wm, wc = rolling_window_study(
            raw, events, lgbm_kwargs=common["lgbm_kwargs"], rf_kwargs=rf_params,
            include_ebm=False, min_source_records=s.min_source_records, n_jobs=s.n_jobs,
            parallel_grains=s.parallel_grains, exclude_gap=False, blocks="equal",
            n_blocks=s.window_blocks, verbose=s.verbose)
        t["window_study_metrics"], t["window_study_conditions"] = wm, wc
    t["run_info"] = pd.DataFrame([{
        "model_name": COW_MODEL_NAME, "model_version": COW_MODEL_VERSION,
        "test_name": COW_TEST_NAME, "experiment": EXPERIMENT_VERSION, "tag": s.tag,
        "seconds": round(time.perf_counter() - started, 1),
        "train_end": split.train_end, "validation_end": split.validation_end,
        "test_start": split.test_start,
    }])
    for name, table in t.items():
        assert not ({"animal", "cow_id", "animal_key"} & set(table.columns)), name
    return result


def comparison_table(result: CowRunResult) -> pd.DataFrame:
    """Every candidate on the same test rows; ``selected`` marks the validation winner."""
    t = result.tables["test_all_candidates"]
    return t[[c for c in COMPARE_COLUMNS if c in t]].sort_values(
        ["grain", "accuracy_pct"], ascending=[True, False]).reset_index(drop=True)


def write_cow_run(result: CowRunResult, out: Path) -> Path:
    folder = Path(out) / COW_MODEL_NAME / COW_TEST_NAME / result.settings.tag
    folder.mkdir(parents=True, exist_ok=True)
    for name, table in result.tables.items():
        table.to_csv(folder / f"{name}.csv", index=False)
    return folder


def print_cow_run(result: CowRunResult, folder: Path) -> None:
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)
    info = result.tables["run_info"].iloc[0]
    print(f"\n{info['model_name']} ({info['model_version']}) | test {info['test_name']} | "
          f"tag {info['tag']} | {info['seconds']:.0f}s")
    sections = [("split (cow-days)", "split"), ("tuned settings", "settings"),
                ("validation winners", "winners"),
                ("COMPARISON: every candidate on the same test rows "
                 "(selected = chosen on validation; others for comparison only)", None),
                ("selected models by test year", "test_selected_by_year"),
                ("herd mean yield per recorded cow-day (errors can cancel)", "herd_level"),
                ("noise floor (records 1-3 days apart, same lactation)", "noise_floor"),
                ("yearly refit by test year", "yearly_refit_by_year"),
                ("window study: test-block conditions", "window_study_conditions"),
                ("window study: accuracy by window", "window_study_accuracy")]
    for title, key in sections:
        if key is None:
            table = comparison_table(result)
        elif key == "window_study_accuracy" and "window_study_metrics" in result.tables:
            table = window_summary(result.tables["window_study_metrics"]).reset_index()
        elif key in result.tables:
            table = result.tables[key]
        else:
            continue
        if key == "winners":
            table = table[["grain", "model", "accuracy_pct", "within_10pct", "bias_pct",
                           "skill_vs_persistence_pct"]]
        if key in {"test_selected_by_year", "yearly_refit_by_year"}:
            table = table[["block", "grain", "model", "status", "periods", "accuracy_pct",
                           "within_10pct", "bias_pct", "skill_vs_persistence_pct"]]
        print(f"\n=== {title} ===")
        print(table.round(2).to_string(index=False))
    print(f"\nAggregate CSVs in {folder}/ (no outlook files, nothing written to the database).")


def compare_cow_runs(out: Path, tags: list[str]) -> pd.DataFrame:
    """Side-by-side selected-model test accuracy of earlier ``cow-yield`` runs by tag."""
    base = Path(out) / COW_MODEL_NAME / COW_TEST_NAME
    rows = []
    for tag in tags:
        path = base / tag / "test_all_candidates.csv"
        if not path.exists():
            raise FileNotFoundError(f"no cow-yield run with tag {tag!r} at {path}")
        t = pd.read_csv(path)
        for row in t[t["selected"]].itertuples(index=False):
            rows.append({"tag": tag, "grain": row.grain, "model": row.model,
                         "accuracy_pct": row.accuracy_pct, "within_10pct": row.within_10pct,
                         "bias_pct": row.bias_pct,
                         "skill_vs_persistence_pct": row.skill_vs_persistence_pct})
    out_t = pd.DataFrame(rows)
    return out_t.pivot_table(index="grain", columns="tag",
                             values=["accuracy_pct", "within_10pct", "bias_pct"]).round(2)


def synthetic_inputs(n_cows: int = 40, seed: int = 17) -> tuple[pd.DataFrame, dict]:
    """SYNTHETIC fictional cow-days and events for a quick terminal smoke run."""
    from ..tests.synthetic_cows import synthetic_cowdays
    from .cow_events import synthetic_events

    s = synthetic_cowdays(n_cows=n_cows, seed=seed)
    s = s[s["date"] <= pd.Timestamp(TEST_END)].copy()
    rng = np.random.default_rng(seed)
    s["litres"] = s["true_litres"] * np.exp(rng.normal(0.0, 0.08, len(s)))
    s = s[s["litres"] <= 18.0].copy()
    ids = {a: i + 1 for i, a in enumerate(sorted(s["animal"].unique()))}
    raw = pd.DataFrame({
        "cow_id": s["animal"].map(ids), "date": s["date"], "litres": s["litres"],
        "dim": s["dim"], "parity_group": s["parity_group"], "age_days": 730 + s["dim"],
        "milkings": 2.0, "conductivity": np.nan, "milking_duration_sec": np.nan,
        "avg_blood": np.nan, "avg_cell_count": np.nan, "avg_bcs": np.nan,
        "avg_weight": np.nan, "avg_rectal_temp": np.nan, "thi_mean": 68.0,
    })
    health, treatments, availability = synthetic_events(raw[["cow_id", "date"]], seed=seed)
    return raw, {"health": health, "treatments": treatments, "availability": availability}


def two_year_windows(dates: pd.Series, block_years: int = 2) -> list[dict]:
    """Consecutive 2-calendar-year blocks of the clean data; each block tests the next.

    Years with any clean cow-day are grouped in order into blocks of ``block_years``
    (a year directly after a recording gap starts a new block, so 2025-11 .. 2026 forms
    the last block). Window *i* trains on block *i* and tests on block *i+1*.
    """
    years = sorted(pd.to_datetime(dates).dt.year.unique())
    blocks, current = [], []
    for y in years:
        if current and (y != current[-1] + 1 or len(current) == block_years):
            blocks.append(current)
            current = []
        current.append(int(y))
    if current:
        blocks.append(current)
    # A lone trailing year after a gap (e.g. 2025 with 2 months) joins the next block.
    merged = []
    for b in blocks:
        if merged and len(merged[-1]) == 1 and b[0] == merged[-1][-1] + 1:
            merged[-1] = merged[-1] + b
        else:
            merged.append(b)
    return [{"window": f"train {a[0]}-{a[-1]} / test {b[0]}-{b[-1]}",
             "train_start": date(a[0], 1, 1), "train_end": date(a[-1], 12, 31),
             "test_start": date(b[0], 1, 1), "test_end": date(b[-1], 12, 31)}
            for a, b in zip(merged, merged[1:])]


def equal_record_windows(dates: pd.Series, n_blocks: int = 5) -> list[dict]:
    """Cut the clean cow-days into ``n_blocks`` chronological blocks of equal size.

    Every block holds (as nearly as whole days allow) the same number of cow-days, so
    a block starting late in a year (data begin in late 2015) is not smaller than the
    others. Window *i* trains on block *i* and tests on block *i+1*.
    """
    d = pd.to_datetime(pd.Series(dates)).dt.normalize()
    per_day = d.value_counts().sort_index()
    cum = (per_day.cumsum() / per_day.sum()).to_numpy()
    days = per_day.index
    ends = [days[min(int(np.searchsorted(cum, k / n_blocks, "left")), len(days) - 1)]
            for k in range(1, n_blocks)] + [days[-1]]
    starts = [days[0]] + [days[days > e][0] for e in ends[:-1]]
    blocks = []
    for i, (a, b) in enumerate(zip(starts, ends), start=1):
        blocks.append({"block": i, "start": a.date(), "end": b.date(),
                       "cow_days": int(((d >= a) & (d <= b)).sum())})
    return [{"window": f"train B{x['block']} ({x['start']}..{x['end']}) / "
                       f"test B{y['block']} ({y['start']}..{y['end']})",
             "train_start": x["start"], "train_end": x["end"], "train_cow_days": x["cow_days"],
             "test_start": y["start"], "test_end": y["end"], "test_cow_days": y["cow_days"]}
            for x, y in zip(blocks, blocks[1:])]


def window_conditions(frame: pd.DataFrame) -> dict:
    """Aggregate description of a window's test rows (what 'condition' it represents)."""
    q = frame[frame["period"] == "test"]
    if q.empty:
        return {"test_cow_days": 0}
    months = max(q["date"].dt.to_period("M").nunique(), 1)
    out = {
        "test_cow_days": len(q), "test_cows": q["animal"].nunique(),
        "test_mean_litres": q["litres"].mean(),
        "records_per_cow_per_month": len(q) / q["animal"].nunique() / months,
        "scoreable_cow_days": int(q["score_eligible"].sum()),
    }
    for family in ("health", "treatment", "milkings_prev", "conductivity_prev"):
        col = f"{family}_status"
        if col in q:
            out[f"{family}_available_pct"] = 100 * float((q[col] == "available").mean())
    return out


def rolling_window_study(raw: pd.DataFrame, events: dict | None, *,
                         lgbm_kwargs: dict | None = None, rf_kwargs: dict | None = None,
                         include_ebm: bool = False, min_source_records: int = 100,
                         n_jobs: int = -1, parallel_grains: bool = True,
                         exclude_gap: bool = True, blocks: str = "equal",
                         n_blocks: int = 5, fit_fn=None, fit_kwargs: dict | None = None,
                         expanding: bool = True, verbose: bool = False
                         ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on one block, test on the next, for every consecutive pair of clean blocks.

    ``blocks="equal"`` (default) cuts the clean cow-days into ``n_blocks`` equal-sized
    chronological blocks; ``blocks="two_years"`` uses 2-calendar-year blocks.
    ``expanding=True`` (default) trains each window on *all* blocks before its test block
    (window k trains on blocks 1..k); ``False`` trains on the single preceding block.

    Each window uses only its own cow-days (history before the window is not available
    to it), fits every candidate on its training block and scores all of them,
    walk-forward, on its test block. No selection happens here: the table shows how each
    model behaves under different conditions (years, recording density, health/treatment
    availability, yield level). Returns (metrics per window/grain/model, conditions).
    """
    raw = exclude_recording_gap(raw, RECORDING_GAP if exclude_gap else None)
    dates = pd.to_datetime(raw["date"])
    metrics, conditions = [], []
    windows = (equal_record_windows(dates, n_blocks) if blocks == "equal"
               else two_year_windows(dates))
    first_start = windows[0]["train_start"] if windows else None
    for w in windows:
        if expanding and w["train_start"] != first_start:
            test_part = w["window"].split("/ test ", 1)[1]
            if w["window"].startswith("train B"):  # equal-record blocks, e.g. "B3"
                k = w["window"].split(" ", 2)[1]
                label = f"train B1..{k} ({first_start}..{w['train_end']}) / test {test_part}"
            else:                                   # calendar-year blocks
                label = f"train {first_start.year}-{w['train_end'].year} / test {test_part}"
            w = {**w, "train_start": first_start, "window": label}
        t0 = time.perf_counter()
        sub = raw[(dates >= pd.Timestamp(w["train_start"]))
                  & (dates <= pd.Timestamp(w["test_end"]))]
        if verbose:
            print(f"[cow-windows] {w['window']}: {len(sub):,} cow-days", flush=True)
        if fit_fn is None:  # LightGBM / forest / MLP pipeline of notebook 05
            models = fit_accuracy_models(
                sub, include_ebm=include_ebm, lgbm_kwargs=lgbm_kwargs, rf_kwargs=rf_kwargs,
                train_end=w["train_end"], validation_end=w["train_end"],
                evaluation_mode="walk_forward", events=events,
                min_source_records=min_source_records, n_jobs=n_jobs,
                parallel_grains=parallel_grains, verbose=False)
        else:  # e.g. cow_torch.fit_torch_models (notebook 06)
            models = fit_fn(sub, train_end=w["train_end"], validation_end=w["train_end"],
                            events=events, min_source_records=min_source_records,
                            **(fit_kwargs or {}))
        m, _ = score_models(models, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE, blocks=("test",))
        metrics.append(m.assign(window=w["window"]))
        conditions.append({"window": w["window"],
                           "train_cow_days": int((models.frame["period"] == "train").sum()),
                           **window_conditions(models.frame),
                           "seconds": round(time.perf_counter() - t0, 1)})
        if verbose:
            print(f"[cow-windows]   done in {conditions[-1]['seconds']:.0f}s", flush=True)
    table = pd.concat(metrics, ignore_index=True) if metrics else pd.DataFrame()
    cond = pd.DataFrame(conditions)
    for t in (table, cond):
        assert not ({"animal", "cow_id", "animal_key"} & set(t.columns))
    return table, cond


def window_summary(table: pd.DataFrame, metric: str = "accuracy_pct") -> pd.DataFrame:
    """Models as rows, windows as columns, one table per grain (``metric`` values)."""
    return table.pivot_table(index=["grain", "model"], columns="window", values=metric).round(2)
