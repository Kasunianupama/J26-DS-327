"""Write ``05_individual_cow_accuracy.ipynb`` with empty outputs.

The committed notebook is generated from reviewable source.  Agents may run it only with
the synthetic setting; the user runs the real-data setting locally.
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
# Farm X: individual-cow milk-yield model comparison

This notebook uses a strict chronological development protocol:

- **recording gap excluded:** cow records from May 2022 to October 2025 are sparse
  fragments with implausibly low yields; section 1b shows the evidence, and these
  cow-days are neither trained on nor scored. Clean recording resumes on 2025-11-01;
- **75 / 5 / 20 split by cow-days:** the remaining clean cow-days are cut, in time order,
  into training (75%), validation/model selection (5%) and an untouched final test (20%);
  section 1b prints the cut dates and achieved shares;
- **final refit:** training plus validation, weights then frozen for the test; and
- **yearly refit (section 6b):** the selected families refitted every test year.

It compares:

1. a persistence benchmark (the cow's latest earlier record);
2. a mixed-effects Wood lactation curve;
3. an Explainable Boosting Machine lactation curve;
4. Ridge, random-forest, two-layer neural MLP and LightGBM corrections using identical
   origin-safe history.

**Health and treatment history are model inputs.** Every `core.health_episode` (mastitis,
udder/teat, preventive and other health groups, diagnosis groups, categories, diagnosis
names, milk-withhold periods) and every `core.treatment_history` record (treatment name,
diagnosis, course length, diverted milk) is encoded for each cow-day using only events
dated **strictly before** that day: 30- and 365-day counts, days since the last event,
active withhold/treatment flags and one-hot counts of the most frequent training labels.
Sensor values (`core.daily_milk`) enter as the cow's previous-record value and THI as the
previous day's value; same-day values are never used.

**Recent level.** The residual models also see the herd's and the cow's recent yield
relative to the Wood curve (last 28 days of all recorded cow-days; the cow's last 7
records), measured before the forecast origin. This lets a frozen model follow herd-wide
level shifts.

**Herd campaigns are not illness.** A treatment given to 20 or more cows on the same day
is counted as a campaign (vaccination, preventive dosing), separately from individual
treatments.

**Unavailable is not zero and not null.** When a source table has fewer than
`MIN_SOURCE_RECORDS_PER_YEAR` records in a calendar year, its features for that year are marked `unavailable` (a 0/1 flag plus a status
column), so the models learn to rely on health and treatment history only in the years it
was recorded. A cow with no prior sensor value in a recorded year is `missing`. A missing
diagnosis or treatment is never treated as proof of health.

The target is a unique `core.animal_daily` cow-day record in `(0, 18]` litres. Placeholder,
unlinked, bad-date and duplicate cow-days are excluded in SQL and checked again in Python.
Shipment milk is never read.

Cleaning is applied at the source boundary:

- `core.animal_daily`: require `animal_key <> 'A_PLACEHOLDER'`, the animal placeholder
  flag to be false, and `0 < yield_litres <= 18`;
- `model_input2.day_panel` elsewhere in PFOI: never use its stored milk total. Rebuild the
  target from `milk_per_recorded_cow` (which is based on identified cow records at or below
  18 L) and remove the day if that reconstructed per-cow value is outside `(0, 18]`.

This individual-cow notebook uses the first path. It does not combine `day_panel` milk
with the cow-day target.

Cow identifiers are replaced by per-run integers and remain internal. The notebook creates
separate internal training, validation and test dataframes, but displays only aggregate
split summaries. Model weights stay frozen after development. In the walk-forward test,
only yields from strictly earlier dates may become lag features.
Metrics are calculated on cow-day, cow-week and cow-month errors before aggregation.

The model families follow the supplied research: Wood/lactation-curve modelling and
quantile ideas (Ranzato et al.), Ridge/RF/boosting comparisons and feature ablations
(Hooker et al.; Lasser et al.), interpretable nonlinear curves, and missing-modality
caution (Liu et al.; Nguyen et al.). CNN encoder-decoder lactation forecasting
(Liseune et al.) is represented here by a compact neural baseline, while their full
encoder-decoder CNN remains a future experiment because this split does not provide
complete prior lactations for a fair like-for-like training set.

| Supplied research idea | Notebook decision |
|---|---|
| Ranzato et al. (2024): compare biologically meaningful lactation curves | Wood mixed-effects baseline; retain nonlinear curve alternatives |
| Hooker et al. (2025): Ridge, RF and boosting | Same-split origin-safe Ridge/RF/LightGBM models |
| Liseune et al. (2021): deep encoder-decoder for the next lactation curve | Two-layer MLP baseline now; full CNN only after constructing complete-lactation cohorts |
| Lasser et al. (2023): diverse sources and source ablation | Catalogue unavailable modalities, but exclude them from forecast candidates |
| Liu et al. (2023) and Nguyen et al. (2025): robust missing modalities | Preserve missingness; never convert absent health/treatment records into healthy labels |

The unrelated vision, social-network and LLM-orchestration papers are not treated as
evidence for a milk-yield estimator. They can inform later components or orchestration,
but adding them here would not make this holdout comparison more valid.
""")

