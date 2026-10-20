# PFOI plan for PP1 (Fri 2026-10-23)

Written 2026-10-20. Assessment and plan only; nothing in it is implemented yet.
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

### Status

| # | Status | Date | Notes |
|---|---|---|---|
| M1 | implemented and tested; **not yet evaluated** | 2026-10-20 | `MilkConfig(k_mode="anchor_first")`, CLI `--k anchor_first`, file tag `_kf`. `MilkWithheld` with reason `milk_withheld:no_trusted_recent_days`; backtests count withheld origins in their notes. pfoi-1.0.0 and 1.1.0 hashes unchanged (tested). Tests: `tests/test_outage_recovery.py` (7). Outlook (`outlook.py`) not yet changed: waits for the pfoi-1.1.1 edits to be committed. Real-data check: RUN BATCH 1 |
| M2 | implemented and tested; **not yet evaluated** | 2026-10-20 | `pfoi/outage_sim.py` (own command, `cli.py` untouched). Scenarios: normal (0, 0) plus outage length 28 / 90 / 180 days × days of records back 0 / 3 / 7 / 14. Hidden days feed neither k, the early herd-fitted curve nor persistence; scoring uses recorded actuals only; nothing imputed. Prints forecast/withheld counts per scenario, outage cost (vs no outage and vs persistence, identical periods) and error spread by days since the last trusted day (input for M4). Limit printed with every run: only milk is hidden, herd records stay complete, so results are optimistic. Tests: `tests/test_outage_sim.py` (10). Real-data check: RUN BATCH 2 |

