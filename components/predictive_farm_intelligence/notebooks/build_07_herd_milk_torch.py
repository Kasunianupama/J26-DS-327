"""Write ``07_herd_milk_torch.ipynb`` with empty outputs.

Herd-level version of notebook 06: forecasts the whole herd's milk (not each cow's
yield) with herd movement as input. Agents may run it only with the synthetic setting;
the user runs the real-data setting locally. Run it in its own kernel: on macOS PyTorch
crashes in a process where LightGBM has trained.
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
# Farm X: herd milk with PyTorch and herd movement (pfoi-herd-milk-torch-1.9.0-dev)

Notebook 06 forecasts **each cow's** yield. This notebook forecasts the **whole herd's
milk**: litres per day for the herd, per day, per week and per calendar month.

- **target:** the clean herd milk of `docs/model_input2.md` §5: milk per recorded cow x
  milking herd, placeholder and shipped milk never used. Weekly and monthly values are
  mean litres per day over the period (x days = the period total);
- **same protocol as notebook 06:** the May 2022 – October 2025 recording gap excluded;
  75 / 5 / 20 chronological split of the recorded herd-days; walk-forward forecasts of
  the next day / week / month with inputs known before its first day; tuning and pooled
  selection on pre-test data only; untouched test;
- **herd movement as input.** Herd milk = milking cows x litres per cow, so every
  forecast starts from a structural base: the last 7 recorded days' litres per cow x
  the milking herd projected along its last-28-day trend to the middle of the period.
  The networks learn a bounded correction to it from milk history, **herd movement**
  (calvings, dry-offs, exits, entries, births per milking cow; net milking inflow),
  **herd composition** (lactation-stage and parity shares, pregnant dry cows and heifers
  per milking cow), lagged weather and health, and the season;
- **candidates:** persistence, `herd_structural` (the base), `herd_kalman` (Kalman level
  of litres per cow x projected milking), `torch_mlp_small`, `torch_mlp_large` (tuned),
  `torch_mlp_nomove` (**ablation**: the small network without herd movement and
  composition), `torch_gru` (GRU over the last 28 days of milk and movement),
  `torch_q50` (10–90% range), each also walk-forward recalibrated (`_recal`), plus a
  validation-fitted blend with persistence;
- weekly and monthly networks train on rolling 7- and 30-day windows from every day
  (many more samples than calendar periods) and are scored on calendar periods only.

The herd series is short (clean records exist mainly from August 2020), so monthly
scores rest on few months and swing by several points; daily and weekly are the stable
read-outs. Run this notebook in its own kernel (PyTorch next to LightGBM crashes on
macOS). Everything shown is herd-level aggregate; no animal identifier is loaded.
""")

