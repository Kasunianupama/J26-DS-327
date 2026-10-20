# pfoi-1.1.0: recency-weighted rates and the correction layer

**Status: frozen 2026-10-20 as pfoi-1.1.0 (hash `2a865a0c2687`, see freeze.md).** This
file is the decision record; "candidate" below is the name it had before the freeze, and
`--preset candidate` still works as an alias of `--preset pfoi-1.1`.

**Before the freeze:** `pfoi-1.0.0` (configuration `3cbd28787fcb`) stays the
published model. Its hash, its run-once final-test markers and the outlook are unchanged
(test: `tests/test_candidate_version.py::test_frozen_hash_unchanged_by_new_option`).

## Why (diagnosis from the 2024-01 forecast chart)

At the 2024-01 forecast date, pfoi-1.0.0 projects the total herd flat and milking cows
slightly *up*. The recorded outcome falls (episode E3: about 750 culls, sales and deaths in
Mar–Jun 2024), and milking cows fall too. In the frozen model:

1. **Rates are a flat 12-month mean.** Every month in the window counts equally. The
   abortion surge (E2, from 2023-11: 21–44 a month against 1–12 before) is only 2 of 12
   months at that origin, so the projected abortion rate is roughly a third of the current
   one. Known pregnancies then turn into too many calvings and milking cows. This matches
   the test-block calving over-forecast (+64 % at 1 month) and the milking over-forecast
   (+14 to +22 %).
2. **The removal rate lags in the same way.** Exits were already speeding up in late
   2023, but the window averages that with the calmer months before.
3. A one-off removal campaign like E3 is a management decision. No rate model can forecast
   its timing from herd history alone. It belongs in the scenario layer
   (`scenarios.py`, episode library) and in honest, downside-skewed intervals.

The candidate addresses 1 and 2. Point 3 stays a scenario and is not claimed as forecastable.

## What changes

| Part | pfoi-1.0.0 (frozen) | pfoi-1.1.0 (candidate) |
|---|---|---|
| Rate window | 12 months, equal weights | 24 months, **weight 0.5^(age / 6 months)** |
| Conception months | all months before the origin (leakage audit L2) | only months confirmable at the origin (`known`) |
| Starting herd | `day_cell` (L3) | `day_cell_known` |
| Known conceptions | lag rule, 35 days | recorded pregnancy check, rate lag 90 days |
| Milk | frozen settings | same as frozen |

Weighting: `rates.recency_weighted`. Month-indexed exposure, transitions and panel events
are weighted by age (the last complete month has weight 1). Inputs without a month
(open cow-days, pregnant milking-days) are scaled by the window's mean weight, so ratios
that mix the two stay consistent. Steady rates are unchanged by weighting (tested).
A recent surge moves the rate within 1–2 months (tested).

The 24-month window and the 6-month half-life are **starting values, not tuned**. Choose
them on the development block (grid below, then `nested-cv`). If another setting wins,
change `CANDIDATE_ENGINE` in `pfoi/freeze.py` before any 2024–26 replay.

## Versions in the outputs

Every backtest row has a `model_version`: `pfoi-1.0.0` only for the frozen configuration,
`pfoi-1.1.0` for the candidate, and `experiment-<hash>` for anything else.
Before this change, every run was labelled `pfoi-1.0.0`. File names carry `_hl<months>`
when weighting is on.

## Blocks

* `--block development`: origins 2017–2023. Choose settings only here.
* `--block test`: refuses the candidate. The run-once test belongs to pfoi-1.0.0.
* `--block posthoc` (new): replays 2024–26 origins for a non-frozen version. It writes no
  marker, and its files are tagged `_posthoc`. It refuses pfoi-1.0.0. Report these numbers
  as **post-hoc**: they are not an untouched test.

## Commands (run on your machine; they print herd-level aggregates only)

1. Development grid (half-life 3 / 6 / 12, 24-month window, honest flags):

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --preset candidate --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 24 --half-life 3 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 24 --half-life 12 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
```

2. Compare with pfoi-1.0.0 rules on the same honest inputs (no weighting), if not already
   in `logs/pfoi` from the runbook:

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 24 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
```

3. Ratio tables for each (same options plus `herd-report`):

```bash
python -m components.predictive_farm_intelligence.pfoi.cli herd-report --preset candidate
```

