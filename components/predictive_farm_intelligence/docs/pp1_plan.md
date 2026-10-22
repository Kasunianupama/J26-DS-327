# PFOI plan for PP1 (Fri 2026-10-23)

Written 2026-10-20. The initial assessment is retained below; later status and results
sections record implementation and evaluation, including the latest supplied run batch.
**Decision (user, 2026-10-20): every milestone below is done before PP1, none is
deferred to after it.** Where data, not time, limits what can be shown, the milestone
is still built and run, and its result is labelled with what it can and cannot show.

Status words used throughout:

* **implemented and tested**: code exists and passes synthetic unit tests;
* **evaluated**: the user ran it on Farm X data and supplied aggregates;
* **post-test development**: evaluated on 2024–26, which has already been inspected, so
  it is not a held-out confirmation;
* **not interpretable**: fewer than 12 scored periods (`targets.md`).

Synthetic tests prove the code is correct, not that it forecasts well.

The frontend prototype that shows all of this is planned in `pp1_frontend_plan.md`
(features F1–F9, one per milestone, same deadline).

---

## 1. Current implementation (verified in code, 2026-10-20)

| Area | What the code does | Where | Status |
|---|---|---|---|
| Starting herd | `day_cell` / `day_cell_known` on the day before the forecast date, leakage guard | `data.py:45`, `data.py:112` | implemented and tested |
| Herd engine | daily cohorts: calving, dry-off, conception, abortion, extra pregnancy loss, deaths/culls/sales, births, entries, calf sex, generation = dam + 1 | `herd_engine.py:1-30`, `:253` | implemented and tested |
| Rates | trailing window, beta-binomial shrinkage, cow conception by parity × 4 DIM bands, gestation and dry-off-by-gestation histograms, recency weighting (half-life 6 months, pfoi-1.1.0) | `rates.py:265-420`, `:224` | evaluated (herd backtests documented) |
| Milk | `k × Σ cells × Wood curve × pregnancy factor`; herd-fitted shape before 2020-09; anchored k on the last 14 scoreable days | `milk_baseline.py:191-241` | evaluated |
| Correction layers | bias correction, adaptive Kalman level, ridge driver layer (THI, rain, health, sensors, quality, season) | `error_tools.py:28`, `adaptive.py:53`, `drivers.py:201` | implemented and tested; **no real-data driver result is documented** |
| Intervals | outlook: plain 5/95 % quantiles; ACI with quality scaling only in `scorecard` | `outlook.py:69`, `intervals.py:71`, `scorecard.py:89` | ACI implemented, **not used in published outputs** |
| Evaluation | rolling origin, persistence, seasonal naive, ETS, SARIMA, common periods, quality bands, recovery buckets, nested CV | `backtest_milk.py:86`, `:273`, `episodes.py`, `nested_cv.py` | implemented |

Unit tests: 238 passed (2026-10-20, synthetic only).

**Documentation out of date:** `AGENTS.md` §5 (24-month default, 5/95 % intervals, THI and
mastitis as Shapley factors; the code uses 12 months in 1.0.0, and THI/mastitis sit in the
residual); `freeze.py:53` cites `docs/pfoi_1_1_1.md`, which does not exist.

## 2. Earlier findings, checked

| Finding | Verdict |
|---|---|
| Historical calibration needed before anchoring | **Confirmed.** `prepare_milk` raises "no usable months to calibrate k" (`milk_baseline.py:212-213`) before `anchor_k` runs (`backtest_milk.py:144-148`; same in `outlook.py`). The 12-month k window ends two months before the forecast date (`:60-63`), so after the 11-month gap no origin can be built even with 14 good recent days. Explains the 15 of 32 skipped post-hoc origins and the 2025-09 / 2025-12 / 2026-04 outlooks that cannot be built. |
| Daily/weekly test milk worse than persistence | Documented (daily 1.27 / 1.25 / 1.45). Plausible cause, not diagnosed: the anchor is a 14-day mean while daily persistence uses the last week (`backtest_milk.py:93-98`), and engine drift is added on top. |
| Few scoreable monthly test periods | Confirmed (n 1–5): caused by record gaps, not by the model. |
| Calvings and dry-offs useful | Dry-offs hold. pfoi-1.0.0 calving skill was partly hindsight (L3); honest 6-month calving accuracy ≈ 82 % vs ≈ 92 % with hindsight. Report the honest figure. |
| Poor adaptation to contraction and recovery | Confirmed. Total herd loses to persistence after 2024 in both versions; the E3 removal campaign is a management decision. |
| 90 % intervals under-cover | Confirmed (34–83 %). ACI exists but is not published. |
| Pregnancy built from future outcomes | Partly resolved: `day_cell_known` and `conception_known="recorded"` fix L2–L4 in pfoi-1.1.0. Open: L5 (`entered_ts` exists, no cut run) and L6 (definitions of `is_scoreable`, `is_implausible_volume`, `data_gap` are in the ETL repo). |
| Shipped vs produced milk | Handled: k per source, mixed-source periods not scored (`backtest_milk.py:53-58`). |
| Heat and mastitis not learned factors | Half right: in the driver layer (`drivers.py:38-53`), synthetically tested, never evaluated on real data. `thi_max` is loaded (`data.py:864`) but unused; no 1–7 day lags. |

**New risks found:**

1. **Weather availability.** Weather is ERA5 reanalysis (`docs/database/app_database_setup.md`
   in the repo root docs). ERA5T is published about 5 days behind real time and may be
   revised. Driver features use THI up to the day before the forecast date
   (`drivers.py:159`), which is not operationally available. Fix: 6-day availability lag.
2. **Simulated outages are optimistic.** Masking milk leaves herd records complete; in the
   real outage (E5c) calvings were also missed (≈ 29 % of cows giving milk have no open
   lactation).
3. **Recovery buckets use hand-dated breaks** (`episodes.py:33`): evaluation only, never an
   input.

## 3. Input inventory

| Input | Where | Coverage | Verified? |
|---|---|---|---|
| THI: `thi_mean`, `thi_max`, `hours_thi_above`; temp, RH, rain | `day_panel` (from `core.weather_day` / `weather_hour`, ERA5) | probably the whole period; `weather_is_complete` per year | **Unverified:** THI formula, the `hours_thi_above` threshold, UTC vs local day, grid point (ETL repo). ERA5 is modelled, not measured on the farm. |
| Archived weather forecasts | none | — | Forecasts can use only climatology or labelled scenarios |
| Herd milk target | `day_panel.target_*` | shipments 2015-08 – 2020-07, DelPro after; gaps 2022, 2024, 2024-09 – 2025-09 | verified per scored period |
| Reliable per-cow milk | `core.cow_day` | 2020 ≈ 174k, 2021 ≈ 75k, 2022 ≈ 11k, 2023–25 < 1k, 2026 ≈ 7k cow-days | documented |
| Session sensors (sessions, blood, conductivity alarms) | `day_panel` counts; `core.milk_session` | from 2025-09 | overlap with identified milk only ≈ 2026-04 onward (≈ 5 months), all post-test |
| Diagnoses, treatments | `health_episode`, `treatment_history` | mostly 2015–18, almost none since 2023 | not usable as labels for 2023–26 |
| Pregnancy checks, inseminations | `core.preg_check`, `insemination`, `conception_known_date` | whole period | check lag median 41–85 days |

## 4. Architecture

```
herd records ─► herd engine (rates, reproductive pipeline) ─► cows by parity × DIM × pregnancy
                                                               │
milk records ─► trust gate (freshness, completeness, plausibility, source agreement)
                 │ trusted recent days                         ▼
                 └──────────────► level k (anchor first; 12-month k only as fallback) × curve litres
                                                               ▼
THI known at origin − 6 days ─► driver layer (lagged / peak heat; climatology for the target)
herd-level sensor aggregates (SQL) ─► driver layer, shadow → probation → active
                                                               ▼
intervals: ACI × quality band × staleness factor ─► forecast, or WITHHELD with a reason code
```

* Reproductive rates come only from herd records; resumed milk at a new level never
  changes them (`rates.py` reads no milk).
* Animal-level histories enter only as herd-level aggregates computed in SQL (no animal
  keys in Python). Individual detection is Component 3.

## 5. Milestones (all before PP1)

| # | Change | Files | Synthetic tests | User-run (aggregates only) | Keep if |
|---|---|---|---|---|---|
| **M1** | Anchor first; 12-month k only as fallback; if both fail, herd-only output with reason `milk_withheld:no_trusted_recent_days`. New flag, outside the 1.0.0 and 1.1.0 hashes | `milk_baseline.py`, `backtest_milk.py`, `outlook.py` (after the 1.1.1 commit) | gap > 14 months with 10 good recent days gives a forecast; leakage test; old configuration reproduces old results exactly | development weekly milk backtest with and without the flag; `scorecard --block posthoc` | development MAE no worse than +1 % at any horizon; more post-hoc origins buildable |
| **M2** | Outage simulator: target days in [origin − r − G, origin − r) hidden from the model, actual values still used for scoring; one engine run per origin, re-anchor only | new `pfoi/outage_sim.py`, CLI command | masked days never reach k; scored actual values unchanged; r = 0, G ≥ 28 is withheld | development weekly origins (`--every 2`), G ∈ {0, 28, 90, 180}, r ∈ {0, 3, 7, 14}: MAE, bias, withheld counts | always (a measurement; feeds M4) |
| **M3** | Trust gate for anchor days: litres per projected milking cow inside the training-period range, current source, identified-share band | `milk_baseline.py` | an implausible day (> 20 L per cow) is excluded; gate uses past data only | as M1 | post-hoc recovery improves, development not worse |
| **M4** | Interval width grows with staleness (scale from M2 errors by days since the last trusted day); ACI for herd milk in the outlook | `intervals.py`, `outlook.py` | coverage holds on synthetic drift; width rises with staleness | `scorecard --intervals aci`, development | 90 % coverage in 85–95 % without width90 doubling |
| **M5** | THI: 6-day availability lag; lagged `thi_max` (days 1–3 mean), 7-day mean, consecutive days above the training-period P75/P90, anomaly vs training climatology; two hinge specifications (knot P75 vs P90), no fixed universal threshold; oracle switch with actual target THI, labelled and excluded from operational claims | `drivers.py`, `data.py` | lag respected; oracle never in an operational run; planted lagged effect recovered | THI coverage SQL (below); `drivers --groups season quality` vs `+ weather`, operational and oracle, identical periods | operational run cuts daily or weekly MAE by ≥ 2 % **and** the oracle shows signal; otherwise reported as "no detectable herd-level effect" |
| **M6** | Sensor and animal-level aggregates as herd-level features computed in SQL: share of milking cows with persistent (≥ 3 of 7 days) or combined blood + conductivity alarms, share of incomplete sessions, sessions per cow, sensor coverage share; recent herd milk trend and variability, deviation of herd milk from curve expectation. Missing = missing, never zero or healthy | `data.py` (new aggregate loader), `drivers.py` | feature is missing before the sensor start and after recording stops; stays in shadow below 24 rows; no animal key leaves SQL | `drivers --groups ... sensor` on the post-hoc block; feature registry status counts | reported as a shadow-mode evaluation with n; promoted only if it reaches probation and improves MAE. Expected: too few rows, so it stays in shadow (a data limit, stated) |
| **M7** | Reproductive timing: calving → first recorded AI → conception (known) → maintained pregnancy → next calving, as herd-level survival curves with censoring (open cows are censored, not failures; exits are competing events; "no recorded AI" stays unknown). Compare the engine's implied time-to-conception with these curves; if they disagree, finer DIM bands for cow conception (30-day bands) behind a flag | new `pfoi/repro_timing.py`, `rates.py` (flag), CLI report | censored animals not counted as failures; competing exits handled; finer bands reproduce the old rates when collapsed | aggregate SQL / CLI report by calving period; herd backtest with the finer-band flag (development) | finer bands kept only if calvings and milking MAE at 6–12 months improve on development |
| **M8** | Separate outcomes, not one efficiency score: yield relative to curve expectation, days to first service and to known conception, pregnancy maintenance, alarm persistence, productive vs non-productive days; by generation, adjusted descriptively for parity, calving period, THI band and recording coverage | `pfoi/cli.py` report (extends `explain-generation`) | strata sums equal totals | one command | descriptive only; associations, not genetic or causal effects; no feed-efficiency claim (no intake data) |

**THI coverage SQL (user runs; aggregates only):**

```sql
SELECT EXTRACT(year FROM date) AS yr, COUNT(*) AS days,
       AVG(weather_is_complete::int) AS complete_share,
       MIN(thi_mean), AVG(thi_mean), MAX(thi_mean),
       percentile_cont(ARRAY[0.5,0.75,0.9]) WITHIN GROUP (ORDER BY thi_max) AS thi_max_p50_75_90,
       AVG(hours_thi_above) AS mean_hours_above,
       AVG((hours_thi_above = 0)::int) AS share_zero_hours,
       AVG((hours_thi_above = 24)::int) AS share_24_hours
FROM model_input.day_panel GROUP BY 1 ORDER BY 1;
```

Ask the ETL for the THI formula, the `hours_thi_above` threshold and whether days are
UTC or local. If `hours_thi_above` is 24 on most days, that fixed threshold carries no
information here.

**Comparison ladder (identical eligible periods; n and withheld reasons reported):**
1 persistence → 2 pfoi-1.1.0 milk → 3 + M1/M3 → 4 + THI (M5) → 5 + sensors (M6) →
6 combined. Daily 1/7/14 and weekly 1/4; MAE, RMSE, bias, ratio to persistence; outage
recovery error and recovery time (M2); coverage and width; split into normal,
heat (THI ≥ training P90), outage and recovery bands. Rungs 5–6 can only be scored on
2024–26 (post-test development) and are expected to be not interpretable.

### Status (2026-10-20)

All eight milestones are **implemented and tested on synthetic data**. Evaluation and
keep/drop decisions are recorded below from user-supplied aggregates. Keep-or-drop
rules are the "Keep if" column of the table above, unchanged.

| # | Status | What exists | Tests |
|---|---|---|---|
| M1 | **kept**: development unchanged (by construction), more 2024–26 dates built (results below) | `MilkConfig(k_mode="anchor_first")`, `--k anchor_first` (tag `_kf`); `MilkWithheld` reason `milk_withheld:no_trusted_recent_days`; backtests count withheld origins; outlook keeps the herd forecast and publishes no milk rows (never 0) | `test_outage_recovery.py`, `test_pp1_outlook.py` |
| M2 | **evaluated (development, simulated)** (results below) | `pfoi/outage_sim.py` (own command): scenarios, outage cost, staleness spread; limit printed every run | `test_outage_sim.py` |
| M3 | **dropped** by its keep rule: 2024–26 recovery much worse (results below); option kept, off | `MilkConfig(anchor_gate=True)`, `--anchor-gate on` (tag `_kfg`): anchor only on verified days (targets.md rule: identified share ≥ 0.2, ≤ 20 L per milking cow) | `test_outage_recovery.py` |
| M4 | **kept for daily/weekly milk and herd series** (calibrated, width < 2×); monthly milk keeps the quantile ranges | `intervals.StalenessScale` (from the M2 table; no table = no widening, stated), `aci_interval_next`; `build-outlook --intervals aci --staleness <csv>`; record status (`pfoi/record_status.py`) | `test_pp1_outlook.py` |
| M5 | **dropped** by its keep rule: heat makes weekly forecasts worse and leaves daily unchanged; oracle no better | driver layer: 6-day weather lag (ERA5), lagged peak heat, 7-day mean, hot runs and heat load above herd knots P75 / P90, `--oracle` (labelled, never offered to model selection) | `test_thi_features.py` |
| M6 | sensors: cannot be validated with current data (all shadow in development) | `SqlHerdSource.sensor_daily` (herd-level SQL over `core.milk_session`), sensor + recent-milk features with missing-not-zero rule | `test_sensor_features.py` (SQL itself untested without a database) |
| M7 | descriptive tables evaluated; **conception shape dropped** by its keep rule (milking worse at 6 and 12 months) | `repro_steps` SQL, `pfoi/repro_timing.py` (censoring, competing exits, engine comparison), `repro-timing` command; `--conception-shape on` (within-band DIM shape, tag `_cs`) | `test_repro_timing.py` |
| M8 | evaluated, descriptive (associations; small-n cells flagged) | `generation_yield / _days / _alarms` SQL, `pfoi/generation_outcomes.py`, `generation-outcomes` command | `test_generation_outcomes.py` |
| M9 | **kept as an option, off by default** (keep rule met, results in "M9" below); making it the PP1 default is the user's decision | `MilkConfig(borrow_other_source_k=False)`, `--borrow-k off` (tag suffix `s`): never use the other record source's 12-month k; `pfoi/regimes.py` (errors by recording regime, matched A/B comparison, refuses mixed files) | `test_source_k.py` |
| M10 | **rejected (user decision, 2026-10-21)**: combining the model with persistence is not used for PP1 outputs; code kept, off by default; results below kept as evidence only | `pfoi/blend.py`, `blend` command: daily and weekly milk forecast = past-skill-weighted blend of the adaptive model and persistence (no fitted parameter); monthly untouched | `test_blend.py` |
| F1–F9 | implemented, build and browser-checked on the demo run | `frontend/.../panels/Pp1Panels.tsx`, page-document keys (`page_run._pp1_sections`), `evidence-ladder` command | `test_evidence.py`, `npm run build` |

Hashes of pfoi-1.0.0 (`3cbd28787fcb`) and pfoi-1.1.0 (`2a865a0c2687`) are unchanged (tested).
Development builds are published as `pfoi-1.2.0-dev`, never under a frozen name.

### M9: source-break k (2026-10-21; user runs, herd-level aggregates)

**Why.** The monthly target check showed `target_source` is `shipment` to Jul 2022 and `delpro`
from Aug 2022 (Sep–Oct 2022 empty), with litres per recorded milking cow-day falling from
about 12 to 5 before the switch. With fewer than 3 usable months for the current source the
model borrowed the other source's 12-month k and only flagged `source_switch`.

**Keep rule** (proposed by the assistant before the run, not changed by the user afterwards):
keep `--borrow-k off` if (a) MAE on the periods both runs forecast does not worsen, and
(b) fewer than about 5 % of origins are withheld. It is a fallback-behaviour option, not a
new model: forecasts that still exist are identical.

**Result** (`regimes.py`, `kf` vs `kfs`, development block, window 24; shipment and DelPro to
Dec 2023 only, the post-2024-05 regime needs `--block posthoc`):

* (a) **Met, trivially.** On common periods MAE and bias are identical in every regime, grain
  and horizon (e.g. DelPro weekly h13: 6,426 L both; shipment unchanged by construction).
* (b) **Met.** `off` declines 0–4 monthly, 2–4 daily and 1–10 weekly periods; about 3 % of all
  origins, but up to about 20 % of the DelPro regime's weekly h13 periods, all just after the
  Aug 2022 switch.
* **What the declined periods were.** The borrowed level gave MAE 25–30k L weekly (regime
  typical 1.8–6.4k), about 4.6–5.0k L daily (typical 270–460) and 56–133k L monthly (typical
  20–107k): 5 to 15 times worse than normal.
* In the DelPro regime, 35.6 % of forecasts have no same-source 12-month k (DelPro needs 3
  usable months; Sep–Nov 2022 empty or partial) and run on the 14 recent days alone.
* Earlier pooled `_kf_` regime output was discarded: the glob matched several window and
  exit-model variants (n inflated 4–5 times). `regimes.py` now refuses such input.

**Limits.** The DelPro regime has few periods (monthly 6–8, flagged small-n); overlapping
horizons from neighbouring origins are not independent. Monthly h12 bias of +102 % in that
regime is origins before the break forecasting after it, not a level-setting error.
The by-regime tables for 2024-05 onward are post-hoc and descriptive.

**Decision pending (user):** keep as an option only, or use `--borrow-k off` for forecasts
issued soon after a source change. Not part of a frozen model; hashes unchanged.

### M10: persistence blend for daily and weekly milk (2026-10-21; development block)

**Diagnosis** (saved dev errors of the `pfoi-1.2.0-dev` point forecast, `milk_baseline_adaptive`,
tag `..._kf_w24_..._hl6_adhq0.1t365z3`; MAE ratio to persistence on the same periods): daily
1.19 / 1.05 / 1.03 and weekly h1 1.06, i.e. no better than carrying the last value; in the DelPro
regime (Aug 2022 on) daily 1.50 and weekly 1.49 pooled. Monthly is 0.60-0.71 and is where the
structural forecast earns its keep.

**Change** (`pfoi/blend.py`, `blend` command, `test_blend.py`): forecast = w x structural +
(1 - w) x persistence, per grain, series and horizon, with w = (1/MAE_s) / (1/MAE_s + 1/MAE_p)
from forecasts **whose target period had ended by the origin** (tested: unfinished outcomes never
move w); w = 1 with fewer than 8 finished pairs. No fitted parameter. Applied to daily and weekly
rows only. Intervals are recomputed from the blend's own past errors.

**Result** (development, origins 2017-2023, matched periods; ratio adaptive -> blend):

| | h1 | h4 / h7 | h8 | h13 / h14 |
|---|---|---|---|---|
| daily | 1.20 -> 1.05 | 1.05 -> 0.97 | | 1.03 -> 0.95 |
| weekly | 1.06 -> 0.97 | 0.93 -> 0.87 | 0.95 -> 0.90 | 0.91 -> 0.86 |

By regime (MAE per period, adaptive -> blend): DelPro weekly h1/4/8/13 2,252 -> 1,748, 5,725 ->
3,900, 9,567 -> 5,936, 9,284 -> 5,904; daily h1/7/14 449 -> 309, 544 -> 387, 691 -> 510.
Shipment: daily -8 / -4 / -4.5 %, weekly -6 / -3 / 0 / -2 %. 90 % interval coverage rose in
every daily and weekly cell (for example weekly h13 80 -> 89 %) at similar or narrower width.
After the break the ranges are still too narrow for both models (about 50 % coverage).

**Honest limits.**
* Design choices were made on this block after seeing it: the weighting rule was picked from
  8 variants (inverse-MAE vs grid-searched weight, all-past vs recent window, per-source or not);
  the simplest was kept; most others were within about 1-2 points of it, and the two grid-searched
  recent-window variants were worse at weekly h8 and h13. Monthly was excluded because the
  blend made it 5-10 % worse in both regimes.
* Not uniformly better: stable years lose a little (weekly 2021 about 11 % worse, 2017-18 slightly);
  the gain comes mostly from 2022-23, when persistence beat the structural model. The weights adapt
  with a delay (errors must finish first).
* Weekly h13 bias in litres rises in the shipment regime (3.6k -> 5.2k) while MAE improves.
* **Post-hoc replay (2024-26, offline from the saved raw errors; adaptive layer rebuilt from dev plus
  earlier post-hoc errors, reproduction of the dev file exact to 1e-9):** the blend lowers the previous
  model's MAE in every daily and weekly cell (daily -17 / -12 / -21 %, weekly -17 / -32 / -29 / -25 %),
  but it still does not beat persistence except daily h1 (ratio 0.98): daily 1.11 / 1.19, weekly
  1.06 / 1.85 / 1.58 / 1.43 (n 28-61, effective sample 12-13 forecast months).
* **How solid is it** (`robustness()` in `make_blend_figures.py`, block bootstrap over forecast months,
  `docs/data/m10_blend_robustness.csv`). Neighbouring origins overlap, so the effective sample is 12-15
  forecast months, not the 28-51 periods. DelPro regimes: MAE ratio blend / previous 0.62-0.78 (dev) and
  0.68-0.81 (post-hoc), 90 % intervals below 1 except post-hoc h1 (0.65-1.12). But the five best forecast
  months carry 73-100 % of the net gain (a few blow-ups after the Sep-Oct 2022 and Mar-Apr 2024 gaps),
  and the typical week is not always better (post-hoc weekly h4 median error 5.7k -> 7.4k L while the
  mean improves). Shipment regime: weekly h4-h13 intervals span 1 (0.91-1.08): no reliable gain there.
  Judged only on forecasts issued inside the DelPro era, the previous model is worse than persistence
  (1.15 / 1.45 / 1.65 / 1.27) and the blend roughly ties it (1.03 / 1.11 / 1.14 / 0.90). Only 2-22 % of
  DelPro-target rows come from forecasts issued before the break, so the three-way regime split is not
  what drives these results.
* **Reading.** The blend is a safeguard that removes the worst misses, not a general accuracy gain, and
  persistence remains hard to beat at weekly range after the break. The cause is upstream: after a data
  gap the structural level rests on few recent days (56.8 % of forecasts from May 2024 have no 12-month k).
* Backtest layer only. The live outlook (`outlook.OutputLayer`) does not apply the blend yet; no
  adaptive post-hoc (2024-26) files exist, so there is no out-of-block check. Neither is frozen.

**"The line is too straight": what was tested (development block, 2026-10-21).**
* *Is the structural bend real?* Over 13 weeks the previous model predicts a mean change of 12.9 % against
  14.2 % actual, but the slope of actual change on predicted change is 0.56 (correlation 0.56): about
  half the bend is right in size. A calibrated bend is therefore about 7 %, and the blend's is 8.3 %.
  Keeping the structural bend at full strength (one level factor, shape kept) was no better in development
  (weekly 0.87 vs 0.86) and worse post-hoc at weekly h4-h8 (2.96 and 2.45 vs 2.08 and 1.93).
* *Day-of-week pattern?* None in the shipment era (0.5 %); in DelPro about +2 % at weekends in 2022-23 but it
  changes between years (reversed in 2026). Not usable. The daily ratio around the weekly mean has a spread
  of 3.6 %, and the daily blend's error (about 2.5 %) is already near that floor.
* *Recent trend (ETS) as a third partner.* Daily h1 improves (ratio to persistence 1.04 -> 0.90), daily h7 and
  h14 by about 1.5 %, post-hoc daily improves at all three horizons (29-36 periods); weekly does not (h4
  0.87 -> 0.89, h13 0.85 -> 0.87). So daily is now persistence + ETS + structural, weekly stays
  persistence + structural (`blend.skill_blend`, `PARTNERS` in `blend_outlook.py`). Where ETS cannot be fitted
  (recent gaps: 2023-11, 2024-01, 2024-07, 2026-04) the daily blend falls back to two-way.
* *Reading.* The remaining misses are mostly unforecastable movements (for example the Nov 2023 and Jul
  2024 declines), not a missing bend. A flatter line is statistically appropriate here.
* *New split by the user (shipment origins before / from Aug 2020):* from Aug 2020 to Jul 2022 the weekly
  blend is slightly worse than the previous model at h4-h13 (ratio 1.03-1.06, intervals span 1); the
  clear gains are before Aug 2020 at h1 and in the DelPro regimes.