code(r"""
USE_SYNTHETIC = True       # Set False yourself for the read-only Farm X run.
INPUT_SCHEMA = "model_input2"
DATA_SCOPE = "clean"       # "clean": drop May 2022 - Oct 2025 | "through_mid2023": drop Jul 2023 - Oct 2025
SPLIT = (0.75, 0.05, 0.20)
MIN_PERIOD_COVERAGE = 1.00  # weekly/monthly values only from fully recorded periods
SELECTION_BLOCKS = 4        # expanding windows on pre-test data, pooled with validation
DEVICE = "cpu"              # the herd table is small: CPU is faster than the GPU here ("auto" = MPS)
TUNE = True
N_TRIALS = 12
# Network training (as notebook 06): stop only when accuracy on the held-out weeks stays
# more than STOP_DROP_PP points below its best for STOP_PATIENCE epochs, never before
# MIN_EPOCHS. Best weights are kept.
MAX_EPOCHS = 250
MIN_EPOCHS = 50
STOP_DROP_PP = 0.5
STOP_PATIENCE = 15
DROPOUT = 0.3
BATCH_SIZE = 64
ENSEMBLE = 3
USE_KALMAN = True
USE_GRU = True
SEQ_LEN = 28               # days of milk and movement in the GRU sequence
USE_QUANTILE = True
USE_ABLATION = True        # torch_mlp_nomove: same network without herd movement inputs
MODEL_OPTIONS = {"ensemble": ENSEMBLE, "use_kalman": USE_KALMAN, "use_gru": USE_GRU,
                 "seq_len": SEQ_LEN, "use_quantile": USE_QUANTILE, "use_ablation": USE_ABLATION}
SELECTION_OPTIONS = {**MODEL_OPTIONS, "ensemble": 1}
REPORT_WINDOW_OPTIONS = {**MODEL_OPTIONS, "ensemble": 1, "use_gru": False}
RUN_WINDOW_STUDY = True
WINDOW_BLOCKS = 5
VERBOSE = True
SEED = 17
# Section 9: two-year outlook (every month up to OUTLOOK_MONTHS ahead).
RUN_OUTLOOK = True
OUTLOOK_MONTHS = 24
MILKING_PATH = "engine"    # "engine": herd-engine projection | "trend": damped 28-day trend
OUTLOOK_ENSEMBLE = 3
DROP_PP = 5.0              # marker: trailing accuracy this many points below month 1
RELIABLE_WITHIN10 = 85.0   # marker: share of months within +-10% falls below this
BOUND_Q = (0.05, 0.95)     # lower / upper bound = these quantiles of past errors

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

COMPONENT_DIR = Path.cwd().resolve()
if COMPONENT_DIR.name == "notebooks":
    COMPONENT_DIR = COMPONENT_DIR.parent
REPO_ROOT = COMPONENT_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from components.predictive_farm_intelligence.pfoi.herd_torch import (
    FEATURE_FAMILIES, HERD_TEST_NAMES, HERD_TORCH_MODEL_NAME, add_blend, apply_blend,
    assert_torch_safe_process, chronological_split, exclude_gap, expanding_windows,
    feature_catalogue, fit_herd_models, gap_for, herd_contract_checks, herd_year_summary,
    interval_coverage, movement_importance, plot_herd_forecast, plot_herd_movement,
    pool_metrics, resolve_device, score_herd, tune_herd, window_summary,
)
from components.predictive_farm_intelligence.pfoi.cow_accuracy import TEST_END, TRAIN_START
assert_torch_safe_process()

GAP = gap_for(DATA_SCOPE)
TEST_NAME = HERD_TEST_NAMES[DATA_SCOPE]
OUT_DIR = COMPONENT_DIR / "logs" / "pfoi_mi2" / HERD_TORCH_MODEL_NAME / TEST_NAME
if USE_SYNTHETIC:
    OUT_DIR = OUT_DIR / "synthetic_only"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CHART_DIR = OUT_DIR / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
NOTEBOOK_START = time.perf_counter()
print("Model:", HERD_TORCH_MODEL_NAME, "| Test:", TEST_NAME, "| Device:", resolve_device(DEVICE))
print("Mode:", "SYNTHETIC FICTIONAL DATA" if USE_SYNTHETIC else "FARM X READ-ONLY model_input2")
""")

md(r"""
## 1. Load the herd day table

One row per calendar day: clean herd milk (recorded days only), herd stocks, herd
movement events, the milking herd's lactation-stage and parity mix, weather and health.
All herd-level aggregates computed in SQL; no animal key leaves the database.
""")

code(r"""
if USE_SYNTHETIC:
    from components.predictive_farm_intelligence.pfoi.herd_torch import synthetic_herd_daily
    daily = synthetic_herd_daily(seed=SEED)
else:
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    from components.predictive_farm_intelligence.pfoi.herd_torch import load_herd_daily
    os.environ["PFOI_MODEL_INPUT_SCHEMA"] = INPUT_SCHEMA
    source = SqlHerdSource.from_env()
    assert source.placeholder_free(), "model_input2 expected: the target must be placeholder-free"
    daily = load_herd_daily(source)
print("Days:", f"{len(daily):,}", "| recorded milk days:", f"{int(daily['ok'].sum()):,}")
""")

md(r"""
### Data-cleaning contract checks

Executable checks, not descriptions: one row per calendar day inside the experiment,
litres only on recorded days, litres per milking cow in (0, 18] L, a milking herd on
every recorded day, and no key, placeholder, shipped or DelPro-total milk column. The
notebook stops if any check fails.
""")