code(r"""
USE_SYNTHETIC = True       # Set False yourself for the read-only Farm X run.
INPUT_SCHEMA = "model_input2"
MIN_COWS_PER_DAY = 10
MIN_PERIOD_COVERAGE = 1.00
INCLUDE_EBM = True
VERBOSE = True
SEED = 17
EVALUATION_MODE = "walk_forward"
MIN_SOURCE_RECORDS_PER_YEAR = 100  # fewer records in a calendar year => source unavailable
RUN_YEARLY_BACKTEST = True         # section 6b: refit every year (slow on real data)
EXCLUDE_RECORDING_GAP = True       # drop May 2022 - Oct 2025 cow fragments (section 1b)
SPLIT = (0.75, 0.05, 0.20)         # train / validation / test share of clean cow-days
# CPU only (no GPU). Set N_JOBS = 1, PARALLEL_GRAINS = False and PARALLEL_FOLDS = 1 to run
# everything one step at a time if anything misbehaves.
N_JOBS = -1                        # CPU cores for LightGBM / random forest (-1 = all)
PARALLEL_GRAINS = True             # daily / weekly / monthly models in parallel processes
PARALLEL_FOLDS = 3                 # yearly refit folds run at the same time
TUNE_HYPERPARAMETERS = True        # section 4a: time-series search inside training only
N_TRIALS_LGBM = 30                 # LightGBM settings tried (trial 0 = current default)
N_TRIALS_RF = 8                    # random-forest settings tried (slower per trial)
RUN_WINDOW_STUDY = True            # section 6c: train on one block, test on the next
WINDOW_BLOCKS = 5                  # equal-sized chronological blocks -> 4 windows

from pathlib import Path
from datetime import date
import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

COMPONENT_DIR = Path.cwd().resolve()
if COMPONENT_DIR.name == "notebooks":
    COMPONENT_DIR = COMPONENT_DIR.parent
REPO_ROOT = COMPONENT_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from components.predictive_farm_intelligence.pfoi.cow_accuracy import (
    TRAIN_START, TEST_END, RECORDING_GAP,
    BASE_FEATURES, EXPERIMENT_VERSION, LEVEL_FEATURES, COW_MODEL_NAME, COW_MODEL_VERSION,
    COW_TEST_NAME, chronological_split, cow_accuracy_sql,
    exclude_recording_gap, recording_gap_check,
    expanding_backtest, fit_accuracy_models, load_accuracy_inputs,
    plot_model_performance, prepare_accuracy_frame,
    feature_catalogue, lgbm_shap_summary, safe_column_profile, safe_input_summary,
    safe_test_coverage_by_year,
    safe_split_summary, score_models, score_performance_windows, select_validation_winners,
    split_accuracy_frames, winner_map, write_accuracy_outputs,
    add_blend_candidate, apply_blend_spec, blend_weights_table,
)
from components.predictive_farm_intelligence.pfoi.cow_diagnostics import (
    error_breakdown, herd_level_accuracy, noise_floor, sensor_scale_by_year,
)
from components.predictive_farm_intelligence.pfoi.cow_tuning import (
    build_folds, tune_residual_model,
)
from components.predictive_farm_intelligence.pfoi.cow_runner import (
    equal_record_windows, rolling_window_study, window_summary,
)
from components.predictive_farm_intelligence.pfoi.cow_events import (
    availability_by_year, treatment_campaign_summary,
)

# A kernel that imported pfoi before an update keeps the old code. Restart the kernel
# ("Restart & Run All") whenever this check fails.
assert EXPERIMENT_VERSION == "cow-accuracy-v10", (
    f"stale pfoi module loaded ({EXPERIMENT_VERSION}); restart the kernel")
print("Experiment:", EXPERIMENT_VERSION, "| CPU cores:", os.cpu_count())
print("Model:", COW_MODEL_NAME, f"({COW_MODEL_VERSION})", "| Test:", COW_TEST_NAME)

OUT_DIR = COMPONENT_DIR / "logs" / "pfoi_mi2" / COW_MODEL_NAME / COW_TEST_NAME
if USE_SYNTHETIC:
    # Never mix fictional outputs with Farm X outputs.
    OUT_DIR = OUT_DIR / "synthetic_only"
CHART_DIR = OUT_DIR / "charts"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CHART_DIR.mkdir(parents=True, exist_ok=True)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
print("Mode:", "SYNTHETIC FICTIONAL DATA" if USE_SYNTHETIC else "FARM X READ-ONLY CORE")
import time
NOTEBOOK_START = time.perf_counter()
""")

md(r"""
## 1. Load the restricted modelling frame

The real-data query reads `core.animal_daily` for the target and joins optional
`core.daily_milk` measurements and `core.weather_day`. Two further read-only queries return
the health episodes and treatment records of the same cows (per-run integer only, never the
pseudonym key), and a third returns whole-table record counts per year, which decide when
each source is available. Nothing row-level is displayed.

The following output is year-level only. Individual rows and internal cow integers are
deliberately never displayed.
""")

