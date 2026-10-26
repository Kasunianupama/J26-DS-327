"""Write ``08_herd_milk_with_cow_model.ipynb`` with empty outputs.

Herd milk (notebook 07) with notebook 06's per-cow yield predictions as an extra input.
Notebooks 06 and 07 are not changed. Agents may run it only with the synthetic setting;
the user runs the real-data setting locally, in its own kernel (PyTorch only).
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
# Farm X: herd milk with notebook 06's per-cow predictions (pfoi-herd-milk-cow06-1.10.0-dev)

Herd milk = milking cows x litres per cow. Notebook 07 takes litres per cow from the
herd's own recent average. This notebook adds **notebook 06's prediction of every
recorded cow's yield** (her lactation stage, parity, history, health) as an input, and
measures whether it helps. Notebooks 06 and 07 are not changed.

- **no leakage:** notebook 06's models are refitted walk-forward here. At each cut they
  are trained on cow-days up to the cut and predict only the next block, so every
  per-cow prediction used is out-of-sample (the first block has none). Daily values use
  records up to the day before; weekly and monthly ones are frozen at the start of the
  week / month, as in notebook 06;
- **herd-level only:** the per-cow predictions are averaged per day / week / month
  (mean predicted litres per recorded cow-day) before they leave the cow model;
- **new candidates:** `cow06_structural` = notebook 06's predicted litres per cow x
  projected milking cows (no training), and `torch_mlp_cow06` = notebook 07's small
  network plus the gap between notebook 06's prediction and the herd's recent litres
  per cow; both also `_recal`. Every notebook 07 candidate is fitted alongside;
- **fair comparison:** every candidate is scored on the same periods, i.e. only where
  a notebook 06 prediction exists; selection is pooled on pre-test data as in 07.

Same target, gap, 75 / 5 / 20 split and protocol as notebook 07. Caveat: the per-cow mean
is over the cows recorded in the period (the target's cohort), which is only known
afterwards; a live forecast would have to assume the recent cohort.
""")

code(r"""
USE_SYNTHETIC = True       # Set False yourself for the read-only Farm X run.
INPUT_SCHEMA = "model_input2"
DATA_SCOPE = "clean"
SPLIT = (0.75, 0.05, 0.20)
MIN_PERIOD_COVERAGE = 1.00
SELECTION_BLOCKS = 4
DEVICE = "cpu"
ENSEMBLE = 3
VERBOSE = True
SEED = 17
# Notebook 06 side. Default: the models notebook 06 selected on Farm X (Kalman level
# per cow, by parity x days in milk for daily/weekly), refitted with one small network.
COW_MODEL_BY_GRAIN = None  # None = notebook 06's Farm X winners; or {"daily": "...", ...}
COW_MAX_EPOCHS = 250
MIN_SOURCE_RECORDS_PER_YEAR = 100
MIN_COWS_PER_DAY = 10
# Herd networks: notebook 07's tuned settings if its tuning file exists, else defaults.
USE_NB07_TUNING = True

import os
import sys
import ast
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
    DEFAULT_PARAMS, HERD_TEST_NAMES, HERD_TORCH_MODEL_NAME, SEARCH_SPACE, add_blend,
    apply_blend, assert_torch_safe_process, chronological_split, equal_day_cuts,
    exclude_gap, expanding_windows, fit_herd_models, gap_for, herd_contract_checks,
    herd_year_summary, plot_herd_forecast, pool_common_parts, resolve_device, score_herd,
)
from components.predictive_farm_intelligence.pfoi.herd_cow_link import (
    HERD_COW_MODEL_NAME, LIGHT_COW_FIT, NB06_FARM_X_WINNERS, cow_herd_predictions,
    cow_pred_series, cow_prediction_summary,
)
if COW_MODEL_BY_GRAIN is None:
    COW_MODEL_BY_GRAIN = dict(NB06_FARM_X_WINNERS)
from components.predictive_farm_intelligence.pfoi.cow_accuracy import (
    TEST_END, TRAIN_START, cow_accuracy_sql, exclude_recording_gap,
)
from components.predictive_farm_intelligence.pfoi.cow_diagnostics import cleaning_contract_checks
assert_torch_safe_process()

GAP = gap_for(DATA_SCOPE)
TEST_NAME = HERD_TEST_NAMES[DATA_SCOPE]
OUT_DIR = COMPONENT_DIR / "logs" / "pfoi_mi2" / HERD_COW_MODEL_NAME / TEST_NAME
NB07_DIR = COMPONENT_DIR / "logs" / "pfoi_mi2" / HERD_TORCH_MODEL_NAME / TEST_NAME
if USE_SYNTHETIC:
    OUT_DIR, NB07_DIR = OUT_DIR / "synthetic_only", NB07_DIR / "synthetic_only"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CHART_DIR = OUT_DIR / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
NOTEBOOK_START = time.perf_counter()
print("Model:", HERD_COW_MODEL_NAME, "| Test:", TEST_NAME, "| Device:", resolve_device(DEVICE))
print("Mode:", "SYNTHETIC FICTIONAL DATA" if USE_SYNTHETIC else "FARM X READ-ONLY model_input2 + core")
print("Notebook 06 models used:", COW_MODEL_BY_GRAIN)
""")

