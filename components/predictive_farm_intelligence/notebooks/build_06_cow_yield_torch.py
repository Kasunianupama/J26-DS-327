"""Write ``06_cow_yield_torch.ipynb`` with empty outputs.

PyTorch-only version of notebook 05 on the Apple GPU. Agents may run it only with the
synthetic setting; the user runs the real-data setting locally. Run it in its own kernel:
on macOS PyTorch crashes in a process where LightGBM has trained.
"""
from __future__ import annotations

import json
from pathlib import Path

CELLS: list[dict] = []


def md(source: str) -> None:
    CELLS.append({"cell_type": "markdown", "id": f"md-{len(CELLS):03d}", "metadata": {},
                  "source": [line + "\n" for line in source.strip().splitlines()]})


def code(source: str) -> None:
    CELLS.append({"cell_type": "code", "id": f"code-{len(CELLS):03d}",
                  "execution_count": None, "metadata": {},
                  "outputs": [], "source": [line + "\n" for line in source.strip().splitlines()]})


md(r"""
# Farm X: individual-cow milk yield with PyTorch on the GPU (pfoi-cow-yield-torch-1.6.0-dev)

The same experiment as notebook 05, with every learned model in PyTorch so it can run on
the Apple GPU (MPS):

- **same data and protocol:** clean `core.animal_daily` cow-days in (0, 18] L; the May
  2022 – October 2025 recording gap excluded; 75 / 5 / 20 chronological split by
  cow-days; walk-forward daily, weekly and monthly forecasts with origin-safe features
  (yield history per lactation, health episodes, treatments split into individual vs
  herd campaigns, lagged sensors and THI, recent herd and cow level);
- **models:** persistence and the Wood mixed curve as baselines, and two PyTorch
  residual networks on top of Wood (`torch_mlp_small` 64-32, `torch_mlp_large`, tuned),
  each also recalibrated (`*_recal`), plus a validation-fitted blend with persistence;
- **tuning:** random search over network settings on expanding folds inside the training
  block only.

**Version 3 (torch v3) adds, learning from the v1/v2 runs:**

- a **per-cow Kalman model** (`kalman_state`): each record = curve x cow level x noise;
  the noise is estimated from the data, so a fresh record counts more than an old one,
  and an old one fades back to the curve. Its level and uncertainty are also inputs to
  every network;
- **seed ensembles** (`ENSEMBLE` networks per architecture, averaged);
- a **GRU sequence model** (`torch_gru`) over each cow's last `SEQ_LEN` same-lactation
  records (yield vs curve, days to the predicted day, days in milk);
- a **quantile network** (`torch_q50`) with a 10–90% range per forecast and its coverage;
- **cleaner training targets:** records under 60% of the median of the cow's neighbouring
  records (likely partial, e.g. one of two milkings; 20–26% of 2017–2021 records, 9% in
  2026) are left out of *training* only; every record is still forecast and scored;
- networks train up to 250 epochs (at least 50), stopping only on a sustained 0.5-point
  accuracy drop over 15 epochs; dropout 0.3.

Lesson from v2: the monthly test holds only 4 complete months, so its scores swing by
several points; weekly and daily are the stable read-outs.

**Run this notebook in its own kernel.** On macOS PyTorch crashes in a process where
LightGBM has trained; the notebook never imports LightGBM and stops early if it finds it.
Everything displayed is aggregate; no cow identifier or row is shown or saved.
""")