code(r"""
if USE_SYNTHETIC:
    from components.predictive_farm_intelligence.tests.synthetic_cows import synthetic_cowdays
    # Dense fictional cow-days exercise daily, weekly and monthly scoring. They are not
    # shaped from, or calibrated to, Farm X records.
    s = synthetic_cowdays(n_cows=80, seed=SEED)
    s = s[(s["date"] <= pd.Timestamp(TEST_END))].copy()
    rng = np.random.default_rng(SEED)
    s["litres"] = s["true_litres"] * np.exp(rng.normal(0.0, 0.08, len(s)))
    s = s[s["litres"] <= 18.0].copy()
    ids = {a: i + 1 for i, a in enumerate(sorted(s["animal"].unique()))}
    raw = pd.DataFrame({
        "cow_id": s["animal"].map(ids), "date": s["date"], "litres": s["litres"],
        "dim": s["dim"], "parity_group": s["parity_group"],
        "age_days": 730 + s["dim"], "milkings": 2.0,
        "conductivity": np.nan, "milking_duration_sec": np.nan,
        "avg_blood": np.nan, "avg_cell_count": np.nan, "avg_bcs": np.nan,
        "avg_weight": np.nan, "avg_rectal_temp": np.nan, "thi_mean": 68.0,
    })
    from components.predictive_farm_intelligence.pfoi.cow_events import synthetic_events
    health, treatments, availability = synthetic_events(raw[["cow_id", "date"]], seed=SEED)
else:
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    # ``from_env`` reads the schema from PFOI_MODEL_INPUT_SCHEMA; it has no ``mi``
    # keyword argument. Set the documented configuration before constructing the
    # read-only source. The accuracy target itself is loaded from ``core``.
    os.environ["PFOI_MODEL_INPUT_SCHEMA"] = INPUT_SCHEMA
    source = SqlHerdSource.from_env()
    inputs = load_accuracy_inputs(source, TRAIN_START, TEST_END)
    raw = inputs["raw"]
    health, treatments, availability = (
        inputs["health"], inputs["treatments"], inputs["availability"])

EVENTS = {"health": health, "treatments": treatments, "availability": availability}
print("Eligible input rows:", f"{len(raw):,}")
print("Health episodes of modelled cows:", f"{len(health):,}")
print("Treatment records of modelled cows:", f"{len(treatments):,}")
# Aggregate: how many treatment records per year are herd campaigns vs individual cows.
display(treatment_campaign_summary(treatments))
print("Columns loaded:", len(raw.columns), "(identifiers are not displayed)")
""")

md(r"""
### 1b. Recording gap and the 75 / 5 / 20 split

The table shows, per year, cow-days, cows, mean litres and mean recorded milkings per
cow-day (aggregate only). Years inside the recording gap have few cow-days and low yields;
if they also show fewer recorded milkings, the low yields are partial records rather than
a real fall in production. With `EXCLUDE_RECORDING_GAP = True` those cow-days are removed
before any modelling.

The clean cow-days are then split in time order. A day is never divided, so achieved
shares can differ from 75 / 5 / 20 by a fraction of a percent.
""")

code(r"""
display(recording_gap_check(raw))
GAP = RECORDING_GAP if EXCLUDE_RECORDING_GAP else None
rows_before = len(raw)
raw = exclude_recording_gap(raw, GAP)
print(f"Recording gap {GAP}: removed {rows_before - len(raw):,} of {rows_before:,} cow-days")

split = chronological_split(raw["date"], SPLIT)
SELECTION_TRAIN_END = split.train_end      # model-selection fit ends here
VALID_START = SELECTION_TRAIN_END + pd.Timedelta(days=1).to_pytimedelta()
VALID_END = split.validation_end           # winners chosen on VALID_START..VALID_END
FINAL_TRAIN_END = VALID_END                # final refit: training + validation
TEST_START = split.test_start              # untouched test from here
display(split.summary)
""")

md(r"""
### Data-cleaning contract checks

These are executable checks, not descriptive claims. The real-data SQL must select the
individual-cow target only from `core.animal_daily`; shipment, internal-milk and historical
herd-total columns are forbidden. It must also exclude placeholder, unlinked, bad-date,
invalid-yield, duplicate and out-of-range cow-days.

The displayed evidence is aggregate only. No cow identifier or individual row is printed.
The notebook stops immediately if any required cleaning condition fails.
""")

code(r"""
target_sql = cow_accuracy_sql("core")
forbidden_milk_fields = (
    "milk_shipped", "milk_internal", "milk_hand_milked_est", "milk_delpro",
    "herd_milk_measured", "milk_observed_placeholder_litres",
)
forbidden_source_keys = {"animal_key", "record_key", "group_key"}

litres = pd.to_numeric(raw["litres"], errors="coerce")
dates = pd.to_datetime(raw["date"], errors="coerce")
duplicate_cow_days = int(raw.duplicated(["cow_id", "date"], keep=False).sum())
outside_range = int((litres.isna() | ~litres.gt(0) | ~litres.le(18.0)).sum())
outside_dates = int((dates.isna()
                     | dates.lt(pd.Timestamp(TRAIN_START))
                     | dates.gt(pd.Timestamp(TEST_END))).sum())
forbidden_columns_loaded = sorted(
    set(raw.columns).intersection(forbidden_source_keys.union(forbidden_milk_fields))
)

cleaning_checks = pd.DataFrame([
    {
        "check": "target source is core.animal_daily",
        "passed": "FROM core.animal_daily" in target_sql,
        "aggregate_evidence": "required source clause present",
    },
    {
        "check": "shipment/history/placeholder-total fields are absent",
        "passed": not any(name in target_sql for name in forbidden_milk_fields),
        "aggregate_evidence": "0 forbidden target fields referenced",
    },
    {
        "check": "placeholder animals are excluded",
        "passed": ("d.animal_key <> 'A_PLACEHOLDER'" in target_sql
                   and "NOT COALESCE(a.is_placeholder, false)" in target_sql),
        "aggregate_evidence": "both placeholder predicates present",
    },
    {
        "check": "invalid, bad-date and unlinked records are excluded",
        "passed": ("d.is_yield_valid" in target_sql
                   and "NOT COALESCE(d.is_bad_date, false)" in target_sql
                   and "NOT COALESCE(d.is_unlinked_animal, false)" in target_sql),
        "aggregate_evidence": "all three validity predicates present",
    },
    {
        "check": "yield is restricted to (0, 18] litres",
        "passed": outside_range == 0,
        "aggregate_evidence": f"out-of-range rows after loading: {outside_range:,}",
    },
    {
        "check": "one row per cow and date",
        "passed": duplicate_cow_days == 0,
        "aggregate_evidence": f"duplicate cow-day rows after loading: {duplicate_cow_days:,}",
    },
    {
        "check": "dates are inside the declared experiment",
        "passed": outside_dates == 0,
        "aggregate_evidence": f"out-of-window or invalid dates: {outside_dates:,}",
    },
    {
        "check": "restricted source keys and forbidden milk fields are not retained",
        "passed": len(forbidden_columns_loaded) == 0,
        "aggregate_evidence": f"forbidden loaded columns: {len(forbidden_columns_loaded)}",
    },
])
cleaning_checks["status"] = np.where(cleaning_checks["passed"], "PASS", "FAIL")
display(cleaning_checks[["status", "check", "aggregate_evidence"]])

assert cleaning_checks["passed"].all(), "Data-cleaning contract failed; do not fit models"
print("Clean target range (aggregate):",
      f"min={litres.min():.3f} L, max={litres.max():.3f} L")
""")

