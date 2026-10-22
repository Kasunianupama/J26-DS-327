# pfoi-1.8.0-dev: Notebook 6 milk predictor + pfoi-1.2.0-dev herd (development, files only)

Status 2026-10-22: implemented and tested on synthetic data. Not run on Farm X data yet,
not evaluated, not published. pfoi-1.2.0-dev files are read, never rewritten.

## 1. Notebook 6 selection protocol (from `notebooks/build_06_cow_yield_torch.py`)

- Data: clean `core.animal_daily` cow-days in (0, 18] L; the recording gap
  2022-05-01 – 2025-10-31 is removed (`DATA_SCOPE="clean"`); 75 / 5 / 20 chronological
  split by cow-days.
- Candidates per grain (daily, weekly, monthly; walk-forward): persistence, Wood mixed,
  `kalman_state`, `torch_mlp_small`, `torch_mlp_large` (tuned shape), `torch_gru`,
  `torch_q50`, each raw / `_recal` (herd level) / `_grp` (parity x DIM level).
- Choice: lowest **pooled cow-period WAPE** over the validation block plus
  `SELECTION_BLOCKS` expanding windows on pre-test data (persistence excluded). Then a
  persistence blend replaces it only if its cross-fitted validation WAPE is lower.
  Written to `winners.csv`. The test block never enters the choice. The training
  monitor (every 10th week of the training block) only stops training early; it is not
  held-out accuracy.
- The selection unit is the **cow-period** (cow-day / cow-week / cow-month yield), not
  the herd total.

### Farm X result (Notebook 6 run, aggregates supplied by the user, 2026-10-22)

Split: selection training to 2021-05-17, validation to 2021-11-28, test from 2021-11-29.

| Grain | Winner (pooled) | Pooled accuracy | Validation accuracy | Best network, pooled |
|---|---|---|---|---|
| daily | kalman_state_grp | 72.74% | 71.66% | torch_q50_grp 72.04% |
| weekly | kalman_state_grp | 73.05% | 72.28% | torch_q50_grp 72.39% |
| monthly | **kalman_state** | 74.75% (WAPE 25.25%, 37,984 cow-months) | 74.47% | torch_mlp_small_grp 74.12% |

All blend weights are 1.0 (blend = winner). On validation alone `torch_gru_grp` led the
monthly grain (74.73%); the pooled rule chose `kalman_state`. Margins are under one
point. **The selected monthly predictor is therefore not a neural network:** Wood mixed
curve, walk-forward herd recalibration, and each cow's Kalman level decayed to the
target day. Accuracy is cow-month yield (100 - WAPE), not herd-total accuracy.

## 2. Which grain is a forecast from one fixed origin

| Grain | Features frozen at | Fixed-origin forecast? |
|---|---|---|
| daily | the predicted day (records up to the day before) | no: one-day-ahead **updated** prediction |
| weekly | each Monday | no: week 2 would need records after the origin |
| monthly | the 1st of the month; predicts days 1–31 | **yes**, for the origin month |

pfoi-1.8.0-dev uses the **monthly** winner. Milk after the origin month is published as
`unsupported_horizon` (no number); nothing is extrapolated.

## 3. Herd milk

`herd_litres(d) = milking(d) x mean predicted yield per cohort cow(d)`, the same form
as the clean target (`milk_per_recorded_cow x milking`, `docs/model_input2.md` §5).

- `milking(d)`: **pfoi-1.2.0-dev's** milking-cow forecast (disclosed dependency): days
  1–14 as published, the rest of the month a constant that makes the month mean equal
  the published monthly mean exactly (audit in the artifact).
- Cohort: cows with a record in the 28 days before the origin and at least 3 records in
  the current lactation. Future days: DIM and age advanced, same parity, no yield,
  sensors or THI; features measured strictly before the origin. Days past DIM 400 are
  dropped (dry-off proxy). Calvers, entrants and short-history cows are not predicted;
  they enter only through the herd-engine count.
- Fewer than 10 cohort cows on a day: no forecast (`missing_prediction:*`).
- Origins inside the recording gap (e.g. 2024-01-01) have no clean records before them
  and therefore **no neural milk forecast**; this is reported, never hidden.
- Source availability for the origin's year: carried forward from the previous
  complete year when the year to date is below 100 records.
- Weeks and the month are sums of the daily path (tested).

## 4. Persisted predictor (`<out>/models/pfoi-1.8.0-dev/<YYYYMM>/`)

