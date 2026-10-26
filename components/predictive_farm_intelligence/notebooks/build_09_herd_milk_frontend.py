"""Write ``09_herd_milk_frontend.ipynb`` with empty outputs.

The combined herd milk notebook: herd movement (herd engine path), the herd milk models
of notebook 07 (one-step and 24-month outlook) and notebook 06's per-cow predictions
(as in notebook 08), producing every output the PFOI page needs (rows, bounds, record
status, withheld periods, reliability markers, exact explanations, evidence, replay,
reproducibility). Notebooks 06, 07 and 08 are not changed. Agents may run it only with
the synthetic setting; the user runs the real-data setting locally, in its own kernel.
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
# Farm X: combined herd milk model for the PFOI page (pfoi-herd-milk-combined-1.11.0-dev)

One notebook that brings together:

| Part | From | Role |
|---|---|---|
| **Herd movement** | herd engine (`MILKING_PATH = "engine"`) | milking cows, calvings, dry-offs, lactation stage and herd counts for 24 months |
| **Herd milk, next period** | notebook 07 | daily / weekly / monthly one-step models (base = litres per cow x milking cows, PyTorch correction) |
| **Herd milk, 24 months** | notebook 07, section 9 | one network for all horizons on the herd-movement path |
| **Per-cow yield** | notebooks 06 / 08 | each recorded cow's predicted yield, refitted walk-forward, as an input |

and produces **everything the PFOI page reads** (`frontend/src/data/pfoi/contract.ts`,
`shared/schemas/pfoi_outlook.py`), as files only (no database writes):

| Page need | Section |
|---|---|
| Milk rows in litres per period: daily 1–14, weekly 1–13, monthly 1–24 from one origin, adding up across grains | 8 |
| Herd rows (milking, dry, heifers, calves, total herd, calvings, dry-offs, deaths, culls + sales) from the same path | 8 |
| 5% / 95% bounds per grain and horizon; quality flag; reliability markers and status badges | 7, 8 |
| Record status (F1) and withheld milk periods (F2) instead of silent gaps | 1, 8 |
| Exact explanations: parts add up to each month's change (herd size, stage, parity, pregnancy, yield level, heat, mastitis, per-cow model, residual); past months too | 9 |
| Evidence: back-test rows in litres (model, persistence, seasonal naive), coverage, evidence ladder, replay | 5, 7, 10 |
| Version, configuration hash, seeds, cut dates, saved network weights | 11 |

Protocol as notebooks 06–08: clean target (identified cows, ≤ 18 L, no placeholder,
x milking herd), May 2022 – Oct 2025 recording gap excluded, 75 / 5 / 20 split, inputs
from before each origin only, selection on pre-test data, untouched test.

**Notebook 06 live:** its per-cow mean is over the cows recorded in the period, which is
only known afterwards. It is therefore evaluated (sections 5, 10) but not used for the
live forecast; the live one-step model is the best candidate without it.
""")

code(r"""
USE_SYNTHETIC = True       # Set False yourself for the read-only Farm X run.
INPUT_SCHEMA = "model_input2"
DATA_SCOPE = "clean"
SPLIT = (0.75, 0.05, 0.20)
MIN_PERIOD_COVERAGE = 1.00
SELECTION_BLOCKS = 4
WINDOW_BLOCKS = 5
DEVICE = "cpu"
ENSEMBLE = 3
VERBOSE = True
SEED = 17
# Herd movement over the horizon: "engine" = herd engine; synthetic runs use a labelled stand-in.
MILKING_PATH = "engine"
OUTLOOK_MONTHS = 24
OUTLOOK_ENSEMBLE = 3
DROP_PP = 5.0              # marker: trailing accuracy this many points below month 1
RELIABLE_WITHIN10 = 85.0   # marker: share of months within +-10% falls below this
# Notebook 06 side (None = its Farm X winners); refitted walk-forward with light settings.
COW_MODEL_BY_GRAIN = None
COW_MAX_EPOCHS = 250
MIN_SOURCE_RECORDS_PER_YEAR = 100
MIN_COWS_PER_DAY = 10
# Herd networks: notebook 07's tuned settings if saved; TUNE = True tunes here instead.
USE_NB07_TUNING = True
TUNE = False
N_TRIALS = 12
CORE_VERSION = None        # optional: latest publish.publish_log.version, typed by you

import os
import sys
import ast
import json
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
    DEFAULT_PARAMS, HERD_TEST_NAMES, HERD_TORCH_MODEL_NAME, SEARCH_SPACE,
    assert_torch_safe_process, chronological_split, equal_day_cuts, exclude_gap,
    expanding_windows, fit_herd_models, gap_for, herd_contract_checks, herd_year_summary,
    pool_common_parts, resolve_device, score_herd, tune_herd,
)
from components.predictive_farm_intelligence.pfoi.herd_cow_link import (
    LIGHT_COW_FIT, NB06_FARM_X_WINNERS, cow_herd_predictions, cow_pred_series,
    cow_prediction_summary,
)
from components.predictive_farm_intelligence.pfoi import herd_outlook as HO
from components.predictive_farm_intelligence.pfoi import herd_frontend as FE
from components.predictive_farm_intelligence.pfoi.cow_accuracy import (
    TEST_END, TRAIN_START, cow_accuracy_sql, exclude_recording_gap,
)
from components.predictive_farm_intelligence.pfoi.cow_diagnostics import cleaning_contract_checks
from components.predictive_farm_intelligence.pfoi.cow_torch import TORCH_MODEL_NAME
assert_torch_safe_process()
if COW_MODEL_BY_GRAIN is None:
    COW_MODEL_BY_GRAIN = dict(NB06_FARM_X_WINNERS)

GAP = gap_for(DATA_SCOPE)
TEST_NAME = HERD_TEST_NAMES[DATA_SCOPE]
OUT_DIR = COMPONENT_DIR / "logs" / "pfoi_mi2" / FE.COMBINED_MODEL_NAME / TEST_NAME
NB07_DIR = COMPONENT_DIR / "logs" / "pfoi_mi2" / HERD_TORCH_MODEL_NAME / TEST_NAME
if USE_SYNTHETIC:
    OUT_DIR, NB07_DIR = OUT_DIR / "synthetic_only", NB07_DIR / "synthetic_only"
CHART_DIR, FRONT_DIR = OUT_DIR / "charts", OUT_DIR / "frontend"
for p in (OUT_DIR, CHART_DIR, FRONT_DIR):
    p.mkdir(parents=True, exist_ok=True)
MODEL_VERSION = FE.COMBINED_MODEL_NAME + ("-synthetic" if USE_SYNTHETIC else "")
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
NOTEBOOK_START = time.perf_counter()
print("Model:", MODEL_VERSION, "| Test:", TEST_NAME, "| Device:", resolve_device(DEVICE))
print("Mode:", "SYNTHETIC FICTIONAL DATA" if USE_SYNTHETIC else "FARM X READ-ONLY model_input2 + core")
""")