md(r"""
## 2. Privacy-safe data analysis

This profile shows the available columns, data types, aggregate non-null counts,
missingness and cardinality. It deliberately excludes the internal cow integer and every
source key. No individual cow row or example value is displayed.
""")

code(r"""
raw_column_profile = safe_column_profile(raw)
display(raw_column_profile)
""")

md(r"""
## 3. Feature engineering design and source availability

The catalogue lists every time-safe feature used by the residual models, including the
health, treatment, lagged-sensor and lagged-weather families, and the same-day fields
that stay excluded. A prediction for day *t* uses facts dated before *t* only.

The source table shows, per calendar year, the whole-table record counts for
`health_episode` and `treatment_history`. A year below `MIN_SOURCE_RECORDS_PER_YEAR` is
`unavailable`. The availability table then shows, per family and year, the share of
cow-days that are available, missing or unavailable.
""")

code(r"""
source_years = (availability.pivot_table(index="year", columns="source", values="records",
                                         aggfunc="sum", fill_value=0)
                .reindex(range(TRAIN_START.year, TEST_END.year + 1), fill_value=0))
source_status = source_years.ge(MIN_SOURCE_RECORDS_PER_YEAR).replace(
    {True: "available", False: "unavailable"})
display(source_years.join(source_status, rsuffix="_status"))

preview = prepare_accuracy_frame(
    raw, train_end=FINAL_TRAIN_END, validation_end=FINAL_TRAIN_END,
    evaluation_mode=EVALUATION_MODE, events=EVENTS,
    min_source_records=MIN_SOURCE_RECORDS_PER_YEAR,
)
event_features = preview.attrs["event_features"]
print("Model features:", len(BASE_FEATURES) + len(event_features) + len(LEVEL_FEATURES),
      f"({len(event_features)} health/treatment/sensor/weather, "
      f"{len(LEVEL_FEATURES)} recent level)")
print("Sensor columns dropped (empty, <1% filled or constant):",
      preview.attrs.get("dropped_sensors", []))
display(feature_catalogue(list(event_features) + list(LEVEL_FEATURES)))
family_availability = availability_by_year(preview)
display(family_availability.pivot_table(index="year", columns="family", values="status",
                                        aggfunc="first"))
""")

md(r"""
### 3b. Diagnostics before modelling: noise floor and sensor scales

**Noise floor.** For pairs of records of the same cow, in the same lactation, 1–3 days
apart: how much does her recorded yield change? If two records two days apart already
differ by a median of x%, no model predicting a single cow-day can reliably beat roughly
that error. `short_gap_persistence_accuracy_pct` is the accuracy of "same as a record 1–3
days earlier" on those pairs, an empirical ceiling for daily per-cow accuracy.

**Sensor scales.** Per-year mean, median and share of zeros of each sensor. A sensor
whose scale jumps between years (e.g. milkings recorded as 0 in 2020) misleads a model
trained on one regime and tested on another; 0 milkings is now treated as missing.
""")

code(r"""
NOISE_FLOOR = noise_floor(preview)
SENSOR_SCALES = sensor_scale_by_year(raw)
display(NOISE_FLOOR)
display(SENSOR_SCALES)
NOISE_FLOOR.to_csv(OUT_DIR / "diagnostics_noise_floor.csv", index=False)
SENSOR_SCALES.to_csv(OUT_DIR / "diagnostics_sensor_scales.csv", index=False)
split.summary.to_csv(OUT_DIR / "split_summary.csv", index=False)
del preview
""")

md(r"""
## 4. Development fit and validation

All candidate models are first fitted on the training block (75% of clean cow-days). Only
the validation block (the next 5%) is used to select the winning model separately at
daily, weekly and monthly grain.
Public charts show mean litres per recorded cow-day, never a herd total, shipment total,
placeholder total or stored `period_panel` total.
No test-block accuracy is inspected during selection.

Residual models predict a bounded log correction to the Wood baseline. Validation is
walk-forward: each previous outcome becomes available only after its date has passed.
""")

