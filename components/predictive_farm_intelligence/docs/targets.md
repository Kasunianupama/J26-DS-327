# Accuracy targets and metrics (agreed 2026-10-19)

These targets are the yardstick for the modelling work after PP1 (pfoi-1.1 onward).
They were set **before** measuring the baseline with the scorecard, and are not loosened
afterwards without a dated note here. The code holds the same numbers:
`pfoi/scorecard.py` (`TARGETS`, `COUNT_SERIES`); a unit test keeps the two in step.

## Metrics (same for every series)

| Metric | Definition | Why |
|---|---|---|
| **Accuracy** | 1 − WAPE = 1 − Σ\|forecast − actual\| ÷ Σ actual | "80–90 % accuracy"; stable on small totals, unlike MAPE |
| **Skill** | 1 − MAE(model) ÷ MAE(best benchmark), on the periods both forecast | Proves the model adds something. High accuracy alone can come from persistence |
| **Bias** | Σ (forecast − actual) ÷ Σ actual | Systematic over- or under-forecasting |
| **Coverage 80 / 90** | Share of actuals inside the 80 % / 90 % interval (coverage scored from 2018) | "High confidence" = honest intervals |
| **Width 90** | Mean (upper − lower) ÷ forecast of the 90 % interval | Stops intervals being widened until coverage passes |
| **Deviance ratio** | Mean Poisson deviance of the model ÷ that of persistence (trailing rate), same periods | Small-count events only |

* **Best benchmark** = the benchmark (persistence, seasonal naive, ETS, SARIMA) with the
  lowest MAE on the periods it shares with the model, among benchmarks that forecast at
  least 12 periods and at least half the model's periods.
* **Calibrated** = 80 % coverage in [75, 85] % **and** 90 % coverage in [85, 95] %.
* Intervals are the empirical quantiles (10/90 % and 5/95 %) of the model's own past
  relative errors, using only errors whose target period ended before the origin
  (`error_tools.add_intervals`). For the test block, development errors count as past.
* A row with fewer than **12** scored periods is reported as *not interpretable*.

## Targets (monthly horizons 1/3/6/12, weekly 1/4/13, daily 1/7/14)

| Series | Grain | Accuracy ≥ | Other conditions |
|---|---|---|---|
| Herd milk | monthly | 92 / 90 / 88 / 85 % | skill > 0 at every horizon; \|bias\| ≤ 3 %; width 90 ≤ 0.30 (±15 %) at 3 months |
| Herd milk | weekly | 93 / 90 / 87 % (week 8: reported, no target) | skill > 0 at 4 and 13 weeks |
| Herd milk | daily | 95 / 92 / 90 % | skill ≥ −0.05 (a tie with persistence is accepted) |
| Milking cows | monthly | 97 / 95 / 92 / 88 % | skill > 0 from 3 months |
| Total herd | monthly | 98 / 96 / 94 / 90 % | skill > 0 at 6 and 12 months |
| Calvings | monthly | 80 / 80 / 75 / 65 % | skill ≥ 0.20 at 3 and 6 months |
| Dry-offs | monthly | 75 / 70 / 70 / 65 % | skill > 0 |
| Real abortions, deaths, culls, sales | monthly | no accuracy target | 80 % interval calibrated and deviance ratio < 1 |
| Mastitis | — | descriptive only | diagnoses stopped being recorded; no honest target |

**Recovery target (agreed 2026-10-19):** in the first 0–2 whole months after a break
(origin minus break date, breaks in `pfoi/episodes.py`), weekly herd milk 4 weeks ahead
reaches **≥ 90 %** accuracy on verified periods (n ≥ 12). Baseline pfoi-1.0.0: 67.2 %
(development, n 19, all bands). Code: `scorecard.RECOVERY_TARGETS`, `recovery_verdicts`.

Herd series at weekly grain, the corrected variants and every other series are reported
without a target.

Each target row gets two verdicts: **target** (accuracy and the extra conditions) and
**calibration** (the coverage bands). "Met" needs both.