md(r"""
## 1. Herd day table, gap and 75 / 5 / 20 split (as notebook 07)
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
daily = exclude_gap(daily, GAP)
split = chronological_split(pd.Series(daily.index[daily["ok"]]), SPLIT)
SELECTION_TRAIN_END, VALID_END = split.train_end, split.validation_end
FINAL_TRAIN_END, TEST_START = VALID_END, split.test_start
VALID_START = SELECTION_TRAIN_END + timedelta(days=1)
display(split.summary.rename(columns={"cow_days": "herd_days"}))
""")

md(r"""
## 2. Cow-day data for notebook 06's models

The same clean cow-days as notebook 06 (`core.animal_daily`, (0, 18] L, no placeholder),
with the same cleaning contract and the same recording gap removed.
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
## 3. Out-of-sample per-cow predictions (walk-forward)

Cuts: the end of each of the `SELECTION_BLOCKS` pre-test blocks of notebook 07, the end
of selection training and the end of validation. At each cut notebook 06's models are
fitted on cow-days up to it and predict only until the next cut (the last fit, at the
end of validation, predicts the test). The table compares the predicted herd mean per
cow with the recorded mean of the same cows (aggregate).
""")

code(r"""
t0 = time.perf_counter()
pre_test = daily[daily.index <= pd.Timestamp(VALID_END)]
CUTS = list(equal_day_cuts(pre_test, VALID_END, SELECTION_BLOCKS))[:-1] + [
    pd.Timestamp(SELECTION_TRAIN_END), pd.Timestamp(VALID_END)]
COW_FIT = {**LIGHT_COW_FIT, "params": {"max_epochs": COW_MAX_EPOCHS}, "device": DEVICE,
           "seed": SEED, "min_source_records": MIN_SOURCE_RECORDS_PER_YEAR}
cow_table = cow_herd_predictions(raw, EVENTS, CUTS, daily.index.max(), COW_MODEL_BY_GRAIN,
                                 COW_FIT, MIN_COWS_PER_DAY, MIN_PERIOD_COVERAGE, verbose=VERBOSE)
COW_PREDS = cow_pred_series(cow_table)
display(cow_prediction_summary(cow_table, daily))
cow_table.to_csv(OUT_DIR / "nb06_herd_level_predictions.csv", index=False)
d = cow_table[cow_table["grain"] == "daily"].set_index("period_start")
fig, ax = plt.subplots(figsize=(15, 4))
ax.plot(daily.index, daily["per_cow"], ".", ms=2, color="black", label="herd target: litres per milking cow")
ax.plot(d.index, d["pred_litres_per_cow"], ".", ms=2, color="#1f77b4",
        label="notebook 06: mean predicted litres per recorded cow (out-of-sample)")
ax.axvspan(pd.Timestamp(GAP[0]), pd.Timestamp(GAP[1]), color="#e5e7eb", alpha=0.8)
ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_title("Litres per cow per day", fontsize=10)
fig.savefig(CHART_DIR / "nb06_vs_herd_per_cow.png", dpi=150, bbox_inches="tight")
plt.show(); plt.close(fig)
print(f"Cow models took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 4. Herd network settings

Notebook 07's tuned settings are reused when its `tuning_trials.csv` exists (same data
mode), so the comparison with notebook 07 changes only the input; otherwise defaults.
""")