**RUN BATCH 1 (M1, user runs from the repository root; prints aggregates only):**

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --block posthoc --jobs 0
```

Send back: the "MAE by horizon" tables and the "Notes" tables (origins skipped, withheld
and their reasons) of both runs. The development run should match the existing pfoi-1.1
milk files on every origin both can build (same k by construction); the post-hoc run shows
how many 2024–26 origins become buildable (previously 15 of 32 monthly origins skipped).
Post-hoc numbers are post-test development.


**RUN BATCH 1 results (user, 2026-10-20; aggregates only).**

*M1 post-hoc replay 2024–26 (`--k anchor_first --block posthoc`), forecast dates built.
Post-test development: counts of buildable forecasts, not accuracy.*

| Origins | Total | Forecast built | of which: no 12-month k (recovered by M1) | of which: stale 12-month k (no recent trusted days) | Withheld (`no_trusted_recent_days`) |
|---|---|---|---|---|---|
| Monthly | 32 | 26 (was 17) | 9 | 8 | 6 |
| Weekly | 138 | 116 | 43 | 37 | 22 |

Reading: M1 makes 9 more monthly and 43 more weekly forecast dates buildable after the
outage, and withholds the rest with a stated reason. The 8 monthly / 37 weekly dates that
fall back to a 12-month k have **no trusted recent days**: those are the cases M3 (trust
gate) and M4 (staleness-widened intervals) must handle. Accuracy on 2024–26 is not yet
reported (needs `milk-report ... --block posthoc`).

*M1 post-hoc accuracy 2024–26 (`milk-report --preset pfoi-1.1 --k anchor_first --block
posthoc`). **Post-test development**, all origins M1 can build, MAE ratio vs persistence:*

| Grain | Horizons | milk_baseline | milk_baseline_corrected | n | 90 % coverage (baseline) |
|---|---|---|---|---|---|
| Daily | 1 / 7 / 14 | 0.97 / 1.03 / 1.09 | 1.05 / 1.13 / 1.21 | 61 / 57 / 56 | 62 / 56 / 55 % |
| Weekly | 1 / 4 / 8 / 13 | 0.97 / 1.40 / 1.35 / 1.81 | 1.07 / 1.71 / 1.42 / 2.48 | 38 / 35 / 30 / 28 | 82 / 63 / 63 / 61 % |
| Monthly | 1 / 3 / 6 | 0.79 / 2.40 / 0.62 | 1.10 / 2.71 / 1.95 | 5 / 3 / 3 | not interpretable |

Reading (post-test, not a confirmation):
* Daily and 1-week forecasts tie with persistence (0.97–1.09). Beyond 1 week the baseline
  loses clearly (1.35–1.81): after 2024 the herd engine drifts away from the recorded level.
* ETS is far better where it can run (daily 0.34 / 0.52 / 0.68, n 29–36), but needs an
  unbroken history, so it covers about half the periods. On common periods (n 17–22) the
  baseline is 1.20–1.23 against persistence.
* The 2-year mean bias correction makes 2024–26 worse at every grain and horizon: it
  carries errors learned before the outage across it. Evidence for a gap-aware correction.
  The pfoi-1.1.0 adaptive layer is not in these files (it is applied by `adapt`).
* 90 % ranges cover 55–63 %, far below 85–95 %. M4 is needed.
* These rows mix recovered origins with origins that were buildable before M1 (for those,
  forecasts are identical by construction). M1's own effect needs the split below.

*M1 post-hoc split by where the level came from (user, 2026-10-20). **Post-test
development.** MAE ratio vs persistence on the same periods (n):*

| Level from | Daily 1 / 7 / 14 | Weekly 1 / 4 / 8 / 13 |
|---|---|---|
| Recent days + 12-month k (buildable before M1) | 1.15 / 1.19 / 1.19 (29 / 26 / 23) | 1.12 / 1.08 / 0.99 / 0.70 (24 / 16 / 13 / 7) |
| **Recent days only (recovered by M1)** | **0.88 / 0.90 / 0.94** (31 / 29 / 30) | **0.62** / 1.04 / 1.24 / 1.58 (13 / 15 / 14 / 15) |
| Stale 12-month k (no trusted recent days) | 4.78 / 4.09 / 3.40 (1 / 2 / 3) | 3.25 / 3.46 / 3.83 / 9.31 (1 / 4 / 3 / 6) |

Monthly: n = 1–4 per row, not interpretable.

Reading:
* **M1's recovered dates beat persistence up to 2 weeks ahead** (daily 0.88–0.94, n ≈ 30;
  weekly 1 week 0.62, n 13). From 8 weeks on they lose (1.24, 1.58): the recent level is
  right, the projected change after it is not.
* **Falling back to a stale 12-month k is badly wrong** (3.3–9.3× persistence's error).
  Each row is small (n 1–6), but all 7 rows agree. This supports withholding the milk
  forecast when there are no trusted recent days, instead of the fallback.
* Decision rule: the withholding change is decided on the development block (M2,
  scenarios with records still missing at the forecast date, `resumed = 0`), not on these
  post-test numbers, which only motivated the question.

*M1 development block (`--k anchor_first`):* every MAE, bias, MAPE, coverage and n is
identical to pfoi-1.1 without M1 (table below), as expected, because no development origin
lacked a 12-month k. M1's "keep if" rule (development no worse than +1 %) is met (0 %).

*Reference: pfoi-1.1 milk without M1 (`--k anchored`), development block, MAE ratio vs
persistence on common periods (all models except SARIMA for monthly):*

| Grain | Horizons | milk_baseline | milk_baseline_corrected | n |
|---|---|---|---|---|
| Monthly | 1 / 3 / 6 / 12 | 0.66 / 0.77 / 0.91 / 0.64 | 0.63 / 0.62 / 0.89 / 0.68 | 59 / 58 / 59 / 57 |
| Weekly | 1 / 4 / 8 / 13 | 1.08 / 0.86 / 0.83 / 0.87 | 1.06 / 0.84 / 0.84 / 0.90 | 299 / 297 / 294 / 283 |
| Daily | 1 / 7 / 14 | 1.12 / 1.02 / 0.96 | 1.13 / 1.05 / 1.00 | 314 / 312 / 311 |

Short-range weakness confirmed in development: the baseline loses to persistence at
1 day (MAE 457 vs 387 L) and 1 week, and ETS is best at 1 day (0.82). The baseline's
upward bias grows with horizon (daily +50 → +279 L/day at 1 → 14 days; monthly +41k /
+81k L at 3 / 6 months). 90 % interval coverage is 82–84 % weekly and daily and 49 % at
12 months, below the 85–95 % target. These are the targets for M3 (recent level),
M4 (intervals) and M5 (THI).

**RUN BATCH 2 (M2, development block only; aggregates only; may take hours, run in the
background):**

```bash
python -m components.predictive_farm_intelligence.pfoi.outage_sim --preset pfoi-1.1 --every 2 --jobs 0
```

Send back the three printed tables: "forecast dates per scenario", "outage cost" and
"error spread by days since the last trusted milk day". If it is too slow, add
`--every 4` and say so (fewer origins, same scenarios).

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