**Preview before any database write (files only).** `blend-outlook` derives `<version>-blend` documents from
the built `pfoi-1.2.0-dev` ones (weights from backtest forecasts finished by each forecast date, persistence
and ETS from the document's own recorded history, the wider of two ranges); `compare-runs --also` draws
pfoi-1.0.0, pfoi-1.2.0-dev and the blend with the recorded outcome and scores them on the periods all three
forecast. On the eight page dates the blend beat 1.2.0-dev at 4 of 7 daily dates and 4 of 8 weekly dates
(2019-06 weekly MAE 7,096 -> 2,931 L); pfoi-1.0.0 had the lowest daily error at 5 of 7 dates, but over the
whole development block 1.0.0 and 1.2.0-dev are tied at daily and weekly range (1.18 vs 1.19, 0.97 vs 0.91)
and 1.2.0-dev is clearly better at monthly (0.60-0.71 vs 0.86-0.95), so the eight dates are a noisy sample.
`build-outlook --write` does not apply the blend yet; the preview documents are not what the page reads.

**Decision (user, 2026-10-21): rejected.** The persistence blend is not adopted for PP1 outputs,
and the T1 live option (`--persistence-blend`) stays off. Code, tests and these results are kept as
evidence only. Next direction: a learned (deep-learning / memory) model under a stricter train /
validation / test split; see "T1 rejected; next direction" at the end of this file.

### Results so far (user runs, 2026-10-20; herd-level aggregates)

**Decisions**

* **M1 kept**, with the 7-day minimum of trusted recent days unchanged (user decision,
  2026-10-20: "keep it as frozen"; a 3-day variant was offered and declined).
* **M3 dropped** by its pre-set keep rule (2024–26 recovery must improve). The PP1
  configuration is `--k anchor_first` without the gate (tag `_kf`). `--anchor-gate` stays
  in the code, off by default.

**M1, development (origins 2017–2023).** Identical to the pfoi-1.1 milk results, as the
design guarantees: monthly MAE 17,790 / 54,299 / 89,458 / 83,447 litres (h 1/3/6/12,
n 68/66/64/58); ratio to persistence 0.64 / 0.83 / 0.93 / 0.65. Daily 1/7/14: 1.18 / 1.07 /
1.03 (n 348/348/347). Weekly 1/4/8/13: 1.10 / 0.90 / 0.91 / 0.95 (n 333/330/326/323). No
forecast date withheld or skipped; the 12-month level was used at 2 monthly and 11 weekly
dates (too few trusted recent days).

**M1, 2024–26 (post-test development).** Forecast dates built: monthly 20 of 32 (17 before
M1), weekly 87 of 138; withheld with a reason: 12 monthly, 51 weekly; built from recent days
alone (no 12-month level): 3 monthly, 14 weekly. Without the gate, ratio to persistence on
each model's own periods: daily 0.97 / 1.03 / 1.09 (n 61/57/56); weekly 0.97 / 1.40 / 1.35 /
1.81 (n 38/35/30/28); monthly rows not interpretable (n 3–5). A same-period comparison with
the pfoi-1.1.0 level is pending (evidence ladder on the `_posthoc` files).

**M3, 2024–26 (post-test development).** With the gate: daily 4.00 / 3.52 / 2.93 (n 42),
weekly 5.83 / 2.59 / 1.96 / 2.68 (n 33), bias about −860 L/day. Almost no DelPro milk was
tied to a cow in 2024–26, so the gate discarded nearly every recent day and the level fell
back to an older one. Different period sets from the ungated run, but the gap is far beyond
that. Development: the gate changed 1 of 365 weekly dates.

**M2, simulated outages (development, 183 weekly origins; optimistic: herd records kept).**
No scenario withheld a forecast: outages up to 180 days never removed the 12-month level.

| Outage, days of records back | daily h1 | daily h7 | weekly h1 | weekly h4 |
|---|---|---|---|---|
| 28 d, 0 or 3 d back | 3.97× | 3.07× | 4.05× | 2.22× |
| 90 d, 0 d back | 4.19× | 3.21× | 4.30× | 2.31× |
| 180 d, 0 d back | 4.64× | 3.57× | 4.81× | 2.61× |
| any, 7 d back | 1.12–1.17× | 1.08–1.13× | 1.09–1.13× | 0.96–1.03× |
| any, 14 d back | 1.00–1.02× | 1.00–1.01× | 0.99–1.00× | 1.00–1.01× |

(error relative to the same forecasts without an outage; n 165–175 per cell). Three days
back changes nothing because at least 7 trusted days are needed before the recent level is
used. Against persistence under the same outage, the fallback level loses for 28-day
outages (1.14–1.74 at daily h1 to weekly h4) and wins for 90- and 180-day outages
(0.58–0.85). Claim supported: in simulated outages on 2017–23, accuracy returns to normal
within 7–14 days of records resuming.

**M4 input (measured).** Spread (sd of log error) by days since the last trusted milk day,
weekly h1: 0.174 (fresh, n 1,660), 0.246 (29–90 d, n 166), 0.266 (91–180 d, n 168), 0.306
(181+ d, n 167); similar at other horizons. Ranges therefore widen by up to about 1.8×
(`outage_staleness_*.csv`). The coverage check (scorecard `--intervals aci`) is pending.

**M5 and M6, monthly only (development; weekly and daily to rerun).** Accuracy at h 1/3/6/12
(n 68/66/64/58): adaptive base 0.963 / 0.907 / 0.867 / 0.838; + recent milk 0.963 / 0.912 /
0.878 / 0.843; + heat 0.961 / 0.909 / 0.876 / 0.840; + heat, knot P90 0.961 / 0.906 / 0.877 /
0.840; oracle heat 0.961 / 0.909 / 0.876 / 0.839; all signals 0.962 / 0.910 / 0.876 / 0.840.
Heat adds nothing beyond recent milk, and the oracle (actual future weather) is no better
than the operational run, so no herd-level heat effect is detectable at the monthly grain.
Every sensor signal stayed in shadow on all 144 forecast dates (no session data before
2025); recorded udder/teat episodes reached probation on 38. These runs used the gated tag
and only monthly files (the weekly adaptive files were written later); they are rerun on
the `_kf` tag.

**Wave 1 (user runs, 2026-10-20, development unless stated; tag `_kf`, no gate)**

*M5 heat and M6 signals (driver layer on the adaptive milk forecast).* Accuracy, h as listed:

| Variant | daily 1/7/14 (n 348) | weekly 1/4/8/13 (n 333–323) | monthly 1/3/6/12 (n 68–58) |
|---|---|---|---|
| adaptive base | 0.970 / 0.963 / 0.953 | 0.973 / 0.944 / 0.909 / 0.880 | 0.963 / 0.907 / 0.867 / 0.838 |
| + recent milk | 0.970 / 0.963 / 0.952 | 0.973 / 0.942 / 0.897 / 0.854 | 0.963 / 0.912 / 0.878 / 0.843 |
| + heat (P75) | 0.970 / 0.962 / 0.950 | 0.973 / 0.934 / 0.876 / 0.828 | 0.961 / 0.909 / 0.876 / 0.840 |
| + heat (P90) | 0.970 / 0.962 / 0.950 | 0.973 / 0.933 / 0.875 / 0.826 | 0.961 / 0.906 / 0.877 / 0.840 |
| oracle heat (analysis only) | 0.970 / 0.962 / 0.950 | 0.973 / 0.934 / 0.878 / 0.819 | 0.961 / 0.909 / 0.876 / 0.839 |
| all signals | 0.969 / 0.962 / 0.950 | 0.973 / 0.934 / 0.878 / 0.831 | 0.962 / 0.910 / 0.876 / 0.840 |

* **M5 dropped** (rule: operational heat must cut daily or weekly MAE by ≥ 2 % and the oracle
  must show signal). Heat leaves daily accuracy unchanged and lowers weekly accuracy by 1–5
  points; perfect knowledge of future weather (oracle) is no better. Claim supported: no
  detectable herd-level heat effect on herd milk at daily, weekly or monthly grain in
  2017–23, even with oracle weather. Heat coefficients have mixed signs (collinear features).
* **Recent-milk features: not adopted.** They help monthly 3–12 months (+0.5 to +1.1 points)
  but lower weekly 8–13 weeks (−1.2 and −2.6 points) and leave daily unchanged.
* **M6 sensors: cannot be validated with current data.** Every session-sensor signal stayed in
  shadow on all 2,308 forecast dates (no session records before 2025). Recorded mastitis per
  cow was active on 1,828 dates and udder/teat episodes on 912; identified share on 500.

*M4 intervals (scorecard, ACI; milk_baseline).* 80 / 90 % coverage: daily 0.784 / 0.889,
0.774 / 0.886, 0.780 / 0.875 (n 348–347, calibrated at 1/7/14); weekly 0.777 / 0.883 and
0.771 / 0.882 at 1 and 4 weeks (calibrated), 0.712 / 0.782 at 13 weeks (not); monthly herd
milk 0.732 / 0.857, 0.673 / 0.808, 0.617 / 0.745, 0.400 / 0.514 (not calibrated). The
empirical intervals covered 90 %: daily 83.4–83.5, weekly 82.3–83.9, monthly 87.5 / 82.7 /
87.2 / 48.6 (milk-report). Width check against the empirical intervals is pending
(`scorecard` without `--intervals aci`). Targets met (target and calibrated): 14 of 42 rows
(pfoi-1.0.0 baseline: 8 of 42, a different configuration). Recovery target (weekly h4,
0–2 months after a break) still missed: 0.669 (n 19; target 0.90).

*M7 reproductive timing (record, all lactations before 2026-08-21).*

| Calvings | median days to first recorded service | median days to known conception | calving interval median | pregnancies calved / lost / still pregnant |
|---|---|---|---|---|
| 2015–2019 (n 7,265) | 66 | 255 | 543 | 93.5 / 1.7 / 0.0 % (n 6,445) |
| 2020–2022 (n 3,975) | 74 | 296 | 644 | 85.6 / 3.7 / 0.0 % (n 2,765) |
| 2023–2026 (n 2,257) | 78 | 430 | not reached | 52.3 / 23.2 / 15.9 % (n 1,195) |

(The calved / lost shares above are over all known pregnancies, pending ones included; from
this version the tables also give them over pregnancies with a known outcome.) Leaving the
herd before conception: 11 % / 30 % / 33 % of lactations by period. The engine (rates at
2026-08-01) is close to the record for conception up to day 200 in parities 2 and 3+, too
high for parity 1 (0.42 vs 0.32 by day 300), and has far fewer cows leaving than recorded
(0.11 vs 0.17–0.31 by day 300 in parities 2 and 3+): a likely source of the milking-cow
over-forecast. With the conception shape at 2023-12 the engine conceives faster than the
record (0.24 vs 0.13–0.23 by day 100); the record there is heavily censored (58–74 % still
open), and the unshaped comparison at the same date is pending.

*Data checks for the ETL (aggregate SQL in the run list).* Some lactations have a next
calving within 60 days (2.4 % of 2023–26 lactations, 5.4 % in parity 1) and some first
services 0–3 days after calving; both look like record errors or inferred lactations.

*M8 outcomes by generation (within calving period; associations only).* Yield vs expected,
2020–22: gen 0 1.011, gen 1 0.976, gen 2 1.036 (n 108,635 / 72,560 / 12,290 cow-days);
2023–26 cells have n 72–2,315 cow-days (yield records cover 0.1–2.5 % of milking days), too
few to compare. Days to first recorded service, 2023–26: 102 / 76 / 78 / 83 (gen 0 / 1 / 2 /
3+; n 269 / 1,211 / 583 / 82). Productive share rises with generation in 2023–26 (0.59 →
0.77), confounded with age and parity. Gen 3+ in 2020–22 has n 3 (not interpretable).

**Wave 2–3 (user runs, 2026-10-20)**

*Evidence ladder, development, error relative to persistence on identical periods.*

| Rung | daily 1 / 7 / 14 (n 348–347) | weekly 1 / 4 / 8 / 13 (n 333–323) |
|---|---|---|
| current (adaptive milk) | 1.195 / 1.049 / 1.032 | 1.057 / 0.933 / 0.948 / 0.908 |
| + recent milk | 1.179 / 1.037 / 1.054 | 1.036 / 0.973 / 1.074 / 1.103 |
| + heat | 1.208 / 1.056 / 1.095 | 1.057 / 1.096 / 1.289 / 1.299 |
| + sensors & health | 1.216 / 1.057 / 1.101 | 1.056 / 1.108 / 1.269 / 1.275 |
| oracle heat (analysis only) | 1.194 / 1.052 / 1.108 | 1.063 / 1.102 / 1.265 / 1.367 |

Hottest periods (target THI above the past 90th percentile; n 30 weekly and 35–39 daily
overlapping forecasts, few independent heat spells): the current model over-forecasts at 8–13
weeks (ratio 1.63 / 1.40, bias +7.9k / +10.7k litres a week) and no heat feature, oracle
included, fixes it. After a break (n 31–37 weekly): 1.44–1.68 against persistence.

*M1 against the pfoi-1.1.0 level, 2024–26, identical periods (post-test development).*
Identical errors on every shared period (weekly n 25 / 20 / 16 / 13, daily n 30 / 28 / 26),
as the design guarantees; both lose to persistence there (weekly 1.49–2.14, daily
1.42–1.79). M1's gain is therefore coverage, not accuracy: 3 monthly and 14 weekly 2024–26
forecast dates built that pfoi-1.1.0 could not build, and 12 monthly / 51 weekly withheld
with a stated reason instead of failing.

*Record checks (ETL, counts by calving year).* Next calving within 60 days: 0–1 a year to
2020, then 4 / 11 / 12 / 7 / 32 / 4 (2021–2026; 32 of 534 lactations in 2025). First service
within 10 days of calving: 0–5 a year to 2021, then 10 / 5 / 7 / 19 / 6. None of these
lactations is marked inferred. Both rise after the 2024–25 outage: to raise with the ETL.

*M7 herd backtest with the conception shape (development, monthly ratio to persistence).*
Calvings 0.63 / 0.17 / 0.34 / 0.65 and milking 0.85 / 0.73 / 0.80 / 0.50 at 1/3/6/12 months.
Without the shape (same periods): calvings 0.63 / 0.17 / 0.34 / 0.66, milking 0.85 / 0.73 /
0.79 / 0.48. **Shape dropped** by its keep rule: calvings unchanged at 6 months and 0.01
better at 12, milking 0.01 worse at 6 and 0.02 worse at 12 (all differences ≤ 0.02).
`--conception-shape` stays in the code, off. Without the shape at 2023-12 the engine's
conception curve is almost the same (23.8 vs 24.3 % by day 100, 64.4 % by day 300 in both),
so nothing is lost. At that date the engine conceives far faster than the 2023 calvings did
(64 % vs 35–40 % by day 300; the record is 58–74 % censored, so beyond about day 150 it is
indicative), consistent with the +22 to +24 calvings a month over-forecast at 2023-11 and
2024-01: the 2023 fertility drop was not yet in the rates (90-day confirmation lag,
recency-weighted window). Pregnancies with a known outcome that calved, 2020–22: 86.6 %
(n 2,562; 82.2 % over all known pregnancies). Milking is over-forecast either way (raw bias
+39 / +80 cows at 3 / 6 months without the shape); the bias-corrected engine leaves −2 to −6.

*Development outlook, 2026-08-01 (pfoi-1.2.0-dev, not frozen).* Herd milk per month from
124.5k (Aug 2026; range 100k–144k) through a dip to 105.7k (Sep) to a peak of 186.3k (Jan
2027). Ranges widen fast after the first month (Sep 73k–219k), reflecting the large
2024–26 errors. The Sep dip is not yet explained (check the `corrections` section of the
run document). 2025-09-01: milk withheld (no trusted recent days), herd forecast kept.
The page ladder of this build came from the 2024–26 ladder files (they overwrote the
development ones); rebuild after rerunning the development ladders.

*M4 width check (scorecard, development; quantile → adaptive).* 90 % coverage and width90:
milk daily 83.4 / 83.5 / 83.4 → 88.9 / 88.6 / 87.5 % (width 0.119–0.179 → 0.195–0.302, 1.6–1.7×);
weekly 1 / 4: 82.3 / 83.9 → 88.3 / 88.2 % (1.3–1.4×); weekly 13: 82.3 → 78.2 % (neither
calibrated); monthly milk 87.5 / 82.7 / 87.2 / 48.6 → 85.7 / 80.8 / 74.5 / 51.4 % (adaptive worse
at 3 and 6 months); milking cows 81.2 / 73.3 / 72.2 / 85.7 → 87.5 / 81.7 / 79.6 / 78.6 % (width
< 1.4×). Rows meeting target and calibration: 4 of 42 with quantile ranges, 14 of 42 with
adaptive ones. **Decision (keep rule):** adaptive ranges for daily and weekly milk and every
herd series; monthly milk keeps the quantile ranges (`outlook.run_interval_table`, tested).

**Forecast-date comparisons (compare-runs, monthly, 12 months after each date; user runs
2026-10-20; each row is one forecast date, so these are examples, not evidence).**

* **pfoi-1.2.0-dev equals pfoi-1.1.0 at all eight dates** (change 0 % for every series). At
  these dates the 12-month calibration existed, so M1 sets the same level; M4 changes only
  ranges. M1's gain shows only at dates pfoi-1.1.0 cannot build (2025-09 withheld,
  2025-12, 2026-04), which `compare-runs` cannot pair.
* Against pfoi-1.0.0 (MAE change, negative = better): milking −24 to −45 % at 2019-06,
  2020-08, 2022-09, 2023-11, 2024-01, but +168 % at 2017-01 and +57 % at 2024-07; total herd
  better at 2019-06, 2022-09, 2023-11, 2024-01 (−5 to −59 %), worse at 2017-01, 2020-08,
  2024-07 (+10 to +47 %); herd milk better at 2019-06 and 2020-08 (−45 %, −49 %), worse at
  2017-01, 2022-09, 2023-11, 2024-01, 2024-07 (+5 to +292 %, n 2–12 recorded months).

*What the charts show (both versions, herd level):*

1. **Abortion surges are missed.** Forecasts stay near the window's recent rate (about 4–13 a
   month) while the record reaches 15–44 a month after 2023-11 (and 10–24 in late 2020). A
   constant-rate model cannot anticipate a surge; the honest output is a wide, downside range.
2. **Herd contractions are over-forecast.** At 2023-11 and 2024-01 milking cows are forecast
   at 600–850 while the record falls to about 400, and total herd at 2,000–2,200 against
   about 1,600 (the 2024 removal campaign, a management decision). This matches the engine
   having far fewer cows leaving than recorded (M7).
3. **The recovery after 2024 is under-forecast.** At 2024-07 the herd is forecast to keep
   shrinking to about 1,200 while the record stays near 1,650: exit rates learned in the
   removal year are carried forward. The correction layer adds about +83 milking cows there,
   making milking worse (+57 % against pfoi-1.0.0).
4. **2017-01 milk is far too high** (peak about 1.3 M litres a month against 0.83 M), while
   cows and calvings track well: the yield level for the spring-2017 wave of fresh cows is
   too high (early-years curve and level, 2015–16 restocking in the window).
5. **The correction layer pulls milk down after breaks** (−23k to −27k litres a month at
   2019-06, 2020-08, 2022-09): it helps where the structural forecast was too high (2019-06,
   2020-08) and hurts at 2022-09, where the record was higher.
6. **Bug found and fixed:** the page document (and therefore these charts) had no milk range
   for pfoi-1.1.0 and the development build, because it was built without the adaptive milk
   model's own errors. The `c1_output.outlook` tables were correct. Rebuild both versions'
   page documents to show milk ranges (`build_page_run(..., interval_errors=...)`, tested).

### PP1 improvements (user decision 2026-10-20: build 1a, 1b, 1c and the exit fix; publish)

Implemented and tested on synthetic data. The following keep rules were fixed before any
real-data run; the latest evaluation is recorded immediately after this table:

| # | Change | Option / command | Keep rule (development, unless stated) |
|---|---|---|---|
| 1a | Break reset: corrections use only errors from forecast dates after the latest break visible at the forecast date (herd size ±10 % over 90 days, or milk back after 28+ days; breaks within 60 days merged) | `break-reset` (evaluates on saved errors, writes `_br` candidates); `build-outlook --break-reset on` | after-break accuracy improves for herd milk (weekly 4 w, monthly 3 m) and milking (monthly 3, 6 m), and all-dates accuracy drops ≤ 1 point on every key row |
| 1b | Faster half-life for abortions, pregnancy losses, exits and conceptions (other rates keep 6 months) | `--fast-half-life 3` (tag `_fhl3`) | real abortions and total herd MAE improve at 3–6 months; milking and calvings no worse than +2 % at any horizon |
| exit fix | Milking-cow exits measured from dated lactation records by parity × DIM band × pregnancy status (shrunk to the pooled rate), split into deaths / culls / sales as before | `--exit-model lactation` (tag `_xl`) | milking and total herd MAE improve at 3–6 months; calvings no worse than +2 %; engine "left herd" curve closer to the record (`repro-timing`) |
| 1c | "What if it happens again" bands for milk, milking cows and total herd, from responses after earlier episodes (herd contraction, abortion surge, heat, …) | `scenarios --herd-tag`; shown on the page | descriptive; always labelled "what happened before, not a forecast"; n episodes shown |

All options stay outside the pfoi-1.0.0 / 1.1.0 hashes (tested). Development builds that use
them are published as `pfoi-1.2.0-dev`.

### First supplied batch: decisions and provenance (2026-10-20)

Historical review of the first attachments. The completed-build follow-up below supersedes
this subsection's interrupted-build, publication and stale-comparison findings; keep/drop
rules and missing exit/milk checks remain applicable.

Evidence: eleven pasted command outputs, the break-reset and milk-run outputs pasted in
chat, and aggregate PNGs explicitly permitted by the user in `logs/pfoi/compare/` and
`logs/pfoi/evidence/`. No other log file was opened; no database or `.env` was accessed.
Exact supplied aggregate tables are retained in the appendix below. Repeated reports are
one result, not independent replications. No result below is a fresh held-out test.

**Apply the original keep rules without changing them:**

| Option | Decision | Reason |
|---|---|---|
| 1a break reset | **Keep by the numerical development rule**, with small-sample qualification | All four required after-break accuracies improve and none of the seven all-date accuracies falls. Three required after-break cells have n < 12; those cells are not interpretable under `targets.md`. This is a mechanical pass, not strong confirmation. |
| 1b fast half-life 3 | **Drop from the selected configuration** | Abortions improve, but total-herd MAE at 6 months rises 8.1%, and milking at 12 months rises 5.7%, exceeding its +2% safeguard. |
| Lactation exit option alone | **Pending full keep rule** | Raw milking and total-herd MAE improve at both 3 and 6 months; documented monthly calving MAEs at 3/6/12 months stay within +2%. The supplied batch has no new `repro-timing` exit curve, and the complete baseline safeguard across horizons still needs the aggregate summary. Do not call it fully accepted yet. |
| Fast half-life + lactation exits | **Do not select the combination** | It does not rescue 1b: total-herd MAE at 6 months rises 5.2%, calvings at 12 months rise 3.2%, and milking at 12 months rises 8.1%. Better post-test scores cannot override the development rule. |
| 1c scenarios | **Keep as descriptive** | Every response cell has only 1–8 usable episodes (< 12): show n and the range; no causal or reliable predictive claim. |

The raw-engine comparisons below use the pre-existing half-life-6 baseline in
`pfoi_1_1_candidate.md`, development origins 2017–2023. Percent changes are derived from
the supplied, rounded MAEs, not new measurements. They do not establish a win for the
published correction layer, whose candidate MAEs are separately retained in the appendix.

| Series | Monthly horizon (n) | Baseline | Fast 3 | Lactation exits | Both |
|---|---|---|---|---|---|
| Milking | 3 (82) | 68.07 | 66.35 (−2.5%) | 66.81 (−1.9%) | 65.04 (−4.4%) |
| Milking | 6 (79) | 106.09 | 102.25 (−3.6%) | 99.60 (−6.1%) | 93.86 (−11.5%) |
| Milking | 12 (73) | 93.79 | 99.09 (+5.7%) | 94.76 (+1.0%) | 101.37 (+8.1%) |
| Total herd | 3 (82) | 74.79 | 74.60 (−0.3%) | 73.17 (−2.2%) | 72.89 (−2.5%) |
| Total herd | 6 (79) | 123.93 | 133.94 (+8.1%) | 120.96 (−2.4%) | 130.35 (+5.2%) |
| Calvings | 3 (82) | 8.05 | 8.00 (−0.6%) | 8.09 (+0.5%) | 8.03 (−0.2%) |
| Calvings | 6 (79) | 17.08 | 16.81 (−1.6%) | 17.05 (−0.2%) | 16.74 (−2.0%) |
| Calvings | 12 (73) | 25.63 | 26.22 (+2.3%) | 26.03 (+1.6%) | 26.45 (+3.2%) |
| Real abortions | 3 (82) | 3.88 | 3.64 (−6.2%) | 3.88 (0.0%) | 3.65 (−5.9%) |
| Real abortions | 6 (79) | 4.13 | 4.07 (−1.5%) | 4.13 (0.0%) | 4.08 (−1.2%) |

**1a, development.** Four detected breaks (years 2015, 2016, 2022, 2023). Accuracy is
1 − WAPE, not the ratio to persistence. All-date n and after-break n refer to scored
forecast periods; they are not counts of independent breaks.

| Series, grain, horizon | n / n after break | All dates, before → reset | After break, before → reset |
|---|---|---|---|
| Milk, weekly 4 | 330 / 33 | .944 → .945 | .834 → .851 |
| Milk, monthly 3 | 66 / 6 | .907 → .908 | .735 → .789 |
| Milking, monthly 3 | 82 / 8 | .942 → .945 | .878 → .923 |
| Milking, monthly 6 | 79 / 8 | .932 → .942 | .739 → .893 |
| Total herd, monthly 6 | 79 / 8 | .957 → .961 | .896 → .944 |
| Total herd, monthly 12 | 73 / 2 | .954 → .955 | .831 → .873 |
| Calvings, monthly 3 | 82 / 8 | .936 → .937 | .913 → .944 |

**1a, post-test development (2024–26 already inspected).** Six detected breaks (the four
above plus 2024 and 2025). This run is for the original tags, not `_fhl3_xl`.

| Series, grain, horizon | n / n after break | All dates, before → reset | After break, before → reset |
|---|---|---|---|
| Milk, weekly 4 | 35 / 16 | .589 → .773 | .311 → .684 |
| Milk, monthly 3 | 3 / 2 | .612 → .647 | .625 → .652 |
| Milking, monthly 3 | 29 / 12 | .924 → .881 | .946 → .918 |
| Milking, monthly 6 | 26 / 11 | .853 → .808 | .871 → .890 |
| Total herd, monthly 6 | 26 / 11 | .864 → .881 | .906 → .935 |
| Total herd, monthly 12 | 20 / 6 | .750 → .740 | .713 → .697 |
| Calvings, monthly 3 | 29 / 12 | .686 → .662 | .660 → .631 |

Weekly milk improves by 18.4 percentage points overall and 37.3 after breaks. Milking
falls by 4.3/4.5 points overall at 3/6 months, and calvings by 2.4 points at 3 months.
Do not describe the reset as improving every target. Monthly milk n = 3 is not interpretable.

**Combined engine, post-test development.** Raw monthly total-herd MAE at 3/6/12 months
is 93.91/207.72/434.44 (n 29/26/20), versus persistence 85.93/159.87/204.55: ratios
1.09/1.30/2.12. Corrected total herd is also worse (105.85/220.94/409.45; same n).
Raw milking is 43.94/63.46/80.19; corrected 32.90/58.95/123.31, versus persistence
42.85/81.10/131.44 (same n). These are mixed results, not a general improvement.
This backtest did not include break reset; do not attribute its scores to 1a.

**1c scenarios.** Library: 9 abortion surges, 10 dry spells, 2 contractions and 6 mastitis
surges; no heat episode is listed in the supplied output (no heat response can be claimed).
Usable n varies by response and horizon. Four-week milk after abortion surges: median
−.024, range −.145 to +.044 (n 6). Four-week contraction responses: milking −.067
(−.091 to −.042, n 2), total herd −.027 (−.033 to −.021, n 2), no usable milk response.
Three-month contraction responses: milking −.121 and total herd −.055 (n 1 each).
All responses are excess relative errors after removing the preceding year's typical
forecast bias (`scenarios.md`), not direct percentage changes in production or herd size.
The centred episode library includes 2024; label the library descriptive with post-test
development exposure. Counts of episodes are not counts of successful forecasts.

**Milk-run completeness.** The two pasted `_fhl3_xl --block posthoc` runs contain notes,
not MAE/RMSE/coverage tables. They scheduled 32 monthly and 138 weekly origins; monthly
notes: curve 26, k 52, k_window 8, no_window_k 9, withheld 6; weekly: curve 116, k 232,
k_window 37, no_window_k 43, withheld 22. Notes overlap and k can occur more than once
per origin; never add them to get the number of origins. These runs are repeats, not
independent samples. The first warns that development monthly and weekly errors are
missing; the second still warns for weekly. Absence of the second monthly warning does
not establish what changed. A clean development-before-posthoc rerun and `milk-report`
are required before claiming milk accuracy or calibration for that tag.

**Build and comparison provenance.** The pasted build requests `_kf_fhl3_xl`, reset and
ACI at 11 dates. Nine dates finish (2017-01 through 2025-12); 2026-04 is interrupted
with `^C` before its result, and no 2026-08 completion is supplied. Both 2025-09 and
2025-12 withhold milk while retaining herd forecasts. This updates the earlier
expectation that 2025-12 would produce milk. Every completed run says it was not written
to the database; there is no supplied evidence of publication.

The comparison output is **not a matched comparison of that completed configuration**:
its July 2024 chart starts near 165k L, while the new build prints 154,266 L; its milk
ranges remain absent although the build prints ranges. `compare-runs` reads saved page
documents, and every development configuration shares the same version/date path with
config hash `dev` (`cli._build_outlook_one`). This permits mixed generations of artifacts.
The exact chronology cannot be proved from these outputs; do not blame ignored options:
the code passes both engine options to `run_model`. Rerun comparisons after one complete
build and keep that configuration's artifacts together. There is no fresh numeric
comparison against pfoi-1.0.0 in the supplied attachments; old percentages above remain
historical, not measurements of the combined option run.

**PNG review: all eight monthly dates against both older versions (16 PNGs).**

* Against 1.1.0, the supplied comparison is unchanged at six scored dates (2019-06,
  2020-08, 2022-09, 2023-11, 2024-01, 2024-07; n = 12 herd months each; milk n =
  12/12/9/6/4/2). At 2017-01 (n 12 per series), MAE changes are milk +4.38%, milking
  +9.47%, total herd +55.84%, calvings +3.10%, abortions −47.62%. This supersedes
  the earlier "identical at all eight dates" description for these saved artifacts.
* Against 1.0.0, the saved charts still show a tradeoff: lower milk over-forecast in
  2019/2020, better tracking of declining milking counts in 2022/2023, but milk too low
  after the 2022 gap; 2017 milk and herd remain too high. These are visual comparisons,
  not newly computed percentage improvements; n is one forecast origin per chart.
* Recorded outcomes still expose the same failures: the 2023/2024 abortion surge is
  missed; 2024 milking and herd contractions are too small; July 2024 projects continued
  herd decline while the recorded herd stabilises. Wider ranges do not fix point bias.
* August 2026 has **n = 0 complete recorded future months** in the supplied comparison.
  Its different milk trajectory and broad herd ranges are outlooks, not accuracy evidence.
* Candidate milk ranges are missing in the saved 1.1.0 comparisons and several 1.0.0
  comparisons; no general candidate milk coverage claim can be made from these examples. Rebuild the page documents before judging the interval fix.

**Six evidence PNGs, post-test development; M1 versus 1.1.0 level only.** Both bars are
identical, so these compare M1 on shared periods, not 1a/1b/exits. Ratios to
persistence read from the rounded chart labels:

| Grain / band | Horizons | n | Ratio (both models) |
|---|---|---|---|
| Daily, all | 1/7/14 | 30/28/26 | 1.41/1.68/1.79 |
| Daily, recovery | 1/7/14 | 27/26/25 | 1.38/1.74/1.82 |
| Daily, normal | 1/7/14 | 3/2/1 | 3.38/.83/.48 (not interpretable) |
| Weekly, all | 1/4/8/13 | 25/20/16/13 | 1.49/1.90/1.46/2.14 |
| Weekly, recovery | 1/4/8/13 | 23/20/16/13 | 1.48/1.90/1.46/2.14 |
| Weekly, normal | 1 only | 2 | 1.72 (not interpretable) |

**Next user-run checks (aggregate output only).** No new database SQL is needed for this
review. First supply the missing exit comparison at the same as-of date as the earlier
record curve, with and without the option; retain its n/censoring fields:

```bash
python -m components.predictive_farm_intelligence.pfoi.cli repro-timing --preset pfoi-1.1 --asof 2026-08-21
python -m components.predictive_farm_intelligence.pfoi.cli repro-timing --preset pfoi-1.1 --exit-model lactation --asof 2026-08-21
```

The original three new engine backtests need not be repeated. For the full exit safeguard,
the user can print only aggregate metric rows from the existing baseline summaries:

```python
from pathlib import Path
import pandas as pd
for grain in ('monthly', 'weekly'):
    p = Path('logs/pfoi') / f'herd_backtest_summary_{grain}_w24_ck_kn_rk_lag90_hl6.csv'
    s = pd.read_csv(p)
    keep = s['series'].isin(['milking', 'n_herd', 'calvings', 'real_abortions'])
    keep &= s['model'].isin(['herd_engine', 'herd_engine_corrected', 'persistence'])
    print(s.loc[keep, ['grain', 'series', 'horizon', 'model', 'n', 'mae']].to_string(index=False))
```

After the exit decision, run milk development first with the **selected** flags, then
posthoc, and print `milk-report` for both blocks with identical flags. Drop
`--fast-half-life 3`; add `--exit-model lactation` only if its full keep rule passes.
Evaluate break reset again on any newly selected engine/milk tags before transferring
the old-tag result to that configuration. Finish all 11 build dates, rerun compare-runs
against both frozen versions, review aggregates, then the user can publish the chosen
build with `--write`. No write or commit was performed during this review.

Review validation: `python -m pytest
components/predictive_farm_intelligence/tests/test_pp1_improvements.py
components/predictive_farm_intelligence/tests/test_pp1_outlook.py -q` — **23 passed**
in 265.35 seconds, synthetic sources only. Frozen hash assertions passed. Aggregate-table
preservation and Markdown fence/details checks passed; `git diff --check` passed for this
document. This review changed only this plan; existing code and concurrent frontend work
were left as found.

### Completed build and refreshed comparisons (follow-up, 2026-10-20)

Sources: three new user-pasted outputs (`build-outlook --write`, then comparisons against
1.1.0 and 1.0.0), plus all 16 refreshed monthly aggregate PNGs in the permitted compare
folder. This supersedes the previous comparison and interrupted-build findings above.
The exact new aggregate outputs are retained in the follow-up appendix below.

**Completion and publication:** the user's command reports **11/11 dates built** and
`written to c1_output` plus `run_document` at every date. This is user-supplied evidence
of publication, not an agent database verification. The command still includes
`--fast-half-life 3 --exit-model lactation --break-reset on`, as well as anchor-first,
ACI and the measured staleness file. Thus the published development configuration includes
the combination that failed the fixed development safeguards; successful publication
does not change that decision. The exit-only decision and missing milk backtest reports
are still pending. No code, defaults, output data or database state was changed in this review.

**Consistency checks:** the candidate's MAE, bias, coverage and correction-layer values
match between both new comparison tables at all 40 origin/series rows, with matching n.
The July 2024 chart now starts at about 154k L, matching the build's 154,266 L, and the
August 2026 curve starts at about 130k L, matching 130,270 L. Milk ranges are now visible
after the earliest origin. The earlier artifact mismatch is resolved by these supplied
outputs and charts. This is not an independent inspection of the saved JSON files.

**Point forecast results versus 1.1.0: MAE change %, negative is better.** Each row is one
forecast origin, evaluated across its available future months, not a rolling-backtest
average or an independent sample of twelve origins. Origins before 2024 are development
examples; 2024–26 origins are post-test development. The 2023-11 example also includes
already inspected 2024 outcomes and is not independent confirmation.

| Origin | Milk n | Herd-series n each | Milk | Milking | Total herd | Calvings | Abortions |
|---|---|---|---|---|---|---|---|
| 2017-01 | 12 | 12 | +4.38 | +9.47 | +55.84 | +3.10 | −47.62 |
| 2019-06 | 12 | 12 | −1.33 | +5.63 | +104.50 | −3.32 | −.29 |
| 2020-08 | 12 | 12 | −1.27 | +10.90 | +40.24 | −.40 | +.41 |
| 2022-09 | 9 | 12 | +.65 | −1.68 | +10.61 | −6.91 | −4.16 |
| 2023-11 | 6 | 12 | −32.64 | +80.85 | +86.72 | +3.38 | −1.58 |
| 2024-01 | 4 | 12 | −.26 | +64.08 | +80.51 | +34.23 | −9.21 |
| 2024-07 | 2 | 12 | −36.03 | −63.22 | +44.99 | −10.14 | −16.78 |
| 2026-08 | 0 | 0 | — | — | — | — | — |

**Versus 1.0.0, same n and status labels as the preceding table:**

| Origin | Milk | Milking | Total herd | Calvings | Abortions |
|---|---|---|---|---|---|
| 2017-01 | +9.97 | +193.13 | +122.26 | +69.98 | −13.69 |
| 2019-06 | −45.85 | −20.00 | +94.73 | +83.01 | +3.99 |
| 2020-08 | −50.07 | −21.70 | +105.77 | −21.08 | +4.91 |
| 2022-09 | +294.53 | −35.53 | −54.49 | +25.26 | −.32 |
| 2023-11 | +38.61 | −.37 | +44.69 | −15.22 | −1.86 |
| 2024-01 | +37.30 | +9.02 | +31.98 | +1.83 | −12.55 |
| 2024-07 | −18.62 | −42.34 | +59.08 | −28.45 | −15.13 |
| 2026-08 | — | — | — | — | — |

**Reading the results against the recorded outcomes:**

* **Total herd is the clearest regression.** It is worse than 1.1.0 at all seven scored
  origins (n 12 months each). Against 1.0.0 it is worse at six of seven, improving only
  at 2022-09 (−54.49%). Do not average the percentages across these selected, overlapping
  examples to claim overall model accuracy.
* **Contraction is still missed and the correction layer sometimes amplifies it.** At
  2023-11 the candidate over-forecasts milking by 235.02 cows and total herd by 442.89
  animals on average (n 12 each); its mean correction adds +85.45 cows and +71.17 herd.
  At 2024-01 the over-forecasts are +259.77 and +525.79, with corrections +123.00 and
  +166.71 (n 12 each). These positive additions worsen the mean bias. They do not prove
  that break reset alone caused the regression: engine rates and exits changed too.
* **July 2024 milking improves substantially**, MAE 98.34 → 36.16 cows versus 1.1.0,
  bias +.79 (n 12). But total herd is now under-forecast by 331.54 animals versus 228.66
  before (n 12). Its mean correction is zero for both series, so this particular herd
  miss remains in the structural projection. The chart carries removal rates forward
  while the recorded herd stabilises.
* **Milk is mixed.** Versus 1.0.0 it improves in 2019/2020 (n 12 each), but the 2022-09
  under-forecast has MAE 43,751.98 L versus 11,089.63 L (n 9, not interpretable). The
  2023-11 gain versus 1.1.0 (MAE 41,487.39 → 27,947.89 L, n 6) still loses to 1.0.0
  (20,163.18 L). Milk comparisons at 2022-09 onward have n 9/6/4/2, all below the
  agreed n ≥ 12 interpretation threshold. They cannot justify selecting the combination.
* **Abortion point forecasts still miss the surge.** January 2024 MAE falls from 22.23
  to 20.18 events/month versus 1.1.0 (n 12), yet bias is −20.18: an improvement without
  capturing the surge's level. Wider bands are not an improvement in point prediction.

**Intervals: rendering fixed, usefulness unresolved for this combined configuration.**
Candidate monthly milk coverage is .83/1.00/.00/.50/.25/.50 at 2019-06/2020-08/2022-09/
2023-11/2024-01/2024-07, with scored-month n 12/12/9/6/4/2. The first origin has no
ranges and the last has no complete realised month. `compare_runs.score` computes
coverage over the subset with non-degenerate ranges; it does not print that subset's n,
so scored-month n is not necessarily the coverage denominator. Do not infer formal
calibration from these examples. The frozen 1.1.0 documents still have missing milk
ranges, so their blank coverage is unavailable, not zero coverage.

The new blue event ranges are visibly excessive in several charts: at 2023-11 and
2024-01, calving upper bounds reach roughly 4,000/month; July 2024 abortion bounds reach
roughly 800–900/month (visual estimates from one origin per chart, not exact exported
bounds). They flatten the plotted point forecasts. Even candidate coverage of 1.00 for
January 2024 abortions (n 12 scored months) cannot establish useful uncertainty at that
width. The prior M4 coverage/width result belongs to the earlier configuration, not this
combination. A matched coverage-and-width audit remains required. The code uses
quality-scaled log-ratio errors for ACI; without the permitted aggregate diagnostic
output, the specific source of this inflation is not established. No interval was
clipped or tolerance changed to make these charts look better.

**August 2026 outlook (post-test development; n = 0 complete realised monthly periods).**
Milk is 130,270 L in August (116,718–142,994), 130,280 L in September (88,650–147,787),
peaks at 180,296 L in January 2027 (112,371–213,960), and ends at 136,561 L in July
(78,370–170,029). The former September dip is absent in this build, but cannot be called
an accuracy improvement. The April 2026 build now completes (153,401 L in its first
month, 137,251–168,433; `no_window_k`), and September/December 2025 still withhold milk
while retaining herd forecasts. All printed monthly forecasts and ranges are preserved
in the follow-up appendix; forecast counts are not scored sample sizes.

**Decision unchanged:** retain this as a published **development experiment**, not the
selected PP1 configuration or a validated replacement for 1.1.0. The fast-half-life
combination already failed the original development rule. Resolve exit-only and
selected-configuration interval/milk checks as listed above; changes to selected options
must be evaluated on their own tags. No fresh model-selection claim follows from these
eight selected forecast dates.

Follow-up validation: candidate n/MAE/bias/coverage/correction values match across all
40 rows of both comparisons; all three supplied outputs retained, Markdown structure
and `git diff --check` passed. `python -m pytest
components/predictive_farm_intelligence/tests/test_pp1_improvements.py -q -k
'not scenarios_command'` — **11 passed, 1 deselected in 3.83 seconds**, synthetic only.
The deselected synthetic scenario CLI integration test was included in the preceding
23-test pass; no code changed between these reviews. Only this plan was edited.

### Decision sequence requested by the user (2026-10-20)