code(r"""
USE_SYNTHETIC = True       # Set False yourself for the read-only Farm X run.
INPUT_SCHEMA = "model_input2"
MIN_COWS_PER_DAY = 10
MIN_PERIOD_COVERAGE = 1.00
MIN_SOURCE_RECORDS_PER_YEAR = 100
DATA_SCOPE = "clean"       # "clean": drop May 2022 - Oct 2025 | "through_mid2023": drop Jul 2023 - Oct 2025
SELECTION_BLOCKS = 4       # expanding windows on pre-test data, pooled with validation
SPLIT = (0.75, 0.05, 0.20)
DEVICE = "auto"            # "auto" = Apple GPU (MPS) if present, else CPU
TUNE = True
N_TRIALS = 12
# Network training (applied to tuning and every fit). Training stops only when accuracy
# on the held-out weeks stays more than STOP_DROP_PP points below its best for
# STOP_PATIENCE epochs in a row, and never before MIN_EPOCHS. Best weights are kept.
MAX_EPOCHS = 250
MIN_EPOCHS = 50
STOP_DROP_PP = 0.5         # accuracy drop (percentage points) that counts as "worse"
STOP_PATIENCE = 15
DROPOUT = 0.3              # default; tuning searches 0.2 - 0.5
# Models (torch v3). Fewer seeds / no GRU = faster.
ENSEMBLE = 3               # networks per architecture, averaged
USE_KALMAN = True
USE_GRU = True
GRU_SEEDS = 1
SEQ_LEN = 16               # records per cow in the GRU sequence
USE_QUANTILE = True
ROBUST_TRAINING = True     # leave likely partial records out of training (not scoring)
MODEL_OPTIONS = {"ensemble": ENSEMBLE, "use_kalman": USE_KALMAN, "use_gru": USE_GRU,
                 "gru_seeds": GRU_SEEDS, "seq_len": SEQ_LEN, "use_quantile": USE_QUANTILE,
                 "robust_training": ROBUST_TRAINING}
# Windows refit everything several times, so they use lighter settings: one seed for the
# selection windows (same candidates, so they can be pooled), and one seed without the
# GRU for the report-only windows of section 6.
SELECTION_OPTIONS = {**MODEL_OPTIONS, "ensemble": 1}
REPORT_WINDOW_OPTIONS = {**MODEL_OPTIONS, "ensemble": 1, "use_gru": False}
RUN_WINDOW_STUDY = True
WINDOW_BLOCKS = 5
VERBOSE = True
SEED = 17

import os
import sys
import time
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

COMPONENT_DIR = Path.cwd().resolve()
if COMPONENT_DIR.name == "notebooks":
    COMPONENT_DIR = COMPONENT_DIR.parent
REPO_ROOT = COMPONENT_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from components.predictive_farm_intelligence.pfoi.cow_torch import (
    TORCH_MODEL_NAME, assert_torch_safe_process, fit_torch_models, interval_coverage,
    resolve_device, tune_torch,
)
assert_torch_safe_process()
from components.predictive_farm_intelligence.pfoi.cow_accuracy import (
    COW_MODEL_NAME, DATA_SCOPES, SCOPE_TEST_NAMES, TEST_END, TRAIN_START, LEVEL_FEATURES,
    pool_metrics,
    cow_accuracy_sql, feature_catalogue, plot_model_performance, prepare_accuracy_frame,
    safe_column_profile, safe_input_summary,
    add_blend_candidate, apply_blend_spec, blend_weights_table, chronological_split,
    exclude_recording_gap, load_accuracy_inputs, recording_gap_check, score_models,
    score_performance_windows, select_validation_winners, winner_map,
)
from components.predictive_farm_intelligence.pfoi.cow_diagnostics import (
    cleaning_contract_checks, error_breakdown, herd_level_accuracy, noise_floor,
    period_cleaning_checks, record_consistency, sensor_scale_by_year,
)
from components.predictive_farm_intelligence.pfoi.cow_events import (
    availability_by_year, treatment_campaign_summary,
)
from components.predictive_farm_intelligence.pfoi.cow_runner import (
    equal_record_windows, rolling_window_study, window_summary,
)
from components.predictive_farm_intelligence.pfoi.cow_tuning import build_folds

COW_TEST_NAME = SCOPE_TEST_NAMES[DATA_SCOPE]
GAP = DATA_SCOPES[DATA_SCOPE]
RUN_DIR = COMPONENT_DIR / "logs" / "pfoi_mi2" / TORCH_MODEL_NAME / COW_TEST_NAME
if USE_SYNTHETIC:
    RUN_DIR = RUN_DIR / "synthetic_only"
V1_DIR = RUN_DIR                     # first torch run (12:35 on 2026-10-22) wrote here
V2_DIR = RUN_DIR / "torch_v2"        # recal base, pooled selection (12:57)
OUT_DIR = RUN_DIR / "torch_v3"       # this version: Kalman, ensembles, GRU, quantiles
OUT_DIR.mkdir(parents=True, exist_ok=True)
CHART_DIR = OUT_DIR / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
NOTEBOOK_START = time.perf_counter()
print("Model:", TORCH_MODEL_NAME, "| Test:", COW_TEST_NAME, "| Device:", resolve_device(DEVICE))
print("Mode:", "SYNTHETIC FICTIONAL DATA" if USE_SYNTHETIC else "FARM X READ-ONLY CORE")
""")