code(r"""
HERD_PARAMS = dict(DEFAULT_PARAMS)
trials_file = NB07_DIR / "tuning_trials.csv"
if USE_NB07_TUNING and trials_file.exists():
    best = pd.read_csv(trials_file).sort_values("mean_accuracy_pct", ascending=False).iloc[0]
    for k in SEARCH_SPACE:
        v = best[k]
        HERD_PARAMS[k] = ast.literal_eval(v) if isinstance(v, str) else v
    HERD_PARAMS["batch_size"] = int(HERD_PARAMS["batch_size"])
    print("Using notebook 07 tuning from", trials_file)
else:
    print("Notebook 07 tuning not found; defaults")
print({k: HERD_PARAMS[k] for k in SEARCH_SPACE})
FIT = {"params": dict(HERD_PARAMS), "device": DEVICE, "seed": SEED,
       "min_coverage": MIN_PERIOD_COVERAGE, "cow_preds": COW_PREDS}
OPTIONS = {"ensemble": ENSEMBLE}
""")

md(r"""
## 5. Validation fit and pooled selection (all candidates, same periods)

As notebook 07: validation plus expanding windows on pre-test data, errors weighted by
litres; the best candidate per grain wins, then a persistence blend if it is better on
validation. Only periods with a notebook 06 prediction are scored, for every candidate,
and each grain is pooled only over the parts in which every candidate exists
(`torch_mlp_cow06` cannot be trained in the first window: no earlier out-of-sample
per-cow predictions), so no model is ranked on an easier subset.
""")

code(r"""
t0 = time.perf_counter()
validation_models = fit_herd_models(daily, SELECTION_TRAIN_END, VALID_END, options=OPTIONS,
                                    verbose=VERBOSE, **FIT)
print("Periods with a notebook 06 prediction:", validation_models.fitted.get("cow06_periods"))
print("Training windows with it:", validation_models.fitted.get("cow06_train_rows"))
vmet = score_herd(validation_models, ("validation",))
sel_windows, sel_conditions = expanding_windows(
    pre_test, VALID_END, SELECTION_BLOCKS, {**FIT, "options": {"ensemble": 1}},
    verbose=VERBOSE)
display(sel_conditions)
parts = [vmet] + ([g for _, g in sel_windows.groupby("window")] if len(sel_windows) else [])
pooled = pool_common_parts(parts, "pooled_selection")
display(pooled[["grain", "model", "parts", "periods", "accuracy_pct", "within_10pct"]])
pooled_winner = (pooled[pooled["model"] != "persistence"].groupby("grain").first()["model"]
                 .to_dict())
print("Pooled winners:", pooled_winner)
BLEND_SPEC = add_blend(validation_models, pooled_winner, block="validation")
validation_metrics = score_herd(validation_models, ("validation",))
rows = []
for grain, base_name in pooled_winner.items():
    v = validation_metrics[validation_metrics["grain"] == grain].set_index("model")
    choice = base_name
    if "blend" in v.index and base_name in v.index and v.loc["blend", "accuracy_pct"] > v.loc[base_name, "accuracy_pct"]:
        choice = "blend"
    rows.append({"grain": grain, "model": choice, "pooled_base": base_name})
winners = pd.DataFrame(rows)
display(winners)
SELECTED = dict(zip(winners["grain"], winners["model"]))
pooled.to_csv(OUT_DIR / "pooled_selection.csv", index=False)
winners.to_csv(OUT_DIR / "winners.csv", index=False)
print(f"Validation stage took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 6. Final refit, untouched test, and with vs without notebook 06

The with/without table pairs each notebook 06 candidate with its notebook 07
counterpart on the same test periods: `cow06_structural` vs `herd_structural` (same
milking projection, per-cow level from notebook 06 vs the herd's recent average) and
`torch_mlp_cow06` vs `torch_mlp_small` (same network, plus the notebook 06 input).
""")