## When a target counts as met

1. **Claimed** if it is met in the development block (origins 2017–2023; from pfoi-1.1
   on, the nested and purged CV of that block).
2. **Reported** on the 2024–26 block, which is post-hoc for every version after
   pfoi-1.0.0. It is *confirmed* if test accuracy is at most 5 points below development
   accuracy.
3. **Monitored** on the prospective holdout (months published after the pfoi-1.1
   freeze). Too few points to claim; shown with n.

## Command

```bash
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block both
```

Reads the backtest error files in `logs/pfoi/` (it does not re-run any backtest, so it
does not use up the final test), prints herd-level aggregates only, and writes
`logs/pfoi/scorecard_<block>_<milk config>_w<window>.csv`.

## Baseline: pfoi-1.0.0 (scorecard run 2026-10-19, aggregates supplied by the user)

Rows met (target and calibrated), primary models: **development 8 of 42**, **test 3 of 41**
(3 test milk rows not interpretable: 2–5 months scored).

| Series (monthly unless noted) | Development accuracy 1/3/6/12 | Test accuracy 1/3/6/12 | Main reason for misses |
|---|---|---|---|
| Herd milk | 96.5 / 90.2 / 85.7 / 79.1 % | not interpretable (n 2–5) | upward bias +1 / +7 / +11 / +18 %; 90 % coverage 86 → 34 % |
| Herd milk, weekly 1/4/13 | 97.2 / 94.9 / 89.0 % | 93.2 / 81.0 / 71.9 % | test: skill < 0, bias −9 to −21 % |
| Herd milk, daily 1/7/14 | 97.0 / 96.2 / 95.5 % | 92.1 / 89.5 / 86.4 % | skill < 0 (ETS / persistence win at 1–7 days) |
| Milking cows | 97.9 / 94.5 / 91.8 / 90.0 % | 96.3 / 86.2 / 77.9 / 75.8 % | over-forecast (dev +3 to +6 %, test +14 to +22 %) |
| Total herd | 99.2 / 97.1 / 95.4 / 93.9 % | 98.9 / 94.1 / 86.3 / 73.5 % | test: under-forecast −15 % at 12 months; coverage 10 % |
| Calvings | 83.6 / 91.4 / 93.2 / 77.4 % | 35.6 / 64.3 / 71.6 / 48.3 % | test: over-forecast +64 % at 1 month |
| Dry-offs | 60.8 / 59.1 / 56.3 / 56.1 % | 52.3 / 48.9 / 51.5 / 51.2 % | accuracy (skill +0.34, so the benchmark is worse) |

Observations:

1. **Calibration is the most common miss.** 90 % intervals cover 55–83 % in development at
   3+ months and far less in the test block (H3).
2. **Milk bias grows with horizon** and follows the milking-cow over-forecast (Step 3).
3. **Test failures sit in the two disruption episodes below**, which the current model has
   no way to recognise.
4. **Weekly accuracy of dry-offs (7 %), culls (12 %) and sales (7 %) is far below monthly**
   (56–61 %, 40–47 %, 29–41 %). This suggests the events are recorded in batches rather
   than on the day they happen. Check: `docs/sql/episode_checks.sql`, query 2.
5. **Sales in the test block:** forecast bias +62 % to +890 % against very few recorded
   sales, so accuracy is negative. WAPE is not meaningful there; sales is judged as a
   count series only.

No target is changed after this baseline. Dry-offs is reviewed after query 2: if dry-offs
are batch-recorded, the monthly target stays and weekly dry-offs are not scored.

## Known disruption episodes (user, 2026-10-19; months from episode_checks.sql, same day)

The user reported a herd contraction around 2022–2024 and a DelPro outage around
2024–2025. The monthly aggregates (queries 1–3) set the months below and show that
recording broke down gradually, not in a single on/off outage.