md(r"""
### 4a. Time-series hyperparameter tuning (training block only)

The training block is split into four expanding folds (train up to the 60th, 70th, 80th
and 90th percentile of training cow-days, score the next slice, walk-forward). Each
setting is scored by pooled WAPE over the folds. Trial 0 is the previous default, so
the table shows whether tuning helped. Validation and test cow-days are never used.
The tuned settings are used for every grain (they are tuned on the daily forecast).
""")

code(r"""
LGBM_PARAMS, RF_PARAMS = {}, {}
if TUNE_HYPERPARAMETERS:
    tuning_folds = build_folds(raw, SELECTION_TRAIN_END, events=EVENTS,
                               min_source_records=MIN_SOURCE_RECORDS_PER_YEAR,
                               verbose=VERBOSE)
    LGBM_PARAMS, lgbm_trials = tune_residual_model(
        tuning_folds, "lgbm", n_trials=N_TRIALS_LGBM, seed=SEED, n_jobs=N_JOBS,
        verbose=VERBOSE)
    display(lgbm_trials.head(10))
    lgbm_trials.to_csv(OUT_DIR / "tuning_lgbm_trials.csv", index=False)
    if N_TRIALS_RF > 0:
        RF_PARAMS, rf_trials = tune_residual_model(
            tuning_folds, "rf", n_trials=N_TRIALS_RF, seed=SEED, n_jobs=N_JOBS,
            verbose=VERBOSE)
        display(rf_trials.head(10))
        rf_trials.to_csv(OUT_DIR / "tuning_rf_trials.csv", index=False)
    del tuning_folds
print("LightGBM settings:", LGBM_PARAMS or "default")
print("Random-forest settings:", RF_PARAMS or "default")
""")

code(r"""
validation_models = fit_accuracy_models(
    raw,
    include_ebm=INCLUDE_EBM,
    lgbm_kwargs={**LGBM_PARAMS, "random_state": SEED},
    rf_kwargs=RF_PARAMS,
    ebm_kwargs={"outer_bags": 8, "interactions": 3, "random_state": SEED},
    train_end=SELECTION_TRAIN_END,
    validation_end=VALID_END,
    evaluation_mode=EVALUATION_MODE,
    events=EVENTS,
    min_source_records=MIN_SOURCE_RECORDS_PER_YEAR,
    n_jobs=N_JOBS,
    parallel_grains=PARALLEL_GRAINS,
    verbose=VERBOSE,
)
selection_parts = split_accuracy_frames(validation_models.frame)
selection_train_df = selection_parts["train"]
validation_df = selection_parts["validation"]
selection_future_test_df = selection_parts["test"]
display(safe_split_summary(selection_parts))
display(safe_input_summary(validation_models.frame))
display(safe_column_profile(validation_models.frame))
print("Candidate models:", ", ".join(validation_models.predictions))
""")

md(r"""
### Aggregate TreeSHAP feature importance

LightGBM's native TreeSHAP contributions are calculated on at most 2,000 validation
cow-days, then immediately aggregated to mean absolute and signed contribution. No
per-cow SHAP values, identifiers or rows are displayed or saved. These values explain
the model's **log correction to Wood**, not litres directly.
""")

code(r"""
display(lgbm_shap_summary(
    validation_models, "lgbm_residual_history", period="validation", max_rows=2000,
).head(15))
""")

md(r"""
## 5. Select winners using the validation block only

Only cows with at least three strictly earlier records and a biologically valid DIM are
scoreable. New cows become eligible after accumulating three prior observations. No cow
roster is used to construct a herd total. Weeks and months require
100% calendar coverage. Chart values are mean yield per eligible cow-day, while MAE,
RMSE, WAPE, bias and the within-10% rate are calculated on individual cow-period errors
before public aggregation, so different cows' errors cannot cancel.

**Recalibrated candidates (`*_recal`).** Every model also appears rescaled by the herd's
recent actual/predicted ratio over the 28 days before the forecast origin (past outcomes
only, shrunk towards 1, clipped to 0.7–1.4). This corrects level bias such as the 2026
under-prediction without refitting.

**Blend.** The best single candidate per grain is mixed with persistence ("same as the
cow's last record"), with a weight per days-since-record band fitted on validation. The
blend's validation score is cross-fitted (weights from one half of validation score the
other half), so it competes fairly with the single models.
""")

code(r"""
validation_metrics, validation_performance = score_models(
    validation_models,
    min_cows=MIN_COWS_PER_DAY,
    min_coverage=MIN_PERIOD_COVERAGE,
    blocks=("validation",),
)
best_single = (validation_metrics[validation_metrics["model"] != "persistence_last_yield"]
               .sort_values("wape_pct").groupby("grain")["model"].first().to_dict())
BLEND_SPEC = add_blend_candidate(validation_models, best_single, block="validation")
display(blend_weights_table(BLEND_SPEC))
blend_weights_table(BLEND_SPEC).to_csv(OUT_DIR / "blend_weights.csv", index=False)
validation_metrics, validation_performance = score_models(
    validation_models,
    min_cows=MIN_COWS_PER_DAY,
    min_coverage=MIN_PERIOD_COVERAGE,
    blocks=("validation",),
)
validation_metrics = validation_metrics.sort_values(
    ["grain", "wape_pct", "model"]
).reset_index(drop=True)
winners = select_validation_winners(validation_metrics, metric="wape_pct")
display(validation_metrics)
display(winners[["grain", "model", "accuracy_pct", "within_10pct", "wape_pct",
                 "mae_per_cow_day", "bias_pct", "skill_vs_persistence_pct"]])
validation_metrics.to_csv(OUT_DIR / "validation_metrics_all_candidates.csv", index=False)
winners.to_csv(OUT_DIR / "validation_winners.csv", index=False)
""")