code(r"""
t0 = time.perf_counter()
final_models = fit_herd_models(daily, FINAL_TRAIN_END, FINAL_TRAIN_END, options=OPTIONS,
                               verbose=VERBOSE, **FIT)
apply_blend(final_models, BLEND_SPEC)
test_all = score_herd(final_models, ("test",))
test_all["selected"] = [SELECTED.get(g) == m for m, g in zip(test_all["model"], test_all["grain"])]
COMPARE = ["grain", "model", "selected", "periods", "accuracy_pct", "within_5pct",
           "within_10pct", "mae_litres_per_day", "bias_pct", "skill_vs_persistence_pct"]
display(test_all[COMPARE])
acc = test_all.set_index(["grain", "model"])["accuracy_pct"]
pairs = [("cow06_structural", "herd_structural"), ("cow06_structural_recal", "herd_structural_recal"),
         ("torch_mlp_cow06", "torch_mlp_small"), ("torch_mlp_cow06_recal", "torch_mlp_small_recal")]
rows = []
for grain in test_all["grain"].unique():
    for with_m, without_m in pairs:
        if (grain, with_m) in acc.index and (grain, without_m) in acc.index:
            rows.append({"grain": grain, "with_nb06": with_m, "without_nb06": without_m,
                         "accuracy_with_pct": acc[(grain, with_m)],
                         "accuracy_without_pct": acc[(grain, without_m)],
                         "gain_pp": acc[(grain, with_m)] - acc[(grain, without_m)]})
with_without = pd.DataFrame(rows)
display(with_without)
nb07_test = NB07_DIR / "test_all_candidates.csv"
if nb07_test.exists():
    prev = pd.read_csv(nb07_test)
    prev = prev[prev["selected"]][["grain", "model", "periods", "accuracy_pct", "within_10pct"]]
    print("Notebook 07 selected models on ITS test periods (all periods, not only those with a "
          "notebook 06 prediction; for orientation only)")
    display(prev)
test_all.to_csv(OUT_DIR / "test_all_candidates.csv", index=False)
with_without.to_csv(OUT_DIR / "with_without_nb06_test.csv", index=False)
print(f"Final stage took {time.perf_counter() - t0:,.0f}s")
""")

md(r"""
## 7. Charts
""")

code(r"""
path = CHART_DIR / "selected_final_test.png"
fig = plot_herd_forecast(final_models, SELECTED, path, GAP,
                         "Final refit with notebook 06 input: selected models on the untouched test")
plt.show(); plt.close(fig)
compare = {g: "cow06_structural" for g in final_models.tables
           if "cow06_structural" in final_models.predictions and g in final_models.predictions["cow06_structural"]}
if compare:
    path = CHART_DIR / "cow06_structural_final.png"
    fig = plot_herd_forecast(final_models, compare, path, GAP,
                             "cow06_structural: notebook 06 litres per cow x projected milking cows")
    plt.show(); plt.close(fig)
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
    target = Path(__file__).with_name("08_herd_milk_with_cow_model.ipynb")
    target.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
