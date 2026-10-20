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
| F1–F9 | implemented, build and browser-checked on the demo run | `frontend/.../panels/Pp1Panels.tsx`, page-document keys (`page_run._pp1_sections`), `evidence-ladder` command | `test_evidence.py`, `npm run build` |

Hashes of pfoi-1.0.0 (`3cbd28787fcb`) and pfoi-1.1.0 (`2a865a0c2687`) are unchanged (tested).
Development builds are published as `pfoi-1.2.0-dev`, never under a frozen name.

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