md(r"""
## 1. Load, exclude the recording gap and split 75 / 5 / 20
""")

code(r"""
if USE_SYNTHETIC:
    from components.predictive_farm_intelligence.pfoi.cow_runner import synthetic_inputs
    raw, EVENTS = synthetic_inputs(n_cows=80, seed=SEED)
else:
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    os.environ["PFOI_MODEL_INPUT_SCHEMA"] = INPUT_SCHEMA
    source = SqlHerdSource.from_env()
    inputs = load_accuracy_inputs(source, TRAIN_START, TEST_END)
    raw = inputs.pop("raw")
    EVENTS = inputs
print("Eligible input rows:", f"{len(raw):,}")
print("Health episodes:", f"{len(EVENTS['health']):,}", "| treatment records:",
      f"{len(EVENTS['treatments']):,}")
display(treatment_campaign_summary(EVENTS["treatments"]))
""")

md(r"""
### Data-cleaning contract checks (same as notebook 05)

Executable checks, not descriptions: the target SQL must read only `core.animal_daily`
and exclude placeholder, unlinked, bad-date and invalid records; the loaded frame must
hold yields in (0, 18] L, one row per cow and date, dates inside the experiment and no
source keys or forbidden milk fields. The notebook stops if any check fails.
""")

code(r"""
cleaning_checks = cleaning_contract_checks(raw, cow_accuracy_sql("core"), TRAIN_START, TEST_END)
display(cleaning_checks[["status", "check", "aggregate_evidence"]])
assert cleaning_checks["passed"].all(), "Data-cleaning contract failed; do not fit models"
litres = pd.to_numeric(raw["litres"], errors="coerce")
print(f"Clean target range (aggregate): min={litres.min():.3f} L, max={litres.max():.3f} L")
display(safe_column_profile(raw))
display(sensor_scale_by_year(raw))
""")

md(r"""
### Recording gap and the 75 / 5 / 20 split
""")

code(r"""
display(recording_gap_check(raw))
print(f"Data scope {DATA_SCOPE!r}: removing {GAP[0]} .. {GAP[1]}")
raw = exclude_recording_gap(raw, GAP)
split = chronological_split(raw["date"], SPLIT)
SELECTION_TRAIN_END, VALID_END = split.train_end, split.validation_end
FINAL_TRAIN_END, TEST_START = VALID_END, split.test_start
VALID_START = SELECTION_TRAIN_END + pd.Timedelta(days=1).to_pytimedelta()
display(split.summary)
""")

md(r"""
### Features, availability by year and record consistency

The feature catalogue lists every origin-safe feature the networks use; the availability
table shows, per family and year, whether its source was recorded (`available`), recorded
but missing for the cow (`missing`) or not recorded at all (`unavailable`).

**Record consistency** asks whether the large day-to-day changes in a cow's recorded
yield are real. Each record is compared with the median of the cow's previous 5 records
in the same lactation. A real cow rarely gives under 60% or over 150% of that; a large
share in those bands points to partial (e.g. one of two milkings) or mis-assigned
records. Yield by recorded milkings and by weekday are shown alongside.
""")