code(r"""
checks = herd_contract_checks(daily)
display(checks[["status", "check", "aggregate_evidence"]])
assert checks["passed"].all(), "Data-cleaning contract failed; do not fit models"
display(herd_year_summary(daily))
""")

md(r"""
### Recording gap and the 75 / 5 / 20 split

The split is by recorded herd-days, in time order. Herd movement inside the gap is kept
(it comes from presence intervals, recorded throughout); only milk is removed.
""")

code(r"""
print(f"Data scope {DATA_SCOPE!r}: removing milk {GAP[0]} .. {GAP[1]}")
daily = exclude_gap(daily, GAP)
recorded = pd.Series(daily.index[daily["ok"]])
split = chronological_split(recorded, SPLIT)
SELECTION_TRAIN_END, VALID_END = split.train_end, split.validation_end
FINAL_TRAIN_END, TEST_START = VALID_END, split.test_start
VALID_START = SELECTION_TRAIN_END + timedelta(days=1)
display(split.summary.rename(columns={"cow_days": "herd_days"}))
herd_year_summary(daily).to_csv(OUT_DIR / "herd_year_summary.csv", index=False)
""")

md(r"""
### Herd movement and herd milk

Monthly milking herd, the moves in and out of it, and the herd milk level. The forecast
base moves the milking herd along its recent trend; the networks see the movement
counts themselves.
""")

code(r"""
fig = plot_herd_movement(daily, CHART_DIR / "herd_movement_overview.png", GAP)
plt.show(); plt.close(fig)
display(feature_catalogue().groupby("family")["feature"].apply(", ".join).to_frame())
""")

md(r"""
## 2. Time-series tuning of the network (training block only)

Trial 0 is the default. Each trial fits `torch_mlp_large` on expanding folds that end at
the 60th / 75th / 90th percentile of the training block's recorded days and scores the
next slice. Validation and test are never used.
""")

code(r"""
TRAINING = {"max_epochs": MAX_EPOCHS, "min_epochs": MIN_EPOCHS, "stop_drop_pp": STOP_DROP_PP,
            "stop_patience": STOP_PATIENCE}
HERD_PARAMS = {**TRAINING, "dropout": DROPOUT, "batch_size": BATCH_SIZE}
if TUNE:
    t0 = time.perf_counter()
    HERD_PARAMS, trials = tune_herd(daily, SELECTION_TRAIN_END, n_trials=N_TRIALS,
                                    device=DEVICE, seed=SEED, fixed=TRAINING,
                                    min_coverage=MIN_PERIOD_COVERAGE, verbose=VERBOSE)
    display(trials)
    trials.to_csv(OUT_DIR / "tuning_trials.csv", index=False)
    print(f"Tuning took {time.perf_counter() - t0:,.0f}s")
print("Network settings:", HERD_PARAMS)
FIT = {"params": dict(HERD_PARAMS), "device": DEVICE, "seed": SEED,
       "min_coverage": MIN_PERIOD_COVERAGE}
""")

md(r"""
## 3. Validation fit, pooled selection, blend and winners

Every candidate is fitted on periods ending by the selection-training end and scored on
validation. **Selection is pooled** so it does not rest on the small validation block
alone: the pre-test data are cut into `SELECTION_BLOCKS` blocks of equal recorded days,
models are refitted on expanding windows (blocks 1..k, scored on block k+1), and those
scores are pooled with validation, errors weighted by litres. The best candidate per
grain wins (persistence excluded). A persistence blend replaces it only if its
validation score is better. No test row is involved.
""")