4. Milk on the candidate (development):

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --preset candidate --jobs 0
```

5. Only after the settings are chosen: the post-hoc replay of 2024–26 (the chart period):

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain monthly --preset candidate --block posthoc --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli herd-report --preset candidate --block posthoc
```

**Send back:** the printed "MAE by horizon" tables and the `herd-report` ratio and bias
tables, for each run. Most useful: milking, n_herd, calvings and real_abortions at
monthly horizons 1/3/6/12.

## Decision rule (set before seeing results)

The candidate replaces pfoi-1.0.0 as the basis for the pfoi-1.1 freeze only if, in the
development block, its monthly MAE for **milking and calvings** is lower at 3 and 6 months
and no key series gets worse by more than 5 % at any horizon. Otherwise the result is
reported as it is, and pfoi-1.0.0 stays.

## Development results (herd, run 2026-10-20, aggregates supplied by the user)

Monthly MAE of `herd_engine`, development origins 2017–2023 (n = 84 / 82 / 79 / 73).
All four runs use the 24-month window and the honest flags; only the weighting differs.

| Series | Horizon | No weighting | Half-life 12 | **Half-life 6** | Half-life 3 |
|---|---|---|---|---|---|
| Milking | 3 | 70.49 | 69.16 | **68.07** (−3.4 %) | 66.65 |
| Milking | 6 | 112.49 | 108.90 | **106.09** (−5.7 %) | 102.75 |
| Milking | 12 | 93.35 | 91.95 | **93.79** (+0.5 %) | 99.88 (+7.0 %) |
| Calvings | 3 | 8.18 | 8.10 | **8.05** (−1.6 %) | 8.00 |
| Calvings | 6 | 17.41 | 17.25 | **17.08** (−1.9 %) | 16.81 |
| Calvings | 12 | 26.09 | 25.51 | **25.63** | 26.48 |
| Total herd | 1 | 23.21 | 23.05 | **22.75** | 21.87 |
| Total herd | 3 | 73.57 | 74.04 | **74.79** (+1.7 %) | 75.17 |
| Total herd | 6 | 118.15 | 119.46 | **123.93** (+4.9 %) | 136.19 (+15.3 %) |
| Total herd | 12 | 143.49 | 139.50 | **144.91** (+1.0 %) | 178.23 (+24.2 %) |
| Real abortions | 1 / 3 / 6 / 12 | 4.23 / 4.39 / 4.58 / 5.17 | 3.88 / 4.08 / 4.28 / 4.84 | **3.57 / 3.88 / 4.13 / 4.60** | 3.17 / 3.64 / 4.08 / 4.45 |

**Decision rule result:** the candidate (half-life 6) **passes**. Milking and calvings
improve at 3 and 6 months, and no key series gets worse by more than 5 % (the closest is
total herd at 6 months, +4.9 %). Half-life 3 **fails** (total herd +15 % at 6 months and
+24 % at 12 months; milking +7 % at 12 months). Half-life 12 also passes, but its gains
are smaller. The candidate stays at half-life 6, the value set before the results.

**Size of the gain: modest.** The gain is 3–6 % on milking and about 2 % on calvings.
Abortions improve most (−8 to −16 %). The development block has few regime changes, so
this is where a small gain is expected. The case the change is aimed at is 2024 (E2, E3),
which only the post-hoc replay can show.

**Still open (candidate report, monthly):**

* **Over-forecast is not fixed.** Raw bias is milking +39 / +80 at 3 / 6 months and total
  herd +43 / +67 / +86 at 3 / 6 / 12 months. Total herd is still worse than persistence at
  1–6 months (ratio 1.12–1.14). The bias-corrected variant removes most of it (milking
  −2 to −6).
* **Pregnant/open split.** At 1 month the biases are heifers open +51 / pregnant −50 and
  dry open +59 / pregnant −66, so they nearly cancel. The likely cause is that
  `day_cell_known` counts a pregnancy only once it is confirmed, while the actual series
  are scored with hindsight. Those ratios (2.5–15) therefore mix a definition difference
  with model error. This needs checking before they are reported.

## Milk, development block (run 2026-10-20, aggregates supplied by the user)

`milk_baseline` MAE (litres per period), 24-month window, honest flags; only the
weighting differs. n = 68 / 66 / 64 / 58 monthly periods.