md(r"""
## 1. Herd day table, record status, gap and split

The record-status check (page F1) runs on the data as loaded: it decides whether milk
can be forecast at all (no trusted milk day in the last 28 days = milk withheld; herd
counts are still shown).
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
checks = herd_contract_checks(daily)
display(checks[["status", "check", "aggregate_evidence"]])
assert checks["passed"].all(), "Data-cleaning contract failed; do not fit models"
display(herd_year_summary(daily))
daily = exclude_gap(daily, GAP)
RECORD_STATUS = FE.record_status(daily)
print("Record status:", RECORD_STATUS["status"], "|", RECORD_STATUS["reason_text"] or "records current")
display(pd.DataFrame(RECORD_STATUS["checks"]))
split = chronological_split(pd.Series(daily.index[daily["ok"]]), SPLIT)
SELECTION_TRAIN_END, VALID_END = split.train_end, split.validation_end
FINAL_TRAIN_END, TEST_START = VALID_END, split.test_start
VALID_START = SELECTION_TRAIN_END + timedelta(days=1)
DATA_THROUGH = daily.index.max()
ORIGIN = HO.next_origin(daily)
pre_test = daily[daily.index <= pd.Timestamp(VALID_END)]
display(split.summary.rename(columns={"cow_days": "herd_days"}))
print("Data through:", DATA_THROUGH.date(), "| live origin:", ORIGIN.date())
""")

md(r"""
## 2. Cow-day data for notebook 06's models

Same clean cow-days and cleaning contract as notebook 06; the recording gap removed.
""")

code(r"""
if USE_SYNTHETIC:
    from components.predictive_farm_intelligence.pfoi.cow_runner import synthetic_inputs
    raw, EVENTS = synthetic_inputs(n_cows=80, seed=SEED)
else:
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import load_accuracy_inputs
    inputs = load_accuracy_inputs(source, TRAIN_START, TEST_END)
    raw = inputs.pop("raw")
    EVENTS = inputs
cow_checks = cleaning_contract_checks(raw, cow_accuracy_sql("core"), TRAIN_START, TEST_END)
display(cow_checks[["status", "check", "aggregate_evidence"]])
assert cow_checks["passed"].all(), "Cow-day cleaning contract failed; do not fit models"
raw = exclude_recording_gap(raw, GAP)
print("Clean cow-days:", f"{len(raw):,}")
""")

md(r"""
## 3. Notebook 06 per-cow predictions, out-of-sample (walk-forward)

At each cut (pre-test block ends, end of selection training, end of validation) notebook
06's models are fitted on cow-days up to the cut and predict only until the next cut.
Averaged per day / week / month before leaving the cow model (no cow keys).
""")

code(r"""
t0 = time.perf_counter()
CUTS = list(equal_day_cuts(pre_test, VALID_END, SELECTION_BLOCKS))[:-1] + [
    pd.Timestamp(SELECTION_TRAIN_END), pd.Timestamp(VALID_END)]
COW_FIT = {**LIGHT_COW_FIT, "params": {"max_epochs": COW_MAX_EPOCHS}, "device": DEVICE,
           "seed": SEED, "min_source_records": MIN_SOURCE_RECORDS_PER_YEAR}
cow_table = cow_herd_predictions(raw, EVENTS, CUTS, DATA_THROUGH, COW_MODEL_BY_GRAIN, COW_FIT,
                                 MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE, verbose=VERBOSE)
COW_PREDS = cow_pred_series(cow_table)
display(cow_prediction_summary(cow_table, daily))
cow_table.to_csv(OUT_DIR / "nb06_herd_level_predictions.csv", index=False)
print(f"Cow models took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 4. Herd network settings
""")

code(r"""
TRAINING = {"max_epochs": DEFAULT_PARAMS["max_epochs"], "min_epochs": DEFAULT_PARAMS["min_epochs"]}
HERD_PARAMS = dict(DEFAULT_PARAMS)
trials_file = NB07_DIR / "tuning_trials.csv"
if TUNE:
    HERD_PARAMS, trials = tune_herd(daily, SELECTION_TRAIN_END, n_trials=N_TRIALS, device=DEVICE,
                                    seed=SEED, fixed=TRAINING, min_coverage=MIN_PERIOD_COVERAGE)
    display(trials); trials.to_csv(OUT_DIR / "tuning_trials.csv", index=False)
elif USE_NB07_TUNING and trials_file.exists():
    best = pd.read_csv(trials_file).sort_values("mean_accuracy_pct", ascending=False).iloc[0]
    for k in SEARCH_SPACE:
        v = best[k]
        HERD_PARAMS[k] = ast.literal_eval(v) if isinstance(v, str) else v
    HERD_PARAMS["batch_size"] = int(HERD_PARAMS["batch_size"])
    print("Using notebook 07 tuning from", trials_file)
else:
    print("Default network settings")
print({k: HERD_PARAMS[k] for k in SEARCH_SPACE})
FIT = {"params": dict(HERD_PARAMS), "device": DEVICE, "seed": SEED,
       "min_coverage": MIN_PERIOD_COVERAGE}
FIT_COW = {**FIT, "cow_preds": COW_PREDS}
OPTIONS = {"ensemble": ENSEMBLE}
""")

md(r"""
## 5. One-step models: selection, test, notebook 06 effect, evidence ladder

All candidates (notebook 07's plus `cow06_structural` and `torch_mlp_cow06`) on the same
periods (those with a notebook 06 prediction); pooled selection over the windows where
every candidate exists. The **live** one-step model per grain is the best pooled
candidate without notebook 06 (its cohort is not known in advance).
""")