code(r"""
t0 = time.perf_counter()
validation_models = fit_herd_models(daily, SELECTION_TRAIN_END, VALID_END,
                                    options=MODEL_OPTIONS, verbose=VERBOSE, **FIT)
if "kalman" in validation_models.fitted:
    print("Kalman noise (log litres per cow):", validation_models.fitted["kalman"])
print("Training windows per grain:", validation_models.fitted["train_rows"])
for (grain, name), (best, ran) in validation_models.fitted.get("epochs", {}).items():
    print(f"  {grain} {name}: best epoch {best} of {ran}")
vmet = score_herd(validation_models, ("validation",))

pre_test = daily[daily.index <= pd.Timestamp(VALID_END)]
sel_windows, sel_conditions = expanding_windows(
    pre_test, VALID_END, SELECTION_BLOCKS,
    {**FIT, "options": SELECTION_OPTIONS}, verbose=VERBOSE)
display(sel_conditions)
parts = [vmet] + ([g for _, g in sel_windows.groupby("window")] if len(sel_windows) else [])
pooled = pool_metrics(parts, "pooled_selection")
display(pooled[["grain", "model", "parts", "periods", "accuracy_pct", "within_10pct"]])
pooled_winner = (pooled[pooled["model"] != "persistence"].groupby("grain").first()["model"]
                 .to_dict())
print("Pooled winners:", pooled_winner)

BLEND_SPEC = add_blend(validation_models, pooled_winner, block="validation")
display(pd.DataFrame([(g, m, w) for g, (m, w) in BLEND_SPEC.items()],
                     columns=["grain", "winner", "weight_on_winner"]))
validation_metrics = score_herd(validation_models, ("validation",))
display(validation_metrics[["grain", "model", "periods", "accuracy_pct", "within_10pct",
                            "bias_pct", "skill_vs_persistence_pct"]])
rows = []
for grain, base_name in pooled_winner.items():
    v = validation_metrics[validation_metrics["grain"] == grain].set_index("model")
    choice = base_name
    if "blend" in v.index and base_name in v.index and v.loc["blend", "accuracy_pct"] > v.loc[base_name, "accuracy_pct"]:
        choice = "blend"
    rows.append({"grain": grain, "model": choice, "pooled_base": base_name,
                 **(v.loc[choice, ["accuracy_pct", "within_10pct", "bias_pct",
                                   "skill_vs_persistence_pct"]].to_dict() if choice in v.index else {})})
winners = pd.DataFrame(rows)
display(winners)
SELECTED = dict(zip(winners["grain"], winners["model"]))
validation_metrics.to_csv(OUT_DIR / "validation_metrics_all_candidates.csv", index=False)
pooled.to_csv(OUT_DIR / "pooled_selection.csv", index=False)
winners.to_csv(OUT_DIR / "winners.csv", index=False)
print(f"Validation stage took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 4. Final refit and untouched test

Refit on everything up to the end of validation; every candidate is scored on the same
test periods for comparison, and `selected` marks the validation winner (the comparison
never changes it).
""")

code(r"""
t0 = time.perf_counter()
final_models = fit_herd_models(daily, FINAL_TRAIN_END, FINAL_TRAIN_END,
                               options=MODEL_OPTIONS, verbose=VERBOSE, **FIT)
apply_blend(final_models, BLEND_SPEC)
test_all = score_herd(final_models, ("test",))
test_all["selected"] = [SELECTED.get(g) == m for m, g in zip(test_all["model"], test_all["grain"])]
COMPARE = ["grain", "model", "selected", "periods", "accuracy_pct", "within_5pct",
           "within_10pct", "mae_litres_per_day", "bias_pct", "skill_vs_persistence_pct", "r2"]
display(test_all[COMPARE])
TEST_WINDOWS = {f"test_{y}": (max(date(y, 1, 1), TEST_START), min(date(y, 12, 31), TEST_END))
                for y in range(TEST_START.year, TEST_END.year + 1)}
by_year = score_herd(final_models, ("test",), windows=TEST_WINDOWS)
if len(by_year):
    by_year["selected"] = [SELECTED.get(g) == m for m, g in zip(by_year["model"], by_year["grain"])]
    display(by_year[by_year["selected"] | (by_year["model"] == "persistence")]
            [["block", "grain", "model", "periods", "accuracy_pct", "within_10pct", "bias_pct",
              "skill_vs_persistence_pct"]])
if USE_QUANTILE:
    print("Prediction ranges: share of test periods inside the 10-90% range (target 80%)")
    coverage = interval_coverage(final_models, "test")
    display(coverage)
    coverage.to_csv(OUT_DIR / "interval_coverage.csv", index=False)
test_all.to_csv(OUT_DIR / "test_all_candidates.csv", index=False)
by_year.to_csv(OUT_DIR / "test_by_year.csv", index=False)
print(f"Final stage took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 5. Does herd movement help?

Two read-outs, both aggregate:

- **ablation:** `torch_mlp_nomove` is `torch_mlp_small` without the herd-movement and
  herd-composition inputs (same settings, same seeds). The difference in test accuracy
  is what those inputs add *beyond* the structural base, which already uses the milking
  herd and its trend;
- **permutation importance:** accuracy lost on the test block when one input family is
  shuffled across periods in the fitted `torch_mlp_small` (nothing refitted).
""")