| Grain | Horizon | No weighting | Half-life 6 | Change |
|---|---|---|---|---|
| Monthly | 1 / 3 / 6 / 12 | 17,955 / 55,659 / 92,484 / 88,111 | 17,790 / 54,299 / 89,458 / 83,447 | −0.9 / −2.4 / −3.3 / −5.3 % |
| Weekly | 4 / 8 / 13 | 5,947 / 9,804 / 14,143 | 5,879 / 9,612 / 13,784 | −1.1 / −2.0 / −2.5 % |
| Daily | 1 / 7 / 14 | 457 / 588 / 718 | 457 / 587 / 714 | about 0 |

Milk improves a little at every horizon, consistent with the herd result. Raw monthly bias
is still +41k / +81k litres at 3 / 6 months; the bias-corrected variant removes most of it.

## Post-hoc replay, 2024–26 (herd, monthly; NOT a test, see "Blocks")

`herd_engine` MAE, origins 2024-01 – 2026-08 (n = 31 / 29 / 26 / 20). The runs differ
only in the weighting.

| Series | No weighting 1 / 3 / 6 / 12 | Half-life 6 1 / 3 / 6 / 12 | Persistence |
|---|---|---|---|
| Real abortions | 11.99 / 11.31 / 12.19 / 13.43 | **10.13 / 10.19 / 9.95 / 10.30** (−10 to −23 %) | 7.59 / 10.74 / 7.93 / 9.25 |
| Total herd | 22.79 / 106.88 / 221.75 / 412.67 | **20.23 / 99.79 / 204.47** / 439.43 (−7 to −11 %; +6.5 % at 12) | 19.20 / 85.93 / 159.87 / 204.55 |
| Milking | **12.67 / 44.34 / 68.36 / 73.24** | 13.24 / 46.48 / 69.54 / 79.34 (+2 to +8 %) | 13.18 / 42.85 / 81.10 / 131.44 |
| Calvings | 20.83 / 10.68 / **12.67 / 18.57** | 20.82 / **10.41** / 13.03 / 20.06 | 13.12 / 15.98 / 21.72 / 23.81 |

**Reading (honest):**

* **What weighting fixed:** abortions (the E2 surge) and total herd at 1–6 months.
* **What it did not fix:**
  * Total herd still loses to persistence at every horizon (ratio 1.05 / 1.16 / 1.28 /
    2.15).
  * Milking is still over-forecast (+46 / +69 at 3 / 6 months) and slightly worse than
    without weighting.
  * The removal campaign (E3) and the later recovery are management-driven. At 12 months
    both runs under-forecast the herd by about 285–290 animals.
* **Pregnancy split dominates the stock errors.** Heifers pregnant −81 to −170 and heifers
  open +75 to +125, with similar values for dry cows. The starting herd counts confirmed
  pregnancies only, while the actuals are scored with hindsight (see "Still open").
* **Most of 2024–26 sits in poor-record bands** (gap, unverified; `targets.md`). This
  table does not split by band; use `scorecard --block posthoc` for that.
* **The bias-corrected milking forecast does best in both blocks.** Its post-hoc ratio is
  0.72 / 0.73 / 0.71 / 0.91 against persistence. A correction layer (Layer 1 adaptive or
  bias correction), not the rate model, is what makes milking beat persistence after a
  break.

**Conclusion so far:** half-life 6 stays the candidate, because it passed the development
rule. It is a small, real improvement, not the fix for the chart. The next gains have to
come from (1) the correction layer, chosen by `nested-cv` on development only, and (2)
scoring pregnancy-split stocks against confirmed-state actuals.

**Fix made after these runs:** `adapt`, `drivers` and `nested-cv` skipped only `_test`
files. They would have read the new `_posthoc` files and let 2024–26 errors steer model
selection. They now skip both (`cli.NOT_DEVELOPMENT`, tested).
`scorecard --block posthoc` scores the replay with development errors as the interval
history, split by record-quality band.

## Correction layer and nested selection (run 2026-10-20, aggregates supplied by the user)

**Adaptive level (`adapt`), recovery 0–5 months after a break (E1, E5a), development:**