| # | Episode | Months | Evidence (herd-level aggregates) | Real or recording? |
|---|---|---|---|---|
| E1 | Herd contraction, phase 1 | 2022-09 – 2023-01 | mean herd 2,879 → 2,477 (−14 %) | real (exits recorded); overlaps milk gap E5a |
| E2 | Abortion surge | from 2023-11, still present | 1–12 a month in 2023 → 21–44 a month from Dec 2023; 11–41 a month in 2025–26 on a smaller herd | real (biological) |
| E3 | Herd contraction, phase 2 | 2024-03 – 2024-06 | mean herd 2,259 → 1,769; culls + sales + deaths ≈ 750 in 4 months (sales 203 in Apr) | real (exits recorded) |
| E4 | Cow identification decay | 2023-01 – 2025-08 | identified share of DelPro milk 0.77 → 0.39 (Dec 2023) → 0.13 (Aug 2024) → ≈ 0 | recording |
| E5 | Milk target gaps | a: 2022-09 – 2022-11; b: 2024-03 – 2024-06 (partial); c: 2024-09 – 2025-09-07 | gap days per month | recording |
| E6 | New system roll-out | 2025-09 – 2026-07 | milking sessions appear and rise from 0.6 to 2.8 per recorded milking cow-day; identified share recovers only from 2026-04 (0.17 → 0.90) | recording |
| E7 | Sales no longer recorded | from 2024-09 | sales 0 in most months since; culls continue | recording (to confirm) |

**Implausible milk per recorded cow.** Litres per recorded milking cow-day are 2.8–5.3 in
2023, 8.9 in Jul–Aug 2024, **13.8–23.8 in Sep 2025 – Mar 2026**, and 9.8–10.2 in Jul–Aug
2026, when the identified share is back to 0.86–0.90. Either the recorded milking-cow
count is far too low, or the unidentified milk volume is inflated, in Sep 2025 – Mar 2026.
There is no shipment series after 2020-08 to check against.

**User's farm knowledge (2026-10-19):** about 4–5 L per cow a day was realistic in the
mismanagement and mistreatment period, and about 10 L is realistic now. **Above 20 L per
cow a day is not realistic.** So yield per cow is a real, management-driven level that
changes over time (the target of the Layer 1 adaptive level), while Oct–Nov 2025
(23.8 and 23.4 L per recorded cow) are recording errors. Rules from now on:

* periods with mean identified share < 0.2, **or more than 20 litres per recorded milking
  cow-day**, are the quality band **"unverified"**: scored and reported separately, never used to fit k, curves or the
  deviation layer;
* the anchored k absorbs the identification loss (k = recorded litres ÷ curve litres of
  *recorded* cows), so a large k is flagged as a data-quality warning, not a yield change.

**Batch recording (query 2).** Calvings are recorded on 20–30 days a month (top-day share
0.07–0.13), so they are recorded as they happen. Dry-offs (top-day share 0.35–0.66, on
4.6–14.8 days a month), culls (0.28–0.70, 1.4–6 days) and sales (0.28–0.56, 2–11 days) are
recorded in batches. Decision, as agreed above: the monthly targets stay; weekly
dry-offs, culls and sales are not scored. Culls and sales are modelled as management
"removal" decisions (E7 makes sales alone unreliable after 2024-08).

Scores inside E4–E6 are reported as their own quality bands, never mixed with normal
periods. The recovery metrics use E1, E3 and E5 as the labelled breaks.

## Scorecard with quality bands and recovery (run 2026-10-19)

**Most of the 2024–26 block cannot test the model.** In the test block, monthly milking,
total-herd and calving forecasts fall mostly in the *gap* (11–18 periods) and
*unverified* (6–8) bands, with 1 *normal* and 2–4 *degraded* periods. Every monthly
target row there has n < 12, so no test-block monthly claim can be made either way.
Where the test records are verified, weekly herd milk 1 week ahead reaches 95.7 %
accuracy with skill +0.12 over persistence (n 16, target met; not calibrated).

**Recovery after a break is slow** (accuracy by whole months from the latest break to
the origin):