code(r"""
pairs = [("torch_mlp_small", "torch_mlp_nomove"), ("torch_mlp_small_recal", "torch_mlp_nomove_recal")]
abl = test_all.set_index(["grain", "model"])["accuracy_pct"]
rows = []
for grain in test_all["grain"].unique():
    for with_m, without_m in pairs:
        if (grain, with_m) in abl.index and (grain, without_m) in abl.index:
            rows.append({"grain": grain, "with_movement": with_m,
                         "accuracy_with_pct": abl[(grain, with_m)],
                         "accuracy_without_pct": abl[(grain, without_m)],
                         "movement_gain_pp": abl[(grain, with_m)] - abl[(grain, without_m)]})
ablation = pd.DataFrame(rows)
display(ablation)
importance = movement_importance(final_models, "torch_mlp_small", block="test", seed=SEED)
if len(importance):
    display(importance.pivot_table(index="family", columns="grain",
                                   values="accuracy_drop_pp").round(2))
    importance.to_csv(OUT_DIR / "feature_family_importance_test.csv", index=False)
ablation.to_csv(OUT_DIR / "ablation_herd_movement_test.csv", index=False)
""")

md(r"""
## 6. Mini train/test windows (equal recorded days, expanding training)

The whole period is cut into `WINDOW_BLOCKS` blocks of equal recorded days. Window k
trains on blocks 1..k and is scored on block k+1. Nothing is selected here; the last
window includes the test period, so this is a report only.
""")

code(r"""
if RUN_WINDOW_STUDY:
    t0 = time.perf_counter()
    window_metrics, window_conditions = expanding_windows(
        daily, TEST_END, WINDOW_BLOCKS, {**FIT, "options": REPORT_WINDOW_OPTIONS},
        verbose=VERBOSE)
    display(window_conditions)
    if len(window_metrics):
        for metric in ("accuracy_pct", "within_10pct", "bias_pct"):
            print(f"{metric} by window")
            display(window_summary(window_metrics, metric))
        window_metrics.to_csv(OUT_DIR / "window_study_metrics.csv", index=False)
    print(f"Window study took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 7. Charts: validation and final test

Herd milk in litres per day: recorded actuals (dots), persistence (grey) and the
selected model's forecast (blue, with its 10–90% range for the quantile network), drawn
only where it is out of sample. Over the periods the model was trained on, its line is a
dashed grey **training fit (in-sample, not a test)**. Validation is shaded yellow, test
blue, the excluded recording gap darker grey. In the final refit, validation is part of
training, so only the test is drawn as a forecast.
""")

code(r"""
chart_paths = []
path = CHART_DIR / "selected_validation.png"
fig = plot_herd_forecast(validation_models, SELECTED, path, GAP,
                         "Validation fit: selected models (test not shown)",
                         show_blocks=("validation",))
plt.show(); plt.close(fig); chart_paths.append(path)
path = CHART_DIR / "selected_final_test.png"
fig = plot_herd_forecast(final_models, SELECTED, path, GAP,
                         "Final refit: selected models on the untouched test",
                         show_blocks=("test",))
plt.show(); plt.close(fig); chart_paths.append(path)
fig, axes = plt.subplots(1, 3, figsize=(16, 6), sharey=False)
for ax, grain in zip(axes, ("daily", "weekly", "monthly")):
    t = test_all[test_all["grain"] == grain].sort_values("accuracy_pct")
    colors = ["#1f77b4" if s else "#9ca3af" for s in t["selected"]]
    ax.barh(t["model"], t["accuracy_pct"], color=colors)
    ax.set_title(f"{grain}: test accuracy (blue = selected)", fontsize=9)
    ax.set_xlim(max(0, t["accuracy_pct"].min() - 5) if len(t) else 0, 100)
    ax.tick_params(axis="y", labelsize=7); ax.grid(axis="x", alpha=0.3)
fig.tight_layout()
path = CHART_DIR / "test_accuracy_all_candidates.png"
fig.savefig(path, dpi=150, bbox_inches="tight"); plt.show(); plt.close(fig)
chart_paths.append(path)
print("Saved charts:"); [print(" -", p) for p in chart_paths]
""")