code(r"""
t0 = time.perf_counter()
validation_models = fit_herd_models(daily, SELECTION_TRAIN_END, VALID_END, options=OPTIONS,
                                    verbose=VERBOSE, **FIT_COW)
vmet = score_herd(validation_models, ("validation",))
sel_windows, sel_conditions = expanding_windows(
    pre_test, VALID_END, SELECTION_BLOCKS, {**FIT_COW, "options": {"ensemble": 1}}, verbose=VERBOSE)
display(sel_conditions)
parts = [vmet] + ([g for _, g in sel_windows.groupby("window")] if len(sel_windows) else [])
pooled = pool_common_parts(parts, "pooled_selection")
display(pooled[["grain", "model", "parts", "periods", "accuracy_pct", "within_10pct"]])
cand = pooled[pooled["model"] != "persistence"]
SELECTED = cand.groupby("grain").first()["model"].to_dict()
no_cow = cand[~cand["model"].str.contains("cow06")]
LIVE_WINNERS = no_cow.groupby("grain").first()["model"].to_dict()
print("Best overall (evidence):", SELECTED)
print("Live one-step models (no notebook 06):", LIVE_WINNERS)

final_models = fit_herd_models(daily, FINAL_TRAIN_END, FINAL_TRAIN_END, options=OPTIONS,
                               verbose=VERBOSE, **FIT_COW)
test_all = score_herd(final_models, ("test",))
test_all["selected"] = [SELECTED.get(g) == m for m, g in zip(test_all["model"], test_all["grain"])]
test_all["live"] = [LIVE_WINNERS.get(g) == m for m, g in zip(test_all["model"], test_all["grain"])]
display(test_all[["grain", "model", "selected", "live", "periods", "accuracy_pct", "within_10pct",
                  "mae_litres_per_day", "bias_pct", "skill_vs_persistence_pct"]])
acc = test_all.set_index(["grain", "model"])["accuracy_pct"]
pairs = [("cow06_structural", "herd_structural"), ("torch_mlp_cow06", "torch_mlp_small"),
         ("cow06_structural_recal", "herd_structural_recal"), ("torch_mlp_cow06_recal", "torch_mlp_small_recal")]
with_without = pd.DataFrame([
    {"grain": g, "with_nb06": a, "without_nb06": b, "accuracy_with_pct": acc[(g, a)],
     "accuracy_without_pct": acc[(g, b)], "gain_pp": acc[(g, a)] - acc[(g, b)]}
    for g in test_all["grain"].unique() for a, b in pairs if (g, a) in acc.index and (g, b) in acc.index])
print("With vs without notebook 06 (test, same periods)")
display(with_without)
LADDER = FE.evidence_ladder(final_models, "test", LIVE_WINNERS)
print("Evidence ladder (F7): one-step test, same periods, ratio = MAE / persistence MAE")
display(LADDER[["grain", "rung", "n", "mae", "wape", "ratio_to_reference", "status"]])
STEP_BANDS = FE.onestep_bands(validation_models, LIVE_WINNERS, ("validation",))
for f, name in ((pooled, "pooled_selection"), (test_all, "onestep_test_all_candidates"),
                (with_without, "with_without_nb06_test"), (LADDER, "evidence_ladder")):
    f.to_csv(OUT_DIR / f"{name}.csv", index=False)
print(f"One-step stage took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 6. Herd movement path and its own back-test

One path per month start: the herd engine run from the herd at that date (facts before it
only). Each run is compared month by month with the recorded herd (herd counts exist
through the milk gap), giving the herd rows' bounds and the herd evidence.
""")

code(r"""
t0 = time.perf_counter()
runs = HO.month_starts(daily.index[daily["ok"]].min() - pd.DateOffset(months=13), ORIGIN)
if USE_SYNTHETIC or MILKING_PATH != "engine":
    PATHS = HO.synthetic_engine_paths(daily, runs)
    PATH_KIND = "synthetic stand-in for the herd engine (seasonal calvings, dry-off and exit rates)"
else:
    PATHS = HO.engine_paths(source, runs, horizon_days=OUTLOOK_MONTHS * 31 + 62, verbose=VERBOSE)
    PATH_KIND = "herd engine (pfoi FROZEN_ENGINE settings)"
print(PATH_KIND, "| runs:", len(PATHS.runs), "| failed:", len(PATHS.failed))
herd_errors = FE.herd_path_errors(daily, PATHS, OUTLOOK_MONTHS)
HERD_BANDS = FE.herd_bands(herd_errors, OUTLOOK_MONTHS)
he = herd_errors.dropna().assign(ape=lambda e: 100 * (e["forecast"] - e["actual"]).abs() / e["actual"].clip(lower=1))
herd_acc = (he[he["horizon"].isin([1, 3, 6, 12, 24])].groupby(["series", "horizon"])["ape"]
            .agg(["size", "mean"]).unstack("horizon").round(1))
print("Herd path: mean absolute % error by months ahead (n and mean), aggregate")
display(herd_acc)
herd_errors.to_csv(OUT_DIR / "herd_path_errors.csv", index=False)
print(f"Herd path took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 7. Two-year milk outlook: model choice, bounds, test, reliability markers

Two models are kept: the **best** candidate on pre-test data (published) and the **best
machine-learning** candidate (`torch_*`); when the best is already a network, only one.

As notebook 07 section 9, on the herd-movement path above. Bounds for the test come from
pre-test errors only; the markers and the live bounds come from the whole-period
back-test (a report, most tested months per horizon).
""")