`predictor.json` + `weights.pt` (SHA-256 checked): selection and source-file hashes,
settings, features, scaler, Wood fixed effects + variance components + smearing,
Kalman parameters, all ensemble weights, blend weights, training cutoff (day before the
origin), data scope, aggregate training counts, git commit. Wood cow intercepts are
recomputed as the exact BLUP from pre-origin records (tested equal to statsmodels), so
no per-animal value is stored. The published forecast comes from the **reloaded**
predictor; the reload check compares it with the fit (aggregate max difference).

Weights are refitted strictly before each origin. The model family and tuned settings
come from Notebook 6, whose validation data may lie after an early origin (e.g.
2018-02-01): such origins carry selection hindsight and are labelled development.

## 5. Document (`outlook/pfoi-1.8.0-dev/run_YYYYMM.json`)

Kept from 1.2.0-dev: herd counts and composition, events, mastitis, heat, moves,
generations, fertility, coverage, repro timing, calving split, actuals/realised.
Removed (structural milk only): milk attribution, milk corrections, milk backtest,
quality bands, replay, blend audit, `cow_model`, milk scenarios, outage simulation,
evidence ladder. Added: `milk_model` (selection, formula, dependency, cohort, reload
check, exact stage decomposition baseline → learned, status of explanation and
evaluation), `provenance`, per-row `source_model`. Intervals: **uncalibrated**
(lower = upper = forecast) until this predictor's own rolling-origin errors exist.

## 6. Why the pfoi-1.7.0-dev milk panel was empty (code reading; to confirm)

1. 1.2.0-dev with `--k anchor_first` withholds milk when no trusted recent milk days
   exist; 2024-01-01 is inside the recording gap, so its document may have **no milk
   rows**, and `hybrid_document` only rewrites existing milk rows.
2. Its recorded history (24 months before) and outcomes (2024) are mostly in the gap and
   not scoreable, so neither recorded line is drawn.
3. `cow-torch-produce` fitted on all records before the origin **without** Notebook 6's
   gap exclusion; the 183 cows were recorded inside the gap that Notebook 6 rejects.
4. The 1.2.0-dev outlook CSV has only 14 daily milk days, so a 1.7.0-dev artifact covers
   14 days and cannot fill weeks 3+ or months; `hybrid_document` raises on those.

`milk-panel-check` prints the counts that decide which of these applies.

## 7. Next steps (not done)

1. Rolling-origin evaluation of herd milk vs 1.2.0-dev, persistence and seasonal naive
   on identical eligible periods (MAE, RMSE, bias, WAPE, coverage, n), cow-level
   separately; intervals from these past errors.
2. SHAP for the complete predictor (aggregated, background = pre-origin cohort days),
   global vs the origin month, with additivity error reported. `shap` is not installed.
3. Frontend: show `milk_model`, `withheld` reasons and the uncalibrated label.

## 8. Status 2026-10-22 evening and deferred work (user: "do it later")

Done: predictor persisted per origin (`logs/.../models/pfoi-1.8.0-dev/YYYYMM/`), origin-safe
availability (previous complete year), rolling-origin backtest (`neural-milk-backtest`,
`--max-months 1` = month-1 calibration run), calibrated ranges (`neural-milk-produce
--calibration`), verification before publishing (`neural-milk-compose` checks every
document against its 1.2.0-dev source; `--write` publishes only `pfoi-1.8.0-dev` rows),
backend `model_version` selection with 1.7.0-dev / 1.8.0-dev comparison-only, and the
"Milk Yield per Cow" chart (always daily, over the predictor's month). The herd chart is
renamed "Total Milk Yield".

Deferred (not done; do later):
1. **Speed:** vectorise `cow_kalman._filter` across cows (same arithmetic, exact-match
   test) and run origins in parallel (`--jobs`). Expected full 12-month backtest
   ~1 h -> ~5-10 min. A GPU does not help: the selected model trains no network.
2. **Full 12-month backtest** vs 1.2.0-dev, persistence and seasonal naive; decide from it
   whether months 2+ may be published (`--months N`). Expect the cohort to shrink with
   horizon (no new calvers in the cohort).
3. **Like-for-like 1.2.0-dev errors:** the 1.2.0-dev files in `logs/pfoi` may predate the
   placeholder-free `model_input2` target; check the printed actual difference, rebuild
   on `model_input2` if it is not ~0.
4. Feature-level explanation (exact Wood-term split for `kalman_state`; SHAP only if a
   network is ever selected), Sinhala labels for the new chart texts, frontend display of
   `milk_model` details.