md(r"""
## 8. Comparison with the per-cow notebook 06

Notebook 06 scores cow-periods (yield per cow); this notebook scores the herd total.
The two accuracies answer different questions and are shown side by side only if
notebook 06 saved results for the same data mode. Nothing is recomputed here.
""")

code(r"""
from components.predictive_farm_intelligence.pfoi.cow_torch import TORCH_MODEL_NAME
from components.predictive_farm_intelligence.pfoi.cow_accuracy import SCOPE_TEST_NAMES
nb06 = (COMPONENT_DIR / "logs" / "pfoi_mi2" / TORCH_MODEL_NAME / SCOPE_TEST_NAMES[DATA_SCOPE])
if USE_SYNTHETIC:
    nb06 = nb06 / "synthetic_only"
nb06 = nb06 / "torch_v3" / "test_all_candidates.csv"
ours = test_all[test_all["selected"]].assign(pipeline="herd total (07)")
if nb06.exists():
    theirs = pd.read_csv(nb06)
    theirs = theirs[theirs["selected"]].assign(pipeline="per cow (06)")
    both = pd.concat([ours, theirs], ignore_index=True)
    display(both.pivot_table(index="grain", columns="pipeline",
                             values=["accuracy_pct", "within_10pct", "bias_pct"]).round(2))
else:
    print("No saved notebook-06 results for this data mode yet.")
    display(ours[COMPARE])
""")

md(r"""
## 9. Two-year outlook with bounds and reliability markers

Sections 3–8 forecast only the next day, week or month. This section forecasts **every
calendar month up to `OUTLOOK_MONTHS` (24) ahead** from the 1st of a month:

- **herd movement over the horizon:** the milking herd of each future month comes from
  the **herd engine** (`MILKING_PATH = "engine"`: calvings already due from known
  pregnancies, dry-offs, exits and lactation stage projected from the herd at the
  origin, facts before it only) or a damped 28-day trend (`"trend"`, used for the
  synthetic run). Base = recent litres per cow x projected milking cows;
- **one network for all horizons** (`torch_mlp_horizon`) corrects the base using the
  horizon, the target month's season, the projected movement (calvings, dry-offs,
  fresh-cow share), the same season a year earlier and every input of sections 1–8.
  `torch_mlp_horizon_nomove` drops the movement inputs (ablation); `torch_q_horizon`
  is a 5/50/95% quantile network;
- **lower / upper bounds:** 5% and 95% quantiles of the chosen model's own back-test
  errors per horizon band. Where a band has too few errors, its width is extrapolated
  (widening with the square root of the horizon) and marked as such;
- **markers:** the month ahead where accuracy **drops significantly** (trailing
  3-month mean more than `DROP_PP` points below month 1), where fewer than
  `RELIABLE_WITHIN10` % of months are within ±10%, where skill over persistence is lost,
  and from where there are **too few tested months** to judge.

**Data limit:** clean herd milk exists mainly Aug 2020 – Apr 2022 and from Nov 2025, so
only short horizons can be back-tested. Months beyond the `untested_from` marker are
model output with extrapolated bounds, not validated forecasts.
""")