| Target | Raw (hl6) | Bias-corrected (hl6) | Adaptive pooled q0.1 (hl6) |
|---|---|---|---|
| Weekly milk, 4 weeks (n 32) | 74.1 % | 71.8 % | **80.0 %** |
| Monthly milk, 3 months (n 6) | 46.1 % | 37.9 % | **61.9 %** (q0.5: 65.2 %) |
| Milking, 3 months (n 9) | 92.2 % | 89.8 % | 91.3 % |

The adaptive level clearly speeds up milk recovery. It still misses the 90 % recovery
target (`targets.md`). Accuracy over all origins changes by less than 1 point.

**`nested-cv` (year by year, development only):**

* **Milk** picks the candidate's engine (hl6) in every year: raw in 2019–2021, adaptive per
  horizon q0.1 in 2022–2023. Its latest choice is `hl6_adhq0.1t365z3 / milk_baseline_adaptive`.
  Nested accuracy, monthly 1 / 3 / 6 / 12: 96.4 / 88.9 / 82.5 / 78.4 %.
* **Herd: the run was contaminated.** It also offered `w12_ck`, `w36_ck` and `wexpanding_ck`.
  Those use `day_cell`, whose pregnancy states use hindsight (leakage audit L3), and it picked
  two of them (2021, 2023). Among honest candidates only, the inner scores pick unweighted w24:
  raw or adaptive in 2019–2020, **bias-corrected in 2021–2023**. hl6 corrected is within 1.4 %
  (2023: 0.1569 against 0.1547).
* **Fix:** `nested-cv` now leaves out tags without `_ck_kn_rk` unless `--include-hindsight` is
  given (`cli.HONEST_TAG`, tested).
* **Price of honesty: calvings at 6 months.** Honest candidates score about 82 % against
  about 92 % for the hindsight ones. pfoi-1.0.0's 6-month calving accuracy was partly
  hindsight; report this.

## 2024–26 replay with quality bands (`scorecard --block posthoc`)

* Every monthly target row is *not interpretable* (n = 3–5 verified periods). Most 2024–26
  months fall in the **gap** (11–18) and **unverified** (6–8) bands.
* Weekly milk 1 week ahead meets its target on verified weeks (95.4 %, n 12; not calibrated).
* Recovery, weekly milk 4 weeks ahead: 93.6 % on 5 verified periods (not interpretable).
* 15 of 32 monthly milk origins were skipped: no usable months to anchor k after the outage.

**2024–26 cannot confirm or refute either version.** The record gaps limit it, not the model.

## pfoi-1.1 freeze (decided by the user, 2026-10-20)

One engine for herd and milk, so the milk explanation and the herd forecast agree:
24-month window, honest flags, half-life 6. Herd outputs are bias-corrected; milk is adaptive
(per horizon, q30 0.1, tau 365). The alternative follows the herd selection literally:
no weighting for herd, hl6 for milk. That means two engines. The difference is ≤ 1.4 % in
the inner scores.

**Decision:** one engine (the first option). Frozen as pfoi-1.1.0.

## Forecast-date windows (charts like the page timeline)

`build-outlook --preset pfoi-1.1` runs pfoi-1.1.0 (engine plus correction layer) at any
forecast date and writes `logs/pfoi/outlook/pfoi-1.1.0/`. `--write` publishes it next to
pfoi-1.0.0. `compare-runs` scores both models on the same recorded months after
each date, and draws `logs/pfoi/compare/compare_<YYYYMM>.png`.

| Forecast date | What it tests |
|---|---|
| 2017-01 | early dry-cow peak and milking dip |
| 2019-06 | a stable period |
| 2020-08 | milk record source changes from shipments to DelPro |
| 2022-09 | herd contraction, phase 1 (E1), plus a milk gap |
| 2023-11 | start of the abortion surge (E2) |
| 2024-01 | the large removal (E3) |
| 2025-09 | after the recording outage |
| 2026-08 | the latest outlook (nothing recorded after it yet) |

## After the freeze: honest-only selection and the forecast-date windows (2026-10-20)

**`nested-cv` on honest candidates only** (15 herd and 5 milk hindsight tags left out). It
confirms the earlier reading:

* **Herd:** unweighted w24 bias-corrected is chosen in 2021–2023. hl6 corrected is within
  1.4 %.
* **Milk:** hl6 raw in 2019–2021, then hl6 adaptive per horizon q0.1 in 2022–2023.

