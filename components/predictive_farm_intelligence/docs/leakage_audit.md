# Leakage audit (2026-10-19)

Rule: a forecast made at origin *m* may use only facts that were **known** before *m*,
not only facts **dated** before *m*. The second rule is what the loaders enforce today;
the gap between the two is where the remaining risks are.

Status: **OK** = checked in code (and tested where noted); **FIXED** = changed behind an
option; **CHECK** = needs an aggregate query (`docs/sql/leakage_checks.sql`);
**ASK** = needs the ETL definition; **DESIGN** = handled by a later step.

| # | Item | Status | Effect if it leaks |
|---|---|---|---|
| L1 | Every loader filters to dates before the origin and returns `max_date`; `check_before` raises otherwise | OK, tested (`test_leakage_and_backtest.py`) | — |
| L2 | Heifer and dry-cow conception rates, pregnancy losses and conceptions per AI used every complete transition month before the origin, including the last one or two months whose conceptions could not yet be confirmed | **FIXED** behind `conception_cut="known"` (tested, `test_leakage_audit.py`) | conception rates from months not yet confirmable |
| L3 | The **number** of pregnant heifers and pregnant dry cows at the origin comes straight from `day_cell` (ETL); only their gestation shape is cut at origin − 35 days | **CHECK** query L2, **ASK** | calvings 3–6 months ahead (skill 0.7–0.8) would partly rest on hindsight |
| L4 | `core.lactation.conception_date`: which service, and when is it known? The engine assumes it is known 35 days after the date | **CHECK** query L1, **ASK** whether the farm does pregnancy diagnosis and when | "already determined" calvings too certain |
| L5 | Records entered late (for example back-filled after the outage) look known at earlier origins, because `core` is rebuilt from today's data | **CHECK** query L3 (entry timestamps) | all inputs near an outage |
| L6 | Quality flags: `is_suspect_low` uses the past 28 days (OK); `cow_day.is_reliable` / `is_spike` definitions unknown | **ASK** | a centred spike window would leak a few days into the curve fit (small) |
| L7 | Milk: curve fitted on data before the origin month, anchored k on the last 14 scoreable days before the origin, benchmarks on targets before the origin | OK (code read) | — |
| L8 | Bias correction and intervals use only errors whose target period ended before the origin | OK, tested | — |
| L9 | Model choices (12-month window, herd-fitted curve, anchored k) were picked on 2017–2023 and scored on the same block | **DESIGN**: nested, purged rolling CV (next step) | development numbers are optimistic |
| L10 | Quality bands and episode dates are built from the full data | rule: evaluation only, never a forecast input; Layer 1 may use only daily quality signals up to the origin | — |

## L2 in detail

`state_transition_month` dates a heifer's or dry cow's conception in the month it
happened, but a conception is only confirmed weeks later. With an origin on 1 June, May
and late-April conceptions were not yet known. `conception_cut="known"` keeps only
transition months that ended before origin − 35 days (here, months before April), with
exposure from the same months, for: heifer and dry-cow conception rates, extra pregnancy
losses, and conceptions per AI (whose inseminations stop at the same month). Cow
conceptions while milking were already cut at origin − 35 days.

The frozen pfoi-1.0.0 keeps the old behaviour (`conception_cut="origin"`), and its hash
`3cbd28787fcb` is unchanged (the option is left out of the hash while it has its 1.0.0
value). pfoi-1.1 will use `known`.