code(r"""
from components.predictive_farm_intelligence.pfoi.herd_outlook import (
    MilkingPaths, band_coverage, build_outlook, engine_path_summary, engine_paths,
    error_bands, fit_outlook, horizon_accuracy, horizon_backtest, horizon_markers,
    month_starts, next_origin, outlook_end, plot_horizon_accuracy, plot_outlook,
    pooled_outlook_accuracy,
)
import components.predictive_farm_intelligence.pfoi.herd_outlook as herd_outlook
herd_outlook.BOUND_Q = BOUND_Q
from components.predictive_farm_intelligence.pfoi.herd_torch import equal_day_cuts

if RUN_OUTLOOK:
    t0 = time.perf_counter()
    OUTLOOK_ORIGIN = next_origin(daily)
    path_kind = "trend" if USE_SYNTHETIC else MILKING_PATH
    if path_kind == "engine":
        first = daily.index[daily["ok"]].min() - pd.DateOffset(months=1)
        PATHS = engine_paths(source, month_starts(first, OUTLOOK_ORIGIN),
                             horizon_days=OUTLOOK_MONTHS * 31 + 62, verbose=VERBOSE)
        print(f"Engine runs: {len(PATHS.runs)} | failed (too early or no herd cells): "
              f"{len(PATHS.failed)}")
        display(engine_path_summary(PATHS).describe().round(1))
    else:
        PATHS = MilkingPaths("trend")
    print("Milking path:", PATHS.kind, "| outlook origin:", OUTLOOK_ORIGIN.date(),
          "| last month:", outlook_end(OUTLOOK_ORIGIN, OUTLOOK_MONTHS))
    OUTLOOK_FIT = {"params": dict(HERD_PARAMS), "device": DEVICE, "seed": SEED,
                   "ensemble": OUTLOOK_ENSEMBLE, "min_coverage": MIN_PERIOD_COVERAGE,
                   "max_h": OUTLOOK_MONTHS}
    print(f"Milking paths took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
### 9.1 Choice of the outlook model and its bounds (pre-test data only)

Walk-forward on the same expanding windows as section 3: fit at the end of block k,
forecast 1–24 months from every month start up to the end of block k+1, score months
that ended by the end of validation. The best model over all horizons is used (not
persistence); its errors give the bounds checked on the test in 9.2.
""")

code(r"""
if RUN_OUTLOOK:
    t0 = time.perf_counter()
    cuts = equal_day_cuts(pre_test, VALID_END, SELECTION_BLOCKS)
    pre_errors = horizon_backtest(daily, cuts, VALID_END, PATHS, OUTLOOK_FIT, verbose=VERBOSE)
    pre_pooled = pooled_outlook_accuracy(pre_errors)
    display(pre_pooled)
    OUTLOOK_MODEL = pre_pooled[pre_pooled["model"] != "persistence"]["model"].iloc[0]
    print("Outlook model (pre-test choice):", OUTLOOK_MODEL)
    bands_pre = error_bands(pre_errors, OUTLOOK_MODEL, BOUND_Q, OUTLOOK_MONTHS)
    display(bands_pre[["horizon", "band", "errors", "lower_pct", "upper_pct", "status"]]
            .drop_duplicates("band"))
    pre_errors.to_csv(OUT_DIR / "outlook_pretest_errors.csv", index=False)
    print(f"Pre-test back-test took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
### 9.2 Untouched test by horizon

Fit at the end of validation; forecast 1–24 months from every month start in the test;
score the months that have records. Bounds come from 9.1 (no test errors in them).
""")

code(r"""
if RUN_OUTLOOK:
    t0 = time.perf_counter()
    test_errors = horizon_backtest(daily, [VALID_END, TEST_END], TEST_END, PATHS, OUTLOOK_FIT)
    acc_test = horizon_accuracy(test_errors, OUTLOOK_MONTHS)
    show = acc_test[acc_test["model"].isin([OUTLOOK_MODEL, "persistence"]) & (acc_test["periods"] > 0)]
    display(show.pivot_table(index="horizon", columns="model",
                             values=["periods", "accuracy_pct", "within_10pct"]).round(1))
    print(f"Share of test months inside the {round(100 * (BOUND_Q[1] - BOUND_Q[0]))}% bounds")
    display(band_coverage(test_errors, OUTLOOK_MODEL, bands_pre))
    test_errors.to_csv(OUT_DIR / "outlook_test_errors.csv", index=False)
    acc_test.to_csv(OUT_DIR / "outlook_test_accuracy_by_horizon.csv", index=False)
    print(f"Test took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
### 9.3 Accuracy by months ahead and the reliability markers (whole period, report)

The same walk-forward over the whole period (`WINDOW_BLOCKS` blocks, test included, as
in section 6). This is a report, not a selection input: it gives the markers and the
bounds of the live outlook, because it holds the most tested months per horizon.
""")