md(r"""
## 6. Final refit and untouched test

After model selection is fixed, the candidate families are refitted on training plus
validation and their weights stay frozen. The test is walk-forward: a test yield is not
used for its own prediction, but becomes historical information for a later date. Current
DIM, parity and age are treated as operationally known covariates. This evaluates conditional
individual-cow yield, not the ability to forecast the future herd population.
""")

code(r"""
final_models = fit_accuracy_models(
    raw,
    include_ebm=INCLUDE_EBM,
    lgbm_kwargs={**LGBM_PARAMS, "random_state": SEED},
    rf_kwargs=RF_PARAMS,
    ebm_kwargs={"outer_bags": 8, "interactions": 3, "random_state": SEED},
    train_end=FINAL_TRAIN_END,
    validation_end=FINAL_TRAIN_END,
    evaluation_mode=EVALUATION_MODE,
    events=EVENTS,
    min_source_records=MIN_SOURCE_RECORDS_PER_YEAR,
    n_jobs=N_JOBS,
    parallel_grains=PARALLEL_GRAINS,
    verbose=VERBOSE,
)
apply_blend_spec(final_models, BLEND_SPEC)  # weights from validation, never refitted
final_parts = split_accuracy_frames(final_models.frame)
final_train_df = final_parts["train"]
final_test_df = final_parts["test"]
display(safe_split_summary(final_parts))
display(safe_test_coverage_by_year(final_models.frame, test_start=TEST_START))
final_metrics, final_performance = score_models(
    final_models,
    min_cows=MIN_COWS_PER_DAY,
    min_coverage=MIN_PERIOD_COVERAGE,
    blocks=("test",),
    selected=winner_map(winners),
)
final_metrics = final_metrics.sort_values("grain").reset_index(drop=True)
display(safe_input_summary(final_models.frame))
display(final_metrics)

# Public weekly/monthly chart frames must be complete periods and remain mean cow-day
# yields. They are not shipment totals, stored period totals or partial herd sums.
period_checks = []
for model, grains in final_performance.items():
    for grain, frame in grains.items():
        if grain not in {"weekly", "monthly"} or frame.empty:
            continue
        min_coverage = float(frame["coverage"].min())
        passed = min_coverage == 1.0 and frame["actual"].gt(0).all()
        period_checks.append({
            "model": model,
            "grain": grain,
            "status": "PASS" if passed else "FAIL",
            "periods": len(frame),
            "minimum_day_coverage": min_coverage,
            "mean_cow_period_litres_min": float(frame["actual"].min()),
            "mean_cow_period_litres_max": float(frame["actual"].max()),
            "passed": passed,
        })
period_cleaning_checks = pd.DataFrame(period_checks)
display(period_cleaning_checks.drop(columns="passed"))
assert len(period_cleaning_checks) > 0
assert period_cleaning_checks["passed"].all(), (
    "Weekly/monthly cleaning failed: incomplete periods or a period total reached the chart"
)

TEST_WINDOWS = {"test_all": (TEST_START, TEST_END)}
TEST_WINDOWS.update({f"test_{y}": (max(date(y, 1, 1), TEST_START), min(date(y, 12, 31), TEST_END))
                     for y in range(TEST_START.year, TEST_END.year + 1)})
test_window_metrics = score_performance_windows(final_performance, TEST_WINDOWS)
display(test_window_metrics)
""")

md(r"""
### Test-set prediction accuracy

How to read the accuracy columns (all computed per cow-day, cow-week or cow-month before
pooling, so errors of different cows cannot cancel):

| Column | Meaning |
|---|---|
| `accuracy_pct` | 100 − WAPE: share of recorded litres predicted correctly |
| `within_5pct` / `within_10pct` / `within_20pct` | % of cow-periods predicted within ±5/10/20% |
| `mape_pct`, `median_ape_pct`, `smape_pct` | mean, median and symmetric absolute % error |
| `r2`, `pearson_r` | explained variance and correlation of predicted vs actual |
| `mase`, `skill_vs_persistence_pct` | error relative to "same as the cow's last record" (skill > 0 beats it) |
| `mae_per_cow_day` | litres of absolute error per recorded cow-day, comparable across grains |
| `status` | `insufficient data` when no cow-period could be scored (not 0% accuracy) |

The validation block was used to choose the winners, so it is shown as its own row and
never pooled into a test score. Years inside the excluded recording gap show
`insufficient data`. A window with
`periods = 0` has no scoreable cow-days (no recorded cows), not zero accuracy.
""")

code(r"""
ACCURACY_COLUMNS = [
    "block", "grain", "model", "status", "periods", "cow_days", "accuracy_pct",
    "within_5pct", "within_10pct", "within_20pct", "mape_pct", "median_ape_pct",
    "smape_pct", "mae_per_cow_day", "rmse", "bias_pct", "r2", "pearson_r", "mase",
    "skill_vs_persistence_pct",
]
validation_rows = validation_metrics.merge(
    winners[["grain", "model"]], on=["grain", "model"]
).assign(block="validation")
accuracy_table = pd.concat([
    validation_rows.reindex(columns=ACCURACY_COLUMNS),
    final_metrics.assign(block="test_all").reindex(columns=ACCURACY_COLUMNS),
], ignore_index=True)
display(accuracy_table)

per_year = test_window_metrics[test_window_metrics["block"].str.fullmatch(r"test_\d{4}")]
display(per_year.pivot_table(index="block", columns="grain",
                             values=["accuracy_pct", "within_10pct", "periods"]))
display(per_year[per_year["status"] != "scored"][["block", "grain", "status"]])
accuracy_table.to_csv(OUT_DIR / "test_accuracy_summary.csv", index=False)
""")