| Series, horizon | 0–2 months | 3–5 months | 6–11 months | no break yet |
|---|---|---|---|---|
| Herd milk, weekly, 13 weeks (development) | 34.4 % (n 25) | 66.7 % (13) | 84.9 % (12) | 90.2 % (273) |
| Herd milk, weekly, 4 weeks (development) | 67.2 % (19) | 80.5 % (18) | 88.2 % (13) | 95.5 % (280) |
| Herd milk, monthly, 3 months (development) | 34.1 % (4) | 73.1 % (2) | 76.2 % (2) | 91.1 % (58) |
| Milking cows, monthly, 6 months (test) | 69.9 % (10) | 78.0 % (7) | 91.4 % (6) | — |

The current model needs 6–11 months after a break to get back near its normal accuracy.
This is the main target for Layer 1 (the adaptive level).

**Per-cow milk (query 4 v2, placeholder excluded).** Litres per identified cow-day, real
cows only:

| Period | Cows giving identified milk per day | Recorded milking (day_panel) | Litres per cow-day | Median / p90 | Cow-days > 20 L |
|---|---|---|---|---|---|
| 2023 (Jan–Dec) | 630 → 267 | 854 → 784 | 4.1–5.2 | 3.5–4.5 / 7.9–10.4 | ≤ 0.5 % |
| 2024 (Jan–Aug) | 268 → 90 | 724 → 443 | 5.5–6.3 | 4.9–6.0 / 9.5–12.0 | ≤ 1 % |
| Sep 2024 – Mar 2026 | 1–12 | — | not usable | — | — |
| Jun – Aug 2026 | 477 → 514 | 422 → 398 | 6.7–7.5 | 6.0–7.0 / 12.9–13.8 | 0.7 % |

* Real cows gave about **4–5 L a day in 2023 and about 7 L in mid-2026** (top 10 %
  above 13 L). The "about 10 L per recorded cow" seen in query 3 is inflated by the
  denominator, as the user suspected.
* In 2023, identified cows ÷ recorded milking (0.74) matches the identified milk share
  (0.77), so the gap then is identification loss.
* **In Jun–Aug 2026, with 86–90 % of milk identified, 477–514 cows give milk each day
  while day_panel counts 398–422 as milking: about 100–115 cows (≈ 25 %) are milked
  without being in the milking state.** A likely cause is calvings not recorded during
  the outage (E5c), so those cows never got a lactation record. Query 5 checks this.
* **Query 5 (2026-10-19) confirms it.** Mean cows a day giving identified milk, by
  lactation record on that day:

  | Month | Giving milk | Open lactation | Lactation closed or not yet started | Never any lactation |
  |---|---|---|---|---|
  | 2026-04 | 110 | 84 | 18 | 9 |
  | 2026-05 | 288 | 221 | 32 | 35 |
  | 2026-06 | 477 | 347 | 54 | 76 |
  | 2026-07 | 514 | 367 | 59 | 87 |
  | 2026-08 | 512 | 359 | 58 | 95 |

  About **29 % of cows giving milk (≈ 150 a day) have no open lactation**: about 90 have
  never had a calving recorded, and about 58 have a lactation that is closed (dry-off
  recorded) or starts later. These cows are not in the milking state of `day_cell`, so the
  herd engine starts with too few milking cows and too many heifers or dry cows. **ETL
  issue to raise:** calvings missing since the outage, and dry-off or calving dates out of
  step with milk recording. Until it is fixed, from 2026-04 the count of cows giving milk
  (`core.cow_day`) is a second, independent measure of the milking herd, which Layer 1
  can use alongside `day_cell`.
* Sep 2025 – Mar 2026: only 1–4 identified animals a day, some with 29–31 L a day: one
  or two bad animal records, not usable.

The milking-state count used by the herd engine (`day_cell`) therefore disagrees with the
cows actually milked. This affects both the milking-cow forecast and the milk
denominator, and needs an ETL check. Query 4 v2 excludes the placeholder.