code(r"""
t0 = time.perf_counter()
OUTLOOK_FIT = {"params": dict(HERD_PARAMS), "device": DEVICE, "seed": SEED,
               "ensemble": OUTLOOK_ENSEMBLE, "min_coverage": MIN_PERIOD_COVERAGE,
               "max_h": OUTLOOK_MONTHS}
cuts = equal_day_cuts(pre_test, VALID_END, SELECTION_BLOCKS)
pre_errors = HO.horizon_backtest(daily, cuts, VALID_END, PATHS, OUTLOOK_FIT, verbose=VERBOSE)
pre_pooled = HO.pooled_outlook_accuracy(pre_errors)
display(pre_pooled)
# Best model, and the best machine-learning (torch_*) model; one model if they are the same.
CHOICE = HO.choose_models(pre_pooled)
OUTLOOK_MODEL, ML_MODEL, OUTLOOK_MODELS = CHOICE["best"], CHOICE["best_ml"], CHOICE["models"]
print("Best model (published):", OUTLOOK_MODEL)
print("Best machine-learning model:", ML_MODEL or "none fitted",
      "(same as the best: one model)" if ML_MODEL == OUTLOOK_MODEL else "")
BANDS_PRE_BY = {m: HO.error_bands(pre_errors, m, FE.Q, OUTLOOK_MONTHS) for m in OUTLOOK_MODELS}
BANDS_PRE = BANDS_PRE_BY[OUTLOOK_MODEL]
test_errors = HO.horizon_backtest(daily, [VALID_END, TEST_END], TEST_END, PATHS, OUTLOOK_FIT)
acc_test = HO.horizon_accuracy(test_errors, OUTLOOK_MONTHS)
display(acc_test[acc_test["model"].isin(OUTLOOK_MODELS + ["persistence"]) & (acc_test["periods"] > 0)]
        .pivot_table(index="horizon", columns="model", values=["periods", "accuracy_pct", "within_10pct"]).round(1))
for m in OUTLOOK_MODELS:
    print(f"{m}: test months inside the 5-95% bounds (bounds from pre-test errors)")
    display(HO.band_coverage(test_errors, m, BANDS_PRE_BY[m]))
all_errors = HO.horizon_backtest(daily, equal_day_cuts(daily, TEST_END, WINDOW_BLOCKS), TEST_END,
                                 PATHS, OUTLOOK_FIT, verbose=VERBOSE)
acc_all = HO.horizon_accuracy(all_errors, OUTLOOK_MONTHS)
MARKERS_BY, BANDS_ALL_BY = {}, {}
for m in OUTLOOK_MODELS:
    mk = HO.horizon_markers(acc_all, m, DROP_PP, RELIABLE_WITHIN10, max_h=OUTLOOK_MONTHS)
    mk["outlook_month"] = [(ORIGIN + pd.DateOffset(months=h - 1)).strftime("%Y-%m") for h in mk["horizon"]]
    MARKERS_BY[m] = mk
    BANDS_ALL_BY[m] = HO.error_bands(all_errors, m, FE.Q, OUTLOOK_MONTHS)
MARKERS, BANDS_ALL = MARKERS_BY[OUTLOOK_MODEL], BANDS_ALL_BY[OUTLOOK_MODEL]
markers_all = pd.concat([v.assign(model=m) for m, v in MARKERS_BY.items()], ignore_index=True)
bounds_all = pd.concat([v.assign(model=m) for m, v in BANDS_ALL_BY.items()], ignore_index=True)
display(markers_all)
display(bounds_all[["model", "horizon", "band", "errors", "lower_pct", "upper_pct", "status"]]
        .drop_duplicates(["model", "band"]))
plot_models = list(dict.fromkeys(OUTLOOK_MODELS + ["torch_mlp_horizon_nomove", "herd_structural", "persistence"]))
fig = HO.plot_horizon_accuracy(acc_all, plot_models, MARKERS, CHART_DIR / "outlook_accuracy_by_horizon.png",
                               f"Back-tested accuracy by months ahead (markers: {OUTLOOK_MODEL})")
plt.show(); plt.close(fig)
for f, name in ((pre_errors, "outlook_pretest_errors"), (test_errors, "outlook_test_errors"),
                (all_errors, "outlook_all_windows_errors"), (markers_all, "outlook_markers"),
                (bounds_all, "outlook_bounds_by_horizon")):
    f.to_csv(OUT_DIR / f"{name}.csv", index=False)
print(f"Outlook back-tests took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
### 7b. Fitted vs recorded: training, validation (walk-forward) and test

For each outlook model (best, and best machine-learning) at 1, 3, 6 and 12 months
ahead: the final fit on months it was trained on (grey dashed, in-sample, not a test),
walk-forward forecasts on pre-test data (orange, out-of-sample; validation shaded
yellow) and the test forecasts (blue, with 5-95% bounds and persistence). Then the
one-step daily / weekly / monthly models (live best, and best machine-learning):
training fit + validation, and training fit + untouched test.
""")

code(r"""
# Fitted vs recorded charts: training fit (in-sample), validation / walk-forward and test.
import importlib
import components.predictive_farm_intelligence.pfoi.herd_torch as HT
HT = importlib.reload(HT)
HO = importlib.reload(HO)
t0 = time.perf_counter()
first_month = daily.index[daily["ok"]].min().to_period("M").to_timestamp()
FIT_ALL = HO.fit_outlook(daily, VALID_END, PATHS, HO.month_starts(first_month, TEST_END), **OUTLOOK_FIT)
for m in OUTLOOK_MODELS:
    role = "best model" if m == OUTLOOK_MODEL else "best machine-learning model"
    fig = HO.plot_outlook_fit(daily, FIT_ALL, m, pre_errors, test_errors,
                              CHART_DIR / f"outlook_fit_{m}.png",
                              f"24-month outlook, {role}: {m} (training fit, walk-forward, test)",
                              SELECTION_TRAIN_END, VALID_END, GAP, BANDS_PRE_BY[m])
    plt.show(); plt.close(fig)
# One-step models (next day / week / month): the live best and the best machine-learning ones.
ML_STEP = (no_cow[no_cow["model"].str.startswith(HO.ML_PREFIX)].groupby("grain").first()["model"].to_dict())
step_sets = [("best", LIVE_WINNERS)] + ([("best machine-learning", ML_STEP)] if ML_STEP != LIVE_WINNERS else [])
for label, winners in step_sets:
    tag = label.replace(" ", "_").replace("-", "_")
    fig = HT.plot_herd_forecast(validation_models, winners, CHART_DIR / f"onestep_{tag}_validation.png", GAP,
                                f"One-step {label} models {winners}: training fit and validation",
                                show_blocks=("validation",))
    plt.show(); plt.close(fig)
    fig = HT.plot_herd_forecast(final_models, winners, CHART_DIR / f"onestep_{tag}_test.png", GAP,
                                f"One-step {label} models {winners}: training fit and untouched test",
                                show_blocks=("test",))
    plt.show(); plt.close(fig)
print(f"Charts took {time.perf_counter() - t0:,.0f}s; saved in {CHART_DIR}")
""")