md(r"""
### 6a. Diagnostics: where the selected daily model misses

All tables are aggregates by segment (cow-days, cows, accuracy, bias, within ±10%, and
the accuracy of persistence on the same rows); segments under 20 cow-days are
suppressed. Segments: days since the cow's previous same-lactation record, whether such a
record exists, days in milk, parity, year, how many records the cow had in the 28 days
before, and health/treatment availability. The last table shows the accuracy of the
herd's mean yield per recorded cow-day, where errors of different cows can cancel.
""")

code(r"""
daily_winner = winner_map(winners)
daily_model = next(m for m, grains in daily_winner.items() if "daily" in grains)
print("Daily model diagnosed:", daily_model)
for label, models_, block in (("validation", validation_models, "validation"),
                              ("test", final_models, "test")):
    breakdown = error_breakdown(models_.frame, models_.predictions[daily_model], block=block,
                                naive=models_.predictions["persistence_last_yield"])
    print(f"Error breakdown on the {label} block")
    display(breakdown)
    breakdown.to_csv(OUT_DIR / f"diagnostics_error_breakdown_{label}.csv", index=False)
HERD_LEVEL = herd_level_accuracy(final_performance)
display(HERD_LEVEL)
HERD_LEVEL.to_csv(OUT_DIR / "diagnostics_herd_level_accuracy.csv", index=False)
""")

md(r"""
### 6c. Mini train/test windows: train on one block, test on the next

The clean cow-days are cut, in time order, into `WINDOW_BLOCKS` blocks holding the same
number of records each (whole days are never split), so a block that starts late in a
year is not smaller than the others. With 5 blocks each holds about 20% of the records,
roughly 1.5–2 years of the earlier, densely recorded period. Each block trains a fresh
set of models that is then tested, walk-forward, on the next block.
Each window sees only its own cow-days. Every candidate is scored, and no winner is
chosen here: the point is how each model behaves under different conditions.

The conditions table describes each test block (cow-days, cows, mean yield, records per
cow per month, and how much health, treatment and sensor history was available). The
windows use the tuned settings from section 4a; those were tuned on data up to the
end of the main training block, so early windows carry slight hindsight in their
*settings* (never in their weights or features).
""")

code(r"""
if RUN_WINDOW_STUDY:
    display(pd.DataFrame(equal_record_windows(raw["date"], WINDOW_BLOCKS)))
    window_metrics, window_conditions_table = rolling_window_study(
        raw, EVENTS, lgbm_kwargs={**LGBM_PARAMS, "random_state": SEED}, rf_kwargs=RF_PARAMS,
        include_ebm=False, min_source_records=MIN_SOURCE_RECORDS_PER_YEAR, n_jobs=N_JOBS,
        parallel_grains=PARALLEL_GRAINS, exclude_gap=EXCLUDE_RECORDING_GAP,
        blocks="equal", n_blocks=WINDOW_BLOCKS, verbose=VERBOSE)
    print("Test-block conditions per window")
    display(window_conditions_table)
    for metric in ("accuracy_pct", "within_10pct", "bias_pct", "skill_vs_persistence_pct"):
        print(f"{metric} by window (rows: grain x model)")
        display(window_summary(window_metrics, metric))
    window_metrics.to_csv(OUT_DIR / "window_study_metrics.csv", index=False)
    window_conditions_table.to_csv(OUT_DIR / "window_study_conditions.csv", index=False)
""")

md(r"""
## 6b. Expanding-window yearly refit backtest

The frozen test above keeps one set of weights for the whole test block. Here the
**validation-selected model families** (unchanged) are refitted every test year on all
clean data before that year (the first fold trains up to the day before the test starts)
and scored on forecasts issued in that year. The yield level and later sources can then
adapt. Model weights for year *Y* never see a cow-day dated in *Y*.
""")