## Commands (development block only; the test block runs only the frozen model)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --conception-cut known --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --conception-cut known --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block development --conception-cut known
```

Output files carry `_ck` after the window (for example `herd_backtest_errors_monthly_w12_ck.csv`),
so the pfoi-1.0.0 files are not overwritten. Compare the two development scorecards for
calvings, milking and herd milk.

## Questions for the ETL (L3–L6)

1. How is `day_cell` state `heifer_pregnant` / `dry_pregnant` set: from a pregnancy
   diagnosis record, from the service date of a later calving, or from calving minus a
   fixed gestation?
2. How is `core.lactation.conception_date` set (same three options)?
3. Does the farm record pregnancy diagnoses, and how many days after service?
4. How are `cow_day.is_reliable` and `is_spike` defined: past-only or centred windows?
5. Does any source table keep the date a record was entered?

## If L3 or L4 confirm hindsight

Rebuild the starting pregnant counts "as known": a heifer or dry cow counts as pregnant
only if its pregnancy could be confirmed 35+ days before the origin (diagnosis record, or
the service date of the conception if diagnosis is not recorded); more recent services
count as pregnant with probability = conceptions per AI, as is already done for milking
cows. Report the calving skill before and after, and drop or relabel any claim that
depended on it.

## Results of leakage_checks.sql (user, 2026-10-19)

**L1 / L4: conception date.** All 7,119 conceptions of 2017–2023 that are followed by a
calving fall exactly on an insemination date of the same animal (share 1.000). Gestation
to the next calving: median 277 days, p5–p95 265–285, the most common value only 7.1 %.
So `conception_date` is **the service that led to the next calving**, chosen once the
calving is known; it is not back-calculated. 35 days after the service it is not yet
known which of several services held. Data errors: gestation minimum −546 and maximum
414 days (conception after the next calving, or far too long), to be flagged by the ETL.

**L2 / L3: pregnant heifers in day_cell use hindsight (confirmed).**

| Day | a: day_cell pregnant | b: calve within 300 d | c: confirmable on the day | d: served < 35 d before | e: served 35–285 d before (no outcome) |
|---|---|---|---|---|---|
| 2018-01-01 | 358 | 347 | 327 | 20 | 360 |
| 2019-01-01 | 243 | 267 | 169 | 74 | 197 |
| 2020-01-01 | 175 | 208 | 112 | 59 | 122 |
| 2021-07-01 | 278 | 277 | 224 | 44 | 249 |
| 2022-01-01 | 322 | 313 | 262 | 38 | 285 |
| 2023-07-01 | 89 | 72 | 37 | 21 | 52 |

(12 dates in total; the rest follow the same pattern.) `a` tracks `b`, the heifers that
went on to calve, closely, and 3–74 of them (up to 30 % in Jan 2019 / Jan 2020) had been
served under 35 days earlier, so their pregnancy could not have been known on the day.
**The starting count of pregnant heifers therefore carries hindsight**, and so do the
"already determined" calvings at 3–9 months. The calving results of pfoi-1.0.0 are
labelled accordingly until the as-known count is in place.

**L5: entry timestamps.** `core` has event timestamps (`event_ts`, `start_ts`, …) but no
record-entry or modification dates, so records entered late cannot be cut "as known".
Only the prospective holdout protects against this. `core.preg_check` (pregnancy checks
with `event_ts`) exists and is the basis for an as-known pregnancy date (ETL request E1).

## L9: nested, purged validation (`pfoi/nested_cv.py`)

For each validation year Y in 2019–2023, every candidate (a development backtest
configuration × model, for example `w12/herd_engine` or `w24_ck/herd_engine_corrected`) is
scored only on forecasts whose target period ended before 1 January Y; the one with the
lowest mean WAPE over the agreed target rows is selected and scored on the origins of
year Y. Candidates are compared on the periods they all forecast. Reported per target
row: each candidate's accuracy over 2019–2023, the nested accuracy, the best candidate in
hindsight, and the **optimism** (best in hindsight − nested). Tests:
`tests/test_nested_cv.py`.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli nested-cv --family both
```

It uses every development error file in `logs/pfoi/` (never `_test` files), so run the
candidate backtests first, for example windows 12 and 24, each with
`--conception-cut origin` and `known`. Herd families select among herd options; milk
among milk options. From pfoi-1.1 on, development numbers are reported as nested
accuracy.

## Results (user runs, 2026-10-19)

**L2 effect.** Development backtests with `--conception-cut known` (windows 12 and 24)
differ from the uncut runs by at most 0.2 accuracy points on milking, total herd,
calvings and dry-offs (nested table below). The leak was real but small; `known` is
adopted for pfoi-1.1 at no cost.

**L9 nested validation (herd family, 12 candidates: windows 12/24/36/expanding × cut ×
raw or bias-corrected engine).** Year-by-year selection picks the bias-corrected engine
with a long window (expanding in 2019–2021, 36 months in 2022–2023). Optimism (best in
hindsight − nested) is 0.0–2.1 points, mostly under 1, so pfoi-1.0.0's development
numbers were not much inflated by picking options on the same block. Nested accuracy
2019–2023, monthly 1/3/6/12 months:

| Series | pfoi-1.0.0 (w12, raw) | Nested |
|---|---|---|
| Milking cows | 97.8 / 94.4 / 90.9 / 87.9 | 97.8 / 94.6 / 92.4 / 88.6 |
| Total herd | 99.3 / 97.4 / 95.6 / 94.0 | 99.4 / 97.9 / 96.5 / 95.7 |
| Calvings (hindsight caveat L3) | 82.5 / 89.5 / 92.4 / 77.6 | 92.5 / 91.9 / 92.2 / 76.5 |
| Dry-offs | 57.7 / 55.9 / 57.3 / 52.7 | 58.3 / 55.4 / 57.5 / 51.5 |

## L3 fix: `--cell-table day_cell_known` (2026-10-19)

The ETL now publishes `model_input.day_cell_known` (E1): same grain and totals as
`day_cell`, but an animal is pregnant only from the day its conception is known (positive
pregnancy check, else the calving). `EngineConfig.cell_table` chooses the table for the
starting herd, the exposures and the batched snapshots; the source must read the same
table or loading refuses (tested). The option is left out of the pfoi-1.0.0 hash while it
is `day_cell`. Files carry `_kn` after the window tag.

Commands (development block), once `etl_retest.sql` R1 confirms the table:

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 36 --conception-cut known --cell-table day_cell_known --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --conception-cut known --cell-table day_cell_known --jobs 0
```

Compare calvings 3–9 months ahead against the same runs without `--cell-table`: the drop
is how much of the calving skill came from hindsight. pfoi-1.1 uses `day_cell_known`.

## ETL retest (user, 2026-10-19)

* **E1 fixed.** `day_cell_known`: daily totals equal `day_cell` on every day 2015–2026,
  never more pregnant animals; known pregnant = 73–98 % of `day_cell` pregnant by year
  (mean ratio 0.73–0.98), so 2–27 % of pregnancies were hindsight. Pregnant heifers in
  `day_cell_known` match the confirmable count (e.g. Jan 2019 147 vs 169, Jul 2021 223 vs
  224), not later calvings.
* **New: confirmation lag.** Every known conception is confirmed by a pregnancy check;
  service → check median 41 (2016) to 85 (2022) days, p90 55–180 days. The engine's
  35-day `pregnancy_check_lag_days` is too short: cow conceptions in the milking/dry clocks
  should use `conception_known_date` instead (next model change, option
  `conception_known="recorded"`).
* **E2 not fixed:** 105 conceptions with gestation outside 240–310 days, none flagged.
* **E3 partial:** `core.lactation.is_inferred` exists, but `day_panel.milking` and
  `cells_milking` are unchanged (398–421 vs 477–514 cows giving milk, Jun–Aug 2026).
* **E4 open:** sales ≈ 0 since Sep 2024 (culls 6–64 a month continue); needs farm
  knowledge.
* **E5 partial:** `is_implausible_volume` exists, but Oct–Nov 2025 (23.8 L per recorded
  milking cow-day) still have 14 and 5 scoreable days.
* **E7 done:** `entered_ts` in 13 `core` event tables; late entries can now be measured
  (`etl_retest.sql` R7) and cut "as known".

## Recorded conception dates: `--conception-known recorded` (2026-10-19)

With `conception_known="recorded"` a cow's conception counts as known only when its
`conception_known_date` (positive pregnancy check, ETL E1) is before the origin, instead
of "dated more than 35 days before". It applies to the milking and dry-cow clocks
(gestation of cows already known pregnant), the batched snapshots, cow conceptions and
pregnant milking days in the rate window, and the dry-off-by-gestation histogram. Cow
conceptions are counted only inside the rate window (before origin − lag), so no event
falls outside its exposure. `milking_cowdays` (past milking days for the milk level and
curve) keeps the dated rule; it only covers months well before the origin.

Because checks come a median 41–85 days after service (p90 up to 180), use it with
`--pregnancy-lag 90`, so the rate window ends where most conceptions are already
confirmed. The source and the configuration must agree (tested); the option is left out
of the pfoi-1.0.0 hash while it is `lag`. Files carry `_rk` (and `_lag90`).

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 36 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
```

This is the fully as-known configuration proposed for pfoi-1.1. Compare its calvings
3–9 months ahead with the 1.0.0 run: the difference is what hindsight was worth.