md(r"""
## 8. Live run: one consistent path, bounds, quality flags, herd rows

The 24-month outlook is the master. The live one-step daily and weekly forecasts are
laid over its first weeks (their ratio decays with a 7-day half-life); months 2+ are
rescaled to the monthly forecast. Daily, weekly and monthly rows are sums of the same
daily path (litres per period). If milk is withheld, only herd rows are produced and the
withheld periods are listed. After the last data day the herd is held at its last
recorded state for the short one-step features.
""")

code(r"""
import importlib
FE = importlib.reload(FE); HO = importlib.reload(HO)
t0 = time.perf_counter()
# The herd tables can end before the data frame does: carry the last herd state to its end.
last_milk = daily.index[daily["ok"]].max()
last_herd = daily["milking"].dropna().index.max()
print("Data frame ends:", DATA_THROUGH.date(), "| last recorded milk day:", last_milk.date(),
      "| last day with a milking count:", last_herd.date())
daily_live, carried = FE.carry_last_herd_state(daily)
print(f"Herd state carried forward over {carried} day(s) without herd records")
print("Herd-path runs:", len(PATHS.runs), "| failed:", len(PATHS.failed),
      "| latest run:", max(PATHS.runs).date() if PATHS.runs else None)
if PATHS.failed and not USE_SYNTHETIC and MILKING_PATH == "engine":
    from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs
    from components.predictive_farm_intelligence.pfoi.freeze import FROZEN_ENGINE
    for d in sorted(PATHS.failed)[-2:]:
        try:
            load_origin_inputs(source, d, FROZEN_ENGINE)
            print(f"  run {d}: loads now")
        except Exception as e:  # report why the herd engine could not start there
            print(f"  run {d} failed: {type(e).__name__}: {str(e)[:200]}")
WITHHELD, milk_out, PERIODS, live_step, SHORT = [], pd.DataFrame(), None, None, pd.DataFrame()
live_outlook = HO.fit_outlook(daily_live, DATA_THROUGH.date(), PATHS, [ORIGIN], **OUTLOOK_FIT)
print("Live origin-months:", len(live_outlook.meta), "| outlook model fitted:", OUTLOOK_MODEL in live_outlook.predictions)
if RECORD_STATUS["milk_withheld"] or OUTLOOK_MODEL not in live_outlook.predictions or live_outlook.meta.empty:
    probe = HO.horizon_table(daily_live, HO.asof_features(daily_live), PATHS, "score", [ORIGIN], max_h=1).meta
    print("No live milk forecast. First month inputs:",
          probe[["has_base", "base", "persistence", "milking_path"]].round(1).to_dict("records"))
    WITHHELD = FE.withheld_rows(ORIGIN, OUTLOOK_MONTHS)
else:
    live_step = fit_herd_models(FE.pad_future(daily_live, 45), DATA_THROUGH.date(), DATA_THROUGH.date(),
                                options=OPTIONS, **FIT)
    short = []
    for g in ("daily", "weekly"):
        meta = live_step.tables[g]
        i = np.flatnonzero(meta["origin"] >= ORIGIN)
        if len(i) and LIVE_WINNERS.get(g) in live_step.predictions:
            k = i[0]
            short.append({"grain": g, "period_start": meta["period_start"][k],
                          "period_end": meta["period_end"][k],
                          "forecast": live_step.predictions[LIVE_WINNERS[g]][g][k]})
    SHORT = pd.DataFrame(short, columns=["grain", "period_start", "period_end", "forecast"])
    display(SHORT)
    monthly = live_outlook.meta[["period_start"]].assign(forecast=live_outlook.predictions[OUTLOOK_MODEL])
    PATH = FE.reconcile_path(ORIGIN, monthly, SHORT)
    PERIODS = FE.path_periods(PATH, ORIGIN)
    milk_out = FE.milk_rows(PERIODS, ORIGIN, BANDS_ALL, STEP_BANDS, MARKERS, RECORD_STATUS,
                            MODEL_VERSION, CORE_VERSION)
    check = PERIODS["monthly"].iloc[1:]
    sums = [PATH.loc[PATH["month"] == p, "litres"].sum() for p in check["period_start"]]
    assert np.allclose(sums, check["forecast"]), "daily path does not add up to the months"
herd_out = FE.herd_rows(PATHS, ORIGIN, HERD_BANDS, RECORD_STATUS, MARKERS, MODEL_VERSION,
                        CORE_VERSION, OUTLOOK_MONTHS)
print("Herd rows:", len(herd_out), f"(from the herd-path run of {herd_out['path_run'].iloc[0]})" if len(herd_out) else
      "(no herd-path run on or before the origin)")
parts_ = [f for f in (milk_out, herd_out) if len(f)]
OUTLOOK_ROWS = pd.concat(parts_, ignore_index=True) if parts_ else pd.DataFrame(
    columns=["origin_date", "target_period", "grain", "horizon", "series", "forecast", "lower", "upper",
             "quality_flag", "status", "model_version", "core_version"])
display(OUTLOOK_ROWS.groupby(["series", "grain"]).size().rename("rows").to_frame() if len(OUTLOOK_ROWS)
        else "no forecast rows")
if len(milk_out):
    display(milk_out[milk_out["grain"] == "monthly"][["target_period", "forecast", "lower", "upper",
                                                      "quality_flag", "status"]])
    fig, ax = plt.subplots(figsize=(15, 5))
    hist = daily["litres"].resample("MS").mean()
    hist = hist[hist.index >= ORIGIN - pd.DateOffset(months=24)]
    ax.plot(hist.index, hist, "o-", ms=3, color="black", lw=1, label="recorded (mean litres/day)")
    mo = milk_out[milk_out["grain"] == "monthly"].copy()
    x = pd.to_datetime(mo["target_period"]); days = x.dt.days_in_month
    ax.fill_between(x, mo["lower"] / days, mo["upper"] / days, color="#1f77b4", alpha=0.18, label="5-95% bounds")
    ax.plot(x, mo["forecast"] / days, "o-", ms=3, color="#1f77b4", label=f"monthly ({OUTLOOK_MODEL})")
    ax.plot(PATH["date"], PATH["litres"], lw=0.7, color="#16a34a", label="daily path (reconciled)")
    for r in MARKERS.itertuples():
        c, ls = HO.MARKER_STYLE.get(r.marker, ("black", "--"))
        ax.axvline(ORIGIN + pd.DateOffset(months=r.horizon - 1), color=c, ls=ls, lw=1.3,
                   label=f"{r.marker}: month {r.horizon}")
    ax.set_title("Live herd milk outlook (litres per day)", fontsize=10); ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2, loc="upper left")
    fig.savefig(CHART_DIR / "live_outlook.png", dpi=150, bbox_inches="tight"); plt.show(); plt.close(fig)
print(f"Live run took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 9. Explanations (exact, additive)

For each forecast month: forecast − recent recorded level = **herd size** (projected
milking cows) + **yield level** (recent litres per cow) + the network correction split
by exact Shapley values over input groups (stage, parity and pregnancy mix, heat,
mastitis, …), with the network's output at the training medians and the month-1
short-term overlay as **residual**. Rows are changes from the previous month, so the
parts of each month add up exactly to its change. Past months: each recorded change
split exactly into herd size and litres per cow.
""")