code(r"""
if RUN_YEARLY_BACKTEST:
    yearly_models, yearly_folds = expanding_backtest(
        raw, winner_map(winners), events=EVENTS, test_start=TEST_START,
        min_source_records=MIN_SOURCE_RECORDS_PER_YEAR,
        lgbm_kwargs={**LGBM_PARAMS, "random_state": SEED},
        ebm_kwargs={"outer_bags": 8, "interactions": 3, "random_state": SEED},
        n_jobs=N_JOBS, parallel_folds=PARALLEL_FOLDS,
        blend_spec=BLEND_SPEC, rf_kwargs=RF_PARAMS,
        verbose=VERBOSE,
    )
    display(yearly_folds)
    yearly_metrics, yearly_performance = score_models(
        yearly_models, min_cows=MIN_COWS_PER_DAY, min_coverage=MIN_PERIOD_COVERAGE,
        blocks=("test",), selected=winner_map(winners),
    )
    yearly_windows = score_performance_windows(yearly_performance, TEST_WINDOWS)
    yearly_table = pd.concat([
        yearly_metrics.assign(block="refit_test_all").reindex(columns=ACCURACY_COLUMNS),
        yearly_windows[yearly_windows["block"] != "test_all"]
        .assign(block=lambda d: "refit_" + d["block"]).reindex(columns=ACCURACY_COLUMNS),
    ], ignore_index=True)
    display(yearly_table)

    # Side by side: frozen weights vs yearly refits, same windows and winners.
    compare = pd.concat([
        test_window_metrics.assign(design="frozen"),
        yearly_windows.assign(design="yearly_refit"),
    ])
    display(compare.pivot_table(index=["block", "grain"], columns="design",
                                values=["accuracy_pct", "within_10pct", "bias_pct",
                                        "skill_vs_persistence_pct"]))
    yearly_per_year = yearly_windows[yearly_windows["block"].str.fullmatch(r"test_\d{4}")]
    display(yearly_per_year.pivot_table(index="block", columns="grain",
                                        values=["accuracy_pct", "within_10pct",
                                                "bias_pct", "periods"]))
    yearly_table.to_csv(OUT_DIR / "yearly_refit_accuracy_summary.csv", index=False)
    yearly_windows.to_csv(OUT_DIR / "yearly_refit_window_metrics.csv", index=False)
    yearly_folds.to_csv(OUT_DIR / "yearly_refit_folds.csv", index=False)
""")

code(r"""
published_metrics = pd.concat([validation_metrics, final_metrics], ignore_index=True)
write_accuracy_outputs(published_metrics, final_performance, OUT_DIR)
test_window_metrics.to_csv(OUT_DIR / "selected_test_window_metrics.csv", index=False)
""")

md(r"""
## 7. `c1_output` publication gate

These are individual-cow experimental metrics, not herd-total forecasts. Publishing them
as `series='milk_litres'` would falsely imply that the future milking-cow population was
forecast. The notebook therefore writes experiment CSVs only and never inserts or emits
frontend `BacktestRow`/`c1_output.outlook` records. Publication becomes valid only after
the herd engine projects the future milking roster and combines it with a frozen cow or
cohort yield model.
""")

code(r"""
c1_output_readiness = pd.DataFrame([{
    "artifact": "individual cow accuracy experiment",
    "aggregate_only": True,
    "future_roster_projected": False,
    "prediction_intervals_available": False,
    "publish_to_c1_output": False,
    "reason": "requires herd-engine roster and forecast intervals",
}])
display(c1_output_readiness)
""")

md(r"""
## 8. Validation charts and final-test charts

Every candidate receives a validation chart with the final test hidden. Separate final
charts always retain the complete axis through August 2026, with the excluded recording
gap shaded. Gaps in the walk-forward
test line are periods without enough recorded cows (fewer than `MIN_COWS_PER_DAY`) or
without complete weeks/months; they are never filled.
""")

code(r"""
chart_paths = []
for model, grains in validation_performance.items():
    path = CHART_DIR / f"{model}_validation.png"
    fig = plot_model_performance(model, grains, path, show_test_grains=set(),
                                 valid_start=VALID_START, test_start=TEST_START, gap=GAP)
    plt.show()
    plt.close(fig)
    chart_paths.append(path)

for model, grains in final_performance.items():
    selected_grains = winner_map(winners)[model]
    path = CHART_DIR / f"{model}_selected_final_test.png"
    fig = plot_model_performance(model, grains, path, show_test_grains=selected_grains,
                                 valid_start=VALID_START, test_start=TEST_START, gap=GAP)
    plt.show()
    plt.close(fig)
    chart_paths.append(path)

if RUN_YEARLY_BACKTEST:
    for model, grains in yearly_performance.items():
        path = CHART_DIR / f"{model}_yearly_refit_test.png"
        fig = plot_model_performance(model, grains, path,
                                     show_test_grains=winner_map(winners)[model],
                                     valid_start=VALID_START, test_start=TEST_START, gap=GAP)
        fig.suptitle(f"Farm X — {model}: yearly expanding-window refit", fontsize=12)
        plt.show()
        plt.close(fig)
        chart_paths.append(path)

print(f"Notebook model run time: {time.perf_counter() - NOTEBOOK_START:,.0f}s")
print("Saved validation and selected final-test charts:")
for path in chart_paths:
    print(" -", path)
""")

md(r"""
## 9. Interpretation guardrails

- Rank models separately at daily, weekly and monthly grain; do not select from one pooled score.
- Health episodes, treatments, previous-record sensors and previous-day THI are model
  inputs, always dated strictly before the predicted day. Same-day values are excluded.
- Years in which a source table holds no records are `unavailable` (flag + status), not
  zero events and not null; the frozen model adapts to the recording regime through the flag.
- Sparse treatment or mastitis history is a missing-recording problem, not evidence that
  the cow was healthy.
- Walk-forward scoring keeps model weights frozen and uses only earlier outcomes as lags.
  Test years with very few recorded cow-days (see the per-year table) give unstable scores.
- A production herd forecast requires the herd engine to project the future milking
  population and combine it with cow/cohort yield predictions and intervals.
- Model selection uses the validation block only. The test block must not be used to
  change the winner or tune its settings.
- The May 2022 – October 2025 recording gap is excluded, not modelled; clean data resume
  on 2025-11-01. Accuracy is
  claimed only for clean recording periods; the gap years have no individual-cow score.
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
    target = Path(__file__).with_name("05_individual_cow_accuracy.ipynb")
    target.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