code(r"""
preview = prepare_accuracy_frame(raw, train_end=FINAL_TRAIN_END, validation_end=FINAL_TRAIN_END,
                                 evaluation_mode="walk_forward", events=EVENTS,
                                 min_source_records=MIN_SOURCE_RECORDS_PER_YEAR)
event_features = preview.attrs["event_features"]
print("Sensor columns dropped (empty, <1% filled or constant):",
      preview.attrs.get("dropped_sensors", []))
display(feature_catalogue(list(event_features) + list(LEVEL_FEATURES)))
display(availability_by_year(preview).pivot_table(index="year", columns="family",
                                                  values="status", aggfunc="first"))
consistency = record_consistency(preview)
for name, table in consistency.items():
    print(f"Record consistency: {name}")
    display(table)
    table.to_csv(OUT_DIR / f"diagnostics_record_consistency_{name}.csv", index=False)
del preview
""")

md(r"""
## 2. Time-series tuning of the network (training block only)

Trial 0 is the default setting. Folds train up to the 60th–90th percentile of training
cow-days and score the next slice, walk-forward. Validation and test are never used.
""")

code(r"""
TRAINING = {"max_epochs": MAX_EPOCHS, "min_epochs": MIN_EPOCHS, "stop_drop_pp": STOP_DROP_PP,
            "stop_patience": STOP_PATIENCE, "dropout": DROPOUT}
TORCH_PARAMS = dict(TRAINING)
if TUNE:
    t0 = time.perf_counter()
    folds = build_folds(raw, SELECTION_TRAIN_END, events=EVENTS,
                        min_source_records=MIN_SOURCE_RECORDS_PER_YEAR, verbose=VERBOSE)
    TORCH_PARAMS, torch_trials = tune_torch(folds, n_trials=N_TRIALS, device=DEVICE,
                                            seed=SEED, verbose=VERBOSE, fixed=TRAINING)
    del folds
    display(torch_trials)
    torch_trials.to_csv(OUT_DIR / "tuning_torch_trials.csv", index=False)
    print(f"Tuning took {time.perf_counter() - t0:,.0f}s")
TORCH_PARAMS = {**TORCH_PARAMS, **{k: v for k, v in TRAINING.items() if k != "dropout"}}
print("Network settings:", TORCH_PARAMS)
""")

md(r"""
## 3. Validation fit, recalibration, blend and winner selection

Every network corrects the walk-forward recalibrated Wood curve. Each candidate exists
raw, herd-recalibrated (`_recal`) and recalibrated per parity x days-in-milk group
(`_grp`).

**Selection is pooled** so it no longer rests on the small validation block alone:
the pre-test data (training + validation) are cut into `SELECTION_BLOCKS` equal blocks
and the networks are refitted on expanding windows (blocks 1..k, test block k+1). Those
out-of-sample scores are pooled with the validation scores, cow-period errors weighted
by litres, and the best single candidate per grain wins. No test row is involved.

**Blend:** the winner is then mixed with persistence per days-since-record band. The
weights are fitted on validation *and* on out-of-fold training predictions (training
holds many records only 1–3 days apart). The blend replaces the winner only if its
cross-fitted validation score is better.
""")