code(r"""
ATTR = pd.DataFrame()
if PERIODS is not None:
    recent = daily.loc[daily.index > DATA_THROUGH - pd.Timedelta(days=28), "litres"].mean()
    fc = FE.outlook_attribution(live_outlook, OUTLOOK_MODEL, ORIGIN, recent, PERIODS["monthly"], DEVICE)
    total = fc.groupby("target_period")["contribution"].sum().cumsum().to_numpy() + recent
    assert np.allclose(total, PERIODS["monthly"]["mean"].to_numpy()), "explanation does not add up"
    ATTR = fc
past = FE.past_attribution(daily)
ATTR = pd.concat([ATTR, past], ignore_index=True).assign(
    origin_date=ORIGIN.date(), grain="monthly", series="herd_milk", model_version=MODEL_VERSION,
    core_version=CORE_VERSION)
if len(ATTR):
    display(ATTR.pivot_table(index=["kind", "target_period"], columns="factor", values="contribution",
                             aggfunc="sum").round(1).head(14))
    fig, axes = plt.subplots(1, 2, figsize=(15, 4.5))
    for ax, (kind, label) in zip(axes, (("forecast", "first forecast month"), ("past", "last recorded month"))):
        sub = ATTR[ATTR["kind"] == kind]
        if sub.empty:
            ax.set_axis_off(); continue
        tp = sub["target_period"].min() if kind == "forecast" else sub["target_period"].max()
        s = sub[sub["target_period"] == tp].groupby("factor")["contribution"].sum()
        s = s[s.abs() > 1e-9].sort_values()
        ax.barh(s.index, s.to_numpy(), color=np.where(s > 0, "#16a34a", "#dc2626"))
        ax.set_title(f"{label} ({tp}): change {s.sum():+,.0f} L/day", fontsize=9); ax.grid(axis="x", alpha=0.3)
    fig.tight_layout(); fig.savefig(CHART_DIR / "explanations.png", dpi=150, bbox_inches="tight")
    plt.show(); plt.close(fig)
ATTR.to_csv(OUT_DIR / "attribution.csv", index=False)
""")

md(r"""
## 10. Evidence: back-test rows, coverage and replay

Back-test rows in **litres per period** (MAE, RMSE, bias, coverage, n) for the published
models, persistence and seasonal naive (same calendar period a year earlier) on the same
origin-periods: monthly horizons 1–24 from the outlook back-tests (pre-test windows =
development, test), daily and weekly from the live one-step models. Replay = the test
forecasts as they were made. Status: `not interpretable` when n < 12.
""")

code(r"""
def step_frame(models, grain, blocks):
    e = FE.onestep_errors(models, LIVE_WINNERS[grain], blocks)
    return e[e["grain"] == grain] if len(e) else e

def band_frame(grain):
    lo, hi, n = STEP_BANDS.get(grain, (np.nan, np.nan, 0))
    return pd.DataFrame({"horizon": [1], "lower_log": [lo], "upper_log": [hi]})

parts = [FE.backtest_rows(pre_errors, daily, OUTLOOK_MODEL, BANDS_PRE, "development"),
         FE.backtest_rows(test_errors, daily, OUTLOOK_MODEL, BANDS_PRE, "test")]
replay = [FE.replay_rows(test_errors, OUTLOOK_MODEL, BANDS_PRE, "monthly", MODEL_VERSION, CORE_VERSION)]
for g in ("daily", "weekly"):
    if g in LIVE_WINNERS:
        parts.append(FE.backtest_rows(step_frame(validation_models, g, ("validation",)), daily,
                                      LIVE_WINNERS[g], band_frame(g), "development", g))
        te = step_frame(final_models, g, ("test",))
        parts.append(FE.backtest_rows(te, daily, LIVE_WINNERS[g], band_frame(g), "test", g))
        replay.append(FE.replay_rows(te, LIVE_WINNERS[g], band_frame(g), g, MODEL_VERSION, CORE_VERSION))
BACKTEST = pd.concat([p for p in parts if len(p)], ignore_index=True)
BACKTEST["status"] = np.where(BACKTEST["n"] < FE.MIN_INTERPRETABLE_N, "not interpretable", "development")
REPLAY = pd.concat([r for r in replay if len(r)], ignore_index=True)
display(BACKTEST.pivot_table(index=["block", "grain", "horizon"], columns="model", values="mae").round(0).head(30))
cov = BACKTEST[(BACKTEST["model"] == "pfoi") & BACKTEST["coverage"].notna()]
print("Share of back-tested periods inside the 5-95% bounds (target about 90%)")
display(cov.assign(inside=cov["coverage"] * cov["n"]).groupby(["block", "grain"])
        .agg(periods=("n", "sum"), inside=("inside", "sum"))
        .assign(coverage_pct=lambda t: 100 * t["inside"] / t["periods"])[["periods", "coverage_pct"]])
BACKTEST.to_csv(OUT_DIR / "backtest_rows.csv", index=False)
REPLAY.to_csv(OUT_DIR / "replay_rows.csv", index=False)
""")

md(r"""
## 10b. Best machine-learning model (when it is not the best model)

The published forecast uses the best model on pre-test data. When that is not a
machine-learning (`torch_*`) model, the best machine-learning outlook and one-step models
are also run with the same outputs (rows, bounds, markers, explanation, back-test) and
saved under `frontend/alternative_<model>/` and in the run document's `alternatives`.
""")