**Selected for evaluation:** the six-month reference rates, anchor-first milk, no fast
half-life and no conception shape. Exit-only is the preferred candidate, conditional
on completing the original calving safeguard against the saved development summaries.
Break reset is selected only by its rule on that engine's own tags. Intervals remain
unconfirmed; there is no new calibration or held-out accuracy claim.

**New reproductive evidence (post-test development, supplied aggregates).** Both reports
use lactations starting before 2026-08-21 and engine rates at 2026-08-01. The observed
tables are the same; only the engine's projected curves change. The record comparison
uses 2023–26 lactations: parity 1 n=503 (42.7% censored for conception), parity 2 n=528
(16.3%), parity 3+ n=1,226 (10.3%). The checkpoints are dependent points on three
curves, not 15 independent samples.

| Parity | Mean absolute exit-share gap across five checkpoints, reference → exit-only | Recorded / reference / exit-only left by day 300 |
|---|---|---|
| 1 | 1.90 → 1.20 percentage points | .105 / .111 / .120 |
| 2 | 5.68 → 5.56 points | .169 / .107 / .107 |
| 3+ | 17.16 → 16.04 points | .313 / .107 / .117 |

Derived from the rounded printed checkpoints (days 60/100/150/200/300), the equally
weighted mean absolute gap across all 15 points falls from 8.25 to 7.60 points (about
7.8% relatively). This descriptive summary was not a pre-specified metric: it supports
the original directional "closer" check, not a new tuned threshold. Parity 1 worsens at
day 300; parity 2 barely changes; parity 3+ still misses most exits. The reproductive
part of the exit-only rule is supported with these limits. The new curve does not make
the engine's fertility or exits fully match the record.

**Remaining numerical safeguards are now executable, not assumed.** Agent access to
non-PNG log files remains prohibited. `pfoi/pp1_decisions.py`, run by the user, reads
only the saved baseline and exit-only aggregate summary tables. It checks raw monthly
milking and total-herd MAE strictly improve at 3/6 months, and raw calvings worsen by
at most 2% at all monthly 1/3/6/12 and weekly 1/4/8/13 horizons. Every required cell must
exist, be unique and finite, and have equal n>=12. It prints baseline/candidate MAE, n,
change and verdict per cell. Both runs must use the same development origin schedule,
as in the supplied run list; equal n alone does not prove matching periods.

Missing evidence stops the runner before any real-data command. A failed numerical rule
rejects exit-only and selects the reference engine. A pass selects exit-only, supported
by the supplied reproduction check above. The post-test outcomes never override a failed
development safeguard. The script contains no hard-coded Farm X performance values.

**Break-reset decision:** no automatic transfer from the combined or reference run.
After the selected engine's development milk backtest finishes, the runner invokes
`break-reset` with its own herd and milk tags, reads the aggregate comparison table and
applies the original seven-row rule. The command now saves
`break_reset_comparison_<milk-tag>[_posthoc].csv` so the decision is inspectable.
`break_eval.verdict` previously skipped missing pairs, which could give a partial table
a false pass. Missing/duplicate pairs, nonfinite values or unequal n now prevent a pass.
Small after-break n remains qualified, without changing the original numerical keep rule.
The posthoc reset run is reported separately; it does not select the option.

**Uncertainty-width investigation and decision:** the displayed event ranges are not
accepted as calibrated or useful. Code inspection found two mechanisms to audit:

1. The development outlook passes milk-derived record-quality bands to ACI for herd
   counts and events too; these bands describe milk recording, not direct event quality.
2. Quality scaling divides/multiplies the entire `log(actual/forecast)` residual, without
   separating bias from spread. A synthetic run with 24 completed monthly errors,
   forecast=10 and actual about 100, has upper actual/forecast multiplier 10.10 under
   a normal current band versus 102.02 under an unverified current band. This is the
   same synthetic error history, not measured Farm X performance: doubling a nonzero
   log-residual also squares its bias multiplier. It establishes an inflation mechanism,
   not the exact decomposition of the observed 4,000-calving range.

No cap, tolerance relaxation or change to the frozen interval formula was made. A
candidate remedy is to separate residual location from spread and to avoid treating milk
recording quality as event-record quality; such a method requires its own development
coverage/width comparison before adoption. The runner prints the selected configuration's
empirical, ACI quality-on and ACI quality-off scorecards. The quality-off control is an
audit, not a selected replacement. Its filename now ends `_quality_off.csv`, preventing
it from overwriting the quality-on audit. Compare `n`, `coverage80`, `coverage90`,
`width90` and `calibrated` for identical cells; use the original coverage bands and
less-than-doubling width rule. Raw/bias-corrected scorecard checks do not by themselves
validate adaptive milk or reset-layer published ranges; those need their own errors.

**One user-run command from the repository root:**

```bash
python -m components.predictive_farm_intelligence.pfoi.pp1_decisions --run --jobs 4
```

Without `--run`, it only audits aggregate summaries and prints commands. With `--run`,
the sequence is: exit preflight → milk development → development milk-report → selected
tag break-reset (development) → three interval scorecards → selected engine herd posthoc
→ milk posthoc → posthoc milk-report → selected tag break-reset (posthoc). Commands stop
on execution failure. Development milk always precedes posthoc, so its errors exist
before posthoc correction/interval history is loaded. It never invokes the final test,
`--force`, `build-outlook`, `--write`, a database migration or a commit. It can take a
long time; paste the aggregate tables and verdicts, not animal records.

The user's screenshot shows the eleven visible development origin/version groups each
with `n_builds=1`. This supports one saved run-document row per listed key; it does not
identify which option combination is behind the shared development version or establish
forecast quality. No SQL in the image was executed by the agent.

Validation of this decision workflow: synthetic decision/ordering/error-file guards,
break-reset guards, interval and scorecard suites — **41 passed, 1 deselected in 4.37s**:

```bash
python -m pytest components/predictive_farm_intelligence/tests/test_pp1_decisions.py components/predictive_farm_intelligence/tests/test_pp1_improvements.py components/predictive_farm_intelligence/tests/test_intervals.py components/predictive_farm_intelligence/tests/test_scorecard.py -q -k 'not scenarios_command'
```

The deselected scenario CLI integration test is unrelated to these edits and was included
in the preceding 23-test pass. Frozen hash assertions passed. The runner execution test
mocks every subprocess and uses temporary fictional summaries; it does not launch a
real-data command. `pp1_decisions --help`, Markdown structure and `git diff --check`
passed. A first standalone synthetic inflation probe omitted quality-frame columns and
raised KeyError; after completing that fictional fixture it produced the values reported
above. No real files were involved in that probe. Changes: decision runner, synthetic
tests, reset validation and aggregate comparison export, distinct quality-off scorecard
filename, and this plan. No frontend edits, database access, publication or agent commit.

### Decision-run results supplied by the user (2026-10-20)

Source: pasted `pp1_decisions --run --jobs 12` output. All ten evaluation commands
completed, ending with the runner's completion message. No traceback or missing-file
warning appears. No outlook was published by this sequence. Results from 2024–26 are
post-test development, not new held-out confirmation. Exact supplied output is retained
in the decision-run appendix below.

**Selection now settled by the fixed rules:**

* **Keep exit-only.** All 12 numerical safeguards pass, completing the pending decision;
  the preceding reproductive check provides its separate directional support. Keep the
  six-month reference half-life and `--exit-model lactation`; no `--fast-half-life 3`.
* **Keep break reset on exit-only by its development rule**, qualified by small samples.
  Its own tags are `_xl` and milk `_kf_..._xl`, not `_fhl3_xl`. The post-test run exposes
  mixed behavior and is retained below; it does not replace the pre-fixed selection rule.
* **Keep anchor-first.** Development milk completes without withheld/skipped notes;
  posthoc withheld counts are explicitly reported, never replaced with zero milk.
* **Intervals: partial support only.** Daily milk and weekly 1/4-week raw-milk ACI rows
  satisfy the coverage bands without doubling width. This is not evidence that all herd
  horizons or the adaptive/reset output layers are calibrated. Monthly milk retains the
  existing quantile choice; do not infer that those quantiles are calibrated everywhere.

**Exit safeguards, development, raw engine (n is forecast periods):**

| Grain / series | h | n | Reference MAE | Exit-only MAE | Change % |
|---|---|---|---|---|---|
| Monthly calvings | 1 | 84 | 17.0911 | 17.1021 | +.0642 |
| Monthly calvings | 3 | 82 | 8.0544 | 8.0863 | +.3964 |
| Monthly calvings | 6 | 79 | 17.0824 | 17.0491 | −.1949 |
| Monthly calvings | 12 | 73 | 25.6331 | 26.0303 | +1.5496 |
| Monthly milking | 3 | 82 | 68.0685 | 66.8058 | −1.8551 |
| Monthly milking | 6 | 79 | 106.0881 | 99.6031 | −6.1128 |
| Monthly total herd | 3 | 82 | 74.7944 | 73.1749 | −2.1653 |
| Monthly total herd | 6 | 79 | 123.9300 | 120.9627 | −2.3943 |
| Weekly calvings | 1 | 365 | 6.5673 | 6.5680 | +.0103 |
| Weekly calvings | 4 | 362 | 4.9133 | 4.9154 | +.0426 |
| Weekly calvings | 8 | 358 | 4.4195 | 4.4258 | +.1414 |
| Weekly calvings | 13 | 353 | 4.2538 | 4.2637 | +.2315 |

The largest calving increase is +1.5496%, below the +2% limit. The modest milking and
total-herd gains meet their required 3/6-month directions. These all-date n values differ
from scorecard n below, which excludes unverified/gap target periods.

**Exit-only break reset, development, accuracy = 1 − WAPE:**

| Series, grain, h | n / after-break n | All dates before → reset | After break before → reset |
|---|---|---|---|
| Milk weekly 4 | 330 / 33 | .944 → .945 | .834 → .853 |
| Milk monthly 3 | 66 / 6 | .909 → .910 | .729 → .790 |
| Milking monthly 3 | 82 / 8 | .941 → .943 | .873 → .912 |
| Milking monthly 6 | 79 / 8 | .930 → .939 | .726 → .858 |
| Total herd monthly 6 | 79 / 8 | .956 → .959 | .892 → .935 |
| Total herd monthly 12 | 73 / 2 | .952 → .953 | .829 → .870 |
| Calvings monthly 3 | 82 / 8 | .936 → .938 | .916 → .947 |

All four required after-break rows improve; none of the seven all-date rows falls.
The required milk-monthly and both milking after-break rows have n<12, so the numerical
pass is qualified, not strong confirmation. Four detected breaks: 2015, 2016, 2022, 2023.

**Milk development, exit-only, without the reset (the raw/bias-corrected milk-report):**

| Grain | h | Raw MAE | Raw ratio to persistence | Raw n |
|---|---|---|---|---|
| Monthly | 1/3/6/12 | 17,477 / 50,412 / 81,927 / 78,088 L | .63 / .77 / .85 / .60 | 68/66/64/58 |
| Weekly | 1/4/8/13 | 3,088 / 5,730 / 9,123 / 12,766 L | 1.10 / .87 / .86 / .88 | 333/330/326/323 |
| Daily | 1/7/14 | 457 / 585 / 707 L | 1.18 / 1.07 / 1.02 | 348/348/347 |

Against the earlier reference milk MAEs on the same scheduled development design,
monthly decreases are about 1.8/7.2/8.4/6.4% (derived from rounded printed MAEs; same n).
The monthly 3–6-month claim is supported versus persistence, but daily and one-week
milk do not beat persistence on each model's own scored periods. On periods shared by
all benchmarks, raw ratios are monthly .77/.96/.98/.59 (n35/33/33/31), weekly
1.07/.83/.79/.80 (n299/297/294/283), daily 1.12/1.01/.95 (n314/312/311); ETS is stronger
at the shortest daily horizon. Do not present own-period ratios as common-period scores.
The scorecard's recovery target is still missed: weekly h4 accuracy .674 versus .900,
n19 verified periods in the 0–2-month recovery bucket, without reset.

Development scheduled origins: 84 monthly, 365 weekly; notes curve 84/365, k168/730,
k_window2/11, source_switch7/34 (monthly/weekly). Notes overlap and are not scored n.

**Matched empirical → ACI quality-on audit, development, raw models:**

| Series, grain, h | Scored n | 80% coverage before → ACI | 90% coverage before → ACI | width90 before → ACI (ratio) |
|---|---|---|---|---|
| Milk daily 1 | 348 | .740 → .784 | .831 → .889 | .119 → .195 (1.64×) |
| Milk daily 7 | 348 | .724 → .778 | .835 → .886 | .144 → .237 (1.65×) |
| Milk daily 14 | 347 | .767 → .780 | .834 → .875 | .180 → .304 (1.69×) |
| Milk weekly 1 | 333 | .739 → .777 | .823 → .883 | .121 → .169 (1.40×) |
| Milk weekly 4 | 330 | .739 → .771 | .839 → .886 | .230 → .297 (1.29×) |
| Milk weekly 13 | 323 | .712 → .705 | .830 → .786 | .439 → .437 (1.00×) |
| Milk monthly 1 | 68 | .786 → .732 | .875 → .857 | .141 → .159 (1.13×) |
| Milk monthly 3 | 66 | .577 → .692 | .788 → .808 | .343 → .367 (1.07×) |
| Milk monthly 6 | 64 | .660 → .596 | .851 → .723 | .442 → .406 (.92×) |
| Milk monthly 12 | 58 | .371 → .371 | .486 → .514 | .439 → .524 (1.19×) |

Daily and weekly h1/h4 meet both calibration bands; weekly h13 does not. Monthly ACI
is not calibrated and is worse at h6, supporting retention of monthly quantiles.
The printed primary target/calibration tally rises from 5/42 (empirical) to 14/42 (ACI).
Neither number means every target or horizon has met its accuracy and uncertainty goals.
`n` above counts scored forecasts; the submitted console did not separately print the
coverage denominator. The next audit now prints `n_coverage` from the existing scorecard.

Herd/event ACI still fails many horizons: calvings h6/h12 coverage90=.796/.952
(scored n71/65), milking h3/h6/h12=.817/.796/.762 (n73/71/65), total herd h6/h12=.815/.786
(n71/65). For abortions h1/3/6/12, width90=2.505/3.035/3.594/3.045 and coverage80=
.778/.729/.717/.714 (n75/73/71/65); only h1 is calibrated. Width is mean interval width
divided by its forecast, not a percentage of the whole herd. This does not resolve the
earlier enormous adaptive/reset chart ranges, whose own models are absent from these
primary raw scorecards. Their width/calibration remains unconfirmed.

**Correction to the interval control supplied by the agent:** `--quality off` also
removes quality-based scoring exclusions. Thus monthly n changes from 75/73/71/65 to
84/82/79/73; the apparent differences mix sample changes with scaling changes. Its
14/42 tally cannot be used to identify the effect of scaling alone. The synthetic
inflation mechanism remains established, but the real-data control was confounded.

The audit now provides `--interval-quality off` separately from the existing `--quality`
option. Keep `--quality on` (the default) to retain exactly the scoring bands; only
interval scaling is switched off. Its separate output ends `_interval_quality_off.csv`.
The decision runner is corrected for future use. Defaults, interval formula, frozen
hashes, forecasts and selection rules are unchanged. **Do not rerun the decision runner
or backtests for this correction.** Only these scorecard commands are needed:

```bash
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --preset pfoi-1.1 --exit-model lactation --k anchor_first --block development --intervals aci
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --preset pfoi-1.1 --exit-model lactation --k anchor_first --block development --intervals aci --interval-quality off
```

These rebuild aggregate scorecards from saved errors (plus user-loaded herd-level
record-quality aggregates); they do not rerun forecasts or publish an outlook.

**Exit-only, post-test development (without reset):** monthly raw milking MAE h3/6/12 is
42.52/62.00/82.14 against persistence 42.85/81.10/131.44 (n29/26/20). Total herd remains
worse: 100.12/206.09/443.79 against 85.93/159.87/204.55 (same n; ratios 1.17/1.29/2.17).
This is a modest development improvement with unresolved management/regime-change error,
not a general solution to herd contractions and recovery.

Milk posthoc, raw ratios to persistence: daily .97/1.03/1.10 (h1/7/14, n61/57/56);
weekly .97/1.40/1.34/1.82 (h1/4/8/13, n38/35/30/28). Monthly .79/2.38/.70 at h1/3/6
has n5/3/3 and is not interpretable. The weekly all-model common samples at h1/h13
have n3 each and are also not interpretable. Posthoc scheduled origins 32/138, curves
26/116, k 52/232, k_window 8/37, no_window_k 9/43, milk withheld 6/22 (monthly/weekly).
These runs have no missing development-error warning. Extra buildable origins are
record coverage, not proof of short-horizon skill.

**Exit-only reset, post-test development:** six breaks (2015,2016,2022,2023,2024,2025).

| Series, grain, h | n / after-break n | All dates before → reset | After break before → reset |
|---|---|---|---|
| Milk weekly 4 | 35 / 16 | .587 → .773 | .308 → .685 |
| Milk monthly 3 | 3 / 2 | .611 → .650 | .622 → .654 |
| Milking monthly 3 | 29 / 12 | .918 → .883 | .939 → .924 |
| Milking monthly 6 | 26 / 11 | .836 → .809 | .848 → .900 |
| Total herd monthly 6 | 26 / 11 | .867 → .879 | .909 → .934 |
| Total herd monthly 12 | 20 / 6 | .748 → .738 | .707 → .694 |
| Calvings monthly 3 | 29 / 12 | .686 → .663 | .667 → .630 |

Reset helps weekly milk strongly (+18.6 overall and +37.7 after-break percentage points),
but lowers overall milking accuracy 3.5/2.7 points and calvings 2.3 points. Preserve the
fixed development verdict and these limitations together; do not call the selected
configuration uniformly better. No updated outlook comparison or publication for this
exit-only/reset configuration is supplied yet; the existing published combined build is
a different experiment and must not be used as its evidence.

Review validation: decision, interval, scorecard and PP1-improvement synthetic suites
passed **42 tests, 1 deselected, in 4.65s** using the preceding documented test command.
The new regression test retains identical scoring n, accuracy, bias and skill when only
interval quality scaling changes, while keeping milk-quality scoring exclusions active.
The scorecard now prints its existing `n_coverage` field. Every line of supplied aggregate
output is retained (trailing whitespace removed); Markdown and `git diff --check` pass.
Changes in this review: scorecard control/console metadata, the runner's diagnostic flag,
synthetic regression test and this plan. No model or interval formula changed, and no
real-data run, publication, database access or commit was performed by the agent.

### FINAL RUN BATCH (user runs from the repository root; aggregates only)

Run in order; steps 1–2 are long, start them first. Send back the printed tables named
under each step. Development first; post-hoc (2024–26) numbers are post-test development.

**1. Milk backtests with the new milk level (M1, M3).**

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --anchor-gate on --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --anchor-gate on --block posthoc --jobs 0
```
Send: "MAE by horizon" and "Notes" (withheld / skipped counts) of each run.

**2. Simulated outages (M2, feeds M4).**

```bash
python -m components.predictive_farm_intelligence.pfoi.outage_sim --preset pfoi-1.1 --anchor-gate on --every 2 --jobs 0
```
Send: the three printed tables.

**3. THI coverage (M5).** The SQL in §5 above, plus the ETL questions (THI formula,
`hours_thi_above` threshold, UTC or local days).

**4. Correction layer, then the driver ablation (M5, M6) and the evidence ladder (F7).**

```bash
python -m components.predictive_farm_intelligence.pfoi.cli adapt --family milk
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3 --base milk_baseline_adaptive --groups season quality recent
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3 --base milk_baseline_adaptive --groups season quality recent weather
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3 --base milk_baseline_adaptive --groups season quality recent weather --thi-knot 90
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3 --base milk_baseline_adaptive --groups season quality recent weather --oracle
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3 --base milk_baseline_adaptive
python -m components.predictive_farm_intelligence.pfoi.cli evidence-ladder --grain weekly --rung "current=herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3:milk_baseline_adaptive" --rung "+ recent milk=herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3_dr_w6p75_gQCR:milk_baseline_adaptive_drivers" --rung "+ heat=herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3_dr_w6p75_gWQCR:milk_baseline_adaptive_drivers" --rung "+ heat (P90)=herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3_dr_w6p90_gWQCR:milk_baseline_adaptive_drivers" --rung "+ sensors & health=herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3_dr_w6p75:milk_baseline_adaptive_drivers" --rung "oracle heat=herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3_dr_w6p75_gWQCR_oracle:milk_baseline_adaptive_drivers_oracle"
```
Repeat the last command with `--grain daily`. Send: each `drivers` "feature registry" and
"development accuracy" table, and both ladders. (`adapt` writes the `_adhq0.1t365z3` files
the other commands read.)

**5. Intervals (M4).**

```bash
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block development --preset pfoi-1.1 --k anchor_first --intervals aci
```
Send: the targets table (coverage80, coverage90, width90, calibrated columns).

**6. Reproductive timing (M7).**

```bash
python -m components.predictive_farm_intelligence.pfoi.cli repro-timing --preset pfoi-1.1
python -m components.predictive_farm_intelligence.pfoi.cli repro-timing --preset pfoi-1.1 --conception-shape on --asof 2023-12-31
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --preset pfoi-1.1 --conception-shape on --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli herd-report --preset pfoi-1.1 --conception-shape on
```
Send: the repro tables and "record vs engine" table; the herd "MAE by horizon" and ratio
tables (calvings and milking at 6 and 12 months decide the keep rule).

**7. Generation outcomes (M8).**

```bash
python -m components.predictive_farm_intelligence.pfoi.cli generation-outcomes
```
Send: both printed tables (values and n).

**8. Development outlook for the page (F1–F9), only after 1–7.**

```bash
python -m components.predictive_farm_intelligence.pfoi.cli build-outlook --origin 2025-09-01 2026-08-01 --preset pfoi-1.1 --k anchor_first --intervals aci --staleness logs/pfoi/outage_sim/outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
```
Check the printed numbers, then add `--write` to publish as `pfoi-1.2.0-dev`, start the
backend with `PFOI_OUTLOOK_DB=on` and send a screenshot of the page (herd-level only).

## 6. Schedule (everything before PP1)

| When | Claude (code and synthetic tests) | User |
|---|---|---|
| **Tue 20, evening** | M1 + tests; M2 + tests | commit or finish the pfoi-1.1.1 edits; THI coverage SQL; ask the ETL the THI questions |
| **Wed 21, morning** | M3; M5 + oracle switch + tests | M1 development and post-hoc runs; start M2 in the background (`--every 2`) |
| **Wed 21, afternoon** | M6 SQL aggregates + tests; M7 survival report + tests | `drivers` ablations (operational, oracle); M7 report |
| **Wed 21, evening** | M8 report; M7 finer-band flag | M7 herd backtest with the flag; M6 post-hoc driver run; M8 report |
| **Thu 22, until 14:00** | M4 from the M2 results; one results table across the ladder; docs updated, every post-2024 number labelled post-test development | final runs; send back aggregate tables |
| **Thu 22, from 14:00** | **code freeze**; slides, backup recording, clean `pytest` | rehearse the 2-minute talk |
| **Fri 23** | — | PP1 |

This is tight. Order of priority if a day slips: M1 → M2 → M5 → M4 → M3 → M7 → M6 → M8.
Anything not finished by the Thursday 14:00 freeze is presented as "implemented and
tested, not yet evaluated", never as a result.

**Fallbacks:**
* M2 runtime too long: DelPro-era development origins only (2020-09 – 2023-12).
* THI formula or coverage unclear: present the THI audit and the oracle bound only.
* Sensor features never leave shadow: report the registry counts and the reason (≈ 5
  months of overlap), not a performance number.
* No real-data runs come back: present the code as implemented and tested, with no
  performance claim.

## 7. What PP1 can claim

| Status | Items |
|---|---|
| implemented and tested | herd engine, milk model, Shapley attribution, adaptive and bias correction, ACI, driver layer, M1–M8 as delivered |
| evaluated | development herd and milk results (nested, purged); honest calving accuracy; 2024–26 post-test development with quality bands |
| promising, unconfirmed | outage recovery (M1/M3) on 2024–26; THI value until the ablation is back |
| cannot be validated with this data (built anyway) | sensor features (≈ 5 months of overlap); diagnosis-based health labels (diagnoses stopped after 2023) |

**Defensible contribution:** a structural herd–milk forecaster that separates reproduction
(herd records) from production level (trusted recent milk), measures how accuracy decays
as records go stale (simulated outages scored on real actual values), and withholds the
milk forecast when the evidence is insufficient, while every number stays explained by
construction. Closest prior work: St-Pierre et al. 2001 (Markov herd forecasting),
Murphy et al. 2014 and Zhang et al. 2016 (herd milk model comparisons). Novelty is
stated as "to our knowledge"; a single search is not a full review.

**Do not claim:** a target accuracy; disease detection; THI as a drought measure; causal or
genetic effects of generation; feed efficiency; "held-out validation" for anything changed
after pfoi-1.0.0.

## 8. Risks and open questions

* THI thresholds in tropical crossbred studies range from about 66 to 79 (Michael et al.
  2023; Niyonzima et al. 2022; Mbuthia et al. 2021; Ekine-Dzivenu et al. 2020), hence
  herd-relative knots. Heat effects lag 1–2 days (West 2003, via secondary sources). The
  best THI formula depends on climate (Bohmanova et al. 2007). THI is collinear with
  monsoon season and management changes; a small or null effect is a plausible honest
  result.
* `is_scoreable` and implausibility flags may use hindsight (L6): ask the ETL.
* Calvings missing since the outage push the starting milking herd down (ETL issue).
* M1 and M4 touch `outlook.py`, which has uncommitted pfoi-1.1.1 edits: commit those first.
* Backtest runtime (hours) is the main schedule risk.

## 9. First step

**M1:** anchor first, 12-month k as fallback, explicit withholding. It is the one
confirmed code defect behind the outage-recovery failure, about 40 lines behind a new
flag (1.0.0 and 1.1.0 hashes unchanged), testable synthetically today and evaluated with
one user-run command.

## Sources

* ECMWF, ERA5 latency and ERA5T revisions: https://www.ecmwf.int/node/37468,
  https://www.ecmwf.int/node/37470
* Bohmanova, Misztal & Cole 2007, J. Dairy Sci. 90:1947–1956:
  https://www.aipl.arsusda.gov/publish/jds/2007/90_1947.pdf
* West 2003, J. Dairy Sci. 86:2131–2144 (lag finding via secondary sources, full text not read)
* St-Pierre et al. 2001, J. Dairy Sci.; Murphy et al. 2014, J. Dairy Sci.; Zhang et al. 2016,
  Comput. Electron. Agric.
* Michael et al. 2023, Theor. Appl. Climatol.; Niyonzima et al. 2022, Trop. Anim. Health
  Prod.; Mbuthia et al. 2021, Animal; Ekine-Dzivenu et al. 2020, Livestock Science

## Appendix: exact supplied aggregate tables, latest batch (2026-10-20)

These are metric tables supplied by the user, not row-level data or agent-run real-data
results. Development means origins 2017–2023; post-test development means the inspected
2024–26 block. NaN is missing, never zero. Counts in note tables overlap.


<details>
<summary>Fast half-life 3, development — notes and all printed MAEs (n_origins shown)</summary>

```text
Fallback notes (monthly, number of origins affected):
                                                                note  n_origins
                                                      conception cut         84
                                                           dry clock         83
                                                             entries         69
                                                    exit calibration         84
fast half-life 3 months for abortions, losses, exits and conceptions         84
                                                       milking clock         59
                                              recency-weighted rates         84

Fallback notes (weekly, number of origins affected):
                                                                note  n_origins
                                                      conception cut        365
                                                           dry clock        361
                                                             entries        256
                                                    exit calibration        365
fast half-life 3 months for abortions, losses, exits and conceptions        365
                                                       milking clock        256
                                              recency-weighted rates        365

MAE by horizon (development block, herd level):
model                              ets  herd_engine  herd_engine_corrected  persistence  sarima  n_origins
grain   series         horizon
monthly calvings       1         54.77        17.02                  11.43        27.14   29.07         84
                       3         72.31         8.00                   7.84        46.30   37.85         82
                       6         76.06        16.81                  17.18        50.01   36.03         79
                       12        43.33        26.22                  27.86        39.07   34.91         73
        milking        1         67.53        27.58                  29.41        32.80   48.91         84
                       3        143.44        66.35                  74.38        93.74  100.84         82
                       6        224.83       102.25                  88.68       133.68  139.54         79
                       12       279.79        99.09                  99.04       194.74  175.92         73
        n_herd         1         77.00        21.81                  24.22        20.36   45.19         84
                       3        119.80        74.60                  89.69        65.33   83.69         82
                       6        152.30       133.94                 148.53       110.95  123.86         79
                       12       215.45       169.75                 174.32       210.49  174.41         73
        real_abortions 1           NaN         3.17                   3.28         3.21     NaN         84
                       3           NaN         3.64                   3.95         3.71     NaN         82
                       6           NaN         4.07                   4.79         4.92     NaN         79
                       12          NaN         4.42                   6.08         4.85     NaN         73
weekly  calvings       1           NaN         6.56                   4.65         6.37     NaN        365
                       4           NaN         4.90                   4.37         8.77     NaN        362
                       8           NaN         4.40                   4.25        10.63     NaN        358
                       13          NaN         4.24                   4.29        12.49     NaN        353
        milking        1           NaN        14.91                  16.25        15.76     NaN        365
                       4           NaN        40.52                  41.50        46.83     NaN        362
                       8           NaN        58.15                  60.14        71.43     NaN        358
                       13          NaN        73.96                  79.23        95.36     NaN        353
        n_herd         1           NaN         9.18                   9.06         8.04     NaN        365
                       4           NaN        36.90                  39.05        31.77     NaN        362
                       8           NaN        62.88                  72.75        53.38     NaN        358
                       13          NaN        86.05                 109.65        73.69     NaN        353
        real_abortions 1           NaN         1.07                   1.08         1.17     NaN        365
                       4           NaN         1.09                   1.10         1.30     NaN        362
                       8           NaN         1.11                   1.14         1.25     NaN        358
                       13          NaN         1.15                   1.22         1.34     NaN        353