code(r"""
t0 = time.perf_counter()
validation_models = fit_torch_models(raw, SELECTION_TRAIN_END, VALID_END, events=EVENTS,
                                     min_source_records=MIN_SOURCE_RECORDS_PER_YEAR,
                                     params=dict(TORCH_PARAMS), device=DEVICE, seed=SEED,
                                     options=MODEL_OPTIONS, verbose=VERBOSE)
if "kalman_state" in validation_models.fitted:
    print("Kalman parameters:", validation_models.fitted["kalman_state"])
vmet, _ = score_models(validation_models, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE,
                       blocks=("validation",))
for name, info in validation_models.fitted.items():
    if name.startswith("torch"):
        print(f"daily {name}: best epoch {info['best_epoch']} of {info['epochs']} (first seed)")

# Pooled selection: validation + expanding windows on pre-test data only.
pre_test = raw[pd.to_datetime(raw["date"]) <= pd.Timestamp(VALID_END)]
sel_windows, sel_conditions = rolling_window_study(
    pre_test, EVENTS, min_source_records=MIN_SOURCE_RECORDS_PER_YEAR, exclude_gap=False,
    n_blocks=SELECTION_BLOCKS, expanding=True, fit_fn=fit_torch_models,
    fit_kwargs={"params": dict(TORCH_PARAMS), "device": DEVICE, "seed": SEED, "oof": False,
                "options": SELECTION_OPTIONS},
    verbose=VERBOSE)
display(sel_conditions)
pooled = pool_metrics([vmet] + [g for _, g in sel_windows.groupby("window")], "pooled_selection")
display(pooled)
pooled_winner = (pooled[pooled["model"] != "persistence_last_yield"]
                 .groupby("grain").first()["model"].to_dict())
print("Pooled winners (single models):", pooled_winner)

BLEND_SPEC = add_blend_candidate(validation_models, pooled_winner, block="validation",
                                 use_training_oof=True)
display(blend_weights_table(BLEND_SPEC))
validation_metrics, validation_performance = score_models(
    validation_models, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE, blocks=("validation",))
display(safe_input_summary(validation_models.frame))
validation_metrics = validation_metrics.sort_values(["grain", "wape_pct"]).reset_index(drop=True)
rows = []
for grain, base_name in pooled_winner.items():
    v = validation_metrics[validation_metrics["grain"] == grain].set_index("model")
    choice = "blend" if v.loc["blend", "wape_pct"] < v.loc[base_name, "wape_pct"] else base_name
    rows.append(v.loc[choice].to_dict() | {"grain": grain, "model": choice,
                                           "pooled_base": base_name})
winners = pd.DataFrame(rows)
display(validation_metrics)
display(winners[["grain", "model", "pooled_base", "accuracy_pct", "within_10pct", "bias_pct",
                 "skill_vs_persistence_pct"]])
validation_metrics.to_csv(OUT_DIR / "validation_metrics_all_candidates.csv", index=False)
pooled.to_csv(OUT_DIR / "pooled_selection.csv", index=False)
winners.to_csv(OUT_DIR / "winners.csv", index=False)
print(f"Validation stage took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 4. Final refit and untouched test

Every candidate is scored on the same test rows for comparison; `selected` marks the
validation winner (the comparison never changes it).
""")

code(r"""
t0 = time.perf_counter()
final_models = fit_torch_models(raw, FINAL_TRAIN_END, FINAL_TRAIN_END, events=EVENTS,
                                min_source_records=MIN_SOURCE_RECORDS_PER_YEAR,
                                params=dict(TORCH_PARAMS), device=DEVICE, seed=SEED,
                                options=MODEL_OPTIONS, verbose=VERBOSE)
apply_blend_spec(final_models, BLEND_SPEC)
selected = winner_map(winners)
test_all, perf_all = score_models(final_models, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE,
                                  blocks=("test",))
test_all["selected"] = [g in selected.get(m, set())
                        for m, g in zip(test_all["model"], test_all["grain"])]
COMPARE = ["grain", "model", "selected", "periods", "accuracy_pct", "within_10pct",
           "mae_per_cow_day", "bias_pct", "skill_vs_persistence_pct", "r2"]
display(test_all[COMPARE].sort_values(["grain", "accuracy_pct"], ascending=[True, False]))
TEST_WINDOWS = {"test_all": (TEST_START, TEST_END)}
TEST_WINDOWS.update({f"test_{y}": (max(date(y, 1, 1), TEST_START), min(date(y, 12, 31), TEST_END))
                     for y in range(TEST_START.year, TEST_END.year + 1)})
sel_perf = {m: {g: f for g, f in grains.items() if g in selected.get(m, set())}
            for m, grains in perf_all.items() if m in selected}
by_year = score_performance_windows(sel_perf, TEST_WINDOWS)
display(by_year[["block", "grain", "model", "status", "periods", "accuracy_pct",
                 "within_10pct", "bias_pct", "skill_vs_persistence_pct"]])
display(herd_level_accuracy(sel_perf))
if USE_QUANTILE:
    print("Prediction ranges: share of test cow-days inside the 10-90% range (target 80%)")
    coverage = interval_coverage(final_models)
    display(coverage)
    coverage.to_csv(OUT_DIR / "interval_coverage.csv", index=False)

# Public weekly/monthly frames must be complete periods of mean cow-day yield.
period_checks = period_cleaning_checks(sel_perf)
display(period_checks.drop(columns="passed"))
assert len(period_checks) > 0 and period_checks["passed"].all(), (
    "Weekly/monthly cleaning failed: incomplete periods or a period total reached the chart")
test_all.to_csv(OUT_DIR / "test_all_candidates.csv", index=False)
by_year.to_csv(OUT_DIR / "test_selected_by_year.csv", index=False)
print(f"Final stage took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 5. Diagnostics: noise floor and where the daily model misses (aggregate only)
""")