code(r"""
if RUN_OUTLOOK:
    t0 = time.perf_counter()
    all_cuts = equal_day_cuts(daily, TEST_END, WINDOW_BLOCKS)
    all_errors = horizon_backtest(daily, all_cuts, TEST_END, PATHS, OUTLOOK_FIT, verbose=VERBOSE)
    acc_all = horizon_accuracy(all_errors, OUTLOOK_MONTHS)
    display(pooled_outlook_accuracy(all_errors))
    MARKERS = horizon_markers(acc_all, OUTLOOK_MODEL, DROP_PP, RELIABLE_WITHIN10,
                              max_h=OUTLOOK_MONTHS)
    MARKERS["outlook_month"] = [(OUTLOOK_ORIGIN + pd.DateOffset(months=h - 1)).strftime("%Y-%m")
                                for h in MARKERS["horizon"]]
    print("Reliability markers for", OUTLOOK_MODEL)
    display(MARKERS)
    bands_all = error_bands(all_errors, OUTLOOK_MODEL, BOUND_Q, OUTLOOK_MONTHS)
    display(bands_all[["horizon", "band", "errors", "lower_pct", "upper_pct", "status"]]
            .drop_duplicates("band"))
    path = CHART_DIR / "outlook_accuracy_by_horizon.png"
    fig = plot_horizon_accuracy(acc_all, [OUTLOOK_MODEL, "torch_mlp_horizon_nomove",
                                          "herd_structural", "persistence"], MARKERS, path,
                                f"Back-tested accuracy by months ahead ({OUTLOOK_MODEL})")
    plt.show(); plt.close(fig)
    all_errors.to_csv(OUT_DIR / "outlook_all_windows_errors.csv", index=False)
    acc_all.to_csv(OUT_DIR / "outlook_accuracy_by_horizon.csv", index=False)
    MARKERS.to_csv(OUT_DIR / "outlook_markers.csv", index=False)
    bands_all.to_csv(OUT_DIR / "outlook_bounds_by_horizon.csv", index=False)
    print(f"Whole-period back-test took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
### 9.4 Live two-year outlook

Refit on every recorded month, then forecast the 24 months after the data ends.
`reliability`: `tested` before the first marker, `beyond a marker` after it,
`untested` from the `untested_from` marker. Monthly totals = litres/day x days.
""")

code(r"""
if RUN_OUTLOOK:
    t0 = time.perf_counter()
    live = fit_outlook(daily, daily.index.max().date(), PATHS, [OUTLOOK_ORIGIN], **OUTLOOK_FIT)
    if OUTLOOK_MODEL not in live.predictions:
        raise RuntimeError(f"{OUTLOOK_MODEL} could not be fitted on all data")
    outlook = build_outlook(live, OUTLOOK_MODEL, bands_all, MARKERS)
    display(outlook[["horizon", "period_start", "milking_path", "forecast", "lower", "upper",
                     "forecast_month_total", "bound_status", "reliability"]])
    path = CHART_DIR / "outlook_two_years.png"
    fig = plot_outlook(daily, outlook, MARKERS, path, OUTLOOK_MODEL)
    plt.show(); plt.close(fig)
    outlook.assign(source="synthetic" if USE_SYNTHETIC else "farm_x",
                   model=HERD_TORCH_MODEL_NAME + "/" + OUTLOOK_MODEL,
                   path_kind=PATHS.kind).to_csv(OUT_DIR / "outlook_two_years.csv", index=False)
    print(f"Live outlook took {time.perf_counter() - t0:,.0f}s")
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
    target = Path(__file__).with_name("07_herd_milk_torch.ipynb")
    target.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