```

</details>


<details>
<summary>Lactation exits, development — notes and all printed MAEs (n_origins shown)</summary>

```text
Fallback notes (monthly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut         84
                                                             dry clock         83
                                                               entries         69
                                                      exit calibration         84
                                                         milking clock         59
milking-cow exits by parity x DIM band x pregnancy (lactation records)         84
                                                recency-weighted rates         84

Fallback notes (weekly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut        365
                                                             dry clock        361
                                                               entries        256
                                                      exit calibration        365
                                                         milking clock        256
milking-cow exits by parity x DIM band x pregnancy (lactation records)        365
                                                recency-weighted rates        365

MAE by horizon (development block, herd level):
model                              ets  herd_engine  herd_engine_corrected  persistence  sarima  n_origins
grain   series         horizon
monthly calvings       1         54.77        17.10                  11.48        27.14   29.07         84
                       3         72.31         8.09                   7.87        46.30   37.85         82
                       6         76.06        17.05                  17.35        50.01   36.03         79
                       12        43.33        26.03                  26.71        39.07   34.91         73
        milking        1         67.53        27.80                  29.57        32.80   48.91         84
                       3        143.44        66.81                  76.55        93.74  100.84         82
                       6        224.83        99.60                  90.55       133.68  139.54         79
                       12       279.79        94.76                  93.97       194.74  175.92         73
        n_herd         1         77.00        22.06                  24.37        20.36   45.19         84
                       3        119.80        73.17                  87.61        65.33   83.69         82
                       6        152.30       120.96                 135.31       110.95  123.86         79
                       12       215.45       146.61                 146.42       210.49  174.41         73
        real_abortions 1           NaN         3.57                   3.88         3.21     NaN         84
                       3           NaN         3.88                   4.54         3.71     NaN         82
                       6           NaN         4.13                   5.23         4.92     NaN         79
                       12          NaN         4.61                   6.39         4.85     NaN         73
weekly  calvings       1           NaN         6.57                   4.65         6.37     NaN        365
                       4           NaN         4.92                   4.38         8.77     NaN        362
                       8           NaN         4.43                   4.26        10.63     NaN        358
                       13          NaN         4.26                   4.30        12.49     NaN        353
        milking        1           NaN        14.97                  16.29        15.76     NaN        365
                       4           NaN        40.62                  41.86        46.83     NaN        362
                       8           NaN        58.15                  61.14        71.43     NaN        358
                       13          NaN        73.72                  80.90        95.36     NaN        353
        n_herd         1           NaN         9.14                   9.14         8.04     NaN        365
                       4           NaN        36.41                  38.39        31.77     NaN        362
                       8           NaN        60.98                  70.09        53.38     NaN        358
                       13          NaN        81.92                 101.96        73.69     NaN        353
        real_abortions 1           NaN         1.11                   1.12         1.17     NaN        365
                       4           NaN         1.13                   1.15         1.30     NaN        362
                       8           NaN         1.14                   1.18         1.25     NaN        358
                       13          NaN         1.18                   1.28         1.34     NaN        353
```

</details>


<details>
<summary>Both options, development — notes and all printed MAEs (n_origins shown)</summary>

```text
Fallback notes (monthly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut         84
                                                             dry clock         83
                                                               entries         69
                                                      exit calibration         84
  fast half-life 3 months for abortions, losses, exits and conceptions         84
                                                         milking clock         59
milking-cow exits by parity x DIM band x pregnancy (lactation records)         84
                                                recency-weighted rates         84

Fallback notes (weekly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut        365
                                                             dry clock        361
                                                               entries        256
                                                      exit calibration        365
  fast half-life 3 months for abortions, losses, exits and conceptions        365
                                                         milking clock        256
milking-cow exits by parity x DIM band x pregnancy (lactation records)        365
                                                recency-weighted rates        365

MAE by horizon (development block, herd level):
model                              ets  herd_engine  herd_engine_corrected  persistence  sarima  n_origins
grain   series         horizon
monthly calvings       1         54.77        17.03                  11.42        27.14   29.07         84
                       3         72.31         8.03                   7.84        46.30   37.85         82
                       6         76.06        16.74                  17.18        50.01   36.03         79
                       12        43.33        26.45                  28.04        39.07   34.91         73
        milking        1         67.53        27.59                  29.52        32.80   48.91         84
                       3        143.44        65.04                  75.48        93.74  100.84         82
                       6        224.83        93.86                  89.81       133.68  139.54         79
                       12       279.79       101.37                  96.64       194.74  175.92         73
        n_herd         1         77.00        20.99                  24.31        20.36   45.19         84
                       3        119.80        72.89                  90.26        65.33   83.69         82
                       6        152.30       130.35                 151.13       110.95  123.86         79
                       12       215.45       168.61                 179.31       210.49  174.41         73
        real_abortions 1           NaN         3.17                   3.28         3.21     NaN         84
                       3           NaN         3.65                   3.95         3.71     NaN         82
                       6           NaN         4.08                   4.79         4.92     NaN         79
                       12          NaN         4.43                   6.08         4.85     NaN         73
weekly  calvings       1           NaN         6.56                   4.65         6.37     NaN        365
                       4           NaN         4.90                   4.37         8.77     NaN        362
                       8           NaN         4.41                   4.25        10.63     NaN        358
                       13          NaN         4.25                   4.29        12.49     NaN        353
        milking        1           NaN        15.01                  16.28        15.76     NaN        365
                       4           NaN        40.25                  41.58        46.83     NaN        362
                       8           NaN        56.96                  60.61        71.43     NaN        358
                       13          NaN        71.57                  80.21        95.36     NaN        353
        n_herd         1           NaN         9.01                   9.06         8.04     NaN        365
                       4           NaN        35.79                  39.04        31.77     NaN        362
                       8           NaN        61.00                  72.83        53.38     NaN        358
                       13          NaN        84.07                 109.95        73.69     NaN        353
        real_abortions 1           NaN         1.07                   1.08         1.17     NaN        365
                       4           NaN         1.09                   1.10         1.30     NaN        362
                       8           NaN         1.11                   1.14         1.25     NaN        358
                       13          NaN         1.15                   1.22         1.34     NaN        353
```

</details>


<details>
<summary>Both options, post-test development — notes and all printed MAEs (n_origins shown)</summary>

```text
Fallback notes (monthly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut         32
                                                             dry clock         32
                                                      exit calibration         32
  fast half-life 3 months for abortions, losses, exits and conceptions         32
                                                         milking clock         32
milking-cow exits by parity x DIM band x pregnancy (lactation records)         32
                                                recency-weighted rates         32
POST-HOC: 2024-26 scores of a non-frozen version; report them as post-hoc.

Fallback notes (weekly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut        138
                                                             dry clock        138
                                                      exit calibration        138
  fast half-life 3 months for abortions, losses, exits and conceptions        138
                                                         milking clock        138
milking-cow exits by parity x DIM band x pregnancy (lactation records)        138
                                                recency-weighted rates        138

MAE by horizon (posthoc block, herd level):
model                              ets  herd_engine  herd_engine_corrected  persistence  sarima  n_origins
grain   series         horizon
monthly calvings       1         24.42        20.76                   8.54        13.12   16.48         31
                       3         25.02        10.09                  11.42        15.98   26.04         29
                       6         29.10        14.02                  17.09        21.72   31.22         26
                       12        28.14        21.04                  22.12        23.81   22.48         20
        milking        1         28.09        13.02                   9.90        13.18   29.54         31
                       3         52.79        43.94                  32.90        42.85   81.56         29
                       6         82.32        63.46                  58.95        81.10  152.10         26
                       12       173.50        80.19                 123.31       131.44  222.86         20
        n_herd         1         45.69        17.01                  19.44        19.20   58.32         31
                       3        118.93        93.91                 105.85        85.93  171.99         29
                       6        224.08       207.72                 220.94       159.87  327.02         26
                       12       356.33       434.44                 409.45       204.55  564.31         20
        real_abortions 1           NaN         9.19                   9.53         7.59     NaN         31
                       3           NaN         9.49                   9.35        10.74     NaN         29
                       6           NaN         8.90                   7.83         7.93     NaN         26
                       12          NaN         8.86                   7.20         9.25     NaN         20
weekly  calvings       1           NaN         8.88                   4.00         3.15     NaN        137
                       4           NaN         3.60                   2.51         4.03     NaN        134
                       8           NaN         3.18                   2.94         4.75     NaN        130
                       13          NaN         3.05                   3.40         4.90     NaN        125
        milking        1           NaN         6.91                   5.85         6.19     NaN        137
                       4           NaN        21.97                  16.90        21.51     NaN        134
                       8           NaN        36.06                  26.96        35.62     NaN        130
                       13          NaN        47.90                  35.46        49.37     NaN        125
        n_herd         1           NaN         6.23                   6.53         6.17     NaN        137
                       4           NaN        30.46                  35.24        30.40     NaN        134
                       8           NaN        67.58                  77.49        60.74     NaN        130
                       13          NaN       116.87                 132.15        96.77     NaN        125
        real_abortions 1           NaN         2.54                   2.72         2.98     NaN        137
                       4           NaN         2.59                   2.70         2.90     NaN        134
                       8           NaN         2.60                   2.66         3.18     NaN        130
                       13          NaN         2.55                   2.46         3.45     NaN        125
```

</details>


<details>
<summary>Both options — development herd-report, ratios and biases</summary>

```text
monthly: ratio < 1 means the model beats persistence; bias > 0 means it forecasts too high

ratio
horizon             1     3     6     12
series
ais               2.29  1.38  1.08  1.18
births            0.63  0.17  0.34  0.68
calves            1.01  0.97  1.08  0.66
calvings          0.63  0.17  0.33  0.68
calvings_heifer   0.32  0.19  0.75  0.82
culls             0.77  0.80  0.76  0.81
deaths            0.99  0.73  0.69  0.88
dry_offs          0.65  0.66  0.65  0.62
dry_open          6.83  2.79  1.85  1.39
dry_pregnant      2.49  1.35  1.13  0.48
external_entries  0.69  0.64  0.67  0.70
heifers_open      4.04  1.52  1.11  0.77
heifers_pregnant  4.27  1.33  0.99  0.62
milking           0.84  0.69  0.70  0.52
n_herd            1.03  1.12  1.17  0.80
real_abortions    0.99  0.98  0.83  0.91
sales             0.84  0.79  0.67  0.82

ratio_corrected
horizon             1     3     6     12
series
ais               1.75  1.00  0.79  0.94
births            0.41  0.17  0.34  0.71
calves            1.01  1.03  1.15  0.72
calvings          0.42  0.17  0.34  0.72
calvings_heifer   0.32  0.19  0.54  0.75
culls             0.79  0.83  0.82  0.94
deaths            1.02  0.79  0.74  1.10
dry_offs          0.68  0.68  0.64  0.63
dry_open          3.13  1.35  1.07  1.26
dry_pregnant      1.32  0.93  0.69  0.68
external_entries  0.82  0.76  0.80  0.87
heifers_open      2.65  1.57  1.34  0.88
heifers_pregnant  2.71  1.25  1.05  0.61
milking           0.90  0.81  0.67  0.50
n_herd            1.19  1.38  1.36  0.85
real_abortions    1.02  1.07  0.97  1.25
sales             0.95  0.90  0.75  1.00

bias_engine
horizon               1       3       6       12
series
ais               151.16  167.73  183.60  160.12
births             17.15    2.90    4.63    8.39
calves             13.49   25.71   22.85  -26.11
calvings           16.90    2.91    4.55    8.25
calvings_heifer     0.57    0.75   16.11    3.85
culls              -0.98   -1.16   -2.59   -5.16
deaths              0.85    1.80   -0.12   -4.32
dry_offs           -5.14  -13.65  -17.34   -7.79
dry_open           59.20   67.78   71.89   70.24
dry_pregnant      -65.85  -93.35 -102.72   -3.66
external_entries   -0.98   -0.98   -0.94   -0.84
heifers_open       51.65   50.47   45.25   -3.79
heifers_pregnant  -51.03  -45.54  -48.21   41.89
milking             6.49   25.62   51.54  -43.77
n_herd             13.98   31.44   42.26   36.53
real_abortions     -0.53   -0.59   -0.56    0.13
sales              -3.75    1.04    2.30    4.42

bias_corrected
horizon             1     3      6      12
series
ais              -3.78  4.67  19.13  53.08
births           -1.12 -0.17  -3.50  -0.93
calves           -0.92 -0.05   1.26  -4.92
calvings         -1.02 -0.10  -3.33  -0.85
calvings_heifer   0.09  0.29   0.50   4.21
culls             0.07  0.44   0.52  -0.75
deaths            0.99  1.58   1.61   0.74
dry_offs          2.99 -0.39  -3.58  -2.95
dry_open          4.27  9.11  17.32  30.82
dry_pregnant     -2.45 -4.91 -18.22 -12.90
external_entries -0.13 -0.13  -0.15  -0.11
heifers_open      0.56 -4.16 -14.33 -26.64
heifers_pregnant -1.28 -0.48   5.83  35.53
milking          -2.42 -8.25  -8.71 -13.45
n_herd           -2.23 -8.87 -17.14   7.90
real_abortions   -0.55 -0.64  -0.63  -0.31
sales             0.99  0.78  -1.52  -2.15

weekly: ratio < 1 means the model beats persistence; bias > 0 means it forecasts too high

ratio
horizon              1     4     8     13
series
ais                1.81  1.66  1.41  1.22
births             1.03  0.56  0.41  0.34
calves             1.12  1.10  1.04  1.00
calvings           1.03  0.56  0.41  0.34
culls              0.87  0.86  0.75  0.77
deaths             0.86  0.83  0.74  0.74
dry_offs           0.69  0.79  0.81  0.77
dry_open          14.71  4.90  3.37  2.60
dry_pregnant       4.32  1.88  1.54  1.38
external_entries   0.72  0.70  0.72  0.68
heifers_open      12.83  2.89  1.85  1.45
heifers_pregnant  15.07  2.84  1.66  1.25
milking            0.95  0.86  0.80  0.75
n_herd             1.12  1.13  1.14  1.14
real_abortions     0.91  0.84  0.89  0.86
sales              0.88  0.91  0.80  0.83

ratio_corrected
horizon             1     4     8     13
series
ais               1.23  1.19  1.09  1.02
births            0.72  0.49  0.40  0.34
calves            1.06  1.05  1.08  1.13
calvings          0.73  0.50  0.40  0.34
culls             0.88  0.88  0.77  0.80
deaths            0.88  0.85  0.76  0.77
dry_offs          0.70  0.82  0.85  0.80
dry_open          5.64  1.97  1.40  1.23
dry_pregnant      1.86  1.10  0.96  0.91
external_entries  0.91  0.89  0.93  0.88
heifers_open      6.74  2.17  1.73  1.59
heifers_pregnant  7.80  2.04  1.51  1.30
milking           1.03  0.89  0.85  0.84
n_herd            1.13  1.23  1.36  1.49
real_abortions    0.92  0.85  0.91  0.91
sales             0.98  0.99  0.88  0.96

bias_engine
horizon              1      4      8      13
series
ais               33.13  34.96  36.73  38.22
births             5.92   2.89   1.55   0.40
calves             5.81  19.33  26.02  26.44
calvings           5.84   2.85   1.54   0.40
culls             -0.30  -0.27  -0.27  -0.37
deaths            -0.08   0.32   0.48   0.32
dry_offs           0.29  -2.12  -2.79  -3.18
dry_open          56.74  60.78  64.95  68.55
dry_pregnant     -59.19 -71.08 -84.91 -95.94
external_entries  -0.23  -0.24  -0.24  -0.24
heifers_open      52.69  51.76  51.20  50.40
heifers_pregnant -52.53 -50.34 -47.62 -44.43
milking            2.84  10.93  20.75  29.39
n_herd             6.40  21.60  30.98  35.37
real_abortions    -0.12  -0.13  -0.14  -0.14
sales             -1.71  -0.38   0.21   0.17

bias_corrected
horizon             1     4      8      13
series
ais              -5.19 -5.17  -4.96  -4.31
births           -0.83 -0.52  -0.21   0.03
calves           -0.66 -2.98  -3.94  -4.89
calvings         -0.81 -0.50  -0.21   0.02
culls             0.00  0.03   0.08   0.13
deaths            0.17  0.24   0.34   0.45
dry_offs          0.86  0.63   0.43   0.03
dry_open          1.55  2.30   4.02   7.11
dry_pregnant     -0.73  2.24   3.18   0.10
external_entries -0.04 -0.03  -0.03  -0.02
heifers_open      1.16  0.96  -1.19  -5.54
heifers_pregnant -1.28 -2.55  -3.61  -3.69
milking          -0.94 -5.41  -9.54 -11.73
n_herd           -0.91 -5.54 -11.45 -19.22
real_abortions   -0.15 -0.17  -0.18  -0.22
sales             0.45  0.59   0.64   1.08
```

</details>


<details>
<summary>Fast half-life 3 — development herd-report, ratios and biases</summary>

```text
monthly: ratio < 1 means the model beats persistence; bias > 0 means it forecasts too high

ratio
horizon             1     3     6     12
series
ais               2.31  1.43  1.13  1.21
births            0.63  0.17  0.34  0.68
calves            1.01  0.97  1.07  0.68
calvings          0.63  0.17  0.34  0.67
calvings_heifer   0.32  0.19  0.75  0.82
culls             0.76  0.79  0.75  0.81
deaths            0.99  0.73  0.70  0.88
dry_offs          0.65  0.66  0.65  0.62
dry_open          6.83  2.79  1.85  1.40
dry_pregnant      2.49  1.37  1.16  0.48
external_entries  0.69  0.64  0.67  0.70
heifers_open      4.04  1.52  1.11  0.77
heifers_pregnant  4.27  1.33  0.99  0.62
milking           0.84  0.71  0.76  0.51
n_herd            1.07  1.14  1.21  0.81
real_abortions    0.99  0.98  0.83  0.91
sales             0.84  0.79  0.67  0.82

ratio_corrected
horizon             1     3     6     12
series
ais               1.75  0.99  0.78  0.92
births            0.41  0.17  0.34  0.71
calves            1.01  1.03  1.15  0.72
calvings          0.42  0.17  0.34  0.71
calvings_heifer   0.32  0.19  0.54  0.75
culls             0.79  0.83  0.80  0.94
deaths            1.03  0.79  0.75  1.12
dry_offs          0.68  0.68  0.64  0.63
dry_open          3.13  1.35  1.07  1.26
dry_pregnant      1.32  0.93  0.68  0.67
external_entries  0.82  0.76  0.80  0.87
heifers_open      2.65  1.57  1.34  0.88
heifers_pregnant  2.71  1.25  1.05  0.61
milking           0.90  0.79  0.66  0.51
n_herd            1.19  1.37  1.34  0.83
real_abortions    1.02  1.06  0.97  1.25
sales             0.95  0.90  0.75  1.00

bias_engine
horizon               1       3       6       12
series
ais               152.62  174.81  196.10  172.77
births             17.14    2.69    3.77    7.11
calves             13.49   25.59   21.80  -30.00
calvings           16.89    2.70    3.69    6.99
calvings_heifer     0.57    0.75   16.11    3.85
culls              -2.57   -2.87   -3.83   -6.37
deaths             -1.02   -0.29   -1.89   -6.60
dry_offs           -5.38  -14.55  -18.38   -7.53
dry_open           59.20   67.78   71.97   70.96
dry_pregnant      -65.94  -94.49 -105.41   -3.35
external_entries   -0.98   -0.98   -0.94   -0.84
heifers_open       51.65   50.47   45.15   -4.74
heifers_pregnant  -51.03  -45.54  -48.22   41.74
milking             8.31   36.11   73.54  -16.19
n_herd             15.72   40.67   60.50   60.11
real_abortions     -0.54   -0.62   -0.59    0.15
sales              -3.77    1.00    2.09    3.91

bias_corrected
horizon             1     3      6      12
series
ais              -3.60  5.69  21.32  55.31
births           -1.12 -0.25  -3.83  -1.53
calves           -0.92 -0.09   0.88  -6.48
calvings         -1.02 -0.17  -3.66  -1.45
calvings_heifer   0.09  0.29   0.50   4.21
culls            -0.24  0.03   0.24  -0.97
deaths            0.73  1.21   1.33   0.34
dry_offs          2.93 -0.64  -3.91  -3.20
dry_open          4.27  9.14  17.44  30.96
dry_pregnant     -2.47 -5.26 -19.10 -13.51
external_entries -0.13 -0.13  -0.15  -0.11
heifers_open      0.56 -4.17 -14.38 -27.08
heifers_pregnant -1.28 -0.48   5.83  35.48
milking          -2.11 -6.07  -3.29  -7.83
n_herd           -1.95 -7.05 -12.91  10.99
real_abortions   -0.55 -0.65  -0.64  -0.31
sales             0.99  0.76  -1.62  -2.37

weekly: ratio < 1 means the model beats persistence; bias > 0 means it forecasts too high

ratio
horizon              1     4     8     13
series
ais                1.81  1.67  1.44  1.26
births             1.03  0.56  0.41  0.34
calves             1.12  1.10  1.04  1.00
calvings           1.03  0.56  0.41  0.34
culls              0.85  0.84  0.73  0.76
deaths             0.86  0.83  0.74  0.74
dry_offs           0.69  0.79  0.80  0.76
dry_open          14.71  4.90  3.37  2.60
dry_pregnant       4.32  1.88  1.55  1.39
external_entries   0.72  0.70  0.72  0.68
heifers_open      12.83  2.89  1.85  1.45
heifers_pregnant  15.07  2.84  1.66  1.25
milking            0.95  0.87  0.81  0.78
n_herd             1.14  1.16  1.18  1.17
real_abortions     0.91  0.84  0.89  0.86
sales              0.88  0.91  0.80  0.83

ratio_corrected
horizon             1     4     8     13
series
ais               1.23  1.19  1.09  1.02
births            0.72  0.49  0.40  0.34
calves            1.06  1.05  1.08  1.13
calvings          0.73  0.50  0.40  0.34
culls             0.88  0.87  0.76  0.79
deaths            0.89  0.86  0.77  0.78
dry_offs          0.70  0.82  0.84  0.80
dry_open          5.64  1.97  1.40  1.23
dry_pregnant      1.86  1.09  0.96  0.91
external_entries  0.91  0.89  0.93  0.88
heifers_open      6.74  2.17  1.73  1.59
heifers_pregnant  7.80  2.04  1.51  1.30
milking           1.03  0.89  0.84  0.83
n_herd            1.13  1.23  1.36  1.49
real_abortions    0.92  0.85  0.91  0.91
sales             0.98  0.99  0.88  0.96

bias_engine
horizon              1      4      8      13
series
ais               33.22  35.51  37.89  40.09
births             5.92   2.89   1.53   0.33
calves             5.81  19.32  25.98  26.25
calvings           5.84   2.85   1.52   0.33
culls             -0.62  -0.64  -0.67  -0.73
deaths            -0.48  -0.14  -0.03  -0.17
dry_offs           0.27  -2.21  -2.96  -3.41
dry_open          56.74  60.78  64.95  68.54
dry_pregnant     -59.20 -71.25 -85.56 -97.40
external_entries  -0.23  -0.24  -0.24  -0.24
heifers_open      52.69  51.76  51.20  50.39
heifers_pregnant -52.53 -50.34 -47.62 -44.43
milking            3.26  13.86  27.64  41.53
n_herd             6.81  24.35  37.18  45.85
real_abortions    -0.12  -0.13  -0.15  -0.14
sales             -1.71  -0.38   0.20   0.15

bias_corrected
horizon             1     4      8      13
series
ais              -5.18 -5.11  -4.82  -4.06
births           -0.83 -0.52  -0.22   0.00
calves           -0.66 -2.98  -3.95  -4.95
calvings         -0.81 -0.51  -0.22  -0.01
culls            -0.06 -0.04  -0.00   0.05
deaths            0.13  0.19   0.27   0.38
dry_offs          0.85  0.61   0.38  -0.04
dry_open          1.55  2.30   4.03   7.14
dry_pregnant     -0.74  2.20   2.98  -0.35
external_entries -0.04 -0.03  -0.03  -0.02
heifers_open      1.16  0.96  -1.19  -5.54
heifers_pregnant -1.28 -2.55  -3.61  -3.69
milking          -0.88 -4.99  -8.40  -9.42
n_herd           -0.85 -5.16 -10.51 -17.40
real_abortions   -0.15 -0.17  -0.18  -0.22
sales             0.45  0.59   0.64   1.08
```

</details>


<details>
<summary>Lactation exits — development herd-report, ratios and biases</summary>

```text
monthly: ratio < 1 means the model beats persistence; bias > 0 means it forecasts too high

ratio
horizon             1     3     6     12
series
ais               2.29  1.38  1.06  1.16
births            0.64  0.17  0.34  0.67
calves            0.98  0.90  0.91  0.62
calvings          0.63  0.17  0.34  0.67
calvings_heifer   0.32  0.19  0.76  0.77
culls             0.76  0.79  0.75  0.81
deaths            1.03  0.79  0.73  0.87
dry_offs          0.65  0.66  0.65  0.62
dry_open          6.81  2.77  1.83  1.41
dry_pregnant      2.47  1.32  1.08  0.46
external_entries  0.69  0.64  0.67  0.70
heifers_open      3.97  1.42  1.02  0.72
heifers_pregnant  4.22  1.27  0.90  0.59
milking           0.85  0.71  0.75  0.49
n_herd            1.08  1.12  1.09  0.70
real_abortions    1.11  1.05  0.84  0.95
sales             0.87  0.80  0.68  0.82

ratio_corrected
horizon             1     3     6     12
series
ais               1.75  1.01  0.77  0.94
births            0.41  0.17  0.34  0.68
calves            1.00  0.95  1.01  0.82
calvings          0.42  0.17  0.35  0.68
calvings_heifer   0.32  0.19  0.54  0.70
culls             0.79  0.83  0.81  0.93
deaths            1.08  0.82  0.81  1.10
dry_offs          0.68  0.68  0.64  0.63
dry_open          3.12  1.34  1.09  1.35
dry_pregnant      1.32  0.93  0.69  0.63
external_entries  0.82  0.76  0.80  0.87
heifers_open      2.60  1.49  1.27  0.86
heifers_pregnant  2.69  1.20  0.96  0.57
milking           0.90  0.82  0.68  0.48
n_herd            1.20  1.34  1.22  0.70
real_abortions    1.21  1.22  1.06  1.32
sales             1.00  0.88  0.74  1.02

bias_engine
horizon               1       3       6       12
series
ais               150.53  164.72  178.85  161.81
births             17.22    3.23    5.45   13.17
calves             12.61   22.28   16.29  -26.11
calvings           16.97    3.24    5.35   12.96
calvings_heifer     0.58    0.79   16.29    5.17
culls              -2.19   -2.44   -3.88   -6.12
deaths             -0.65    0.32   -1.67   -5.07
dry_offs           -5.04  -13.13  -16.01   -5.65
dry_open           59.05   67.17   70.85   69.50
dry_pregnant      -65.39  -90.95  -96.62    8.56
external_entries   -0.98   -0.98   -0.94   -0.84
heifers_open       50.98   47.24   39.03  -12.79
heifers_pregnant  -50.16  -41.13  -38.91   53.09
milking             7.40   30.09   61.12  -22.28
n_herd             14.50   35.30   52.96   70.53
real_abortions     -0.27   -0.28   -0.21    0.60
sales              -2.10    2.49    3.79    6.51

bias_corrected
horizon             1     3      6      12
series
ais              -3.74  4.91  19.80  54.96
births           -1.12 -0.15  -3.34  -0.05
calves           -0.84  0.62   2.97  -3.87
calvings         -1.02 -0.07  -3.17   0.01
calvings_heifer   0.09  0.31   0.54   4.69
culls            -0.09  0.20   0.13  -1.22
deaths            0.87  1.37   1.28   0.58
dry_offs          3.00 -0.36  -3.51  -2.33
dry_open          4.26  9.09  17.33  31.64
dry_pregnant     -2.44 -4.72 -17.49  -9.84
external_entries -0.13 -0.13  -0.15  -0.11
heifers_open      0.31 -5.52 -16.68 -29.16
heifers_pregnant -1.05  1.04   9.81  39.32
milking          -2.41 -7.99  -6.76  -5.67
n_herd           -2.16 -7.56 -11.03  21.82
real_abortions   -0.70 -0.74  -0.65  -0.12
sales             1.12  0.60  -1.68  -1.86

weekly: ratio < 1 means the model beats persistence; bias > 0 means it forecasts too high

ratio
horizon              1     4     8     13
series
ais                1.81  1.65  1.41  1.21
births             1.03  0.56  0.42  0.34
calves             1.10  1.06  0.97  0.90
calvings           1.03  0.56  0.42  0.34
culls              0.85  0.84  0.74  0.76
deaths             0.88  0.84  0.75  0.76
dry_offs           0.69  0.79  0.81  0.77
dry_open          14.70  4.88  3.35  2.57
dry_pregnant       4.31  1.86  1.51  1.34
external_entries   0.72  0.70  0.72  0.68
heifers_open      12.79  2.81  1.75  1.35
heifers_pregnant  15.00  2.78  1.59  1.18
milking            0.95  0.87  0.81  0.77
n_herd             1.14  1.15  1.14  1.11
real_abortions     0.95  0.87  0.92  0.88
sales              0.91  0.92  0.81  0.83

ratio_corrected
horizon             1     4     8     13
series
ais               1.23  1.20  1.11  1.04
births            0.72  0.49  0.40  0.34
calves            1.06  1.02  1.00  1.01
calvings          0.73  0.50  0.40  0.34
culls             0.88  0.87  0.76  0.79
deaths            0.89  0.86  0.78  0.80
dry_offs          0.70  0.82  0.85  0.80
dry_open          5.63  1.96  1.39  1.23
dry_pregnant      1.86  1.09  0.97  0.91
external_entries  0.91  0.89  0.93  0.88
heifers_open      6.71  2.10  1.65  1.49
heifers_pregnant  7.78  2.00  1.45  1.21
milking           1.03  0.89  0.86  0.85
n_herd            1.14  1.21  1.31  1.38
real_abortions    0.96  0.88  0.95  0.95
sales             1.02  1.00  0.87  0.93

bias_engine
horizon              1      4      8      13
series
ais               33.11  34.73  36.25  37.49
births             5.93   2.92   1.60   0.49
calves             5.55  17.87  23.23  22.15
calvings           5.84   2.88   1.59   0.49
culls             -0.55  -0.54  -0.55  -0.64
deaths            -0.40  -0.01   0.14  -0.02
dry_offs           0.30  -2.09  -2.71  -3.05
dry_open          56.71  60.56  64.54  67.92
dry_pregnant     -59.08 -70.35 -83.33 -93.21
external_entries  -0.23  -0.24  -0.24  -0.24
heifers_open      52.52  50.70  48.95  46.70
heifers_pregnant -52.31 -48.93 -44.56 -39.26
milking            3.06  12.29  23.65  34.26
n_herd             6.48  22.31  32.97  39.34
real_abortions    -0.06  -0.07  -0.08  -0.07
sales             -1.26  -0.01   0.56   0.53

bias_corrected
horizon             1     4     8      13
series
ais              -5.20 -5.20 -5.00  -4.34
births           -0.83 -0.52 -0.21   0.04
calves           -0.55 -2.24 -2.18  -1.59
calvings         -0.81 -0.51 -0.21   0.03
culls            -0.03 -0.00  0.04   0.07
deaths            0.11  0.17  0.25   0.34
dry_offs          0.86  0.64  0.44   0.04
dry_open          1.53  2.21  3.82   6.78
dry_pregnant     -0.72  2.35  3.47   0.66
external_entries -0.04 -0.03 -0.03  -0.02
heifers_open      1.08  0.43 -2.29  -7.26
heifers_pregnant -1.20 -2.04 -2.44  -1.54
milking          -0.94 -5.42 -9.49 -11.43
n_herd           -0.81 -4.80 -9.45 -14.89
real_abortions   -0.22 -0.24 -0.24  -0.27
sales             0.37  0.47  0.46   0.84
```

</details>


The fourth herd-report attachment repeats the combined report exactly; it is not a
fourth configuration or additional sample. For the four key series, the preceding
backtests supply n = 84/82/79/73 monthly (h 1/3/6/12) and 365/362/358/353 weekly
(h 1/4/8/13). Other series in herd-report have no n in the pasted report; their sample
sizes remain unreported, and no precision claim is made for them.


<details>
<summary>Scenarios — descriptive, including post-test development exposure; n is usable episodes</summary>

```text
=== episode library (herd-level; start months) ===
abortion_surge       9  2017-01, 2018-04, 2018-10, 2019-02, 2019-07, 2020-07, 2022-06, 2022-09, 2023-09
drought             10  2015-12, 2016-07, 2017-04, 2018-07, 2018-11, 2019-04, 2020-01, 2020-09, 2021-09, 2024-02
herd contraction     2  2022-09, 2024-03
mastitis_surge       6  2017-03, 2018-05, 2019-01, 2020-09, 2021-11, 2023-03

=== response (excess relative error after onset), by series ===
            kind   grain  horizon  n  median    low   high    series
  abortion_surge   daily        1  7  +0.004 -0.051 +0.012 herd_milk
  abortion_surge   daily        7  7  +0.003 -0.060 +0.035 herd_milk
  abortion_surge   daily       14  7  +0.053 -0.063 +0.131 herd_milk
  abortion_surge  weekly        1  7  -0.004 -0.055 +0.031 herd_milk
  abortion_surge  weekly        4  6  -0.024 -0.145 +0.044 herd_milk
  abortion_surge  weekly        8  6  +0.023 -0.102 +0.079 herd_milk
  abortion_surge  weekly       13  6  +0.044 -0.037 +0.368 herd_milk
         drought   daily        1  8  +0.007 -0.024 +0.053 herd_milk
         drought   daily        7  8  +0.001 -0.008 +0.041 herd_milk
         drought   daily       14  8  +0.007 -0.014 +0.044 herd_milk
         drought monthly        1  1  -0.029 -0.029 -0.029 herd_milk
         drought monthly        3  1  -0.020 -0.020 -0.020 herd_milk
         drought  weekly        1  8  +0.011 -0.011 +0.025 herd_milk
         drought  weekly        4  7  +0.012 -0.012 +0.064 herd_milk
         drought  weekly        8  6  +0.006 -0.057 +0.061 herd_milk
         drought  weekly       13  7  +0.003 -0.095 +0.108 herd_milk
herd contraction   daily        1  1  +0.086 +0.086 +0.086 herd_milk
herd contraction   daily        7  1  -0.036 -0.036 -0.036 herd_milk
herd contraction  weekly        1  1  +0.012 +0.012 +0.012 herd_milk
herd contraction  weekly       13  2  +0.305 -0.015 +0.624 herd_milk
  mastitis_surge   daily        1  6  +0.009 -0.003 +0.089 herd_milk
  mastitis_surge   daily        7  6  -0.017 -0.036 +0.052 herd_milk
  mastitis_surge   daily       14  6  +0.003 -0.043 +0.074 herd_milk
  mastitis_surge monthly        1  1  +0.019 +0.019 +0.019 herd_milk
  mastitis_surge  weekly        1  6  -0.002 -0.013 +0.024 herd_milk
  mastitis_surge  weekly        4  5  +0.003 -0.024 +0.048 herd_milk
  mastitis_surge  weekly        8  4  +0.064 +0.052 +0.153 herd_milk
  mastitis_surge  weekly       13  4  +0.074 -0.002 +0.296 herd_milk
  abortion_surge monthly        1  2  +0.023 +0.013 +0.032   milking
  abortion_surge monthly        3  2  -0.036 -0.103 +0.032   milking
  abortion_surge  weekly        1  8  +0.004 -0.016 +0.011   milking
  abortion_surge  weekly        4  8  +0.021 -0.092 +0.049   milking
  abortion_surge  weekly        8  8  -0.031 -0.095 +0.053   milking
  abortion_surge  weekly       13  8  -0.028 -0.123 +0.076   milking
         drought monthly        1  2  -0.008 -0.025 +0.008   milking
         drought monthly        3  2  -0.134 -0.292 +0.024   milking
         drought  weekly        1  8  -0.011 -0.055 +0.006   milking
         drought  weekly        4  8  -0.032 -0.082 +0.003   milking
         drought  weekly        8  7  +0.004 -0.167 +0.060   milking
         drought  weekly       13  7  -0.047 -0.218 +0.056   milking
herd contraction monthly        1  2  -0.020 -0.027 -0.012   milking
herd contraction monthly        3  1  -0.121 -0.121 -0.121   milking
herd contraction  weekly        1  2  -0.020 -0.023 -0.016   milking
herd contraction  weekly        4  2  -0.067 -0.091 -0.042   milking
herd contraction  weekly        8  2  -0.182 -0.206 -0.157   milking
herd contraction  weekly       13  2  -0.199 -0.331 -0.067   milking
  mastitis_surge monthly        1  2  -0.013 -0.055 +0.028   milking
  mastitis_surge monthly        3  2  +0.040 -0.060 +0.140   milking
  mastitis_surge  weekly        1  6  +0.004 -0.013 +0.010   milking
  mastitis_surge  weekly        4  6  -0.013 -0.051 +0.047   milking
  mastitis_surge  weekly        8  5  -0.032 -0.076 +0.064   milking
  mastitis_surge  weekly       13  5  -0.046 -0.058 +0.117   milking
  abortion_surge monthly        1  2  +0.002 -0.002 +0.006    n_herd
  abortion_surge monthly        3  2  -0.006 -0.028 +0.017    n_herd
  abortion_surge  weekly        1  8  -0.000 -0.002 +0.002    n_herd
  abortion_surge  weekly        4  8  +0.004 -0.013 +0.012    n_herd
  abortion_surge  weekly        8  8  +0.010 -0.033 +0.026    n_herd
  abortion_surge  weekly       13  8  -0.007 -0.046 +0.022    n_herd
         drought monthly        1  2  -0.007 -0.020 +0.005    n_herd
         drought monthly        3  2  -0.113 -0.201 -0.024    n_herd
         drought  weekly        1  8  -0.003 -0.008 +0.003    n_herd
         drought  weekly        4  8  -0.008 -0.028 +0.008    n_herd
         drought  weekly        8  7  -0.021 -0.055 +0.023    n_herd
         drought  weekly       13  7  -0.013 -0.123 +0.030    n_herd
herd contraction monthly        1  2  -0.014 -0.019 -0.008    n_herd
herd contraction monthly        3  1  -0.055 -0.055 -0.055    n_herd
herd contraction  weekly        1  2  -0.004 -0.006 -0.002    n_herd
herd contraction  weekly        4  2  -0.027 -0.033 -0.021    n_herd
herd contraction  weekly        8  2  -0.095 -0.140 -0.050    n_herd
herd contraction  weekly       13  2  -0.145 -0.219 -0.071    n_herd
  mastitis_surge monthly        1  2  +0.013 +0.010 +0.015    n_herd
  mastitis_surge monthly        3  2  +0.041 +0.016 +0.067    n_herd
  mastitis_surge  weekly        1  6  +0.002 -0.002 +0.004    n_herd
  mastitis_surge  weekly        4  6  +0.007 -0.003 +0.022    n_herd
  mastitis_surge  weekly        8  5  +0.025 -0.027 +0.039    n_herd
  mastitis_surge  weekly       13  5  +0.022 -0.046 +0.066    n_herd
```

</details>


<details>
<summary>Saved 1.1.0 versus development comparison — provenance unresolved; n_months shown</summary>

```text
Recorded months after each forecast date that both versions forecast (pfoi-1.1.0 vs pfoi-1.2.0-dev; n_months = number of periods); MAE and bias: forecast - recorded; change_pct < 0 = candidate better;
cover90 blank = that run has no 5-95 % range (no past errors); layer_candidate = mean correction-layer amount in the candidate's forecast
                     n_months  mae_frozen  bias_frozen  cover90_frozen  mae_candidate  bias_candidate  cover90_candidate  layer_candidate  change_pct
origin  series
2017-01 milk_litres        12   286131.78    284116.56             NaN      298657.61       296640.91                NaN             0.00        4.38
        milking            12      103.50        93.20             NaN         113.30          102.91                NaN             0.00        9.47
        total_herd         12      167.13       167.13             NaN         260.47          260.47                NaN             0.00       55.84
        calvings           12       22.48        -0.70             NaN          23.18            2.17                NaN             0.00        3.10
        abortions          12        7.91         7.91             NaN           4.14            4.14                NaN             0.00      -47.62
2019-06 milk_litres        12    40021.34     14048.73             NaN       40021.34        14048.73                NaN        -27071.79        0.00
        milking            12       31.25        -9.34            1.00          31.25           -9.34               1.00            -8.89        0.00
        total_herd         12       30.55       -17.91            1.00          30.55          -17.91               1.00           -52.05        0.00
        calvings           12       30.23       -20.29            0.58          30.23          -20.29               0.58           -14.75        0.00
        abortions          12        2.83        -1.03            0.58           2.83           -1.03               0.58             0.00        0.00
2020-08 milk_litres        12    49122.40     46419.01             NaN       49122.40        46419.01                NaN        -25676.57        0.00
        milking            12      107.71        59.38            0.75         107.71           59.38               0.75           -10.41        0.00
        total_herd         12      121.02       121.02            1.00         121.02          121.02               1.00            23.03        0.00
        calvings           12       12.58        -6.71            0.75          12.58           -6.71               0.75           -10.60        0.00
        abortions          12        6.80        -6.56            0.50           6.80           -6.56               0.50             0.00        0.00
2022-09 milk_litres         9    43470.67    -43470.67             NaN       43470.67       -43470.67                NaN        -23110.64        0.00
        milking            12       74.63       -14.59            0.58          74.63          -14.59               0.58           -60.25        0.00
        total_herd         12       81.86        62.57            1.00          81.86           62.57               1.00          -114.05        0.00
        calvings           12       29.26       -22.86            0.42          29.26          -22.86               0.42            -7.03        0.00
        abortions          12        3.07        -0.83            0.92           3.07           -0.83               0.92             0.00        0.00
2023-11 milk_litres         6    41487.39     11144.00             NaN       41487.39        11144.00                NaN          6477.53        0.00
        milking            12      129.95       129.95            0.33         129.95          129.95               0.33           -24.65        0.00
        total_herd         12      237.20       237.20            0.42         237.20          237.20               0.42           -95.62        0.00
        calvings           12       24.45        22.06            0.25          24.45           22.06               0.25             1.85        0.00
        abortions          12       23.18       -23.18            0.00          23.18          -23.18               0.00             0.00        0.00
2024-01 milk_litres         4    28832.60    -28169.96             NaN       28832.60       -28169.96                NaN          1360.64        0.00
        milking            12      158.32       158.32            0.17         158.32          158.32               0.17             5.98        0.00
        total_herd         12      291.28       288.76            0.25         291.28          288.76               0.25           -63.87        0.00
        calvings           12       24.72        24.33            0.25          24.72           24.33               0.25             2.83        0.00
        abortions          12       22.23       -22.23            0.17          22.23          -22.23               0.17             0.00        0.00
2024-07 milk_litres         2    35161.49     35161.49             NaN       35161.49        35161.49                NaN         11751.84        0.00
        milking            12       98.34        98.34            0.25          98.34           98.34               0.25            82.72        0.00
        total_herd         12      228.66      -228.66            0.17         228.66         -228.66               0.17            21.78        0.00
        calvings           12       17.60         7.16            0.42          17.60            7.16               0.42             4.03        0.00
        abortions          12       12.36       -12.36            0.83          12.36          -12.36               0.83             0.00        0.00
2026-08 milk_litres         0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        milking             0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        total_herd          0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        calvings            0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        abortions           0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
```

</details>


<details>
<summary>Interrupted combined build — development artifact, 2024–26 origins are post-test development</summary>

```text
=== forecast date 2017-01-01 ===
break reset: 2 breaks before 2017-01-01; latest 2016-05-05
correction layer: 0 herd bias terms, 11 milk levels (from errors ended by 2017-01-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2017-01-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast  lower  upper
   2017-01-01  505005.0    NaN    NaN
   2017-02-01  398708.0    NaN    NaN
   2017-03-01  455872.0    NaN    NaN
   2017-04-01  550055.0    NaN    NaN
   2017-05-01  789850.0    NaN    NaN
   2017-06-01 1029652.0    NaN    NaN
   2017-07-01 1269406.0    NaN    NaN
   2017-08-01 1340873.0    NaN    NaN
   2017-09-01 1237770.0    NaN    NaN
   2017-10-01 1208106.0    NaN    NaN
   2017-11-01 1132514.0    NaN    NaN
   2017-12-01 1136423.0    NaN    NaN
rows: outlook 234, attribution 704, history 102; page document: 364 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/168, week 169/167
not written to the database (add --write after checking the numbers)

=== forecast date 2019-06-01 ===
break reset: 2 breaks before 2019-06-01; latest 2016-05-05
correction layer: 32 herd bias terms, 11 milk levels (from errors ended by 2019-06-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2019-06-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast    lower    upper
   2019-06-01  556716.0 517577.0 601756.0
   2019-07-01  616974.0 439505.0 692785.0
   2019-08-01  641812.0 457199.0 720676.0
   2019-09-01  630065.0 389143.0 704937.0
   2019-10-01  673234.0 415805.0 753236.0
   2019-11-01  687803.0 424803.0 769536.0
   2019-12-01  702888.0 477277.0 746019.0
   2020-01-01  683832.0 464338.0 725794.0
   2020-02-01  578258.0 392651.0 613741.0
   2020-03-01  585866.0 397816.0 621815.0
   2020-04-01  562396.0 381880.0 596906.0
   2020-05-01  579756.0 393667.0 615331.0
rows: outlook 234, attribution 768, history 144; page document: 364 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/168, week 169/169
not written to the database (add --write after checking the numbers)

=== forecast date 2020-08-01 ===
break reset: 2 breaks before 2020-08-01; latest 2016-05-05
correction layer: 32 herd bias terms, 11 milk levels (from errors ended by 2020-08-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2020-08-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast    lower    upper
   2020-08-01  556892.0 514365.0 600376.0
   2020-09-01  510839.0 427540.0 576324.0
   2020-10-01  532166.0 445389.0 600385.0
   2020-11-01  507555.0 326819.0 566356.0
   2020-12-01  539911.0 347654.0 602460.0
   2021-01-01  542598.0 349383.0 605458.0
   2021-02-01  520844.0 377381.0 656518.0
   2021-03-01  533523.0 386568.0 672499.0
   2021-04-01  474486.0 343792.0 598084.0
   2021-05-01  492861.0 357106.0 621245.0
   2021-06-01  499421.0 361859.0 629514.0
   2021-07-01  535057.0 387679.0 674433.0
rows: outlook 234, attribution 768, history 144; page document: 364 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: day 14/13, month 168/168, week 169/168
not written to the database (add --write after checking the numbers)

=== forecast date 2022-09-01 ===
break reset: 2 breaks before 2022-09-01; latest 2016-05-05
correction layer: 32 herd bias terms, 11 milk levels (from errors ended by 2022-09-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2022-09-01  model pfoi-1.2.0-dev (config dev), quality: low_recording;source_switch
target_period  forecast   lower   upper
   2022-09-01   83858.0 76548.0 90486.0
   2022-10-01   78267.0 62371.0 86992.0
   2022-11-01   76278.0 60786.0 84780.0
   2022-12-01   65856.0 42158.0 73513.0
   2023-01-01   62261.0 39857.0 69501.0
   2023-02-01   52494.0 33604.0 58598.0
   2023-03-01   56352.0 38995.0 69563.0
   2023-04-01   50941.0 35251.0 62883.0
   2023-05-01   47840.0 33105.0 59055.0
   2023-06-01   43874.0 30360.0 54159.0
   2023-07-01   45323.0 31363.0 55948.0
   2023-08-01   45656.0 31594.0 56360.0
rows: outlook 234, attribution 761, history 144; page document: 364 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: day 14/0, month 168/165, week 169/157
not written to the database (add --write after checking the numbers)

=== forecast date 2023-11-01 ===
break reset: 4 breaks before 2023-11-01; latest 2023-01-30
correction layer: 24 herd bias terms, 10 milk levels (from errors ended by 2023-11-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2023-11-01  model pfoi-1.2.0-dev (config dev), quality: low_recording
target_period  forecast    lower    upper
   2023-11-01  142169.0 129163.0 156280.0
   2023-12-01  128818.0  85968.0 144646.0
   2024-01-01  125374.0  83670.0 140779.0
   2024-02-01  113738.0  70247.0 133320.0
   2024-03-01  120638.0  74509.0 141408.0
   2024-04-01  118295.0  73062.0 138662.0
   2024-05-01  118551.0  68035.0 147606.0
   2024-06-01  104506.0  59975.0 130119.0
   2024-07-01   97603.0  56013.0 121524.0
   2024-08-01   92851.0  53286.0 115607.0
   2024-09-01   88447.0  50759.0 110124.0
   2024-10-01   90419.0  51890.0 112579.0
rows: outlook 234, attribution 735, history 144; page document: 364 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: day 14/13, month 168/162, week 169/166
not written to the database (add --write after checking the numbers)

=== forecast date 2024-01-01 ===
break reset: 4 breaks before 2024-01-01; latest 2023-01-30
correction layer: 28 herd bias terms, 10 milk levels (from errors ended by 2024-01-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2024-01-01  model pfoi-1.2.0-dev (config dev), quality: low_recording
target_period  forecast   lower    upper
   2024-01-01  105375.0 95735.0 115834.0
   2024-02-01   87109.0 58134.0  97813.0
   2024-03-01   93525.0 62415.0 105016.0
   2024-04-01   92376.0 57054.0 108281.0
   2024-05-01   94422.0 58317.0 110678.0
   2024-06-01   87891.0 54283.0 103023.0
   2024-07-01   85919.0 49308.0 106976.0
   2024-08-01   76699.0 44017.0  95497.0
   2024-09-01   66202.0 37993.0  82427.0
   2024-10-01   65864.0 37799.0  82007.0
   2024-11-01   64169.0 36826.0  79896.0
   2024-12-01   67097.0 38506.0  83541.0
rows: outlook 234, attribution 749, history 144; page document: 364 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/160, week 169/166
not written to the database (add --write after checking the numbers)

=== forecast date 2024-07-01 ===
break reset: 5 breaks before 2024-07-01; latest 2024-04-27
correction layer: 8 herd bias terms, 10 milk levels (from errors ended by 2024-07-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2024-07-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast    lower    upper
   2024-07-01  154266.0 140264.0 169481.0
   2024-08-01  146645.0  97866.0 164664.0
   2024-09-01  133584.0  89149.0 149998.0
   2024-10-01  131212.0  81040.0 153802.0
   2024-11-01  121510.0  75048.0 142431.0
   2024-12-01  123117.0  76040.0 144313.0
   2025-01-01  113864.0  65345.0 141770.0
   2025-02-01   90953.0  52197.0 113244.0
   2025-03-01   90924.0  52180.0 113208.0
   2025-04-01   84538.0  48515.0 105257.0
   2025-05-01   85809.0  49245.0 106839.0
   2025-06-01   81215.0  46608.0 101119.0
rows: outlook 234, attribution 728, history 144; page document: 364 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/158, week 169/165
not written to the database (add --write after checking the numbers)

=== forecast date 2025-09-01 ===
break reset: 5 breaks before 2025-09-01; latest 2024-04-27
2025-09-01: milk forecast withheld (milk_withheld:no_trusted_recent_days); herd forecast kept.
correction layer: 28 herd bias terms, 10 milk levels (from errors ended by 2025-09-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2025-09-01  model pfoi-1.2.0-dev (config dev), quality: milk_withheld:no_trusted_recent_days;no_window_k
Empty DataFrame
Columns: [target_period, forecast, lower, upper]
Index: []
rows: outlook 195, attribution 612, history 144; page document: 325 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: month 143/143, week 156/156
not written to the database (add --write after checking the numbers)

=== forecast date 2025-12-01 ===
break reset: 6 breaks before 2025-12-01; latest 2025-09-08
2025-12-01: milk forecast withheld (milk_withheld:no_trusted_recent_days); herd forecast kept.
correction layer: 8 herd bias terms, 10 milk levels (from errors ended by 2025-12-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2025-12-01  model pfoi-1.2.0-dev (config dev), quality: milk_withheld:no_trusted_recent_days;no_window_k
Empty DataFrame
Columns: [target_period, forecast, lower, upper]
Index: []
rows: outlook 195, attribution 612, history 144; page document: 325 forecasts, 251 backtest rows
realised outcomes (periods, scoreable) by grain: month 104/104, week 156/156
not written to the database (add --write after checking the numbers)

=== forecast date 2026-04-01 ===
break reset: 6 breaks before 2026-04-01; latest 2025-09-08
correction layer: 20 herd bias terms, 10 milk levels (from errors ended by 2026-04-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured (file named in the supplied command)
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
^C
```

</details>

## Appendix: completed-build follow-up aggregate outputs

User-supplied aggregate outputs, 2026-10-20. Forecast origins before 2024 are development
examples; 2024–26 origins are post-test development. Forecast-month rows are herd-level
aggregates, not animal records. Comparison n is scored months, not independent origins;
coverage sample counts are not separately printed. NaN means unavailable.

<details>
<summary>Completed build — user reports 11/11 dates published</summary>

```text
python -m components.predictive_farm_intelligence.pfoi.cli build-outlook --origin 2017-01-01 2019-06-01 2020-08-01 2022-09-01 2023-11-01 2024-01-01 2024-07-01 2025-09-01 2025-12-01 2026-04-01 2026-08-01 --write --preset pfoi-1.1 --k anchor_first --fast-half-life 3 --exit-model lactation --break-reset on --intervals aci --staleness logs/pfoi/outage_sim/outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv

=== forecast date 2017-01-01 ===
break reset: 2 breaks before 2017-01-01; latest 2016-05-05
correction layer: 0 herd bias terms, 11 milk levels (from errors ended by 2017-01-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2017-01-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast  lower  upper
   2017-01-01  505005.0    NaN    NaN
   2017-02-01  398708.0    NaN    NaN
   2017-03-01  455872.0    NaN    NaN
   2017-04-01  550055.0    NaN    NaN
   2017-05-01  789850.0    NaN    NaN
   2017-06-01 1029652.0    NaN    NaN
   2017-07-01 1269406.0    NaN    NaN
   2017-08-01 1340873.0    NaN    NaN
   2017-09-01 1237770.0    NaN    NaN
   2017-10-01 1208106.0    NaN    NaN
   2017-11-01 1132514.0    NaN    NaN
   2017-12-01 1136423.0    NaN    NaN
rows: outlook 234, attribution 704, history 102; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/168, week 169/167
written to c1_output: {'outlook': 234, 'attribution': 704, 'history': 102} + run_document

=== forecast date 2019-06-01 ===
break reset: 2 breaks before 2019-06-01; latest 2016-05-05
correction layer: 32 herd bias terms, 11 milk levels (from errors ended by 2019-06-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2019-06-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast    lower    upper
   2019-06-01  556716.0 517577.0 601756.0
   2019-07-01  616974.0 439505.0 692785.0
   2019-08-01  641812.0 457199.0 720676.0
   2019-09-01  630065.0 389143.0 704937.0
   2019-10-01  673234.0 415805.0 753236.0
   2019-11-01  687803.0 424803.0 769536.0
   2019-12-01  702888.0 477277.0 746019.0
   2020-01-01  683832.0 464338.0 725794.0
   2020-02-01  578258.0 392651.0 613741.0
   2020-03-01  585866.0 397816.0 621815.0
   2020-04-01  562396.0 381880.0 596906.0
   2020-05-01  579756.0 393667.0 615331.0
rows: outlook 234, attribution 768, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/168, week 169/169
written to c1_output: {'outlook': 234, 'attribution': 768, 'history': 144} + run_document

=== forecast date 2020-08-01 ===
break reset: 2 breaks before 2020-08-01; latest 2016-05-05
correction layer: 32 herd bias terms, 11 milk levels (from errors ended by 2020-08-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2020-08-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast    lower    upper
   2020-08-01  556892.0 514365.0 600376.0
   2020-09-01  510839.0 427540.0 576324.0
   2020-10-01  532166.0 445389.0 600385.0
   2020-11-01  507555.0 326819.0 566356.0
   2020-12-01  539911.0 347654.0 602460.0
   2021-01-01  542598.0 349383.0 605458.0
   2021-02-01  520844.0 377381.0 656518.0
   2021-03-01  533523.0 386568.0 672499.0
   2021-04-01  474486.0 343792.0 598084.0
   2021-05-01  492861.0 357106.0 621245.0
   2021-06-01  499421.0 361859.0 629514.0
   2021-07-01  535057.0 387679.0 674433.0
rows: outlook 234, attribution 768, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/13, month 168/168, week 169/168
written to c1_output: {'outlook': 234, 'attribution': 768, 'history': 144} + run_document

=== forecast date 2022-09-01 ===
break reset: 2 breaks before 2022-09-01; latest 2016-05-05
correction layer: 32 herd bias terms, 11 milk levels (from errors ended by 2022-09-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2022-09-01  model pfoi-1.2.0-dev (config dev), quality: low_recording;source_switch
target_period  forecast   lower   upper
   2022-09-01   83858.0 76548.0 90486.0
   2022-10-01   78267.0 62371.0 86992.0
   2022-11-01   76278.0 60786.0 84780.0
   2022-12-01   65856.0 42158.0 73513.0
   2023-01-01   62261.0 39857.0 69501.0
   2023-02-01   52494.0 33604.0 58598.0
   2023-03-01   56352.0 38995.0 69563.0
   2023-04-01   50941.0 35251.0 62883.0
   2023-05-01   47840.0 33105.0 59055.0
   2023-06-01   43874.0 30360.0 54159.0
   2023-07-01   45323.0 31363.0 55948.0
   2023-08-01   45656.0 31594.0 56360.0
rows: outlook 234, attribution 761, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/0, month 168/165, week 169/157
written to c1_output: {'outlook': 234, 'attribution': 761, 'history': 144} + run_document

=== forecast date 2023-11-01 ===
break reset: 4 breaks before 2023-11-01; latest 2023-01-30
correction layer: 24 herd bias terms, 10 milk levels (from errors ended by 2023-11-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2023-11-01  model pfoi-1.2.0-dev (config dev), quality: low_recording
target_period  forecast    lower    upper
   2023-11-01  142169.0 129163.0 156280.0
   2023-12-01  128818.0  85968.0 144646.0
   2024-01-01  125374.0  83670.0 140779.0
   2024-02-01  113738.0  70247.0 133320.0
   2024-03-01  120638.0  74509.0 141408.0
   2024-04-01  118295.0  73062.0 138662.0
   2024-05-01  118551.0  68035.0 147606.0
   2024-06-01  104506.0  59975.0 130119.0
   2024-07-01   97603.0  56013.0 121524.0
   2024-08-01   92851.0  53286.0 115607.0
   2024-09-01   88447.0  50759.0 110124.0
   2024-10-01   90419.0  51890.0 112579.0
rows: outlook 234, attribution 735, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/13, month 168/162, week 169/166
written to c1_output: {'outlook': 234, 'attribution': 735, 'history': 144} + run_document

=== forecast date 2024-01-01 ===
break reset: 4 breaks before 2024-01-01; latest 2023-01-30
correction layer: 28 herd bias terms, 10 milk levels (from errors ended by 2024-01-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2024-01-01  model pfoi-1.2.0-dev (config dev), quality: low_recording
target_period  forecast   lower    upper
   2024-01-01  105375.0 95735.0 115834.0
   2024-02-01   87109.0 58134.0  97813.0
   2024-03-01   93525.0 62415.0 105016.0
   2024-04-01   92376.0 57054.0 108281.0
   2024-05-01   94422.0 58317.0 110678.0
   2024-06-01   87891.0 54283.0 103023.0
   2024-07-01   85919.0 49308.0 106976.0
   2024-08-01   76699.0 44017.0  95497.0
   2024-09-01   66202.0 37993.0  82427.0
   2024-10-01   65864.0 37799.0  82007.0
   2024-11-01   64169.0 36826.0  79896.0
   2024-12-01   67097.0 38506.0  83541.0
rows: outlook 234, attribution 749, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/160, week 169/166
written to c1_output: {'outlook': 234, 'attribution': 749, 'history': 144} + run_document

=== forecast date 2024-07-01 ===
break reset: 5 breaks before 2024-07-01; latest 2024-04-27
correction layer: 8 herd bias terms, 10 milk levels (from errors ended by 2024-07-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2024-07-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast    lower    upper
   2024-07-01  154266.0 140264.0 169481.0
   2024-08-01  146645.0  97866.0 164664.0
   2024-09-01  133584.0  89149.0 149998.0
   2024-10-01  131212.0  81040.0 153802.0
   2024-11-01  121510.0  75048.0 142431.0
   2024-12-01  123117.0  76040.0 144313.0
   2025-01-01  113864.0  65345.0 141770.0
   2025-02-01   90953.0  52197.0 113244.0
   2025-03-01   90924.0  52180.0 113208.0
   2025-04-01   84538.0  48515.0 105257.0
   2025-05-01   85809.0  49245.0 106839.0
   2025-06-01   81215.0  46608.0 101119.0
rows: outlook 234, attribution 728, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/14, month 168/158, week 169/165
written to c1_output: {'outlook': 234, 'attribution': 728, 'history': 144} + run_document

=== forecast date 2025-09-01 ===
break reset: 5 breaks before 2025-09-01; latest 2024-04-27
2025-09-01: milk forecast withheld (milk_withheld:no_trusted_recent_days); herd forecast kept.
correction layer: 28 herd bias terms, 10 milk levels (from errors ended by 2025-09-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2025-09-01  model pfoi-1.2.0-dev (config dev), quality: milk_withheld:no_trusted_recent_days;no_window_k
Empty DataFrame
Columns: [target_period, forecast, lower, upper]
Index: []
rows: outlook 195, attribution 612, history 144; page document: 325 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: month 143/143, week 156/156
written to c1_output: {'outlook': 195, 'attribution': 612, 'history': 144} + run_document

=== forecast date 2025-12-01 ===
break reset: 6 breaks before 2025-12-01; latest 2025-09-08
2025-12-01: milk forecast withheld (milk_withheld:no_trusted_recent_days); herd forecast kept.
correction layer: 8 herd bias terms, 10 milk levels (from errors ended by 2025-12-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2025-12-01  model pfoi-1.2.0-dev (config dev), quality: milk_withheld:no_trusted_recent_days;no_window_k
Empty DataFrame
Columns: [target_period, forecast, lower, upper]
Index: []
rows: outlook 195, attribution 612, history 144; page document: 325 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: month 104/104, week 156/156
written to c1_output: {'outlook': 195, 'attribution': 612, 'history': 144} + run_document

=== forecast date 2026-04-01 ===
break reset: 6 breaks before 2026-04-01; latest 2025-09-08
correction layer: 20 herd bias terms, 10 milk levels (from errors ended by 2026-04-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2026-04-01  model pfoi-1.2.0-dev (config dev), quality: no_window_k
target_period  forecast    lower    upper
   2026-04-01  153401.0 137251.0 168433.0
   2026-05-01  161697.0 109322.0 183518.0
   2026-06-01  157144.0 106244.0 178350.0
   2026-07-01  160312.0  99614.0 190374.0
   2026-08-01  156630.0  97326.0 186001.0
   2026-09-01  159350.0  99016.0 189231.0
   2026-10-01  172798.0  99166.0 215147.0
   2026-11-01  158413.0  90911.0 197237.0
   2026-12-01  149409.0  85744.0 186027.0
   2027-01-01  140395.0  80571.0 174803.0
   2027-02-01  122354.0  70217.0 152340.0
   2027-03-01  131462.0  75444.0 163681.0
rows: outlook 234, attribution 672, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/12, month 56/56, week 169/161
written to c1_output: {'outlook': 234, 'attribution': 672, 'history': 144} + run_document

=== forecast date 2026-08-01 ===
break reset: 6 breaks before 2026-08-01; latest 2025-09-08
correction layer: 24 herd bias terms, 10 milk levels (from errors ended by 2026-08-01)
pfoi-1.2.0-dev: development build (not frozen); options: k=anchor_first, intervals=aci, staleness scale: measured: outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv
evidence tables: ladder, outage, registry, scenarios (in logs/pfoi)
Outlook 2026-08-01  model pfoi-1.2.0-dev (config dev), quality: ok
target_period  forecast    lower    upper
   2026-08-01  130270.0 116718.0 142994.0
   2026-09-01  130280.0  88650.0 147787.0
   2026-10-01  145436.0  98963.0 164980.0
   2026-11-01  156236.0  97375.0 185407.0
   2026-12-01  172870.0 107742.0 205147.0
   2027-01-01  180296.0 112371.0 213960.0
   2027-02-01  161472.0  92666.0 201045.0
   2027-03-01  163960.0  94095.0 204144.0
   2027-04-01  143106.0  82127.0 178179.0
   2027-05-01  139258.0  79918.0 173387.0
   2027-06-01  133011.0  76333.0 165609.0
   2027-07-01  136561.0  78370.0 170029.0
rows: outlook 234, attribution 662, history 144; page document: 364 forecasts, 251 backtest rows; files in logs/pfoi/outlook/pfoi-1.2.0-dev/
realised outcomes (periods, scoreable) by grain: day 14/14, week 26/26
written to c1_output: {'outlook': 234, 'attribution': 662, 'history': 144} + run_document

11/11 forecast dates built
```

</details>

<details>
<summary>Refreshed comparison against 1.1.0 — development and post-test development examples</summary>

```text
python -m components.predictive_farm_intelligence.pfoi.cli compare-runs --origins 2017-01-01 2019-06-01 2020-08-01 2022-09-01 2023-11-01 2024-01-01 2024-07-01 2026-08-01 --base pfoi-1.1.0 --candidate pfoi-1.2.0-dev

Recorded months after each forecast date that both versions forecast (pfoi-1.1.0 vs pfoi-1.2.0-dev; n_months = number of periods); MAE and bias: forecast - recorded; change_pct < 0 = candidate better;
cover90 blank = that run has no 5-95 % range (no past errors); layer_candidate = mean correction-layer amount in the candidate's forecast
                     n_months  mae_frozen  bias_frozen  cover90_frozen  mae_candidate  bias_candidate  cover90_candidate  layer_candidate  change_pct
origin  series
2017-01 milk_litres        12   286131.78    284116.56             NaN      298657.61       296640.91                NaN             0.00        4.38
        milking            12      103.50        93.20             NaN         113.30          102.91                NaN             0.00        9.47
        total_herd         12      167.13       167.13             NaN         260.47          260.47                NaN             0.00       55.84
        calvings           12       22.48        -0.70             NaN          23.18            2.17                NaN             0.00        3.10
        abortions          12        7.91         7.91             NaN           4.14            4.14                NaN             0.00      -47.62
2019-06 milk_litres        12    40021.34     14048.73             NaN       39490.31        13969.63               0.83        -10773.48       -1.33
        milking            12       31.25        -9.34            1.00          33.01           -4.61               1.00            25.14        5.63
        total_herd         12       30.55       -17.91            1.00          62.48           47.53               1.00             7.09      104.50
        calvings           12       30.23       -20.29            0.58          29.22          -16.76               0.67           -11.84       -3.32
        abortions          12        2.83        -1.03            0.58           2.82           -0.86               0.83             0.00       -0.29
2020-08 milk_litres        12    49122.40     46419.01             NaN       48497.29        46339.39               1.00        -15395.40       -1.27
        milking            12      107.71        59.38            0.75         119.45           76.59               0.50            25.11       10.90
        total_herd         12      121.02       121.02            1.00         169.73          169.73               1.00            64.08       40.24
        calvings           12       12.58        -6.71            0.75          12.53           -2.60               0.83            -7.91       -0.40
        abortions          12        6.80        -6.56            0.50           6.83           -6.63               0.58             0.00        0.41
2022-09 milk_litres         9    43470.67    -43470.67             NaN       43751.98       -43751.98               0.00        -19560.22        0.65
        milking            12       74.63       -14.59            0.58          73.38            3.11               1.00           -17.99       -1.68
        total_herd         12       81.86        62.57            1.00          90.55           85.96               1.00           -75.81       10.61
        calvings           12       29.26       -22.86            0.42          27.24          -20.40               1.00            -5.47       -6.91
        abortions          12        3.07        -0.83            0.92           2.95           -1.30               1.00             0.00       -4.16
2023-11 milk_litres         6    41487.39     11144.00             NaN       27947.89         6124.38               0.50         16348.22      -32.64
        milking            12      129.95       129.95            0.33         235.02          235.02               0.33            85.45       80.85
        total_herd         12      237.20       237.20            0.42         442.89          442.89               0.33            71.17       86.72
        calvings           12       24.45        22.06            0.25          25.28           24.54               0.75             1.93        3.38
        abortions          12       23.18       -23.18            0.00          22.81          -22.81               0.83             0.00       -1.58
2024-01 milk_litres         4    28832.60    -28169.96             NaN       28756.83       -28756.83               0.25         10437.04       -0.26
        milking            12      158.32       158.32            0.17         259.77          259.77               0.25           123.00       64.08
        total_herd         12      291.28       288.76            0.25         525.79          525.79               0.17           166.71       80.51
        calvings           12       24.72        24.33            0.25          33.18           33.18               0.33             9.73       34.23
        abortions          12       22.23       -22.23            0.17          20.18          -20.18               1.00             0.00       -9.21
2024-07 milk_litres         2    35161.49     35161.49             NaN       22493.17        22493.17               0.50             0.00      -36.03
        milking            12       98.34        98.34            0.25          36.16            0.79               1.00             0.00      -63.22
        total_herd         12      228.66      -228.66            0.17         331.54         -331.54               0.75             0.00       44.99
        calvings           12       17.60         7.16            0.42          15.81            0.70               0.92             0.00      -10.14
        abortions          12       12.36       -12.36            0.83          10.29          -10.28               1.00             0.00      -16.78
2026-08 milk_litres         0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        milking             0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        total_herd          0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        calvings            0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        abortions           0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN

Charts in logs/pfoi/compare/ (gitignored)
```

</details>

<details>
<summary>Refreshed comparison against 1.0.0 — development and post-test development examples</summary>

```text
python -m components.predictive_farm_intelligence.pfoi.cli compare-runs --origins 2017-01-01 2019-06-01 2020-08-01 2022-09-01 2023-11-01 2024-01-01 2024-07-01 2026-08-01 --base pfoi-1.0.0 --candidate pfoi-1.2.0-dev

Recorded months after each forecast date that both versions forecast (pfoi-1.0.0 vs pfoi-1.2.0-dev; n_months = number of periods); MAE and bias: forecast - recorded; change_pct < 0 = candidate better;
cover90 blank = that run has no 5-95 % range (no past errors); layer_candidate = mean correction-layer amount in the candidate's forecast
                     n_months  mae_frozen  bias_frozen  cover90_frozen  mae_candidate  bias_candidate  cover90_candidate  layer_candidate  change_pct
origin  series
2017-01 milk_litres        12   271578.94    268235.01             NaN      298657.61       296640.91                NaN             0.00        9.97
        milking            12       38.65       -25.44             NaN         113.30          102.91                NaN             0.00      193.13
        total_herd         12      117.19       107.16             NaN         260.47          260.47                NaN             0.00      122.26
        calvings           12       13.63         1.12             NaN          23.18            2.17                NaN             0.00       69.98
        abortions          12        4.80         4.80             NaN           4.14            4.14                NaN             0.00      -13.69
2019-06 milk_litres        12    72921.09     72921.09            1.00       39490.31        13969.63               0.83        -10773.48      -45.85
        milking            12       41.27        40.91            1.00          33.01           -4.61               1.00            25.14      -20.00
        total_herd         12       32.09        11.56            0.92          62.48           47.53               1.00             7.09       94.73
        calvings           12       15.97         4.85            0.50          29.22          -16.76               0.67           -11.84       83.01
        abortions          12        2.71        -1.23            0.67           2.82           -0.86               0.83             0.00        3.99
2020-08 milk_litres        12    97126.74     97126.74            1.00       48497.29        46339.39               1.00        -15395.40      -50.07
        milking            12      152.56       142.19            0.42         119.45           76.59               0.50            25.11      -21.70
        total_herd         12       82.49        82.49            1.00         169.73          169.73               1.00            64.08      105.77
        calvings           12       15.88         6.99            0.75          12.53           -2.60               0.83            -7.91      -21.08
        abortions          12        6.51        -6.29            0.50           6.83           -6.63               0.58             0.00        4.91
2022-09 milk_litres         9    11089.63     -9740.61            0.56       43751.98       -43751.98               0.00        -19560.22      294.53
        milking            12      113.81        99.67            0.58          73.38            3.11               1.00           -17.99      -35.53
        total_herd         12      198.98       198.98            0.75          90.55           85.96               1.00           -75.81      -54.49
        calvings           12       21.75         0.21            0.67          27.24          -20.40               1.00            -5.47       25.26
        abortions          12        2.96        -2.25            0.67           2.95           -1.30               1.00             0.00       -0.32
2023-11 milk_litres         6    20163.18     15160.25            0.67       27947.89         6124.38               0.50         16348.22       38.61
        milking            12      235.91       235.91            0.25         235.02          235.02               0.33            85.45       -0.37
        total_herd         12      306.09       306.09            0.50         442.89          442.89               0.33            71.17       44.69
        calvings           12       29.82        29.82            0.25          25.28           24.54               0.75             1.93      -15.22
        abortions          12       23.24       -23.24            0.00          22.81          -22.81               0.83             0.00       -1.86
2024-01 milk_litres         4    20943.98    -20943.98            0.00       28756.83       -28756.83               0.25         10437.04       37.30
        milking            12      238.29       238.29            0.17         259.77          259.77               0.25           123.00        9.02
        total_herd         12      398.39       398.04            0.33         525.79          525.79               0.17           166.71       31.98
        calvings           12       32.58        32.58            0.17          33.18           33.18               0.33             9.73        1.83
        abortions          12       23.08       -23.08            0.00          20.18          -20.18               1.00             0.00      -12.55
2024-07 milk_litres         2    27640.28     27640.28            0.50       22493.17        22493.17               0.50             0.00      -18.62
        milking            12       62.72        62.72            0.75          36.16            0.79               1.00             0.00      -42.34
        total_herd         12      208.41      -208.41            0.42         331.54         -331.54               0.75             0.00       59.08
        calvings           12       22.10        10.02            0.33          15.81            0.70               0.92             0.00      -28.45
        abortions          12       12.12       -12.12            0.83          10.29          -10.28               1.00             0.00      -15.13
2026-08 milk_litres         0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        milking             0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        total_herd          0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        calvings            0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN
        abortions           0         NaN          NaN             NaN            NaN             NaN                NaN              NaN         NaN

Charts in logs/pfoi/compare/ (gitignored)
```

</details>

## Appendix: reproductive decision evidence (2026-10-20)

User-supplied aggregate tables; descriptive post-test development evidence. N is lactations
or known pregnancies in each printed cell. The comparison uses the same recorded cohorts
for both engines; repeated observed values are not independent replications. Checkpoints
on a curve are dependent. NaN means unavailable, never zero.

<details>
<summary>Reference engine — exact supplied aggregate report</summary>

```text
python -m components.predictive_farm_intelligence.pfoi.cli repro-timing --preset pfoi-1.1 --asof 2026-08-21
Reproductive timing, lactations that started before 2026-08-21 (herd-level counts only).
Open or pregnant cows at that date are censored, not failures; leaving the herd is its own outcome; 'first_ai' is the first RECORDED service.

=== by period ===
   period             step    n  median_days  censored_share  left_herd_share  by_60d  by_100d  by_150d  by_200d  by_300d  p25_days  p75_days  first_event_day  calved_share  lost_share  n_resolved  calved_of_resolved  lost_of_resolved
2015-2019         first_ai 7265         66.0           0.000            0.050   0.406    0.845    0.923    0.941    0.949      53.0      84.0              3.0           NaN         NaN         NaN                 NaN               NaN
2015-2019       conception 7265        255.0           0.000            0.113   0.036    0.133    0.246    0.364    0.593     152.0     415.0             24.0           NaN         NaN         NaN                 NaN               NaN
2015-2019 calving_interval 7265        543.0           0.000            0.170   0.000    0.000    0.000    0.000    0.001     433.0     746.0             38.0           NaN         NaN         NaN                 NaN               NaN
2015-2019        pregnancy 6445          NaN           0.000            0.047     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.935       0.017      6445.0               0.935             0.017
2020-2022         first_ai 3975         74.0           0.001            0.190   0.298    0.678    0.763    0.787    0.805      58.0     136.0              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022       conception 3975        296.0           0.000            0.304   0.047    0.159    0.267    0.365    0.505     142.0       NaN             16.0           NaN         NaN         NaN                 NaN               NaN
2020-2022 calving_interval 3975        644.0           0.003            0.402   0.004    0.005    0.005    0.005    0.008     432.0       NaN              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022        pregnancy 2765          NaN           0.000            0.107     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.856       0.037      2764.0               0.856             0.037
2023-2026         first_ai 2257         78.0           0.053            0.165   0.299    0.669    0.775    0.810    0.828      56.0     130.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026       conception 2257        430.0           0.189            0.330   0.041    0.141    0.210    0.272    0.379     183.0       NaN             21.0           NaN         NaN         NaN                 NaN               NaN
2023-2026 calving_interval 2257          NaN           0.327            0.488   0.024    0.025    0.026    0.026    0.028     550.0       NaN              0.0           NaN         NaN         NaN                 NaN               NaN
2023-2026        pregnancy 1195          NaN           0.159            0.086     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.523       0.232      1005.0               0.622             0.276

=== by period, parity_group ===
   period parity_group             step    n  median_days  censored_share  left_herd_share  by_60d  by_100d  by_150d  by_200d  by_300d  p25_days  p75_days  first_event_day  calved_share  lost_share  n_resolved  calved_of_resolved  lost_of_resolved
2015-2019            1         first_ai 2818         61.0           0.000            0.016   0.494    0.855    0.947    0.973    0.983      49.0      82.0              4.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            1       conception 2818        259.0           0.000            0.050   0.028    0.097    0.195    0.326    0.603     170.0     377.0             39.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            1 calving_interval 2818        541.0           0.000            0.083   0.000    0.000    0.000    0.000    0.000     449.0     673.0            276.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            1        pregnancy 2677          NaN           0.000            0.024     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.965       0.011      2677.0               0.965             0.011
2015-2019            2         first_ai 2288         68.0           0.000            0.042   0.336    0.858    0.939    0.950    0.958      57.0      83.0             14.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            2       conception 2288        242.0           0.000            0.111   0.034    0.148    0.274    0.394    0.618     140.0     395.0             24.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            2 calving_interval 2288        530.0           0.000            0.167   0.000    0.000    0.000    0.000    0.000     422.0     725.0            300.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            2        pregnancy 2033          NaN           0.000            0.045     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.938       0.017      2033.0               0.938             0.017
2015-2019           3+         first_ai 2159         67.0           0.000            0.104   0.367    0.818    0.876    0.888    0.895      56.0      89.0              3.0           NaN         NaN         NaN                 NaN               NaN
2015-2019           3+       conception 2159        262.0           0.000            0.196   0.046    0.165    0.281    0.383    0.552     135.0     568.0             38.0           NaN         NaN         NaN                 NaN               NaN
2015-2019           3+ calving_interval 2159        575.0           0.000            0.287   0.000    0.000    0.001    0.001    0.001     423.0       NaN             38.0           NaN         NaN         NaN                 NaN               NaN
2015-2019           3+        pregnancy 1735          NaN           0.000            0.086     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.887       0.027      1735.0               0.887             0.027
2020-2022            1         first_ai 1007         69.0           0.004            0.088   0.337    0.763    0.869    0.888    0.909      56.0      97.0              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            1       conception 1007        240.0           0.001            0.158   0.057    0.185    0.314    0.425    0.591     127.0     457.0             16.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            1 calving_interval 1007        529.0           0.006            0.230   0.014    0.014    0.014    0.014    0.016     406.0     968.0              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            1        pregnancy  847          NaN           0.000            0.065     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.908       0.027       847.0               0.908             0.027
2020-2022            2         first_ai  724         67.0           0.000            0.112   0.373    0.765    0.849    0.865    0.885      54.0      97.0              2.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            2       conception  724        240.0           0.000            0.207   0.064    0.202    0.336    0.448    0.588     116.0     536.0             23.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            2 calving_interval  724        552.0           0.003            0.304   0.001    0.003    0.003    0.003    0.007     402.0       NaN             24.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            2        pregnancy  574          NaN           0.002            0.089     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.875       0.035       573.0               0.876             0.035
2020-2022           3+         first_ai 2244         80.0           0.000            0.260   0.256    0.611    0.688    0.717    0.733      60.0       NaN              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022           3+       conception 2244        371.0           0.000            0.401   0.037    0.133    0.225    0.312    0.440     162.0       NaN             25.0           NaN         NaN         NaN                 NaN               NaN
2020-2022           3+ calving_interval 2244          NaN           0.001            0.511   0.001    0.001    0.001    0.002    0.004     461.0       NaN             15.0           NaN         NaN         NaN                 NaN               NaN
2020-2022           3+        pregnancy 1344          NaN           0.000            0.141     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.815       0.045      1344.0               0.815             0.045
2023-2026            1         first_ai  503         82.0           0.121            0.092   0.242    0.696    0.831    0.878    0.898      61.0     113.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            1       conception  503        405.0           0.427            0.207   0.021    0.075    0.121    0.202    0.318     250.0     735.0             29.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            1 calving_interval  503        773.0           0.596            0.281   0.054    0.054    0.056    0.056    0.056     564.0       NaN              0.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            1        pregnancy  222          NaN           0.320            0.050     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.477       0.153       151.0               0.702             0.225
2023-2026            2         first_ai  528         71.0           0.044            0.109   0.340    0.731    0.838    0.859    0.886      54.0     109.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            2       conception  528        394.0           0.163            0.226   0.050    0.152    0.231    0.309    0.413     163.0     911.0             34.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            2 calving_interval  528        999.0           0.312            0.386   0.023    0.023    0.025    0.027    0.029     480.0       NaN              6.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            2        pregnancy  337          NaN           0.113            0.083     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.579       0.226       299.0               0.652             0.254
2023-2026           3+         first_ai 1226         78.0           0.029            0.218   0.304    0.632    0.727    0.763    0.776      56.0     177.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026           3+       conception 1226        474.0           0.103            0.414   0.045    0.163    0.236    0.283    0.385     166.0       NaN             21.0           NaN         NaN         NaN                 NaN               NaN
2023-2026           3+ calving_interval 1226          NaN           0.222            0.586   0.013    0.014    0.014    0.014    0.017     576.0       NaN              0.0           NaN         NaN         NaN                 NaN               NaN
2023-2026           3+        pregnancy  636          NaN           0.127            0.101     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.509       0.263       555.0               0.584             0.301

=== share conceived by day in milk: record (calvings 2023-2026) vs engine rates at 2026-08-01 ===
(engine: one conception rate per DIM band)
parity_group  day  recorded_conceived  engine_conceived  recorded_left  engine_left
           1   60               0.021             0.033          0.041        0.016
           1  100               0.075             0.105          0.054        0.029
           1  150               0.121             0.187          0.068        0.049
           1  200               0.202             0.278          0.090        0.070
           1  300               0.318             0.422          0.105        0.111
           2   60               0.050             0.033          0.063        0.016
           2  100               0.152             0.131          0.079        0.029
           2  150               0.231             0.238          0.111        0.048
           2  200               0.309             0.327          0.130        0.068
           2  300               0.413             0.467          0.169        0.107
          3+   60               0.045             0.033          0.147        0.016
          3+  100               0.163             0.130          0.177        0.029
          3+  150               0.236             0.236          0.225        0.048
          3+  200               0.283             0.326          0.264        0.068
          3+  300               0.385             0.466          0.313        0.107

Files in logs/pfoi/repro/. Associations in this herd only.
```

</details>

<details>
<summary>Lactation exit engine — exact supplied aggregate report</summary>

```text
python -m components.predictive_farm_intelligence.pfoi.cli repro-timing --preset pfoi-1.1 --exit-model lactation --asof 2026-08-21
Reproductive timing, lactations that started before 2026-08-21 (herd-level counts only).
Open or pregnant cows at that date are censored, not failures; leaving the herd is its own outcome; 'first_ai' is the first RECORDED service.

=== by period ===
   period             step    n  median_days  censored_share  left_herd_share  by_60d  by_100d  by_150d  by_200d  by_300d  p25_days  p75_days  first_event_day  calved_share  lost_share  n_resolved  calved_of_resolved  lost_of_resolved
2015-2019         first_ai 7265         66.0           0.000            0.050   0.406    0.845    0.923    0.941    0.949      53.0      84.0              3.0           NaN         NaN         NaN                 NaN               NaN
2015-2019       conception 7265        255.0           0.000            0.113   0.036    0.133    0.246    0.364    0.593     152.0     415.0             24.0           NaN         NaN         NaN                 NaN               NaN
2015-2019 calving_interval 7265        543.0           0.000            0.170   0.000    0.000    0.000    0.000    0.001     433.0     746.0             38.0           NaN         NaN         NaN                 NaN               NaN
2015-2019        pregnancy 6445          NaN           0.000            0.047     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.935       0.017      6445.0               0.935             0.017
2020-2022         first_ai 3975         74.0           0.001            0.190   0.298    0.678    0.763    0.787    0.805      58.0     136.0              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022       conception 3975        296.0           0.000            0.304   0.047    0.159    0.267    0.365    0.505     142.0       NaN             16.0           NaN         NaN         NaN                 NaN               NaN
2020-2022 calving_interval 3975        644.0           0.003            0.402   0.004    0.005    0.005    0.005    0.008     432.0       NaN              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022        pregnancy 2765          NaN           0.000            0.107     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.856       0.037      2764.0               0.856             0.037
2023-2026         first_ai 2257         78.0           0.053            0.165   0.299    0.669    0.775    0.810    0.828      56.0     130.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026       conception 2257        430.0           0.189            0.330   0.041    0.141    0.210    0.272    0.379     183.0       NaN             21.0           NaN         NaN         NaN                 NaN               NaN
2023-2026 calving_interval 2257          NaN           0.327            0.488   0.024    0.025    0.026    0.026    0.028     550.0       NaN              0.0           NaN         NaN         NaN                 NaN               NaN
2023-2026        pregnancy 1195          NaN           0.159            0.086     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.523       0.232      1005.0               0.622             0.276

=== by period, parity_group ===
   period parity_group             step    n  median_days  censored_share  left_herd_share  by_60d  by_100d  by_150d  by_200d  by_300d  p25_days  p75_days  first_event_day  calved_share  lost_share  n_resolved  calved_of_resolved  lost_of_resolved
2015-2019            1         first_ai 2818         61.0           0.000            0.016   0.494    0.855    0.947    0.973    0.983      49.0      82.0              4.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            1       conception 2818        259.0           0.000            0.050   0.028    0.097    0.195    0.326    0.603     170.0     377.0             39.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            1 calving_interval 2818        541.0           0.000            0.083   0.000    0.000    0.000    0.000    0.000     449.0     673.0            276.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            1        pregnancy 2677          NaN           0.000            0.024     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.965       0.011      2677.0               0.965             0.011
2015-2019            2         first_ai 2288         68.0           0.000            0.042   0.336    0.858    0.939    0.950    0.958      57.0      83.0             14.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            2       conception 2288        242.0           0.000            0.111   0.034    0.148    0.274    0.394    0.618     140.0     395.0             24.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            2 calving_interval 2288        530.0           0.000            0.167   0.000    0.000    0.000    0.000    0.000     422.0     725.0            300.0           NaN         NaN         NaN                 NaN               NaN
2015-2019            2        pregnancy 2033          NaN           0.000            0.045     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.938       0.017      2033.0               0.938             0.017
2015-2019           3+         first_ai 2159         67.0           0.000            0.104   0.367    0.818    0.876    0.888    0.895      56.0      89.0              3.0           NaN         NaN         NaN                 NaN               NaN
2015-2019           3+       conception 2159        262.0           0.000            0.196   0.046    0.165    0.281    0.383    0.552     135.0     568.0             38.0           NaN         NaN         NaN                 NaN               NaN
2015-2019           3+ calving_interval 2159        575.0           0.000            0.287   0.000    0.000    0.001    0.001    0.001     423.0       NaN             38.0           NaN         NaN         NaN                 NaN               NaN
2015-2019           3+        pregnancy 1735          NaN           0.000            0.086     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.887       0.027      1735.0               0.887             0.027
2020-2022            1         first_ai 1007         69.0           0.004            0.088   0.337    0.763    0.869    0.888    0.909      56.0      97.0              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            1       conception 1007        240.0           0.001            0.158   0.057    0.185    0.314    0.425    0.591     127.0     457.0             16.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            1 calving_interval 1007        529.0           0.006            0.230   0.014    0.014    0.014    0.014    0.016     406.0     968.0              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            1        pregnancy  847          NaN           0.000            0.065     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.908       0.027       847.0               0.908             0.027
2020-2022            2         first_ai  724         67.0           0.000            0.112   0.373    0.765    0.849    0.865    0.885      54.0      97.0              2.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            2       conception  724        240.0           0.000            0.207   0.064    0.202    0.336    0.448    0.588     116.0     536.0             23.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            2 calving_interval  724        552.0           0.003            0.304   0.001    0.003    0.003    0.003    0.007     402.0       NaN             24.0           NaN         NaN         NaN                 NaN               NaN
2020-2022            2        pregnancy  574          NaN           0.002            0.089     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.875       0.035       573.0               0.876             0.035
2020-2022           3+         first_ai 2244         80.0           0.000            0.260   0.256    0.611    0.688    0.717    0.733      60.0       NaN              1.0           NaN         NaN         NaN                 NaN               NaN
2020-2022           3+       conception 2244        371.0           0.000            0.401   0.037    0.133    0.225    0.312    0.440     162.0       NaN             25.0           NaN         NaN         NaN                 NaN               NaN
2020-2022           3+ calving_interval 2244          NaN           0.001            0.511   0.001    0.001    0.001    0.002    0.004     461.0       NaN             15.0           NaN         NaN         NaN                 NaN               NaN
2020-2022           3+        pregnancy 1344          NaN           0.000            0.141     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.815       0.045      1344.0               0.815             0.045
2023-2026            1         first_ai  503         82.0           0.121            0.092   0.242    0.696    0.831    0.878    0.898      61.0     113.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            1       conception  503        405.0           0.427            0.207   0.021    0.075    0.121    0.202    0.318     250.0     735.0             29.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            1 calving_interval  503        773.0           0.596            0.281   0.054    0.054    0.056    0.056    0.056     564.0       NaN              0.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            1        pregnancy  222          NaN           0.320            0.050     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.477       0.153       151.0               0.702             0.225
2023-2026            2         first_ai  528         71.0           0.044            0.109   0.340    0.731    0.838    0.859    0.886      54.0     109.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            2       conception  528        394.0           0.163            0.226   0.050    0.152    0.231    0.309    0.413     163.0     911.0             34.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            2 calving_interval  528        999.0           0.312            0.386   0.023    0.023    0.025    0.027    0.029     480.0       NaN              6.0           NaN         NaN         NaN                 NaN               NaN
2023-2026            2        pregnancy  337          NaN           0.113            0.083     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.579       0.226       299.0               0.652             0.254
2023-2026           3+         first_ai 1226         78.0           0.029            0.218   0.304    0.632    0.727    0.763    0.776      56.0     177.0              1.0           NaN         NaN         NaN                 NaN               NaN
2023-2026           3+       conception 1226        474.0           0.103            0.414   0.045    0.163    0.236    0.283    0.385     166.0       NaN             21.0           NaN         NaN         NaN                 NaN               NaN
2023-2026           3+ calving_interval 1226          NaN           0.222            0.586   0.013    0.014    0.014    0.014    0.017     576.0       NaN              0.0           NaN         NaN         NaN                 NaN               NaN
2023-2026           3+        pregnancy  636          NaN           0.127            0.101     NaN      NaN      NaN      NaN      NaN       NaN       NaN              NaN         0.509       0.263       555.0               0.584             0.301

=== share conceived by day in milk: record (calvings 2023-2026) vs engine rates at 2026-08-01 ===
(engine: one conception rate per DIM band)
parity_group  day  recorded_conceived  engine_conceived  recorded_left  engine_left
           1   60               0.021             0.033          0.041        0.028
           1  100               0.075             0.104          0.054        0.041
           1  150               0.121             0.185          0.068        0.059
           1  200               0.202             0.275          0.090        0.080
           1  300               0.318             0.418          0.105        0.120
           2   60               0.050             0.033          0.063        0.017
           2  100               0.152             0.131          0.079        0.031
           2  150               0.231             0.238          0.111        0.050
           2  200               0.309             0.327          0.130        0.069
           2  300               0.413             0.466          0.169        0.107
          3+   60               0.045             0.033          0.147        0.027
          3+  100               0.163             0.129          0.177        0.041
          3+  150               0.236             0.233          0.225        0.060
          3+  200               0.283             0.322          0.264        0.079
          3+  300               0.385             0.461          0.313        0.117

Files in logs/pfoi/repro/. Associations in this herd only.
```

</details>

## Appendix: completed decision-run output (2026-10-20)

Exact user-supplied aggregate evidence. Development origins are 2017–2023; 2024–26
results are post-test development. Counts are explicitly printed per metric table;
notes overlap and progress counts are not scored n. Coverage denominators were not
separately printed in this run. The quality-off control changes scoring eligibility
and is not a matched scaling-only comparison. NaN is missing, never zero.

<details>
<summary>Full decision-run aggregate output — ten commands, development before posthoc</summary>

```text
python -m components.predictive_farm_intelligence.pfoi.pp1_decisions --run --jobs 12
Exit-only safeguards (DEVELOPMENT; n is scored forecast periods):
  grain   series  horizon   n  baseline_mae  exit_mae  change_pct  passed
monthly calvings        1  84       17.0911   17.1021      0.0642    True
monthly calvings        3  82        8.0544    8.0863      0.3964    True
monthly calvings        6  79       17.0824   17.0491     -0.1949    True
monthly calvings       12  73       25.6331   26.0303      1.5496    True
monthly  milking        3  82       68.0685   66.8058     -1.8551    True
monthly  milking        6  79      106.0881   99.6031     -6.1128    True
monthly   n_herd        3  82       74.7944   73.1749     -2.1653    True
monthly   n_herd        6  79      123.9300  120.9627     -2.3943    True
 weekly calvings        1 365        6.5673    6.5680      0.0103    True
 weekly calvings        4 362        4.9133    4.9154      0.0426    True
 weekly calvings        8 358        4.4195    4.4258      0.1414    True
 weekly calvings       13 353        4.2538    4.2637      0.2315    True
Exit option: KEEP (numerical safeguards passed; reproductive evidence in PP1 plan)

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --k anchor_first --grain both --jobs 12

  monthly: origin 1/84 (2017-01-01)
  monthly: origin 11/84 (2017-11-01)
  monthly: origin 21/84 (2018-11-01)
  monthly: origin 31/84 (2019-05-01)
  monthly: origin 41/84 (2020-05-01)
  monthly: origin 51/84 (2021-03-01)
  monthly: origin 61/84 (2022-01-01)
  monthly: origin 71/84 (2022-11-01)
  monthly: origin 81/84 (2023-09-01)

Notes (monthly origins, number of origins):
         note  n_origins
        curve         84
            k        168
     k_window          2
source_switch          7
  weekly: origin 1/365 (2017-08-14)
  weekly: origin 11/365 (2017-07-03)
  weekly: origin 21/365 (2017-01-30)
  weekly: origin 31/365 (2017-04-10)
  weekly: origin 41/365 (2017-10-09)
  weekly: origin 51/365 (2017-12-18)
  weekly: origin 61/365 (2018-02-26)
  weekly: origin 71/365 (2018-05-07)
  weekly: origin 81/365 (2018-09-10)
  weekly: origin 91/365 (2018-07-30)
  weekly: origin 101/365 (2019-01-28)
  weekly: origin 111/365 (2018-12-17)
  weekly: origin 121/365 (2019-02-25)
  weekly: origin 131/365 (2019-08-26)
  weekly: origin 141/365 (2019-07-15)
  weekly: origin 151/365 (2019-11-18)
  weekly: origin 161/365 (2020-01-27)
  weekly: origin 171/365 (2020-04-06)
  weekly: origin 181/365 (2020-06-15)
  weekly: origin 191/365 (2020-08-24)
  weekly: origin 201/365 (2020-11-02)
  weekly: origin 211/365 (2021-01-11)
  weekly: origin 221/365 (2021-03-22)
  weekly: origin 231/365 (2021-05-31)
  weekly: origin 241/365 (2021-06-14)
  weekly: origin 251/365 (2021-10-18)
  weekly: origin 261/365 (2021-12-27)
  weekly: origin 271/365 (2022-03-07)
  weekly: origin 281/365 (2022-05-16)
  weekly: origin 291/365 (2022-07-25)
  weekly: origin 301/365 (2022-10-03)
  weekly: origin 311/365 (2022-12-12)
  weekly: origin 321/365 (2023-02-20)
  weekly: origin 331/365 (2023-12-11)
  weekly: origin 341/365 (2023-06-05)
  weekly: origin 351/365 (2023-08-14)
  weekly: origin 361/365 (2023-10-23)

Notes (weekly origins, number of origins):
         note  n_origins
        curve        365
            k        730
     k_window         11
source_switch         34

Done. Run milk-report with the same options to see the H1 table. Files in logs/pfoi/.

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli milk-report --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --k anchor_first

=== monthly (herd_fitted_p1_g0_kf, window 24) — litres per period ===
MAE:
model         ets  milk_baseline  milk_baseline_corrected  persistence    sarima  seasonal_naive
horizon
1         45351.0        17477.0                  17654.0      27789.0   32208.0        141442.0
3        141766.0        50412.0                  46976.0      65368.0   77844.0        141442.0
6        284900.0        81927.0                  91488.0      95860.0   95587.0        130780.0
12       379179.0        78088.0                  88015.0     129284.0  137502.0        131136.0
MAE ratio vs persistence (< 1 = better):
model     ets  milk_baseline  milk_baseline_corrected  persistence  sarima  seasonal_naive
horizon
1        1.63           0.63                     0.64          1.0    1.16            5.09
3        2.17           0.77                     0.72          1.0    1.19            2.16
6        2.97           0.85                     0.95          1.0    1.00            1.36
12       2.93           0.60                     0.68          1.0    1.06            1.01
bias (forecast - actual):
model        ets  milk_baseline  milk_baseline_corrected  persistence    sarima  seasonal_naive
horizon
1        -3308.2         4780.8                    303.4       2910.9   17831.2         80507.4
3       -14830.7        34952.3                   2819.3       6452.0   49316.8         80507.4
6       -69494.1        70742.1                   2151.2      13484.9   61489.5         67911.1
12      -62414.7        48869.8                  21905.2      70685.7  106913.4         72341.8
MAPE %:
model      ets  milk_baseline  milk_baseline_corrected  persistence  sarima  seasonal_naive
horizon
1          9.2            4.6                      5.2          6.7     7.6            45.1
3         26.4           14.9                     15.9         14.6    18.0            45.1
6         68.3           21.5                     24.3         22.0    27.8            42.9
12       125.4           27.8                     25.5         45.1    64.3            45.5
90% interval coverage %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  sarima  seasonal_naive
horizon
1        92.0           87.5                     82.1         87.5    87.0            73.6
3        79.5           78.8                     71.2         78.8    78.9            72.5
6        66.7           85.1                     76.6         68.1    44.4            54.3
12       39.4           48.6                     37.1         37.1     8.3            35.3
n periods scored:
model     ets  milk_baseline  milk_baseline_corrected  persistence  sarima  seasonal_naive
horizon
1        62.0           68.0                     68.0         68.0    35.0            65.0
3        58.0           66.0                     66.0         66.0    33.0            65.0
6        59.0           64.0                     64.0         64.0    33.0            63.0
12       57.0           58.0                     58.0         58.0    31.0            57.0

=== monthly: COMMON PERIODS (all models) — MAE ratio vs persistence ===
model    ets  milk_baseline  milk_baseline_corrected  persistence  sarima  seasonal_naive  n_periods
horizon
1       1.64           0.77                     0.68         1.00    1.65            5.87         35
3       2.39           0.96                     0.64         1.00    1.56            2.36         33
6       3.87           0.98                     0.56         1.00    1.26            1.66         33
12      3.15           0.59                     0.58         1.00    0.99            1.00         31

=== monthly: COMMON PERIODS (all models except SARIMA) — MAE ratio vs persistence ===
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive  n_periods
horizon
1       1.57           0.64                     0.62         1.00            4.94         59
3       1.99           0.72                     0.62         1.00            1.95         58
6       2.80           0.84                     0.91         1.00            1.29         59
12      2.89           0.60                     0.67         1.00            1.00         57

=== daily (herd_fitted_p1_g0_kf, window 24) — litres per period ===
MAE:
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        324.0          457.0                    466.0        387.0          4679.0
7        570.0          585.0                    597.0        548.0          4682.0
14       704.0          707.0                    727.0        695.0          4693.0
MAE ratio vs persistence (< 1 = better):
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        0.84           1.18                     1.20          1.0           12.10
7        1.04           1.07                     1.09          1.0            8.55
14       1.01           1.02                     1.05          1.0            6.75
bias (forecast - actual):
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         3.7           48.7                     16.9         -9.6          2929.1
7        34.0          145.1                     -9.5         30.2          2964.6
14       74.5          251.2                    -30.8         77.0          2976.3
MAPE %:
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        2.9            4.3                      4.4          3.4            50.1
7        4.8            6.3                      6.6          5.0            50.3
14       6.2            7.6                      8.1          6.3            50.4
90% interval coverage %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        80.4           83.1                     85.1         79.1            80.1
7        80.6           83.5                     81.8         85.9            80.2
14       83.8           83.4                     81.1         87.5            80.1
n periods scored:
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        329.0          348.0                    348.0        348.0           330.0
7        326.0          348.0                    348.0        348.0           331.0
14       326.0          347.0                    347.0        347.0           330.0

=== weekly (herd_fitted_p1_g0_kf, window 24) — litres per period ===
MAE:
model        ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         2727.0         3088.0                   3052.0       2809.0         32560.0
4         6593.0         5730.0                   5767.0       6567.0         32736.0
8        12152.0         9123.0                   9553.0      10555.0         32694.0
13       19029.0        12766.0                  14299.0      14580.0         32475.0
MAE ratio vs persistence (< 1 = better):
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        0.97           1.10                     1.09          1.0           11.59
4        1.00           0.87                     0.88          1.0            4.99
8        1.15           0.86                     0.91          1.0            3.10
13       1.31           0.88                     0.98          1.0            2.23
bias (forecast - actual):
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        130.5          685.4                     63.2        251.3         19774.1
4        273.4         2887.1                   -415.8        958.5         19914.2
8        242.3         5933.6                  -1195.0       1454.6         19789.9
13      -671.7         9364.6                  -2686.4       2010.6         19447.8
MAPE %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         3.2            3.9                      3.9          3.4            47.4
4         7.0            8.1                      8.5          7.9            47.7
8        12.8           13.0                     14.4         12.1            47.7
13       16.7           17.7                     20.4         15.9            47.6
90% interval coverage %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        83.4           82.3                     82.0         82.3            79.4
4        86.6           83.9                     81.1         86.4            78.4
8        88.0           83.7                     80.4         84.4            77.0
13       93.3           83.0                     79.3         82.7            76.2
n periods scored:
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        309.0          333.0                    333.0        333.0           319.0
4        303.0          330.0                    330.0        330.0           317.0
8        299.0          326.0                    326.0        326.0           315.0
13       290.0          323.0                    323.0        323.0           312.0

=== daily: COMMON PERIODS (all models) — MAE ratio vs persistence ===
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive  n_periods
horizon
1       0.82           1.12                     1.13         1.00           11.64        314
7       1.06           1.01                     1.04         1.00            8.42        312
14      1.03           0.95                     1.00         1.00            6.73        311

=== weekly: COMMON PERIODS (all models) — MAE ratio vs persistence ===
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive  n_periods
horizon
1       0.98           1.07                     1.06         1.00           11.60        299
4       1.00           0.83                     0.84         1.00            4.89        297
8       1.11           0.79                     0.84         1.00            2.91        294
13      1.25           0.80                     0.91         1.00            2.04        283

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli break-reset --herd-tag w24_ck_kn_rk_lag90_hl6_xl --milk-tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_xl --out logs/pfoi
Breaks detected (herd size +/-10 % over 90 days, or milk back after 28+ days): 4; years: 2015, 2016, 2022, 2023

=== correction layer with and without the break reset (development) ===
   series   grain  horizon                     model   n  accuracy  n_after  after_break
herd_milk  weekly        4    milk_baseline_adaptive 330     0.944       33        0.834
herd_milk  weekly        4 milk_baseline_adaptive_br 330     0.945       33        0.853
herd_milk monthly        3    milk_baseline_adaptive  66     0.909        6        0.729
herd_milk monthly        3 milk_baseline_adaptive_br  66     0.910        6        0.790
  milking monthly        3     herd_engine_corrected  82     0.941        8        0.873
  milking monthly        3  herd_engine_corrected_br  82     0.943        8        0.912
  milking monthly        6     herd_engine_corrected  79     0.930        8        0.726
  milking monthly        6  herd_engine_corrected_br  79     0.939        8        0.858
   n_herd monthly        6     herd_engine_corrected  79     0.956        8        0.892
   n_herd monthly        6  herd_engine_corrected_br  79     0.959        8        0.935
   n_herd monthly       12     herd_engine_corrected  73     0.952        2        0.829
   n_herd monthly       12  herd_engine_corrected_br  73     0.953        2        0.870
 calvings monthly        3     herd_engine_corrected  82     0.936        8        0.916
 calvings monthly        3  herd_engine_corrected_br  82     0.938        8        0.947

Keep rule: PASSED
Wrote candidates w24_ck_kn_rk_lag90_hl6_xl_br and herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_xl_br (models *_br).
SELECTED-CONFIG RESET: KEEP
Small after-break samples: numerical verdict is not strong confirmation.

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli scorecard --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --k anchor_first --block development --intervals empirical

=== development block: targets (docs/targets.md), herd-level aggregates ===
                                                n  accuracy  target_accuracy  skill best_benchmark  bias_pct  coverage80  coverage90  width90  deviance_ratio  target calibrated                                           reasons
grain   series         horizon model
daily   herd_milk      1       milk_baseline  348     0.970            0.950 -0.372            ets     0.003       0.740       0.831    0.119             NaN  missed         no                             skill below condition
                       7       milk_baseline  348     0.962            0.920 -0.069    persistence     0.009       0.724       0.835    0.144             NaN  missed         no                             skill below condition
                       14      milk_baseline  347     0.954            0.900 -0.017    persistence     0.016       0.767       0.834    0.180             NaN     met         no
monthly calvings       1       herd_engine     75     0.860            0.800  0.382    persistence     0.139       0.734       0.828    0.240             NaN     met         no
                       3       herd_engine     73     0.935            0.800  0.798         sarima     0.027       0.767       0.850    0.229             NaN     met        yes
                       6       herd_engine     71     0.861            0.750  0.533         sarima     0.057       0.519       0.667    0.324             NaN     met         no
                       12      herd_engine     65     0.767            0.650  0.293         sarima     0.139       0.690       0.905    0.651             NaN     met         no
        culls          1       herd_engine     75     0.472              NaN  0.238    persistence    -0.086       0.862       0.966   11.519           0.537  missed         no                       80% coverage outside 75-85%
                       3       herd_engine     73     0.466              NaN  0.221    persistence    -0.095       0.833       0.981    3.428           0.505     met         no
                       6       herd_engine     71     0.441              NaN  0.268    persistence    -0.170       0.833       0.958   12.301           0.550     met         no
                       12      herd_engine     65     0.400              NaN  0.185    persistence    -0.259       0.750       0.889   19.167           0.520     met        yes
        deaths         1       herd_engine     75     0.762              NaN -0.025    persistence    -0.013       0.703       0.844    1.065           1.023  missed         no  80% coverage outside 75-85%; deviance ratio >= 1
                       3       herd_engine     73     0.725              NaN  0.203    persistence     0.001       0.617       0.717    0.984           0.469  missed         no                       80% coverage outside 75-85%
                       6       herd_engine     71     0.670              NaN  0.249    persistence    -0.027       0.519       0.574    1.051           0.418  missed         no                       80% coverage outside 75-85%
                       12      herd_engine     65     0.586              NaN  0.115    persistence    -0.084       0.429       0.452    1.805           0.669  missed         no                       80% coverage outside 75-85%
        dry_offs       1       herd_engine     75     0.610            0.750  0.360    persistence    -0.025       0.672       0.797    1.505             NaN  missed         no                                    accuracy < 75%
                       3       herd_engine     73     0.593            0.700  0.344    persistence    -0.087       0.633       0.733    1.543             NaN  missed         no                                    accuracy < 70%
                       6       herd_engine     71     0.577            0.700  0.387    persistence    -0.115       0.704       0.778    1.626             NaN  missed         no                                    accuracy < 70%
                       12      herd_engine     65     0.578            0.650  0.416    persistence    -0.014       0.738       0.810    1.501             NaN  missed         no                                    accuracy < 65%
        herd_milk      1       milk_baseline   68     0.965            0.920  0.371    persistence     0.010       0.786       0.875    0.141             NaN     met        yes
                       3       milk_baseline   66     0.900            0.900  0.229    persistence     0.069       0.577       0.788    0.343             NaN  missed         no       accuracy < 90%; |bias| > 3%; width90 > 0.30
                       6       milk_baseline   64     0.838            0.880  0.145    persistence     0.140       0.660       0.851    0.442             NaN  missed         no                       accuracy < 88%; |bias| > 3%
                       12      milk_baseline   58     0.837            0.850  0.396    persistence     0.102       0.371       0.486    0.439             NaN  missed         no                       accuracy < 85%; |bias| > 3%
        milking        1       herd_engine     75     0.979            0.970  0.139    persistence     0.005       0.672       0.797    0.082             NaN     met         no
                       3       herd_engine     73     0.953            0.950  0.292    persistence     0.021       0.700       0.717    0.158             NaN     met         no
                       6       herd_engine     71     0.931            0.920  0.318    persistence     0.048       0.667       0.722    0.153             NaN     met         no
                       12      herd_engine     65     0.932            0.880  0.545    persistence    -0.012       0.571       0.833    0.252             NaN     met         no
        n_herd         1       herd_engine     75     0.993            0.980 -0.104    persistence     0.005       0.734       0.859    0.035             NaN     met         no
                       3       herd_engine     73     0.976            0.960 -0.140    persistence     0.012       0.767       0.817    0.098             NaN     met         no
                       6       herd_engine     71     0.963            0.940 -0.053    persistence     0.020       0.759       0.852    0.137             NaN  missed        yes                             skill below condition
                       12      herd_engine     65     0.953            0.900  0.176         sarima     0.027       0.762       0.786    0.144             NaN     met         no
        real_abortions 1       herd_engine     75     0.424              NaN -0.037    persistence     0.033       0.703       0.859    2.027           0.881  missed         no                       80% coverage outside 75-85%
                       3       herd_engine     73     0.369              NaN -0.021    persistence     0.042       0.600       0.800    2.037           0.916  missed         no                       80% coverage outside 75-85%
                       6       herd_engine     71     0.308              NaN  0.175    persistence     0.071       0.667       0.741    2.123           0.634  missed         no                       80% coverage outside 75-85%
                       12      herd_engine     65     0.228              NaN  0.048    persistence     0.183       0.690       0.738    2.074           0.648  missed         no                       80% coverage outside 75-85%
        sales          1       herd_engine     75     0.381              NaN  0.120    persistence    -0.016       0.734       0.844    2.326           0.537  missed         no                       80% coverage outside 75-85%
                       3       herd_engine     73     0.389              NaN  0.231    persistence     0.072       0.717       0.833    2.220           0.422  missed         no                       80% coverage outside 75-85%
                       6       herd_engine     71     0.368              NaN  0.320    persistence     0.110       0.722       0.852    1.907           0.289  missed         no                       80% coverage outside 75-85%
                       12      herd_engine     65     0.264              NaN  0.135    persistence     0.216       0.595       0.762    1.766           0.505  missed         no                       80% coverage outside 75-85%
weekly  herd_milk      1       milk_baseline  333     0.972            0.930 -0.103            ets     0.006       0.739       0.823    0.121             NaN     met         no
                       4       milk_baseline  330     0.948            0.900  0.127    persistence     0.026       0.739       0.839    0.230             NaN     met         no
                       13      milk_baseline  323     0.884            0.870  0.124    persistence     0.085       0.712       0.830    0.439             NaN     met         no
rows met (target and calibrated): 5 of 42; not interpretable: 0

=== other series and horizons (no target): accuracy and skill ===
                                     accuracy                                             skill
horizon                                    1      3      4      6      8      12     13      1      3      4      6      8      12     13
block       grain   series
development monthly ais                 0.786  0.772    NaN  0.741    NaN  0.730    NaN  -1.141 -0.260    NaN  0.013    NaN -0.162    NaN
                    births              0.858  0.937    NaN  0.860    NaN  0.766    NaN   0.373  0.837    NaN  0.679    NaN  0.348    NaN
                    calves              0.959  0.890    NaN  0.867    NaN  0.890    NaN   0.027  0.143    NaN  0.080    NaN  0.417    NaN
                    calvings_heifer     0.886  0.879    NaN  0.289    NaN  0.357    NaN   0.693  0.839    NaN  0.273    NaN  0.247    NaN
                    dry_open            0.414  0.314    NaN  0.284    NaN  0.276    NaN  -5.507 -1.827    NaN -0.765    NaN -0.305    NaN
                    dry_pregnant        0.870  0.817    NaN  0.796    NaN  0.894    NaN  -1.363 -0.327    NaN -0.077    NaN  0.547    NaN
                    external_entries    0.031  0.027    NaN  0.005    NaN -0.065    NaN   0.279  0.313    NaN  0.344    NaN  0.353    NaN
                    heifers_open        0.868  0.819    NaN  0.766    NaN  0.833    NaN  -3.116 -0.469    NaN -0.081    NaN  0.311    NaN
                    heifers_pregnant    0.771  0.707    NaN  0.611    NaN  0.742    NaN  -3.404 -0.294    NaN  0.065    NaN  0.453    NaN
            weekly  ais                 0.772    NaN  0.766    NaN  0.759    NaN  0.752  -0.789    NaN -0.613    NaN -0.350    NaN -0.158
                    births              0.762    NaN  0.826    NaN  0.844    NaN  0.852  -0.026    NaN  0.459    NaN  0.595    NaN  0.674
                    calves              0.983    NaN  0.936    NaN  0.904    NaN  0.882  -0.086    NaN -0.036    NaN  0.053    NaN  0.109
                    calvings            0.764    NaN  0.827    NaN  0.846    NaN  0.852  -0.031    NaN  0.457    NaN  0.595    NaN  0.672
                    culls               0.097    NaN  0.084    NaN  0.086    NaN  0.087   0.166    NaN  0.147    NaN  0.268    NaN  0.251
                    deaths              0.647    NaN  0.642    NaN  0.628    NaN  0.615   0.106    NaN  0.154    NaN  0.249    NaN  0.228
                    dry_offs            0.062    NaN  0.066    NaN  0.055    NaN  0.044   0.302    NaN  0.201    NaN  0.181    NaN  0.221
                    dry_open            0.432    NaN  0.388    NaN  0.343    NaN  0.307 -13.248    NaN -3.879    NaN -2.381    NaN -1.611
                    dry_pregnant        0.883    NaN  0.858    NaN  0.832    NaN  0.813  -3.163    NaN -0.790    NaN -0.458    NaN -0.249
                    external_entries   -0.257    NaN -0.254    NaN -0.257    NaN -0.264   0.290    NaN  0.267    NaN  0.251    NaN  0.290
                    heifers_open        0.879    NaN  0.868    NaN  0.846    NaN  0.818 -12.275    NaN -1.903    NaN -0.794    NaN -0.404
                    heifers_pregnant    0.770    NaN  0.760    NaN  0.730    NaN  0.685 -14.574    NaN -1.887    NaN -0.645    NaN -0.206
                    herd_milk             NaN    NaN    NaN    NaN  0.917    NaN    NaN     NaN    NaN    NaN    NaN  0.136    NaN    NaN
                    milking             0.989    NaN  0.970    NaN  0.958    NaN  0.948   0.047    NaN  0.141    NaN  0.196    NaN  0.259
                    n_herd              0.997    NaN  0.988    NaN  0.981    NaN  0.974  -0.140    NaN -0.153    NaN -0.154    NaN -0.133
                    real_abortions      0.196    NaN  0.182    NaN  0.170    NaN  0.136   0.047    NaN  0.133    NaN  0.087    NaN  0.134
                    sales               0.099    NaN  0.096    NaN  0.090    NaN  0.086   0.055    NaN  0.088    NaN  0.204    NaN  0.165

=== accuracy by record-quality band (targets use normal + degraded); n in brackets ===
band                                     degraded         gap       normal
block       grain   series    horizon
development daily   herd_milk 1        0.854 (25)              0.972 (323)
                              7        0.869 (22)              0.963 (326)
                              14       0.834 (22)              0.956 (325)
            monthly calvings  1         0.829 (2)   0.835 (9)   0.861 (73)
                              3         0.936 (2)   0.925 (9)   0.935 (71)
                              6         0.946 (2)   0.814 (8)   0.860 (69)
                              12        0.509 (2)   0.848 (8)   0.771 (63)
                    herd_milk 1         0.782 (2)               0.966 (66)
                              3         0.705 (2)               0.901 (64)
                              6         0.695 (2)               0.839 (62)
                              12        0.648 (2)               0.838 (56)
                    milking   1         0.966 (2)   0.976 (9)   0.979 (73)
                              3         0.897 (2)   0.891 (9)   0.954 (71)
                              6         0.808 (2)   0.826 (8)   0.933 (69)
                              12        0.812 (2)   0.854 (8)   0.935 (63)
                    n_herd    1         0.997 (2)   0.991 (9)   0.993 (73)
                              3         0.974 (2)   0.976 (9)   0.976 (71)
                              6         0.916 (2)   0.938 (8)   0.964 (69)
                              12        0.969 (2)   0.941 (8)   0.953 (63)
            weekly  calvings  1        0.782 (21)  0.759 (20)  0.763 (324)
                              4        0.805 (21)  0.770 (20)  0.828 (321)
                              8        0.857 (21)  0.783 (20)  0.845 (317)
                              13       0.884 (21)  0.778 (18)  0.851 (314)
                    herd_milk 1        0.895 (18)              0.973 (315)
                              4        0.777 (18)              0.950 (312)
                              8        0.694 (18)              0.920 (308)
                              13       0.702 (18)              0.886 (305)
                    milking   1        0.983 (21)  0.986 (20)  0.989 (324)
                              4        0.958 (21)  0.933 (20)  0.971 (321)
                              8        0.934 (21)  0.874 (20)  0.959 (317)
                              13       0.907 (21)  0.814 (18)  0.950 (314)
                    n_herd    1        0.997 (21)  0.996 (20)  0.997 (324)
                              4        0.994 (21)  0.981 (20)  0.988 (321)
                              8        0.989 (21)  0.969 (20)  0.980 (317)
                              13       0.976 (21)  0.964 (18)  0.973 (314)

=== accuracy by months from the latest break to the origin; n in brackets ===
since_break                            0-2 months  3-5 months 6-11 months before any break
block       grain   series    horizon
development daily   herd_milk 1        0.912 (21)  0.899 (13)  0.913 (21)      0.972 (293)
                              7        0.854 (22)  0.928 (13)  0.879 (21)      0.965 (292)
                              14       0.787 (22)  0.908 (13)  0.837 (21)      0.959 (291)
            monthly calvings  1         0.827 (8)   0.929 (3)   0.896 (5)       0.857 (68)
                              3         0.935 (6)   0.948 (3)   0.964 (5)       0.932 (68)
                              6         0.770 (6)   0.918 (3)   0.855 (2)       0.862 (68)
                              12        0.716 (5)                               0.777 (68)
                    herd_milk 1         0.867 (3)   0.983 (2)   0.830 (3)       0.967 (60)
                              3         0.379 (4)   0.796 (2)   0.705 (2)       0.909 (58)
                              6         0.448 (4)   0.695 (2)                   0.843 (58)
                              12        0.648 (2)                               0.838 (56)
                    milking   1         0.976 (8)   0.970 (3)   0.970 (5)       0.979 (68)
                              3         0.937 (6)   0.892 (3)   0.916 (5)       0.952 (68)
                              6         0.907 (6)   0.805 (3)   0.890 (2)       0.928 (68)
                              12        0.771 (5)                               0.934 (68)
                    n_herd    1         0.988 (8)   0.992 (3)   0.995 (5)       0.993 (68)
                              3         0.952 (6)   0.970 (3)   0.981 (5)       0.978 (68)
                              6         0.933 (6)   0.921 (3)   0.937 (2)       0.964 (68)
                              12        0.925 (5)                               0.954 (68)
            weekly  calvings  1        0.779 (34)  0.801 (13)  0.798 (22)      0.759 (296)
                              4        0.779 (31)  0.797 (13)  0.820 (22)      0.828 (296)
                              8        0.782 (27)  0.823 (13)  0.840 (22)      0.847 (296)
                              13       0.779 (26)  0.896 (13)  0.848 (18)      0.851 (296)
                    herd_milk 1        0.885 (19)  0.926 (12)  0.907 (19)      0.974 (283)
                              4        0.674 (19)  0.883 (13)  0.808 (18)      0.954 (280)
                              8        0.494 (20)  0.871 (13)  0.687 (17)      0.926 (276)
                              13       0.372 (25)  0.865 (12)  0.655 (13)      0.895 (273)
                    milking   1        0.987 (34)  0.983 (13)  0.982 (22)      0.989 (296)
                              4        0.953 (31)  0.960 (13)  0.955 (22)      0.970 (296)
                              8        0.939 (27)  0.922 (13)  0.932 (22)      0.958 (296)
                              13       0.934 (26)  0.884 (13)  0.905 (18)      0.947 (296)
                    n_herd    1        0.996 (34)  0.997 (13)  0.998 (22)      0.997 (296)
                              4        0.980 (31)  0.992 (13)  0.994 (22)      0.988 (296)
                              8        0.962 (27)  0.983 (13)  0.988 (22)      0.981 (296)
                              13       0.949 (26)  0.964 (13)  0.980 (18)      0.975 (296)

=== recovery targets (verified periods after a break) ===
      block    series  grain  horizon since_break  n  accuracy  target_accuracy target
development herd_milk weekly        4  0-2 months 19     0.674            0.900 missed

Full table: logs/pfoi/scorecard_development_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_xl.csv (gitignored)

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli scorecard --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --k anchor_first --block development --intervals aci

=== development block: targets (docs/targets.md), herd-level aggregates ===
                                                n  accuracy  target_accuracy  skill best_benchmark  bias_pct  coverage80  coverage90  width90  deviance_ratio  target calibrated                                           reasons
grain   series         horizon model
daily   herd_milk      1       milk_baseline  348     0.970            0.950 -0.372            ets     0.003       0.784       0.889    0.195             NaN  missed        yes                             skill below condition
                       7       milk_baseline  348     0.962            0.920 -0.069    persistence     0.009       0.778       0.886    0.237             NaN  missed        yes                             skill below condition
                       14      milk_baseline  347     0.954            0.900 -0.017    persistence     0.016       0.780       0.875    0.304             NaN     met        yes
monthly calvings       1       herd_engine     75     0.860            0.800  0.382    persistence     0.139       0.766       0.875    0.270             NaN     met        yes
                       3       herd_engine     73     0.935            0.800  0.798         sarima     0.027       0.783       0.850    0.278             NaN     met        yes
                       6       herd_engine     71     0.861            0.750  0.533         sarima     0.057       0.685       0.796    0.546             NaN     met         no
                       12      herd_engine     65     0.767            0.650  0.293         sarima     0.139       0.833       0.952    0.742             NaN     met         no
        culls          1       herd_engine     75     0.472              NaN  0.238    persistence    -0.086       0.754       0.860    5.030           0.537     met        yes
                       3       herd_engine     73     0.466              NaN  0.221    persistence    -0.095       0.755       0.849    3.255           0.505     met         no
                       6       herd_engine     71     0.441              NaN  0.268    persistence    -0.170       0.723       0.872    6.691           0.550  missed         no                       80% coverage outside 75-85%
                       12      herd_engine     65     0.400              NaN  0.185    persistence    -0.259       0.714       0.857    8.507           0.520  missed         no                       80% coverage outside 75-85%
        deaths         1       herd_engine     75     0.762              NaN -0.025    persistence    -0.013       0.734       0.859    1.210           1.023  missed         no  80% coverage outside 75-85%; deviance ratio >= 1
                       3       herd_engine     73     0.725              NaN  0.203    persistence     0.001       0.683       0.817    1.257           0.469  missed         no                       80% coverage outside 75-85%
                       6       herd_engine     71     0.670              NaN  0.249    persistence    -0.027       0.667       0.778    1.451           0.418  missed         no                       80% coverage outside 75-85%
                       12      herd_engine     65     0.586              NaN  0.115    persistence    -0.084       0.571       0.643    2.281           0.669  missed         no                       80% coverage outside 75-85%
        dry_offs       1       herd_engine     75     0.610            0.750  0.360    persistence    -0.025       0.797       0.844    2.056             NaN  missed         no                                    accuracy < 75%
                       3       herd_engine     73     0.593            0.700  0.344    persistence    -0.087       0.750       0.833    2.555             NaN  missed         no                                    accuracy < 70%
                       6       herd_engine     71     0.577            0.700  0.387    persistence    -0.115       0.778       0.833    2.859             NaN  missed         no                                    accuracy < 70%
                       12      herd_engine     65     0.578            0.650  0.416    persistence    -0.014       0.810       0.833    2.021             NaN  missed         no                                    accuracy < 65%
        herd_milk      1       milk_baseline   68     0.965            0.920  0.371    persistence     0.010       0.732       0.857    0.159             NaN     met         no
                       3       milk_baseline   66     0.900            0.900  0.229    persistence     0.069       0.692       0.808    0.367             NaN  missed         no       accuracy < 90%; |bias| > 3%; width90 > 0.30
                       6       milk_baseline   64     0.838            0.880  0.145    persistence     0.140       0.596       0.723    0.406             NaN  missed         no                       accuracy < 88%; |bias| > 3%
                       12      milk_baseline   58     0.837            0.850  0.396    persistence     0.102       0.371       0.514    0.524             NaN  missed         no                       accuracy < 85%; |bias| > 3%
        milking        1       herd_engine     75     0.979            0.970  0.139    persistence     0.005       0.766       0.875    0.093             NaN     met        yes
                       3       herd_engine     73     0.953            0.950  0.292    persistence     0.021       0.733       0.817    0.208             NaN     met         no
                       6       herd_engine     71     0.931            0.920  0.318    persistence     0.048       0.667       0.796    0.186             NaN     met         no
                       12      herd_engine     65     0.932            0.880  0.545    persistence    -0.012       0.667       0.762    0.257             NaN     met         no
        n_herd         1       herd_engine     75     0.993            0.980 -0.104    persistence     0.005       0.781       0.859    0.034             NaN     met        yes
                       3       herd_engine     73     0.976            0.960 -0.140    persistence     0.012       0.767       0.850    0.095             NaN     met        yes
                       6       herd_engine     71     0.963            0.940 -0.053    persistence     0.020       0.722       0.815    0.130             NaN  missed         no                             skill below condition
                       12      herd_engine     65     0.953            0.900  0.176         sarima     0.027       0.690       0.786    0.161             NaN     met         no
        real_abortions 1       herd_engine     75     0.424              NaN -0.037    persistence     0.033       0.778       0.873    2.505           0.881     met        yes
                       3       herd_engine     73     0.369              NaN -0.021    persistence     0.042       0.729       0.881    3.035           0.916  missed         no                       80% coverage outside 75-85%
                       6       herd_engine     71     0.308              NaN  0.175    persistence     0.071       0.717       0.868    3.594           0.634  missed         no                       80% coverage outside 75-85%
                       12      herd_engine     65     0.228              NaN  0.048    persistence     0.183       0.714       0.833    3.045           0.648  missed         no                       80% coverage outside 75-85%
        sales          1       herd_engine     75     0.381              NaN  0.120    persistence    -0.016       0.781       0.891    2.643           0.537     met        yes
                       3       herd_engine     73     0.389              NaN  0.231    persistence     0.072       0.767       0.850    2.592           0.422     met        yes
                       6       herd_engine     71     0.368              NaN  0.320    persistence     0.110       0.759       0.833    2.588           0.289     met         no
                       12      herd_engine     65     0.264              NaN  0.135    persistence     0.216       0.667       0.786    2.454           0.505  missed         no                       80% coverage outside 75-85%
weekly  herd_milk      1       milk_baseline  333     0.972            0.930 -0.103            ets     0.006       0.777       0.883    0.169             NaN     met        yes
                       4       milk_baseline  330     0.948            0.900  0.127    persistence     0.026       0.771       0.886    0.297             NaN     met        yes
                       13      milk_baseline  323     0.884            0.870  0.124    persistence     0.085       0.705       0.786    0.437             NaN     met         no
rows met (target and calibrated): 14 of 42; not interpretable: 0

=== other series and horizons (no target): accuracy and skill ===
                                     accuracy                                             skill
horizon                                    1      3      4      6      8      12     13      1      3      4      6      8      12     13
block       grain   series
development monthly ais                 0.786  0.772    NaN  0.741    NaN  0.730    NaN  -1.141 -0.260    NaN  0.013    NaN -0.162    NaN
                    births              0.858  0.937    NaN  0.860    NaN  0.766    NaN   0.373  0.837    NaN  0.679    NaN  0.348    NaN
                    calves              0.959  0.890    NaN  0.867    NaN  0.890    NaN   0.027  0.143    NaN  0.080    NaN  0.417    NaN
                    calvings_heifer     0.886  0.879    NaN  0.289    NaN  0.357    NaN   0.693  0.839    NaN  0.273    NaN  0.247    NaN
                    dry_open            0.414  0.314    NaN  0.284    NaN  0.276    NaN  -5.507 -1.827    NaN -0.765    NaN -0.305    NaN
                    dry_pregnant        0.870  0.817    NaN  0.796    NaN  0.894    NaN  -1.363 -0.327    NaN -0.077    NaN  0.547    NaN
                    external_entries    0.031  0.027    NaN  0.005    NaN -0.065    NaN   0.279  0.313    NaN  0.344    NaN  0.353    NaN
                    heifers_open        0.868  0.819    NaN  0.766    NaN  0.833    NaN  -3.116 -0.469    NaN -0.081    NaN  0.311    NaN
                    heifers_pregnant    0.771  0.707    NaN  0.611    NaN  0.742    NaN  -3.404 -0.294    NaN  0.065    NaN  0.453    NaN
            weekly  ais                 0.772    NaN  0.766    NaN  0.759    NaN  0.752  -0.789    NaN -0.613    NaN -0.350    NaN -0.158
                    births              0.762    NaN  0.826    NaN  0.844    NaN  0.852  -0.026    NaN  0.459    NaN  0.595    NaN  0.674
                    calves              0.983    NaN  0.936    NaN  0.904    NaN  0.882  -0.086    NaN -0.036    NaN  0.053    NaN  0.109
                    calvings            0.764    NaN  0.827    NaN  0.846    NaN  0.852  -0.031    NaN  0.457    NaN  0.595    NaN  0.672
                    culls               0.097    NaN  0.084    NaN  0.086    NaN  0.087   0.166    NaN  0.147    NaN  0.268    NaN  0.251
                    deaths              0.647    NaN  0.642    NaN  0.628    NaN  0.615   0.106    NaN  0.154    NaN  0.249    NaN  0.228
                    dry_offs            0.062    NaN  0.066    NaN  0.055    NaN  0.044   0.302    NaN  0.201    NaN  0.181    NaN  0.221
                    dry_open            0.432    NaN  0.388    NaN  0.343    NaN  0.307 -13.248    NaN -3.879    NaN -2.381    NaN -1.611
                    dry_pregnant        0.883    NaN  0.858    NaN  0.832    NaN  0.813  -3.163    NaN -0.790    NaN -0.458    NaN -0.249
                    external_entries   -0.257    NaN -0.254    NaN -0.257    NaN -0.264   0.290    NaN  0.267    NaN  0.251    NaN  0.290
                    heifers_open        0.879    NaN  0.868    NaN  0.846    NaN  0.818 -12.275    NaN -1.903    NaN -0.794    NaN -0.404
                    heifers_pregnant    0.770    NaN  0.760    NaN  0.730    NaN  0.685 -14.574    NaN -1.887    NaN -0.645    NaN -0.206
                    herd_milk             NaN    NaN    NaN    NaN  0.917    NaN    NaN     NaN    NaN    NaN    NaN  0.136    NaN    NaN
                    milking             0.989    NaN  0.970    NaN  0.958    NaN  0.948   0.047    NaN  0.141    NaN  0.196    NaN  0.259
                    n_herd              0.997    NaN  0.988    NaN  0.981    NaN  0.974  -0.140    NaN -0.153    NaN -0.154    NaN -0.133
                    real_abortions      0.196    NaN  0.182    NaN  0.170    NaN  0.136   0.047    NaN  0.133    NaN  0.087    NaN  0.134
                    sales               0.099    NaN  0.096    NaN  0.090    NaN  0.086   0.055    NaN  0.088    NaN  0.204    NaN  0.165

=== accuracy by record-quality band (targets use normal + degraded); n in brackets ===
band                                     degraded         gap       normal
block       grain   series    horizon
development daily   herd_milk 1        0.854 (25)              0.972 (323)
                              7        0.869 (22)              0.963 (326)
                              14       0.834 (22)              0.956 (325)
            monthly calvings  1         0.829 (2)   0.835 (9)   0.861 (73)
                              3         0.936 (2)   0.925 (9)   0.935 (71)
                              6         0.946 (2)   0.814 (8)   0.860 (69)
                              12        0.509 (2)   0.848 (8)   0.771 (63)
                    herd_milk 1         0.782 (2)               0.966 (66)
                              3         0.705 (2)               0.901 (64)
                              6         0.695 (2)               0.839 (62)
                              12        0.648 (2)               0.838 (56)
                    milking   1         0.966 (2)   0.976 (9)   0.979 (73)
                              3         0.897 (2)   0.891 (9)   0.954 (71)
                              6         0.808 (2)   0.826 (8)   0.933 (69)
                              12        0.812 (2)   0.854 (8)   0.935 (63)
                    n_herd    1         0.997 (2)   0.991 (9)   0.993 (73)
                              3         0.974 (2)   0.976 (9)   0.976 (71)
                              6         0.916 (2)   0.938 (8)   0.964 (69)
                              12        0.969 (2)   0.941 (8)   0.953 (63)
            weekly  calvings  1        0.782 (21)  0.759 (20)  0.763 (324)
                              4        0.805 (21)  0.770 (20)  0.828 (321)
                              8        0.857 (21)  0.783 (20)  0.845 (317)
                              13       0.884 (21)  0.778 (18)  0.851 (314)
                    herd_milk 1        0.895 (18)              0.973 (315)
                              4        0.777 (18)              0.950 (312)
                              8        0.694 (18)              0.920 (308)
                              13       0.702 (18)              0.886 (305)
                    milking   1        0.983 (21)  0.986 (20)  0.989 (324)
                              4        0.958 (21)  0.933 (20)  0.971 (321)
                              8        0.934 (21)  0.874 (20)  0.959 (317)
                              13       0.907 (21)  0.814 (18)  0.950 (314)
                    n_herd    1        0.997 (21)  0.996 (20)  0.997 (324)
                              4        0.994 (21)  0.981 (20)  0.988 (321)
                              8        0.989 (21)  0.969 (20)  0.980 (317)
                              13       0.976 (21)  0.964 (18)  0.973 (314)

=== accuracy by months from the latest break to the origin; n in brackets ===
since_break                            0-2 months  3-5 months 6-11 months before any break
block       grain   series    horizon
development daily   herd_milk 1        0.912 (21)  0.899 (13)  0.913 (21)      0.972 (293)
                              7        0.854 (22)  0.928 (13)  0.879 (21)      0.965 (292)
                              14       0.787 (22)  0.908 (13)  0.837 (21)      0.959 (291)
            monthly calvings  1         0.827 (8)   0.929 (3)   0.896 (5)       0.857 (68)
                              3         0.935 (6)   0.948 (3)   0.964 (5)       0.932 (68)
                              6         0.770 (6)   0.918 (3)   0.855 (2)       0.862 (68)
                              12        0.716 (5)                               0.777 (68)
                    herd_milk 1         0.867 (3)   0.983 (2)   0.830 (3)       0.967 (60)
                              3         0.379 (4)   0.796 (2)   0.705 (2)       0.909 (58)
                              6         0.448 (4)   0.695 (2)                   0.843 (58)
                              12        0.648 (2)                               0.838 (56)
                    milking   1         0.976 (8)   0.970 (3)   0.970 (5)       0.979 (68)
                              3         0.937 (6)   0.892 (3)   0.916 (5)       0.952 (68)
                              6         0.907 (6)   0.805 (3)   0.890 (2)       0.928 (68)
                              12        0.771 (5)                               0.934 (68)
                    n_herd    1         0.988 (8)   0.992 (3)   0.995 (5)       0.993 (68)
                              3         0.952 (6)   0.970 (3)   0.981 (5)       0.978 (68)
                              6         0.933 (6)   0.921 (3)   0.937 (2)       0.964 (68)
                              12        0.925 (5)                               0.954 (68)
            weekly  calvings  1        0.779 (34)  0.801 (13)  0.798 (22)      0.759 (296)
                              4        0.779 (31)  0.797 (13)  0.820 (22)      0.828 (296)
                              8        0.782 (27)  0.823 (13)  0.840 (22)      0.847 (296)
                              13       0.779 (26)  0.896 (13)  0.848 (18)      0.851 (296)
                    herd_milk 1        0.885 (19)  0.926 (12)  0.907 (19)      0.974 (283)
                              4        0.674 (19)  0.883 (13)  0.808 (18)      0.954 (280)
                              8        0.494 (20)  0.871 (13)  0.687 (17)      0.926 (276)
                              13       0.372 (25)  0.865 (12)  0.655 (13)      0.895 (273)
                    milking   1        0.987 (34)  0.983 (13)  0.982 (22)      0.989 (296)
                              4        0.953 (31)  0.960 (13)  0.955 (22)      0.970 (296)
                              8        0.939 (27)  0.922 (13)  0.932 (22)      0.958 (296)
                              13       0.934 (26)  0.884 (13)  0.905 (18)      0.947 (296)
                    n_herd    1        0.996 (34)  0.997 (13)  0.998 (22)      0.997 (296)
                              4        0.980 (31)  0.992 (13)  0.994 (22)      0.988 (296)
                              8        0.962 (27)  0.983 (13)  0.988 (22)      0.981 (296)
                              13       0.949 (26)  0.964 (13)  0.980 (18)      0.975 (296)

=== recovery targets (verified periods after a break) ===
      block    series  grain  horizon since_break  n  accuracy  target_accuracy target
development herd_milk weekly        4  0-2 months 19     0.674            0.900 missed

Full table: logs/pfoi/scorecard_development_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_xl_aci.csv (gitignored)

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli scorecard --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --k anchor_first --block development --intervals aci --quality off

=== development block: targets (docs/targets.md), herd-level aggregates ===
                                                n  accuracy  target_accuracy  skill best_benchmark  bias_pct  coverage80  coverage90  width90  deviance_ratio  target calibrated                                      reasons
grain   series         horizon model
daily   herd_milk      1       milk_baseline  348     0.970            0.950 -0.372            ets     0.003       0.780       0.892    0.201             NaN  missed        yes                        skill below condition
                       7       milk_baseline  348     0.962            0.920 -0.069    persistence     0.009       0.778       0.886    0.259             NaN  missed        yes                        skill below condition
                       14      milk_baseline  347     0.954            0.900 -0.017    persistence     0.016       0.770       0.872    0.285             NaN     met        yes
monthly calvings       1       herd_engine     84     0.858            0.800  0.370    persistence     0.141       0.778       0.875    0.285             NaN     met        yes
                       3       herd_engine     82     0.934            0.800  0.793         sarima     0.026       0.779       0.868    0.265             NaN     met        yes
                       6       herd_engine     79     0.857            0.750  0.485         sarima     0.045       0.677       0.774    0.647             NaN     met         no
                       12      herd_engine     73     0.775            0.650  0.270         sarima     0.112       0.800       0.920    0.696             NaN     met        yes
        culls          1       herd_engine     84     0.459              NaN  0.240    persistence    -0.107       0.754       0.846    4.682           0.538     met         no
                       3       herd_engine     82     0.455              NaN  0.209    persistence    -0.117       0.754       0.852    2.820           0.499     met        yes
                       6       herd_engine     79     0.432              NaN  0.255    persistence    -0.179       0.727       0.855    5.580           0.578  missed         no                  80% coverage outside 75-85%
                       12      herd_engine     73     0.399              NaN  0.191    persistence    -0.270       0.721       0.837    7.443           0.535  missed         no                  80% coverage outside 75-85%
        deaths         1       herd_engine     84     0.765              NaN -0.033    persistence    -0.012       0.750       0.875    1.158           1.052  missed        yes                          deviance ratio >= 1
                       3       herd_engine     82     0.729              NaN  0.213    persistence     0.006       0.750       0.838    1.193           0.474     met         no
                       6       herd_engine     79     0.675              NaN  0.269    persistence    -0.029       0.677       0.790    1.304           0.414  missed         no                  80% coverage outside 75-85%
                       12      herd_engine     73     0.593              NaN  0.134    persistence    -0.085       0.620       0.680    2.084           0.661  missed         no                  80% coverage outside 75-85%
        dry_offs       1       herd_engine     84     0.616            0.750  0.350    persistence    -0.042       0.806       0.861    2.040             NaN  missed        yes                               accuracy < 75%
                       3       herd_engine     82     0.589            0.700  0.344    persistence    -0.113       0.765       0.853    2.272             NaN  missed        yes                               accuracy < 70%
                       6       herd_engine     79     0.563            0.700  0.353    persistence    -0.143       0.774       0.855    2.326             NaN  missed        yes                               accuracy < 70%
                       12      herd_engine     73     0.565            0.650  0.381    persistence    -0.050       0.740       0.820    1.861             NaN  missed         no                               accuracy < 65%
        herd_milk      1       milk_baseline   68     0.965            0.920  0.371    persistence     0.010       0.732       0.857    0.161             NaN     met         no
                       3       milk_baseline   66     0.900            0.900  0.229    persistence     0.069       0.673       0.769    0.341             NaN  missed         no  accuracy < 90%; |bias| > 3%; width90 > 0.30
                       6       milk_baseline   64     0.838            0.880  0.145    persistence     0.140       0.574       0.702    0.399             NaN  missed         no                  accuracy < 88%; |bias| > 3%
                       12      milk_baseline   58     0.837            0.850  0.396    persistence     0.102       0.343       0.486    0.491             NaN  missed         no                  accuracy < 85%; |bias| > 3%
        milking        1       herd_engine     84     0.979            0.970  0.152    persistence     0.006       0.764       0.875    0.090             NaN     met        yes
                       3       herd_engine     82     0.948            0.950  0.287    persistence     0.023       0.706       0.794    0.206             NaN  missed         no                               accuracy < 95%
                       6       herd_engine     79     0.923            0.920  0.249         sarima     0.047       0.613       0.710    0.182             NaN     met         no
                       12      herd_engine     73     0.926            0.880  0.495         sarima    -0.017       0.560       0.660    0.244             NaN     met         no
        n_herd         1       herd_engine     84     0.993            0.980 -0.084    persistence     0.005       0.764       0.875    0.033             NaN     met        yes
                       3       herd_engine     82     0.976            0.960 -0.120    persistence     0.012       0.735       0.838    0.098             NaN     met         no
                       6       herd_engine     79     0.960            0.940 -0.090    persistence     0.017       0.629       0.758    0.126             NaN  missed         no                        skill below condition
                       12      herd_engine     73     0.952            0.900  0.189         sarima     0.023       0.700       0.760    0.155             NaN     met         no
        real_abortions 1       herd_engine     84     0.414              NaN -0.113    persistence    -0.045       0.761       0.859    2.446           1.070  missed        yes                          deviance ratio >= 1
                       3       herd_engine     82     0.354              NaN -0.046    persistence    -0.046       0.716       0.851    2.665           0.959  missed         no                  80% coverage outside 75-85%
                       6       herd_engine     79     0.308              NaN  0.159    persistence    -0.035       0.721       0.852    2.970           0.675  missed         no                  80% coverage outside 75-85%
                       12      herd_engine     73     0.258              NaN  0.049    persistence     0.097       0.740       0.840    2.765           0.682  missed         no                  80% coverage outside 75-85%
        sales          1       herd_engine     84     0.409              NaN  0.129    persistence    -0.043       0.792       0.889    2.535           0.549     met        yes
                       3       herd_engine     82     0.417              NaN  0.204    persistence     0.050       0.765       0.882    2.259           0.439     met        yes
                       6       herd_engine     79     0.404              NaN  0.323    persistence     0.079       0.774       0.855    2.455           0.295     met        yes
                       12      herd_engine     73     0.321              NaN  0.176    persistence     0.150       0.740       0.860    2.233           0.499  missed         no                  80% coverage outside 75-85%
weekly  herd_milk      1       milk_baseline  333     0.972            0.930 -0.103            ets     0.006       0.767       0.873    0.172             NaN     met        yes
                       4       milk_baseline  330     0.948            0.900  0.127    persistence     0.026       0.750       0.861    0.271             NaN     met        yes
                       13      milk_baseline  323     0.884            0.870  0.124    persistence     0.085       0.705       0.801    0.426             NaN     met         no
rows met (target and calibrated): 14 of 42; not interpretable: 0

=== other series and horizons (no target): accuracy and skill ===
                                     accuracy                                             skill
horizon                                    1      3      4      6      8      12     13      1      3      4      6      8      12     13
block       grain   series
development monthly ais                 0.773  0.753    NaN  0.728    NaN  0.712    NaN  -1.288 -0.379    NaN -0.056    NaN -0.160    NaN
                    births              0.857  0.936    NaN  0.855    NaN  0.773    NaN   0.365  0.832    NaN  0.657    NaN  0.331    NaN
                    calves              0.959  0.892    NaN  0.871    NaN  0.888    NaN   0.021  0.103    NaN  0.093    NaN  0.381    NaN
                    calvings_heifer     0.881  0.863    NaN  0.284    NaN  0.351    NaN   0.682  0.812    NaN  0.242    NaN  0.233    NaN
                    dry_open            0.391  0.315    NaN  0.284    NaN  0.231    NaN  -5.808 -1.766    NaN -0.827    NaN -0.407    NaN
                    dry_pregnant        0.863  0.807    NaN  0.786    NaN  0.890    NaN  -1.471 -0.325    NaN -0.082    NaN  0.544    NaN
                    external_entries    0.011  0.011    NaN  0.005    NaN -0.075    NaN   0.306  0.358    NaN  0.330    NaN  0.303    NaN
                    heifers_open        0.883  0.839    NaN  0.792    NaN  0.834    NaN  -2.971 -0.419    NaN -0.023    NaN  0.284    NaN
                    heifers_pregnant    0.772  0.695    NaN  0.597    NaN  0.702    NaN  -3.215 -0.265    NaN  0.103    NaN  0.409    NaN
            weekly  ais                 0.764    NaN  0.755    NaN  0.746    NaN  0.741  -0.808    NaN -0.654    NaN -0.410    NaN -0.214
                    births              0.761    NaN  0.823    NaN  0.842    NaN  0.849  -0.027    NaN  0.442    NaN  0.585    NaN  0.661
                    calves              0.983    NaN  0.936    NaN  0.903    NaN  0.883  -0.102    NaN -0.060    NaN  0.029    NaN  0.096
                    calvings            0.763    NaN  0.824    NaN  0.843    NaN  0.849  -0.031    NaN  0.440    NaN  0.584    NaN  0.659
                    culls               0.107    NaN  0.094    NaN  0.097    NaN  0.098   0.148    NaN  0.161    NaN  0.264    NaN  0.243
                    deaths              0.653    NaN  0.650    NaN  0.637    NaN  0.625   0.124    NaN  0.164    NaN  0.251    NaN  0.244
                    dry_offs            0.075    NaN  0.076    NaN  0.064    NaN  0.047   0.307    NaN  0.208    NaN  0.193    NaN  0.232
                    dry_open            0.422    NaN  0.379    NaN  0.339    NaN  0.312 -13.702    NaN -3.879    NaN -2.348    NaN -1.575
                    dry_pregnant        0.879    NaN  0.851    NaN  0.821    NaN  0.799  -3.312    NaN -0.860    NaN -0.513    NaN -0.344
                    external_entries   -0.274    NaN -0.272    NaN -0.274    NaN -0.276   0.279    NaN  0.303    NaN  0.279    NaN  0.320
                    heifers_open        0.887    NaN  0.875    NaN  0.853    NaN  0.828 -11.785    NaN -1.808    NaN -0.751    NaN -0.354
                    heifers_pregnant    0.773    NaN  0.760    NaN  0.726    NaN  0.677 -14.004    NaN -1.777    NaN -0.592    NaN -0.175
                    herd_milk             NaN    NaN    NaN    NaN  0.917    NaN    NaN     NaN    NaN    NaN    NaN  0.136    NaN    NaN
                    milking             0.988    NaN  0.969    NaN  0.955    NaN  0.943   0.050    NaN  0.133    NaN  0.186    NaN  0.227
                    n_herd              0.997    NaN  0.988    NaN  0.980    NaN  0.973  -0.137    NaN -0.146    NaN -0.142    NaN -0.112
                    real_abortions      0.206    NaN  0.190    NaN  0.177    NaN  0.141   0.047    NaN  0.132    NaN  0.083    NaN  0.121
                    sales               0.111    NaN  0.103    NaN  0.099    NaN  0.094   0.087    NaN  0.076    NaN  0.192    NaN  0.174

=== accuracy by months from the latest break to the origin; n in brackets ===
since_break                            0-2 months  3-5 months 6-11 months before any break
block       grain   series    horizon
development daily   herd_milk 1        0.912 (21)  0.899 (13)  0.913 (21)      0.972 (293)
                              7        0.854 (22)  0.928 (13)  0.879 (21)      0.965 (292)
                              14       0.787 (22)  0.908 (13)  0.837 (21)      0.959 (291)
            monthly calvings  1         0.827 (8)   0.929 (3)   0.896 (5)       0.857 (68)
                              3         0.935 (6)   0.948 (3)   0.964 (5)       0.932 (68)
                              6         0.770 (6)   0.918 (3)   0.855 (2)       0.862 (68)
                              12        0.716 (5)                               0.777 (68)
                    herd_milk 1         0.867 (3)   0.983 (2)   0.830 (3)       0.967 (60)
                              3         0.379 (4)   0.796 (2)   0.705 (2)       0.909 (58)
                              6         0.448 (4)   0.695 (2)                   0.843 (58)
                              12        0.648 (2)                               0.838 (56)
                    milking   1         0.976 (8)   0.970 (3)   0.970 (5)       0.979 (68)
                              3         0.937 (6)   0.892 (3)   0.916 (5)       0.952 (68)
                              6         0.907 (6)   0.805 (3)   0.890 (2)       0.928 (68)
                              12        0.771 (5)                               0.934 (68)
                    n_herd    1         0.988 (8)   0.992 (3)   0.995 (5)       0.993 (68)
                              3         0.952 (6)   0.970 (3)   0.981 (5)       0.978 (68)
                              6         0.933 (6)   0.921 (3)   0.937 (2)       0.964 (68)
                              12        0.925 (5)                               0.954 (68)
            weekly  calvings  1        0.779 (34)  0.801 (13)  0.798 (22)      0.759 (296)
                              4        0.779 (31)  0.797 (13)  0.820 (22)      0.828 (296)
                              8        0.782 (27)  0.823 (13)  0.840 (22)      0.847 (296)
                              13       0.779 (26)  0.896 (13)  0.848 (18)      0.851 (296)
                    herd_milk 1        0.885 (19)  0.926 (12)  0.907 (19)      0.974 (283)
                              4        0.674 (19)  0.883 (13)  0.808 (18)      0.954 (280)
                              8        0.494 (20)  0.871 (13)  0.687 (17)      0.926 (276)
                              13       0.372 (25)  0.865 (12)  0.655 (13)      0.895 (273)
                    milking   1        0.987 (34)  0.983 (13)  0.982 (22)      0.989 (296)
                              4        0.953 (31)  0.960 (13)  0.955 (22)      0.970 (296)
                              8        0.939 (27)  0.922 (13)  0.932 (22)      0.958 (296)
                              13       0.934 (26)  0.884 (13)  0.905 (18)      0.947 (296)
                    n_herd    1        0.996 (34)  0.997 (13)  0.998 (22)      0.997 (296)
                              4        0.980 (31)  0.992 (13)  0.994 (22)      0.988 (296)
                              8        0.962 (27)  0.983 (13)  0.988 (22)      0.981 (296)
                              13       0.949 (26)  0.964 (13)  0.980 (18)      0.975 (296)

=== recovery targets (verified periods after a break) ===
      block    series  grain  horizon since_break  n  accuracy  target_accuracy target
development herd_milk weekly        4  0-2 months 19     0.674            0.900 missed

Full table: logs/pfoi/scorecard_development_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_xl_aci_quality_off.csv (gitignored)

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --grain both --block posthoc --jobs 12
POST-HOC: 2024-26 scores of a non-frozen version; report them as post-hoc.
  monthly: origin 1/32 (2024-02-01)
  monthly: origin 11/32 (2024-09-01)
  monthly: origin 21/32 (2025-09-01)
  monthly: origin 31/32 (2026-08-01)

Fallback notes (monthly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut         32
                                                             dry clock         32
                                                      exit calibration         32
                                                         milking clock         32
milking-cow exits by parity x DIM band x pregnancy (lactation records)         32
                                                recency-weighted rates         32
POST-HOC: 2024-26 scores of a non-frozen version; report them as post-hoc.
  weekly: origin 1/138 (2024-07-29)
  weekly: origin 11/138 (2024-03-11)
  weekly: origin 21/138 (2024-01-15)
  weekly: origin 31/138 (2024-05-27)
  weekly: origin 41/138 (2024-10-07)
  weekly: origin 51/138 (2024-12-16)
  weekly: origin 61/138 (2025-02-24)
  weekly: origin 71/138 (2025-05-05)
  weekly: origin 81/138 (2025-07-14)
  weekly: origin 91/138 (2025-09-22)
  weekly: origin 101/138 (2025-12-01)
  weekly: origin 111/138 (2026-02-09)
  weekly: origin 121/138 (2026-04-20)
  weekly: origin 131/138 (2026-06-29)

Fallback notes (weekly, number of origins affected):
                                                                  note  n_origins
                                                        conception cut        138
                                                             dry clock        138
                                                      exit calibration        138
                                                         milking clock        138
milking-cow exits by parity x DIM band x pregnancy (lactation records)        138
                                                recency-weighted rates        138

MAE by horizon (posthoc block, herd level):
model                              ets  herd_engine  herd_engine_corrected  persistence  sarima  n_origins
grain   series         horizon
monthly calvings       1         24.42        20.82                   8.64        13.12   16.48         31
                       3         25.02        10.46                  12.19        15.98   26.04         29
                       6         29.10        13.13                  15.91        21.72   31.22         26
                       12        28.14        20.27                  21.51        23.81   22.48         20
        milking        1         28.09        12.67                   9.84        13.18   29.54         31
                       3         52.79        42.52                  33.78        42.85   81.56         29
                       6         82.32        62.00                  64.56        81.10  152.10         26
                       12       173.50        82.14                 123.18       131.44  222.86         20
        n_herd         1         45.69        20.25                  22.90        19.20   58.32         31
                       3        118.93       100.12                 114.18        85.93  171.99         29
                       6        224.08       206.09                 225.15       159.87  327.02         26
                       12       356.33       443.79                 426.01       204.55  564.31         20
        real_abortions 1           NaN        10.12                  10.85         7.59     NaN         31
                       3           NaN        10.17                  10.41        10.74     NaN         29
                       6           NaN         9.92                   9.14         7.93     NaN         26
                       12          NaN        10.36                   8.12         9.25     NaN         20
weekly  calvings       1           NaN         8.89                   4.00         3.15     NaN        137
                       4           NaN         3.63                   2.56         4.03     NaN        134
                       8           NaN         3.26                   3.03         4.75     NaN        130
                       13          NaN         3.14                   3.52         4.90     NaN        125
        milking        1           NaN         6.85                   5.85         6.19     NaN        137
                       4           NaN        21.70                  16.98        21.51     NaN        134
                       8           NaN        35.37                  27.23        35.62     NaN        130
                       13          NaN        46.37                  35.98        49.37     NaN        125
        n_herd         1           NaN         6.72                   7.40         6.17     NaN        137
                       4           NaN        33.89                  39.62        30.40     NaN        134
                       8           NaN        71.32                  84.01        60.74     NaN        130
                       13          NaN       119.43                 138.77        96.77     NaN        125
        real_abortions 1           NaN         2.77                   2.97         2.98     NaN        137
                       4           NaN         2.76                   2.95         2.90     NaN        134
                       8           NaN         2.73                   2.87         3.18     NaN        130
                       13          NaN         2.67                   2.67         3.45     NaN        125

Full tables written to logs/pfoi/ (gitignored). Horizons: {'monthly': (1, 3, 6, 12), 'weekly': (1, 4, 8, 13), 'daily': (1, 7, 14)}

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --k anchor_first --grain both --block posthoc --jobs 12
POST-HOC: 2024-26 scores of a non-frozen version; report them as post-hoc.
  monthly: origin 1/32 (2024-01-01)
  monthly: origin 11/32 (2025-06-01)
  monthly: origin 21/32 (2025-02-01)
  monthly: origin 31/32 (2026-05-01)

Notes (monthly origins, number of origins):
                                           note  n_origins
                                          curve         26
                                              k         52
                                       k_window          8
                                    no_window_k          9
withheld (milk_withheld:no_trusted_recent_days)          6
POST-HOC: 2024-26 scores of a non-frozen version; report them as post-hoc.
  weekly: origin 1/138 (2024-05-06)
  weekly: origin 11/138 (2024-06-24)
  weekly: origin 21/138 (2024-02-26)
  weekly: origin 31/138 (2024-07-29)
  weekly: origin 41/138 (2024-11-18)
  weekly: origin 51/138 (2024-12-16)
  weekly: origin 61/138 (2025-04-28)
  weekly: origin 71/138 (2025-07-07)
  weekly: origin 81/138 (2025-08-04)
  weekly: origin 91/138 (2025-11-24)
  weekly: origin 101/138 (2025-11-10)
  weekly: origin 111/138 (2026-02-09)
  weekly: origin 121/138 (2026-03-30)
  weekly: origin 131/138 (2026-07-20)

Notes (weekly origins, number of origins):
                                           note  n_origins
                                          curve        116
                                              k        232
                                       k_window         37
                                    no_window_k         43
withheld (milk_withheld:no_trusted_recent_days)         22

Done. Run milk-report with the same options to see the H1 table. Files in logs/pfoi/.

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli milk-report --preset pfoi-1.1 --out logs/pfoi --exit-model lactation --k anchor_first --block posthoc

=== monthly (herd_fitted_p1_g0_kf, window 24) — litres per period ===
MAE:
model        ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        13008.0         9483.0                  13194.0      11997.0         21943.0
3            NaN        44359.0                  49044.0      18664.0         41522.0
6        23744.0        13326.0                  36214.0      19111.0         41522.0
MAE ratio vs persistence (< 1 = better):
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        1.08           0.79                     1.10          1.0            1.83
3         NaN           2.38                     2.63          1.0            2.22
6        1.24           0.70                     1.89          1.0            2.17
bias (forecast - actual):
model        ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1       -13008.0         2389.3                   3391.8      -4862.3        -19578.7
3            NaN        -1065.1                 -19431.4       -436.5        -41521.6
6       -23744.1       -13326.0                 -36213.7     -19110.8        -41521.6
MAPE %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        12.1            7.8                     10.9         10.0            17.2
3         NaN           34.5                     37.6         14.7            32.1
6        18.1           10.1                     27.8         14.9            32.1
90% interval coverage %:
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        100.0           60.0                     80.0        100.0            75.0
3          NaN           66.7                     66.7        100.0            50.0
6        100.0           66.7                     66.7        100.0            50.0
n periods scored:
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        2.0            5.0                      5.0          5.0             4.0
3        NaN            3.0                      3.0          3.0             2.0
6        2.0            3.0                      3.0          3.0             2.0

=== monthly: COMMON PERIODS (all models) — MAE ratio vs persistence ===
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive  n_periods
horizon
1       1.18           0.81                     1.11         1.00            0.21          2
6       1.38           0.99                     2.99         1.00            2.41          2

=== daily (herd_fitted_p1_g0_kf, window 24) — litres per period ===
MAE:
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        224.0          638.0                    688.0        656.0          1062.0
7        402.0          803.0                    875.0        777.0          1029.0
14       597.0          955.0                   1050.0        872.0          1052.0
MAE ratio vs persistence (< 1 = better):
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        0.34           0.97                     1.05          1.0            1.62
7        0.52           1.03                     1.13          1.0            1.32
14       0.68           1.10                     1.21          1.0            1.21
bias (forecast - actual):
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         90.3          -83.5                    -45.0       -120.0          -738.7
7        166.5         -135.3                   -110.6       -144.8          -814.0
14       344.3         -118.0                   -137.2       -102.3          -864.3
MAPE %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         7.1           14.3                     15.8         14.7            26.0
7        10.0           16.9                     19.0         16.0            23.9
14       15.5           20.7                     23.4         18.6            24.4
90% interval coverage %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        69.4           62.3                     57.4         59.0            70.4
7        73.5           56.1                     54.4         56.1            69.2
14       75.9           55.4                     50.0         60.7            64.0
n periods scored:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        36.0           61.0                     61.0         61.0            27.0
7        34.0           57.0                     57.0         57.0            26.0
14       29.0           56.0                     56.0         56.0            25.0

=== weekly (herd_fitted_p1_g0_kf, window 24) — litres per period ===
MAE:
model       ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         889.0         2195.0                   2413.0       2251.0          6599.0
4           NaN         6075.0                   7394.0       4327.0          7376.0
8        5308.0         7826.0                   8230.0       5822.0          9090.0
13       5751.0         9007.0                  12118.0       4939.0         10568.0
MAE ratio vs persistence (< 1 = better):
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        0.39           0.97                     1.07          1.0            2.93
4         NaN           1.40                     1.71          1.0            1.70
8        0.91           1.34                     1.41          1.0            1.56
13       1.16           1.82                     2.45          1.0            2.14
bias (forecast - actual):
model       ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         657.3          224.6                   -592.5        556.3         -5862.4
4           NaN           43.9                  -2203.9       1053.6         -7018.7
8       -3429.7         1339.3                  -2816.8       1884.4         -9090.5
13      -5671.3          102.7                  -1910.1       1261.4        -10568.1
MAPE %:
model     ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1         3.1            7.6                      8.4          8.1            21.6
4         NaN           21.1                     26.0         15.5            23.9
8        18.8           27.1                     28.3         20.5            29.3
13       18.5           32.4                     43.0         17.3            33.8
90% interval coverage %:
model      ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        100.0           81.6                     78.9         76.3            68.2
4          NaN           62.9                     62.9         85.7            63.2
8         66.7           63.3                     83.3         90.0            46.7
13        83.3           64.3                     89.3         92.9            33.3
n periods scored:
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive
horizon
1        6.0           38.0                     38.0         38.0            22.0
4        NaN           35.0                     35.0         35.0            19.0
8        3.0           30.0                     30.0         30.0            15.0
13       6.0           28.0                     28.0         28.0            12.0

=== daily: COMMON PERIODS (all models) — MAE ratio vs persistence ===
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive  n_periods
horizon
1       0.95           1.23                     1.35         1.00            4.07         22
7       1.04           1.21                     1.49         1.00            3.98         20
14      1.24           1.21                     1.69         1.00            3.13         17

=== weekly: COMMON PERIODS (all models) — MAE ratio vs persistence ===
model    ets  milk_baseline  milk_baseline_corrected  persistence  seasonal_naive  n_periods
horizon
1       0.56           0.66                     1.21         1.00            2.84          3
13      0.30           0.85                     2.14         1.00            2.33          3

/opt/anaconda3/bin/python -m components.predictive_farm_intelligence.pfoi.cli break-reset --herd-tag w24_ck_kn_rk_lag90_hl6_xl --milk-tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_xl --block posthoc --out logs/pfoi
Breaks detected (herd size +/-10 % over 90 days, or milk back after 28+ days): 6; years: 2015, 2016, 2022, 2023, 2024, 2025

=== correction layer with and without the break reset (POST-TEST DEVELOPMENT (2024-26 already inspected)) ===
   series   grain  horizon                     model  n  accuracy  n_after  after_break
herd_milk  weekly        4    milk_baseline_adaptive 35     0.587       16        0.308
herd_milk  weekly        4 milk_baseline_adaptive_br 35     0.773       16        0.685
herd_milk monthly        3    milk_baseline_adaptive  3     0.611        2        0.622
herd_milk monthly        3 milk_baseline_adaptive_br  3     0.650        2        0.654
  milking monthly        3     herd_engine_corrected 29     0.918       12        0.939
  milking monthly        3  herd_engine_corrected_br 29     0.883       12        0.924
  milking monthly        6     herd_engine_corrected 26     0.836       11        0.848
  milking monthly        6  herd_engine_corrected_br 26     0.809       11        0.900
   n_herd monthly        6     herd_engine_corrected 26     0.867       11        0.909
   n_herd monthly        6  herd_engine_corrected_br 26     0.879       11        0.934
   n_herd monthly       12     herd_engine_corrected 20     0.748        6        0.707
   n_herd monthly       12  herd_engine_corrected_br 20     0.738        6        0.694
 calvings monthly        3     herd_engine_corrected 29     0.686       12        0.667
 calvings monthly        3  herd_engine_corrected_br 29     0.663       12        0.630

Intervals remain unconfirmed until matched coverage AND width are reviewed. No outlook was published. Posthoc scores are post-test development.
```

</details>


### T0 protocol fixed before revised tables (2026-10-21)

Reporting correction only; no model selection or fitted boundary. Keep T0 if synthetic
checks separate origin-source × target-source cells, split shipment at Aug 2020 by
issuance date, retain unmatched A/B counts, and preserve frozen hashes. Cross-break
forecasts never enter the same-source DelPro average. Existing M9/M10 keep rules
remain unchanged; re-tabulation does not authorize adoption.

Old error files lack origin_source. Use the documented Aug 2022 source timeline as an
explicitly labelled fallback, not k_source: the latter can be borrowed in M9. Calendar
cells are descriptive, not confirmed change points. Validate boundary support with
breaks.detect_breaks on strictly pre-origin daily aggregates; real-data check pending
user run. No future values may alter that audit.

Development selection uses origins 2017–2023 and no outcomes from 2024 onward. Later
origins/targets are descriptive. T2 remains daily-resolution, with per-regime 80:20
chronological splits, horizon embargo and pooled training strictly before each test
window; n and autocorrelation-adjusted effective n are required at T2, not inferred
from monthly error counts.

### T0 boundary audit supplied by user; T1 protocol (2026-10-21)

User-run pre-origin detector audit: Aug/Sep 2020 have 2 breaks and latest ages
1549/1580 days (1827/1858 input days); Aug/Sep 2022 have 2 breaks and ages
2279/2310 (2557/2588 days). No recent detector support for either boundary.
Keep those dates as descriptive recording/data-state labels only. Post-hoc
Mar/May/Jun 2024: 4/5/5 breaks, ages 396/4/35 days, n_days 3135/3196/3227.
The late-April 2024 detector hit is descriptive, not a tuning signal.

T1 keep rule before implementation/replay: keep an OFF-by-default persistence-only
live option if synthetic tests prove finished-error-only weights, pre-origin
persistence, unchanged monthly/herd forecasts, page/table agreement, honest blend
labels/audit and unchanged frozen hashes. No adoption or accuracy claim follows
from implementation. User decides adoption after replay; 2024–2026 stays descriptive.
Use M10's exact persistence convention (last available complete calendar week with
at least 5/7 scoreable days; mean per day, times seven for weekly totals), report its
date and age. Missing reference keeps adaptive output; insufficient history gives
weight one. Use the next longer scored horizon for unscored horizons (same mapping
as OutputLayer), and the blend's own historical errors for intervals. Reconciled
1.1.1 is unsupported for this option, because its path bypasses OutputLayer.

T1 implementation result: off-by-default `--persistence-blend on` in build-outlook,
version `pfoi-1.2.0-dev-persistence`; persisted page audit and own-error intervals.
67 distinct selected synthetic tests passed (guarded regression: 26 passed, one
SQLite integration test deselected). Both frozen hashes unchanged. The first
regression selection accidentally ran that in-memory SQLite test before being
stopped; subsequent runs block SQLAlchemy/SQLite connections. No farm DB accessed.
See `t1_live_persistence.md` for files, checks, limitations and four user-run replay
commands. Adoption and real-data replay remain pending; T2 has not started.

### T1 rejected; next direction (user decision, 2026-10-21)

The user rejected combining the forecast with persistence (M10 and T1). `--persistence-blend` stays
off, the replay commands in `t1_live_persistence.md` are no longer needed, and no PP1 output uses
the blend. Code and tests are kept (off by default); frozen hashes are unchanged.

Next direction requested by the user: a deep-learning or memory-based milk model, trained and
evaluated under an explicit chronological train / validation / test split with a horizon embargo.
Split protocol and model choice to be agreed with the user before implementation.

### Neural milk model (2026-10-21; implemented, real-data run pending)

User-chosen split (`pfoi/neural.py`, `STAGES`): stage 1 shipment, train 2015-08 – 2017-06,
validation 2017-07 – 2017-12, test 2018-01 – 2019-12; stage 2 DelPro, train 2020-08 – 2022-06,
validation 2022-07 – 2022-12, test 2023-01 – data end, fine-tuned from stage 1 (`neural_transfer`)
and also trained from scratch (`neural_scratch`) so transfer is measured. Targets are masked at
each part's end (embargo); inputs use days before the origin only; the engine path is the latest
weekly run at or before the origin. Model: GRU over 56 days of log(litres / 28-day level) + herd
state (DIM, parity, dry-pregnant and heifer-pregnant per milking cow, recent calvings, season) +
the engine's 98-day path; output = correction added to the engine path; 5-seed ensemble. Scored
on Monday test origins (daily 1/7/14, weekly 1/4/8/13) against milk_baseline, persistence,
seasonal naive and ETS on identical periods. Stage-2 test from 2024 was viewed before: descriptive.
Not written to `c1_output`; writing is a later user decision. Tests: `test_neural.py` (synthetic).

### pfoi-1.2.1-dev: target and baseline (2026-10-22)

**Target (user, 2026-10-22):** 85 % of milk forecasts within ±10 % of the recorded value, at every
horizon including **week 13 and months 6–12**. Measured with `hit-rate` (`pfoi/hit_rate.py`) on
trusted record periods (quality band normal or degraded); unverified and gap periods are reported
separately, never dropped silently. The tolerance and the definition stay fixed.

**Baseline, pfoi-1.2.0-dev (`milk_baseline_adaptive`), development origins 2017–2023, trusted periods,
share within ±10 % (persistence in brackets, benchmark only):** day 1 / 7 / 14: 0.922 / 0.885 / 0.833
(0.945 / 0.888 / 0.830); week 1 / 4 / 8 / 13: 0.925 / 0.782 / 0.663 / 0.545 (0.943 / 0.752 / 0.604 /
0.440); month 1 / 3 / 6 / 12: 0.897 / 0.667 / 0.531 / 0.431 (0.794 / 0.500 / 0.250 / 0.207). WAPE month
6 / 12: 13.3 % / 16.2 %. Target met in 7 of 22 cells. 2024–26 (engine without correction): trusted
n only 27 daily / 21 weekly / 3 monthly periods, 334 forecasts unverified or gap: descriptive only.

**Assessment:** month 6–12 and week 13 need the typical error cut about threefold (WAPE ≈ 4–5 %).
Reachability is unknown; `milk-error-split` (`pfoi/error_split.py`) measures it first: milk error =
cow-count part + yield-per-cow part, with the hit rate each would allow if exact (hindsight ceilings,
diagnostic only). The first 1.2.1-dev change is chosen from that split.

**Error split result (user run, 2026-10-22; development, trusted periods).** Yield per cow, not
the cow count, is 85–93 % of the squared milk error (mean absolute cow error 1–8 %, yield error
4–22 %). Within ±10 % now / if cows exact / if yield exact: week 4 0.782 / 0.745 / 0.991; week 13
0.545 / 0.551 / 0.808; month 3 0.667 / 0.576 / 0.864; month 6 0.531 / 0.594 / 0.719; month 12
0.431 / 0.379 / 0.707. Month-12 yield bias +14 %. So the user's 85 % target at months 6–12 and week
13 needs both parts improved (yield first); yield alone could reach it up to week 4 and month 3.
The chart-based guess that cow drift dominates is not supported on 2017–2023.

### pfoi-1.2.1-dev change 1: damped trend in the yield correction (2026-10-22): tested and dropped

Method in `docs/layer1_adaptive.md` (section "Damped trend"). **Keep rule, fixed before any
real run:** on development origins 2017–2023, trusted periods, share within ±10 %, keep
`milk_baseline_adaptive_trend` only if it rises at week 13 and months 3, 6 and 12, does not
fall at week 1 or month 1, and no forecast year is worse by more than 5 percentage points
(a year's share = mean over its horizons, each horizon weighted equally). Otherwise it is
recorded here as tested and dropped (code kept, off). Applied by
`hit-rate --keep-rule milk_baseline_adaptive milk_baseline_adaptive_trend`.
Synthetic warning: after a decline ends, the trend overshoots and the year-by-year choice
lags one year, so the per-year check may fail on 2022–2023.

**Result (user run, 2026-10-22; development 2017–2023, trusted periods): DROP.** Code kept, off.
- `adapt-trend`: with the trend off, the correction reproduces pfoi-1.2.0-dev `milk_baseline_adaptive`
  (2,611 of 2,611 rows, max relative difference 2.6e-15 = CSV rounding).
- Year-by-year choice: **off was chosen in every year 2018–2023** (2017: no earlier periods, off).
  Every trend setting (phi 0.8 / 0.9 / 0.95 × q_trend 0.01 / 0.05) missed ±10 % more often than off
  on the earlier periods of every fold; share outside ±10 %, off vs best trend (d0.8b0.01):
  2018 0.250 / 0.285, 2019 0.178 / 0.205, 2020 0.147 / 0.176, 2021 0.147 / 0.170,
  2022 0.160 / 0.171, 2023 0.207 / 0.217.
- So `milk_baseline_adaptive_trend` equals `milk_baseline_adaptive` on every forecast: within ±10 %
  week 13 / month 3 / 6 / 12 = 0.545 / 0.667 / 0.531 / 0.431, unchanged. Keep rule fails on all four
  "must rise" checks (change 0.000); the hold and per-year checks pass trivially.
- Hit rate by forecast year (`milk_baseline_adaptive`, mean share within ±10 % over horizons):
  2017 0.755, 2018 0.897, 2019 0.933, 2020 0.743, 2021 0.806, **2022 0.399, 2023 0.376**.
  Stable years 2018–2019 are close to the 85 % target at most horizons (2019: 1.000 up to week 4,
  week 13 0.885, month 3 1.000); misses concentrate in regime-change years: 2020 (source switch;
  month 12 0.100), 2021 (yield decline; month 6 0.100, month 12 0.000) and 2022–2023, where even
  day 1 drops to 0.744 / 0.660 (persistence 0.872 / 0.720), so the short horizons miss too.
- Error split unchanged (same forecasts): yield per cow by forecast year, month 12 +16.7 % (2020),
  +48.2 % (2021), +36.7 % (2022); week 13 +20.9 % (2022) then −21.2 % (2023).
- Reading: a damped slope learned from finished errors does not help, because the yield drift is
  only seen at long horizons 6–12 months after the fact, and the rebounds (2022→2023) reverse it;
  this matches the synthetic warning (overshoot after a drift ends). The PP1 finding stands on the
  diagnosis: accurate in stable years, misses come from regime changes, measured by the error split
  and now by hit rate per forecast year.

### Stability gate G1 (2026-10-22; implemented and tested, real-data run pending)

User decision: keep pfoi-1.2.0-dev for stable conditions; a gate decides at each forecast date
whether Farm X is unstable, and only then a specialist forecasts (persistence excluded; free,
locally run models only). G1 tests whether instability is recognisable at all before specialists
are built. Design, pre-registered go rule, the user's AUC target (about 0.80 within each grain x
horizon, especially week 13 and months 6 and 12) and synthetic limits: `stability_gate.md`.
Command: `cli gate-audit`. **Result (user run, 2026-10-22): GO by the pre-registered rule**
(logistic Brier skill 0.124, within-cell AUC 0.776, skill in 3 of 5 fold years). AUC 0.80 reached
at day 1–14 and week 1–4 (point estimates), not at week 13 (0.70) or months 6–12 (below 0.65).
The gate recognises unstable regimes (2022–2023), not timing within a year. Switching to existing
models does not help long horizons (hindsight ceiling month 12: 0.38). Detail: `stability_gate.md`.

### G2 specialists (2026-10-22; implemented and tested, real-data runs pending)

Track A (`specialist-a`): fast re-level S1 used only where the G1 gate says unstable, day 1 to month 3.
Track B (`specialist-b`): zero-shot Chronos-2 yield per cow x engine cows for week 13 and months 6–12,
all periods. Keep rules fixed before the runs: `stability_gate.md` (G2).
**Results (user runs, 2026-10-22): both DROPPED** by their rules (code kept, off). Track A: +0.010 mean
(rule +0.02); helps only where switched (2023 Track A mean 0.417 → 0.487). Track B: worse at week 13
(0.447 vs 0.598), month 6 (0.293 vs 0.552) and month 12 (0.214 vs 0.429); better only in 2022–2023
(n 29 and 18 long periods). The structural model remains the best long-horizon forecaster tested.