code(r"""
display(noise_floor(final_models.frame))
daily_model = next(m for m, g in selected.items() if "daily" in g)
print("Daily model diagnosed:", daily_model)
breakdown = error_breakdown(final_models.frame, final_models.predictions[daily_model],
                            block="test",
                            naive=final_models.predictions["persistence_last_yield"])
display(breakdown)
breakdown.to_csv(OUT_DIR / "diagnostics_error_breakdown_test.csv", index=False)
""")

md(r"""
## 6. Mini train/test windows (equal-record blocks, expanding training)

The whole period is cut into `WINDOW_BLOCKS` blocks of equal size. Window k trains on
*all* blocks 1..k (expanding, so later windows learn from more data) and tests on block
k+1. Every candidate is scored and nothing is selected here: the table shows how each
model behaves under different conditions. The last window includes the test period, so
this section is a report, never a selection input.
""")

code(r"""
if RUN_WINDOW_STUDY:
    t0 = time.perf_counter()
    # Expanding training: window k trains on blocks 1..k.
    windows_table = pd.DataFrame(equal_record_windows(raw["date"], WINDOW_BLOCKS))
    windows_table["train_start"] = windows_table["train_start"].iloc[0]
    windows_table["train_cow_days"] = (windows_table["train_cow_days"].iloc[0]
                                       + windows_table["test_cow_days"].shift(1).fillna(0)
                                       .cumsum().astype(int))
    display(windows_table)
    window_metrics, window_conditions_table = rolling_window_study(
        raw, EVENTS, min_source_records=MIN_SOURCE_RECORDS_PER_YEAR, exclude_gap=False,
        n_blocks=WINDOW_BLOCKS, expanding=True, fit_fn=fit_torch_models,
        fit_kwargs={"params": dict(TORCH_PARAMS), "device": DEVICE, "seed": SEED, "oof": False,
                    "options": REPORT_WINDOW_OPTIONS},
        verbose=VERBOSE)
    display(window_conditions_table)
    for metric in ("accuracy_pct", "within_10pct", "bias_pct"):
        print(f"{metric} by window")
        display(window_summary(window_metrics, metric))
    window_metrics.to_csv(OUT_DIR / "window_study_metrics.csv", index=False)
    print(f"Window study took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 6b. Charts: validation and final test

One validation chart per candidate (test hidden), and a final-test chart per selected
model through August 2026 with the recording gap shaded. Values are mean litres per
recorded cow-day; gaps are periods without enough recorded cows.
""")