code(r"""
# Best machine-learning model as an alternative outlook (only when it is not the best model).
ALTERNATIVES = []
ML_WINNERS = (no_cow[no_cow["model"].str.startswith(HO.ML_PREFIX)]
              .groupby("grain").first()["model"].to_dict())
print("Best machine-learning one-step models (no notebook 06):", ML_WINNERS)
if ML_MODEL is None or ML_MODEL == OUTLOOK_MODEL:
    print("The best outlook model is a machine-learning model (or none was fitted): one model only.")
elif PERIODS is None or ML_MODEL not in live_outlook.predictions:
    print(f"Milk withheld or {ML_MODEL} not fitted on all data: no alternative outlook.")
else:
    ALT_DIR = FRONT_DIR / f"alternative_{ML_MODEL}"
    ALT_DIR.mkdir(parents=True, exist_ok=True)
    alt_version = f"{MODEL_VERSION}/{ML_MODEL}"
    short_ml = []
    for g in ("daily", "weekly"):
        m = ML_WINNERS.get(g)
        meta = live_step.tables[g]
        i = np.flatnonzero(meta["origin"] >= ORIGIN)
        if m and len(i) and g in live_step.predictions.get(m, {}):
            k = i[0]
            short_ml.append({"grain": g, "period_start": meta["period_start"][k],
                             "period_end": meta["period_end"][k],
                             "forecast": live_step.predictions[m][g][k]})
    SHORT_ML = pd.DataFrame(short_ml, columns=["grain", "period_start", "period_end", "forecast"])
    monthly_ml = live_outlook.meta[["period_start"]].assign(forecast=live_outlook.predictions[ML_MODEL])
    PATH_ML = FE.reconcile_path(ORIGIN, monthly_ml, SHORT_ML)
    PERIODS_ML = FE.path_periods(PATH_ML, ORIGIN)
    step_bands_ml = FE.onestep_bands(validation_models, ML_WINNERS, ("validation",))
    milk_ml = FE.milk_rows(PERIODS_ML, ORIGIN, BANDS_ALL_BY[ML_MODEL], step_bands_ml, MARKERS_BY[ML_MODEL],
                           RECORD_STATUS, alt_version, CORE_VERSION)
    recent = daily.loc[daily.index > DATA_THROUGH - pd.Timedelta(days=28), "litres"].mean()
    attr_ml = FE.outlook_attribution(live_outlook, ML_MODEL, ORIGIN, recent, PERIODS_ML["monthly"], DEVICE)
    total = attr_ml.groupby("target_period")["contribution"].sum().cumsum().to_numpy() + recent
    assert np.allclose(total, PERIODS_ML["monthly"]["mean"].to_numpy()), "explanation does not add up"
    attr_ml = attr_ml.assign(origin_date=ORIGIN.date(), grain="monthly", series="herd_milk",
                             model_version=alt_version, core_version=CORE_VERSION)
    bt_ml = pd.concat([FE.backtest_rows(pre_errors, daily, ML_MODEL, BANDS_PRE_BY[ML_MODEL], "development"),
                       FE.backtest_rows(test_errors, daily, ML_MODEL, BANDS_PRE_BY[ML_MODEL], "test")],
                      ignore_index=True)
    bt_ml["model"] = bt_ml["model"].replace({"pfoi": ML_MODEL})
    bt_ml["status"] = np.where(bt_ml["n"] < FE.MIN_INTERPRETABLE_N, "not interpretable", "development")
    side = (milk_out[milk_out["grain"] == "monthly"][["horizon", "target_period", "forecast", "lower", "upper", "status"]]
            .merge(milk_ml[milk_ml["grain"] == "monthly"][["horizon", "forecast", "lower", "upper", "status"]],
                   on="horizon", suffixes=(f" ({OUTLOOK_MODEL})", f" ({ML_MODEL})")))
    side["ml_vs_best_pct"] = 100 * (side[f"forecast ({ML_MODEL})"] / side[f"forecast ({OUTLOOK_MODEL})"] - 1)
    print(f"Monthly forecasts, litres per month: best ({OUTLOOK_MODEL}) vs best machine-learning ({ML_MODEL})")
    display(side.round(1))
    print("Explanation of the machine-learning outlook (litres/day, change from the previous month)")
    display(attr_ml.pivot_table(index="target_period", columns="factor", values="contribution",
                                aggfunc="sum").round(1).head(12))
    fig, ax = plt.subplots(figsize=(15, 5))
    hist = daily["litres"].resample("MS").mean()
    hist = hist[hist.index >= ORIGIN - pd.DateOffset(months=24)]
    ax.plot(hist.index, hist, "o-", ms=3, color="black", lw=1, label="recorded (mean litres/day)")
    for rows_, name, colour in ((milk_out, OUTLOOK_MODEL, "#1f77b4"), (milk_ml, ML_MODEL, "#dc2626")):
        mo = rows_[rows_["grain"] == "monthly"]
        x = pd.to_datetime(mo["target_period"]); days = x.dt.days_in_month
        ax.fill_between(x, mo["lower"] / days, mo["upper"] / days, color=colour, alpha=0.12)
        ax.plot(x, mo["forecast"] / days, "o-", ms=3, color=colour, label=f"{name} (5-95% bounds shaded)")
    ax.set_title("Best model vs best machine-learning model (litres per day)", fontsize=10)
    ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.savefig(ALT_DIR / "best_vs_ml_outlook.png", dpi=150, bbox_inches="tight"); plt.show(); plt.close(fig)
    milk_ml.to_csv(ALT_DIR / "milk_rows.csv", index=False)
    attr_ml.to_csv(ALT_DIR / "attribution.csv", index=False)
    bt_ml.to_csv(ALT_DIR / "backtest_rows.csv", index=False)
    side.to_csv(ALT_DIR / "best_vs_ml_monthly.csv", index=False)
    ALTERNATIVES.append({
        "model": ML_MODEL, "role": "best machine-learning model (not published as the main forecast)",
        "model_version": alt_version, "one_step_models": ML_WINNERS,
        "outlook": FE.page_rows(milk_ml), "attribution": FE.page_rows(attr_ml),
        "backtest": FE.page_rows(bt_ml),
        "horizon_reliability": json.loads(MARKERS_BY[ML_MODEL].to_json(orient="records"))})
    print("Saved to", ALT_DIR)
""")