| Nested accuracy, monthly 1 / 3 / 6 / 12 | |
|---|---|
| Milking | 97.7 / 94.2 / 92.0 / 91.4 % |
| Total herd | 99.4 / 97.5 / 96.1 / 95.9 % |
| Calvings | 91.8 / 92.7 / 79.9 / 72.6 % |
| Dry-offs | 56.7 / 55.3 / 58.0 / 51.8 % |
| Herd milk | 96.4 / 88.9 / 82.5 / 78.4 % |
| Herd milk, weekly 1 / 4 / 13 | 97.2 / 94.5 / 87.4 % |

pfoi-1.1.0 uses one hl6 engine for both. Its herd outputs are therefore the hl6 variant of
the chosen correction, which is ≤ 1.4 % from the selected one (decision above).

**Windows: one forecast date each (`compare-runs`), monthly, 12 months after the date.**
Each row is a single forecast date (n = 12 months, or fewer for milk), so read them as
examples, not as evidence. The evidence is the backtests above. Change in MAE, pfoi-1.1.0
against pfoi-1.0.0 (negative = 1.1 better):

| Forecast date | Milk | Milking | Total herd | Calvings | Abortions |
|---|---|---|---|---|---|
| 2017-01 | +5 % | +168 % | +43 % | +65 % | +65 % |
| 2019-06 | −45 % | −24 % | −5 % | +89 % | +4 % |
| 2020-08 | −49 % | −29 % | +47 % | −21 % | +4 % |
| 2022-09 (E1) | +292 % (n 9) | −34 % | −59 % | +35 % | +4 % |
| 2023-11 (E2) | +106 % (n 6) | −45 % | −23 % | −18 % | 0 % |
| 2024-01 (E3, your chart) | +38 % (n 4) | −34 % | −27 % | −24 % | −4 % |

**Reading:**

* **In the disruption windows, 1.1 is clearly better on the herd.** At the 2024-01 chart
  date, the milking over-forecast drops from +238 to +158 cows. Total herd drops from +398
  to +289 animals, and calvings from +33 to +24 a month. It is still too high: the removal
  campaign is not forecastable from history.
* **Milk is worse in those windows** (n 4–9 recorded months, low-recording periods). In
  2022-09, 1.1 under-forecasts by about 43k litres a month, where 1.0 was at −10k.
  `layer_candidate` in the next `compare-runs` run shows whether that comes from the
  adaptive milk level or from the engine.
* **2017-01 is worse on everything.** At that date the 24-month window reaches into the
  2015–16 build-up, when the herd was being stocked, and there are no past errors yet to
  correct with.
* **Abortions are under-forecast by about 23 a month by both versions at 2023-11 and 2024-01.**
  The surge had only just started.

**Open issues found:**

1. **The pfoi-1.0.0 documents show 0 % coverage everywhere.** Most likely they carry no
   ranges (lower = upper = forecast) because the w12 backtest files were not found, or they
   are older builds. `compare-runs` now leaves coverage blank when a run has no range.
   Rebuild them to check.
2. **2025-09 cannot be built by either version.** There are no clean milk months to anchor k
   after the outage (the same reason 15 of 32 post-hoc milk origins were skipped).
   `build-outlook` now says so instead of failing. Use the first date with clean records
   instead.

**Rerun (2026-10-20), with the correction-layer amount shown:**

* **The pfoi-1.0.0 documents had no ranges.** Its w12 backtest files are not in `logs/pfoi`
  (all eight "not found"), so its coverage is blank. `build-outlook --backtests <folder>`
  now reads them from another folder (for example `logs/pfoi_ref`).
* **Where the milk change comes from:**
  * 2019-06 and 2020-08: the adaptive milk level removes about 26–27k litres of
    over-forecast (bias +73k → +14k, +97k → +46k).
  * 2022-09: it adds −23k, which is about half of the −43k under-forecast; the rest comes
    from the engine. That forecast date sits at the source switch and in low recording.
* **Where the herd correction helps and hurts:**
  * Total herd: −114 at 2022-09 helps a lot; +23 at 2020-08 hurts.
  * Calvings: −15 a month at 2019-06 hurts (+89 %).
* **2025-12 and 2026-04 cannot be built either.** There are still no clean milk months to
  anchor k. The window after the outage needs a herd-only outlook (proposed follow-up).