code(r"""
chart_paths = []
for model, grains in validation_performance.items():
    path = CHART_DIR / f"{model}_validation.png"
    fig = plot_model_performance(model, grains, path, show_test_grains=set(),
                                 valid_start=VALID_START, test_start=TEST_START, gap=GAP)
    plt.show(); plt.close(fig); chart_paths.append(path)
for model, grains in sel_perf.items():
    path = CHART_DIR / f"{model}_selected_final_test.png"
    fig = plot_model_performance(model, grains, path, show_test_grains=selected[model],
                                 valid_start=VALID_START, test_start=TEST_START, gap=GAP)
    plt.show(); plt.close(fig); chart_paths.append(path)
# Accuracy of every candidate on the test block, per grain (comparison only).
fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
for ax, grain in zip(axes, ("daily", "weekly", "monthly")):
    t = test_all[test_all["grain"] == grain].sort_values("accuracy_pct")
    colors = ["#1f77b4" if s else "#9ca3af" for s in t["selected"]]
    ax.barh(t["model"], t["accuracy_pct"], color=colors)
    ax.set_title(f"{grain}: test accuracy (blue = selected on validation)", fontsize=9)
    ax.set_xlim(0, 100); ax.grid(axis="x", alpha=0.3)
fig.tight_layout()
path = CHART_DIR / "test_accuracy_all_candidates.png"
fig.savefig(path, dpi=150, bbox_inches="tight"); plt.show(); plt.close(fig)
chart_paths.append(path)
print("Saved charts:"); [print(" -", p) for p in chart_paths]
""")

md(r"""
## 7. Comparison with notebook 05 (LightGBM / forest / MLP on CPU)

If notebook 05 or `pfoi cow-yield` has saved results for the same test, the selected
models of both are shown side by side on the test block. Nothing is recomputed here.
""")

code(r"""
LOGS = COMPONENT_DIR / "logs" / "pfoi_mi2" / ("synthetic_only" if USE_SYNTHETIC else "")
candidates_05 = [LOGS / COW_MODEL_NAME / COW_TEST_NAME / "default" / "test_all_candidates.csv"]
found = next((p for p in candidates_05 if p.exists()), None)
ours = test_all[test_all["selected"]].assign(pipeline="torch (06)")
if found is not None:
    theirs = pd.read_csv(found)
    theirs = theirs[theirs["selected"]].assign(pipeline="lightgbm/forest (05 / cli)")
    both = pd.concat([ours, theirs], ignore_index=True)
    display(both.pivot_table(index="grain", columns="pipeline",
                             values=["accuracy_pct", "within_10pct", "bias_pct"]).round(2))
else:
    print("No saved notebook-05 / cow-yield results for this test yet. Run:\n"
          "  python -m components.predictive_farm_intelligence.pfoi.cli cow-yield --tag default")
    display(ours[COMPARE])
# This version vs the earlier torch runs, selected models on the test block.
versions = [ours.assign(version="torch v3 (this run)")]
for label, folder in (("torch v1", V1_DIR), ("torch v2", V2_DIR)):
    f_prev = folder / "test_all_candidates.csv"
    if f_prev.exists():
        prev = pd.read_csv(f_prev)
        versions.append(prev[prev["selected"]].assign(version=label))
if len(versions) > 1:
    allv = pd.concat(versions, ignore_index=True)
    print("Torch versions, selected models, test block")
    display(allv.pivot_table(index="grain", columns="version",
                             values=["accuracy_pct", "within_10pct", "bias_pct"]).round(2))
    display(allv[["version", "grain", "model"]])
    # Best of each model family in this run, all grains (comparison only, not selection).
    fam = test_all.assign(family=test_all["model"].str.replace(r"_(recal|grp)$", "", regex=True))
    print("This run: best variant of each model family on the test block (comparison only)")
    display(fam.sort_values("accuracy_pct", ascending=False).groupby(["grain", "family"])
               .first()[["model", "accuracy_pct", "within_10pct", "bias_pct"]].round(2))
print(f"Notebook total: {time.perf_counter() - NOTEBOOK_START:,.0f}s on {resolve_device(DEVICE)}")
""")


def main() -> None:
    notebook = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    target = Path(__file__).with_name("06_cow_yield_torch.ipynb")
    target.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