md(r"""
## 11. Frontend files: c1_output rows, run document, model state

- `frontend/c1_outlook.csv`, `frontend/c1_attribution.csv`: rows of the shared
  `c1_output` contract (validated by `shared/schemas/pfoi_outlook.py`; series outside
  that contract stay in the run document);
- `frontend/run_document.json`: the run-document keys this model fills, in the page's
  vocabulary (`milk_litres`, `day` / `week` / `month`), including `record_status`,
  `withheld`, `interval_method`, `evidence_ladder`, `horizon_reliability`, `milk_model`,
  `cow06_input`, `herd_path` and `reproducibility`;
- `frontend/model_state.pt`: weights and scalers of the published networks.

Nothing is written to the database; publishing to `c1_output` is a separate step you
decide on. Synthetic runs are labelled `source = demo`.
""")

code(r"""
first = {r.marker: r.horizon for r in MARKERS.itertuples()}
supported_to = (ORIGIN + pd.DateOffset(months=first.get("untested_from", OUTLOOK_MONTHS + 1) - 1)
                - pd.Timedelta(days=1)).date()
CONFIG = {"model_version": MODEL_VERSION, "data_scope": DATA_SCOPE, "split": SPLIT,
          "min_period_coverage": MIN_PERIOD_COVERAGE, "selection_blocks": SELECTION_BLOCKS,
          "window_blocks": WINDOW_BLOCKS, "herd_params": HERD_PARAMS, "ensemble": ENSEMBLE,
          "outlook_months": OUTLOOK_MONTHS, "outlook_ensemble": OUTLOOK_ENSEMBLE,
          "milking_path": PATH_KIND, "cow_models": COW_MODEL_BY_GRAIN, "cow_max_epochs": COW_MAX_EPOCHS,
          "drop_pp": DROP_PP, "reliable_within10": RELIABLE_WITHIN10, "bounds": FE.Q, "seed": SEED}
nets_to_save = {}
if OUTLOOK_MODEL in live_outlook.nets:
    nets_to_save["outlook/" + OUTLOOK_MODEL] = live_outlook.nets[OUTLOOK_MODEL]
if live_step is not None:
    for g, m in LIVE_WINNERS.items():
        if m in live_step.nets.get(g, {}):
            nets_to_save[f"one_step/{g}/{m}"] = live_step.nets[g][m]
saved = FE.save_model_state(FRONT_DIR / "model_state.pt", nets_to_save) if nets_to_save else []
import torch
reproducibility = {
    "config_hash": FE.config_hash(CONFIG), "config": json.loads(json.dumps(CONFIG, default=str)),
    "seeds": [SEED + 101 * i for i in range(max(ENSEMBLE, OUTLOOK_ENSEMBLE))],
    "selection_train_end": str(SELECTION_TRAIN_END), "validation_end": str(VALID_END),
    "test_start": str(TEST_START), "data_through": str(DATA_THROUGH.date()),
    "cow_cuts": [str(pd.Timestamp(c).date()) for c in CUTS], "saved_networks": saved,
    "versions": {"torch": torch.__version__, "pandas": pd.__version__, "numpy": np.__version__},
}
milk_model = {
    "model_version": MODEL_VERSION, "status": "development",
    "reason": RECORD_STATUS["reason_text"],
    "selected_model": f"monthly: {OUTLOOK_MODEL}; daily: {LIVE_WINNERS.get('daily')}; "
                      f"weekly: {LIVE_WINNERS.get('weekly')}",
    "model_family": "litres per cow x herd-movement milking path, PyTorch correction",
    "is_neural_network": OUTLOOK_MODEL.startswith("torch") or any(
        str(m).startswith("torch") for m in LIVE_WINNERS.values()),
    "supported_from": str(ORIGIN.date()), "supported_to": str(supported_to),
    "dependency": PATH_KIND,
    "intervals": "5/95% empirical quantiles of back-test errors per horizon band; daily and "
                 "weekly combine one-step and monthly errors in quadrature",
}
cow06_input = {"model_version": TORCH_MODEL_NAME, "models": COW_MODEL_BY_GRAIN,
               "used_live": False, "evaluated_in": ["evidence_ladder", "with_without_nb06_test.csv"],
               "reason": "per-cow mean is over the cows recorded in the period, known only afterwards",
               "best_with_nb06": SELECTED}
herd_path = {"kind": PATH_KIND, "runs": len(PATHS.runs), "failed_runs": len(PATHS.failed),
             "backtest_months": int(herd_errors["period_start"].nunique()) if len(herd_errors) else 0}
interval_method = {"milk": "empirical_quantiles",
                   "staleness_scale": "none: milk withheld after 28 days without trusted records",
                   "staleness_days": RECORD_STATUS["staleness_days"], "cow_model": "not used live"}
c1_outlook, c1_attr = FE.c1_tables(OUTLOOK_ROWS, ATTR) if len(OUTLOOK_ROWS) else (pd.DataFrame(), pd.DataFrame())
DOC = FE.run_document(source="demo" if USE_SYNTHETIC else "model", model_version=MODEL_VERSION,
                      core_version=CORE_VERSION, origin=ORIGIN, data_through=DATA_THROUGH,
                      outlook=OUTLOOK_ROWS, attribution=ATTR, backtest=BACKTEST, replay=REPLAY,
                      record_status=RECORD_STATUS, withheld=WITHHELD, interval_method=interval_method,
                      ladder=LADDER, markers=MARKERS, milk_model=milk_model, cow06_input=cow06_input,
                      herd_path=herd_path, reproducibility=reproducibility,
                      alternatives=ALTERNATIVES)
c1_outlook.to_csv(FRONT_DIR / "c1_outlook.csv", index=False)
c1_attr.to_csv(FRONT_DIR / "c1_attribution.csv", index=False)
(FRONT_DIR / "run_document.json").write_text(json.dumps(DOC, indent=1, default=str))
summary = pd.DataFrame([(k, len(v) if isinstance(v, list) else ("object" if isinstance(v, dict) else v))
                        for k, v in DOC.items()], columns=["key", "rows / value"])
display(summary)
print("c1_output rows:", len(c1_outlook), "outlook,", len(c1_attr), "attribution")
print("Config hash:", reproducibility["config_hash"], "| files in", FRONT_DIR)
print(f"Notebook total: {time.perf_counter() - NOTEBOOK_START:,.0f}s")
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
    target = Path(__file__).with_name("09_herd_milk_frontend.ipynb")
    target.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
