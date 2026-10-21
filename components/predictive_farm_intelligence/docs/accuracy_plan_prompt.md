# Prompt: improve the milk forecast accuracy before PP1 (Fri 2026-10-23)

Paste this into a new Claude Code session opened in the monorepo root. Written 2026-10-21 from
the working sessions "Milk per day prediction improvements" and its fork. The user wants **all of
it done before PP1**.

---

## Role and rules (they override everything below)

You are working on PFOI (Component 1), herd-level milk and herd forecasting for **"Farm X"**.
Read first: root `CLAUDE.md` / `AGENTS.md`, `components/predictive_farm_intelligence/CLAUDE.md`,
`docs/pp1_plan.md` (M1 to M10), `docs/milk_model.md`, `docs/command_sheet.md`.

* **No database access.** Never connect to `farmx_app`, `farmx_research` or DelPro, never read
  `.env`. Write the SQL or command; the user runs it and sends aggregates back.
* **Saved herd-level aggregate files** under `logs/pfoi*` (backtest error and summary CSVs) may be
  read in this task: the user allowed it in the originating chat. Never open row-level data, keys
  or names. `AGENTS.md` still says not to read `logs/`; do not edit that rule.
* "Farm X" everywhere. No real names. No real data in Git. Nothing is committed unless the user
  asks; do not touch teammates' branches or shared files without asking.
* Frozen hashes must stay unchanged: pfoi-1.0.0 `3cbd28787fcb`, pfoi-1.1.0 `2a865a0c2687`
  (`tests/test_freeze.py`, `test_source_k.py`). New options go in `LEGACY_*_VALUES` in `freeze.py`
  at their legacy value. Dev builds are `pfoi-1.2.0-dev`, never under a frozen name.
* Design choices on the **development block only** (origins 2017 to 2023). 2024 to 2026 is post-hoc
  and descriptive. Fix each keep rule **before** looking at results and record it in `pp1_plan.md`.
* Report failing checks as they are. Never loosen a test or tolerance without the user's say.
* The model to improve is **`pfoi-1.2.0-dev`**: pfoi-1.1.0 engine, `--k anchor_first`, adaptive
  correction layer, ACI intervals. Its milk point forecast is `milk_baseline_adaptive`
  (files `milk_backtest_errors_{monthly,weekly}_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3.csv`).
* Python: `.venv/bin/python -m pytest ...` from the monorepo root (system python has no pytest).

## What we learned (aggregates supplied by the user, 2026-10-21)

Supporting detail: **Appendix A to D** (source timeline, no-data months, litres per cow-day, the SQL and the ETL
retest results) and **Appendix E** (the five problem-chart screenshots, in `docs/figures/accuracy_problem_charts/`).

1. **The milk target is not one series.** `target_source` is `shipment` to Jul 2022 and `delpro`
   from Aug 2022. Sep to Oct 2022, Apr 2024 and Oct 2024 to Aug 2025 have no scoreable days.
   Litres per recorded milking cow-day: 10 to 19 (2016 to mid 2020), 12 falling to 5 (Aug 2020 to
   Jul 2022, shipment), 3 to 5 (Aug 2022 to Feb 2024), about 10 (2026). Docs still say DelPro from
   2020-08; that is when DelPro milk starts, not when it becomes the target.
2. **Recorded milking undercounts cows giving milk in 2026.** At identified share 0.86 to 0.90:
   409 vs 514 (Jul) and 398 vs 512 (Aug), ratio 0.78 to 0.80. Yield per cow actually milked is about
   7.8 L/day, not 9.8. Cannot be checked for 2021 to 2024 (reliable cow-days under 1k a year).
3. **Event entry was late in 2022 and 2024** (calvings over 7 days late: 39 % and 38 %; dry-offs
   median 12 days in 2024; exits 13.7 days). 2025 to 2026 are back to about 1.4 days.
4. **ETL checks:** R1 passes; R2 fails (105 impossible gestations unflagged); `hand_milked_est` is
   empty; no inferred lactations (R3b empty); DelPro identified share about 0.001 to 0.015 from Sep
   2025 to Mar 2026, 0.86 to 0.90 by Jul to Aug 2026; implausible days are never scoreable (R5b).
5. **Where 1.2.0-dev loses** (dev block, MAE ratio to persistence, matched): daily 1.19 / 1.05 /
   1.03, weekly h1 1.06; DelPro regime weekly 1.30 / 1.41 / 1.66 / 1.44, daily 1.76 / 1.38 / 1.47.
   Monthly 0.60 to 0.71 and is where the structure earns its keep. Bias is positive and grows with
   horizon (monthly +9 % at h6 and h12), worst in 2022 (+15 % weekly h8 to h13).
6. **Earlier ML experiments** (`logs/pfoi_experiments/dev_monthly_v1`, monthly): ridge, boosted, TCN
   and residual TCN are all worse than the structural model (pooled WAPE h1/h3/h6/h12: structural
   3.6 / 9.5 / 12.1 / 32.7; TCN 22.6 / 29.7 / 51.4 / 92.4; residual TCN 6.4 / 14.8 / 20.6 / 48.9).
   **Caveat:** the run never tested the post-break regime. Same-source training had 0 to 7 examples
   (minimum 24) in 2023, so no 1 and 3 month forecasts exist for 2023, and the inputs had no
   identified share, no quality flags and no per-cow target. The verdict "sequence models lose" is
   proven for the shipment era only.

## Already done (do not redo; check `git status` and `pp1_plan.md` first)

* **M9** `--borrow-k off` (`MilkConfig.borrow_other_source_k`, tag suffix `s`), `pfoi/regimes.py`
  (errors by regime, `--against` matched A/B comparison, refuses mixed files). Result: on matched
  periods identical; the declined periods had MAE 5 to 15 times normal. Kept as an option.
* **M10** `pfoi/blend.py`, `cli blend`: daily and weekly forecast = w x structural + (1 - w) x
  persistence, w from past finished errors (Bates-Granger), monthly untouched. Dev gain about 5 to 15
  % MAE at daily and weekly, mostly 2022 to 2023; stable years lose a little. Backtest layer only.
* A parallel session ("Milk per day prediction improvements") owns these files; **check
  `git status` and the transcript before editing `cli.py`, `regimes.py`, `blend.py`, `pp1_plan.md`,
  `command_sheet.md`** to avoid overwriting its work.

## Work to finish before PP1, in this order

**T0. Fix the regime definition first (Appendix F).** Replace the calendar labels in `pfoi/regimes.py`
with (origin source, target source) plus a data-state split: shipment 2017 to Jul 2020; shipment Aug 2020
to Jul 2022; cross-break (origin before 2022-08, target after); same-source DelPro to Feb 2024; DelPro
restart from 2024-05 (post-hoc only). Test any boundary with `breaks.py` using origin-known data only.
Report n and bias per cell, never pool the cross-break rows into a DelPro average. Re-run M9/M10
comparisons with the new labels. *Done when:* the table is reproduced from the saved dev files and the
tests pass.

**T1. Put the M10 blend into the live outlook** (needs the user's decision to adopt).
`outlook.OutputLayer` does not apply it yet. Implement behind an option, off by default, with the
blend weights and the persistence reference recorded in the page document; unit tests on synthetic
data; hashes unchanged. Give the user the post-hoc replay command (2024 to 2026 is descriptive only).
*Done when:* tests pass, the outlook labels the blended series and shows which weight was used.

**T2. Regime-aware learned correction (new candidate, dev block only).**
**Data granularity (user instruction, 2026-10-21): do not train on monthly aggregates.** About 100 monthly
points cannot support a learned model; the earlier run had 24 to 60 per fold and none after the break. Train
and test on **daily herd-level series** (about 4,000 days since 2015-08; daily `day_panel` milk, milking cows,
calvings, dry-offs, quality flags) with direct models per horizon (1 to 14 days, then 7-day and 28-day sums),
and build weeks and months by summing days, as the engine already does. If you need more or different data
points (for example daily aggregates by DIM band or parity, or per-cow-day yield statistics for the curve),
**ask the user for them as aggregate-only SQL and wait**; the user may agree to extra daily aggregates. Per-cow
rows stay inside user-run code and never reach the chat. Daily points are strongly autocorrelated, so the
effective sample is far smaller than 4,000: use a purge or embargo of at least the horizon between train
and validation, report the effective n, and never use a random split. **Splits (user instruction): an 80:20 split inside each regime, not one global split.** For every regime and
place from T0 (shipment 2017 to Jul 2020; shipment Aug 2020 to Jul 2022; same-source DelPro; later DelPro restart),
split the days in time order: the first 80 % of that regime to fit, the last 20 % to test, with an embargo of at
least the forecast horizon between them. Never a random split. **Look-ahead rule:** a model pooled across regimes
may only train on days that come **before** the test window it is scored on (an early-DelPro training day must
not help forecast a 2022 shipment test window). So fit one model per test window using all earlier days of any
regime, plus the regime's own 80 %, and report each regime's 20 % separately with its n and effective n. Expect
tiny test blocks (about 8, 5 and 3 months for the three eras); also report the rolling-origin results the project
already uses, and score the cross-break periods (origin before 2022-08, target after) as their own cell.
Context for choosing windows: 2024 to 2026 stays post-hoc; the real holdout is anything after the last data
day (2026-08-20).
Redo the residual idea properly, because the earlier run could not test post-break.
* Target: log ratio of actual to the structural forecast, or litres per cow-day relative to the
  last trusted level, so training can pool across the source break.
* Inputs: identified share, implausible and suspect flags, scoreable share, days since the source
  switch, source indicator, recent level and trend, calendar, projected milking cows.
* Mask untrustworthy days (the anchor-gate rule: identified share below 0.2 or over 20 L per
  milking cow) from labels and inputs. Never impute.
* Small, regularised models first (ridge, then boosted); a compact GRU or TCN only if the first two
  show signal. Fit inside each time fold, chronological, no random split.
* Score with `regimes.py` (shipment, DelPro 2022 to 2024) on **matched periods** against the
  structural model, the persistence blend (T1) and persistence. Report n and bias; flag n under 10.
* **Keep rule, to be written into `pp1_plan.md` before running:** keep only if it beats the blend on
  matched periods in the DelPro regime without worsening shipment by more than 2 %.
*Done when:* a decision record (M11) with the result, even if the answer is "dropped".

**T3. Zero-shot pretrained time-series model as one more blend member** (time-boxed, optional).
Chronos or TimesFM run **locally**; no farm data may leave the machine. Downloading model weights
needs the user's approval (name file, source, size). Evaluate as a benchmark and as a blend member
with the same rolling harness. Expect roughly ETS-level monthly accuracy.

**T4. Interval calibration after the break.** After Aug 2022 the daily and weekly 90 % ranges cover
only about 50 %. Test regime- or recent-coverage-scaled ACI widths on the dev block; report coverage
and width by regime. Monthly ranges (42 to 77 % covered) get the same treatment if time allows.

**T5. Data-quality items for the ETL owner and the report** (no code needed, write them up):
late event entry in 2022 and 2024; milking undercount in 2026; the 105 unflagged gestations;
empty `hand_milked_est`; no inferred lactations; the docs date for the source switch.

**T6. Documentation and honesty pass.**
* Fix the "DelPro from 2020-08" wording where it describes the target switch.
* Update `pp1_evidence_pack.md` row "Better than boosted / TCN: Not run": the monthly run exists
  (`dev_monthly_v1`); say what it could and could not test.
* Add M11 (T2), and T3/T4 outcomes, to `pp1_plan.md` with keep rules and limits.
* Two-minute talk: one slide on regimes (shipment, DelPro, gap), one on what the blend and the
  `--borrow-k off` option change, one on what is not yet confirmed.

**T7. Final checks.** Full suite `.venv/bin/python -m pytest components/predictive_farm_intelligence/tests -q -p no:cacheprovider`
(about 11 minutes; run in the background), frozen hashes unchanged, `git status` reviewed, no
secrets or data files staged. List every command the user must run, one per code block, with the
aggregate tables to send back.

## Schedule (today is Wed 2026-10-21 evening)

* Wed night: T1 (code and tests), write the T2 keep rule, build T2 features.
* Thu: user runs the T1 replay and T2 backtest; T4; T5 and T6 documents; T3 only if T2 is done.
* Thu evening: T7, freeze the notes, no new features.
* Fri morning: rehearsal only.

If a task cannot be finished by Thursday evening, say so on the day and drop it in the order
T3, then T4, then T2. Never drop T1, T6 or T7. Report outcomes faithfully: a negative result with
its limits is a valid result.

## Report format after each step

Files created or changed; commands run and test results; aggregates supplied by the user; anything
that needs the user's decision. Never paste row-level data.

---

# Appendix A to D: the counts, dates and queries behind the numbers above

Source: the monthly aggregate query below, run by the user on 2026-10-21 (one row per month, no
row-level data), plus the ETL retest queries R1 to R7 in `docs/sql/etl_retest.sql`. The original
CSV export was no longer on disk when this appendix was written; the figures were copied from the
output the user pasted into the session, so **re-run the query and compare before quoting a number
in the report**. "Scoreable" = `day_panel.is_scoreable`.

## A. Source timeline (what `target_source` actually is)

| Period | `target_source` | What happens |
|---|---|---|
| 2015-08 to 2016-12 | shipment | Burn-in. Startup ramp: milking cows rise from 909 (Jan 2016) to about 1,900 (May 2016). Never scored. |
| 2017-01 to 2020-07 | shipment | Development origins start 2017-01. Seasonal litres per milking cow-day, 10.2 to 18.5. |
| 2020-08 to 2022-07 | **shipment** (not DelPro) | DelPro identified milk starts in Aug 2020 (share 0.998) but is not the target. Share then decays: 0.903 (Feb 2021), 0.690 (Mar 2021), 0.548 (Dec 2021), 0.337 (Mar 2022). Litres per cow-day fall from 12.4 (Dec 2020) to 8.6 (Mar 2022) to 5.1 (Jul 2022). |
| **2022-08 onward** | **delpro** (first DelPro target month) | Aug 2022: 27 of 31 days scoreable, 4 suspect-low. |

The code follows the `target_source` column, so it switches on 2022-08. The wording "DelPro from
2020-08" in older docs and in the `milk_baseline.py` header describes when DelPro milk starts, not
when it becomes the target.

## B. No-data and thin months (scoreable days / days in month)

| Month | Scoreable | Notes |
|---|---|---|
| 2022-09 | 0 / 30 | 30 gap days, 28 suspect-low |
| 2022-10 | 0 / 31 | 31 gap days |
| 2022-11 | 7 / 30 | 22 gap days |
| 2022-12 to 2024-02 | 25 to 31 / month | Full months (every day scoreable): Dec 2022, Jan, Feb, Apr, May, Jun, Aug, Sep 2023, Jan and Feb 2024. Partial: Mar 2023 29/31, Jul 28/31, Oct 28/31, Nov 29/30, Dec 25/31. |
| 2024-03 | 11 / 31 | 20 gap days, 20 suspect-low |
| 2024-04 | 0 / 30 | 30 gap days |
| 2024-05, 2024-06 | 20 / 31, 17 / 30 | 11 and 12 gap days |
| 2024-07, 2024-08 | 31 / 31 each | Full |
| 2024-09 | 7 / 30 | 20 gap days, 21 suspect-low |
| **2024-10 to 2025-08** | **0 every month (11 months)** | Gap days 28 to 31 in Oct 2024 to Jul 2025; Aug 2025 has 0 gap days but still 0 scoreable. |
| 2025-09 to 2025-12 | 12/30, 14/31, 5/30, 11/31 | Suspect-low 1, 1, 7, 11 |
| 2026-01 to 2026-08 | 26/31, 19/28, 20/31, 26/30, 25/31, 25/30, 31/31, 19/20 | Aug 2026 has 20 days of data |

Months where every day is scoreable, Aug 2022 onward: **13** (the 10 above in Dec 2022 to Feb 2024,
plus Jul and Aug 2024 and Jul 2026). In the development block (to Dec 2023): **8**. This is why the
DelPro regime has only 6 to 8 scored monthly periods.

## C. Litres per recorded milking cow-day (scoreable days) and identified share

| Month | L per cow-day | Avg milking cows | Identified share |
|---|---|---|---|
| 2016-01 / 2016-12 | 19.4 / 11.3 | 909 / 1,634 | n/a (shipment) |
| 2017-02 / 2017-08 | 10.2 / 18.5 | 1,317 / 1,445 | n/a |
| 2018 range, 2019 range | 12.8 to 15.6, 12.8 to 14.0 | 1,350 to 1,756 | n/a |
| 2020-12 | 12.4 | 1,357 | 0.998 |
| 2021-08 / 2021-12 | 10.5 / 9.9 | 1,260 / 1,106 | 0.820 / 0.548 |
| 2022-03 / 2022-07 | 8.6 / 5.1 | 1,027 / 1,090 | 0.337 / 0.416 |
| 2022-08 (first DelPro target) | 3.2 | 1,053 | 0.567 |
| 2022-12 / 2023-07 | 4.7 / 2.9 | 916 / 899 | 0.792 / 0.609 |
| 2024-02 / 2024-07 / 2024-08 | 5.3 / 8.9 / 8.9 | 697 / 486 / 443 | 0.390 / 0.156 / 0.125 |
| 2025-09 / 2025-11 | 10.1 / 18.3 (5 days) | 361 / 379 | 0.013 / 0.002 |
| 2026-01 / 2026-03 | 8.3 / 12.0 | 394 / 427 | 0.001 / 0.006 |
| 2026-07 / 2026-08 | 9.8 / 10.8 | 409 / 398 | 0.862 / 0.899 |

Identified share depends on the day set: the query above averages scoreable days (2026-04 to 06:
0.181, 0.314, 0.689); `etl_retest.sql` R5 averages all days (0.165, 0.266, 0.574); R3 averages
days with identified cows (0.171, 0.393, 0.783). Quote which one.

## D. The queries

**D1. Monthly target consistency (aggregate-only, run in `farmx_app`).**

```sql
SELECT
    date_trunc('month', date)::date                             AS month,
    min(target_source)                                          AS src_min,
    max(target_source)                                          AS src_max,
    count(*)                                                    AS days,
    sum(is_scoreable::int)                                      AS scoreable_days,
    sum(data_gap::int)                                          AS gap_days,
    sum(is_suspect_low::int)                                    AS suspect_low_days,
    round((avg(milking) FILTER (WHERE is_scoreable))::numeric, 0)          AS avg_milking_cows,
    round((sum(target_litres) FILTER (WHERE is_scoreable))::numeric, 0)    AS litres_scoreable,
    round((
        sum(target_litres) FILTER (WHERE is_scoreable)
        / nullif(sum(milking) FILTER (WHERE is_scoreable), 0))::numeric, 2) AS litres_per_milking_cow_day,
    round((avg(identified_share) FILTER (WHERE is_scoreable))::numeric, 3) AS avg_identified_share,
    round((
        sum(milk_delpro_cows) FILTER (WHERE is_scoreable)
        / nullif(sum(milk_delpro_total) FILTER (WHERE is_scoreable), 0))::numeric, 3) AS cows_share_of_delpro_total,
    round((
        sum(milk_delpro_cows) FILTER (WHERE is_scoreable)
        / nullif(sum(milking) FILTER (WHERE is_scoreable), 0))::numeric, 2) AS delpro_cows_litres_per_milking_cow_day
FROM model_input.day_panel
WHERE date >= DATE '2016-01-01' AND date < DATE '2026-09-01'
GROUP BY 1
ORDER BY 1;
```

**D2. ETL retest results (`docs/sql/etl_retest.sql`, user run 2026-10-21).**

| Query | Result |
|---|---|
| R1 `day_cell_known` vs `day_cell` | `days_total_differs` 0 and `days_more_pregnant` 0 in every year 2015 to 2026. Mean ratio known to day_cell 0.73 to 0.90 (2015: 0.981). Pass. |
| R1b service to confirmed-conception lag | Median 41 (2016), 45, 49, 51, 54, 68 (2021), **85 (2022, p90 180)**, 60, 77 (2024), 59 (2025), 52 (2026). |
| R1c leakage check | `a_known` tracks `c_confirmable` within about 0 to 19 % (for example 2020-01-01: 91 vs 112; 2023-07-01: 32 vs 37). Pass, Jan dates run lower. |
| R2 impossible gestation | `out_of_range` 105 and `out_of_range_unflagged` 105. **Expected 0: fails.** |
| R3 milking vs cows giving milk | 2026-06: 421 vs 477 (ratio 0.883, share 0.783); 2026-07: 409 vs 514 (0.795, 0.862); 2026-08: 398 vs 512 (0.778, 0.899). Apr and May not informative (share 0.17 and 0.39). |
| R3b inferred lactations | No rows. |
| R4 exits | Culls peak Mar 2024 (113) and Feb 2026 (64); sales peak Apr 2024 (203) and May 2024 (105). |
| R5 volume per cow | 2025-10: 23.8 and 2025-11: 23.4 L per recorded cow-day (all days; expected under 20); `hand_milked_est_litres` empty in every month. |
| R5b implausible days | `implausible_and_scoreable` is 0 in every month, 2024-01 to 2026-08. Implausible days: Sep 2025 9, Oct 16, Nov 18, Dec 9, Feb 2026 8, Mar 9. |
| R7 entry lag, share entered over 7 days late | Calvings: 2022 38.6 %, 2023 10.0 %, 2024 37.8 %, 2025 7.5 %, 2026 0.3 %. Dry-offs 2024: median 12 days, 59.8 % over 7 days. Exits 2024: median 13.7 days, 57.5 %; 2022: 9.6 days, 59.9 %. |

---

# Appendix E: the problem charts (screenshots of the current model's page)

Images are in `docs/figures/accuracy_problem_charts/`. They are the page's "Milk per day" and
"Herd population" charts for three forecast dates, plus two history charts. **Values below are read
off the screenshots, so they are approximate**; where a number can be checked against the monthly
query in Appendix D1 it is marked (D1). The charts show herd-level aggregates only.

The user's first observation: *the herd population looks on point most of the time, but milk per
day does not.* The screenshots show that this is only partly true: the **whole herd** is on point
in two of the three, but **cows in milk**, which drives milk, is not.

## E1. Origin Jan 2017, view from Jan 2016 (`01_origin_2017-01_milk_overforecast.webp`)

* Recorded milk falls from about 31.5k L/day (May 2016) to 18.5k (Dec 2016).
* Expected dips to about 14k (Mar 2017) then **climbs to about 34k by Jun 2017**.
* What happened (D1): 16.7k (Jan), 13.5k (Feb), about 12k (Mar, Apr), 15.7k (May), 21k (Jun).
  The recovery was real but **June is over-forecast by about 60 %**.
* The herd chart is close: whole herd about 2,600 to 3,300 and cows in milk about 1,000 to 1,600
  follow the circles. With about 1,150 to 1,250 cows, 34k L/day means **about 28 to 30 L per cow-day**.
  Actual June 2017 was 16.6 (D1). The project's own plausibility rule rejects over 20 L per cow.
* Cause to investigate: the first development origin sits on the startup year (herd rebuilt from
  909 to about 1,900 milking cows in 2016); the herd-fitted curve shape and the anchored level are
  fitted on that unusual period. Check `curve_source`, `k` and the starting-herd DIM mix at origins
  2017-01 to 2017-03. *(T2 input: the implausible-yield mask; T6: say the first origins are fragile.)*

## E2. Origin Nov 2023, view from Nov 2022 (`02_origin_2023-11_herd_culling_wave.webp`)

* Milk: Expected falls from about 4.7k to about 2.8k L/day by Oct 2024, with a wide band (about 2.0k
  to 5.2k). Actual: about 3.5k (Nov 23), 2.9k, 3.5k, 3.7k, then **about 4.3k and 4.0k in Jul and Aug
  2024** (D1: 4,315 and 3,940), above the expected line.
* Herd: **whole herd forecast about 2,300 to 2,400 flat; actual falls to about 1,600** by Oct 2024.
  **Cows in milk forecast about 850 to 950; actual about 400.** The culling and selling wave of
  Mar to May 2024 (R4: 113 culled in Mar; 203 and 105 sold in Apr and May) is not in any rate model.
* The two errors do not cancel the way a simple cows x yield story suggests: recorded milking cows
  halve (795 in Dec 2023 to 486 in Jul 2024, D1) while litres per recorded cow-day go from 3.7 to
  8.9. Either the 2023 count was inflated, or the cows removed were low producers, or both. This is
  the strongest evidence for the denominator problem (Appendix D2, R3).
* This origin is also where D1 shows Mar and Apr 2024 gaps; the chart's "actual" circles around
  those months come from thin data. *(T2: learn the per-cow level change from quality features;
  T4: the interval did contain the outcome, but only because it is very wide.)*

## E3. Origin Aug 2020, view from Aug 2019 (`03_origin_2020-08_milk_decline_missed.webp`)

* Milk: Expected stays about 17 to 18.7k L/day (a bump about 18.7k in Feb 2021) with a band about
  12k to 23k. Actual: 17.3k in Aug 2020 falling steadily to **about 13.6k by Jul 2021** (D1:
  420,404 L / 31 days). **Over-forecast about 27 % at 12 months**, and the actual path leaves the
  band's lower half only late.
* Herd: **whole herd is on point** (about 3,300 to 3,400 flat, actual circles match). **Cows in
  milk are not:** forecast about 1,450 to 1,550 flat, actual falls to about 1,200 (D1: 1,469 in Aug
  2020 to 1,209 in Jul 2021, about -18 %).
* Almost all of the milk fall is therefore cows in milk (D1 litres per cow 11.7 to 11.2, about
  -4 %), which the herd engine did not project, not a yield change. This is the known milking-cow
  over-forecast (`pp1_results.md`: +14 to +22 %) and the reason a flat whole-herd line can hide it.
  *(T1/T2: milking-cow exits and dry-offs; the regime-aware correction should use cows in milk.)*

## E4. History with gaps and the source change (`04_herd_gaps_and_source_change.png`)

* "Record source changes" marker sits about Aug 2022, matching D1 (first DelPro target month).
* Shaded "data gap or flagged record" bands: about Sep to Oct 2022, around Mar to Apr 2024 and mid
  2024, the broad Oct 2024 to Aug 2025 block, and short bands in late 2025 and early 2026 (D1
  Appendix B). The recorded milk line breaks at each.
* Total herd falls from about 2,900 (2021) to about 1,700 (mid 2024) and stays; milking cows fall
  from about 1,200 to about 400. Forecast date about Aug 2026: milking cows about 410, forecast
  rising to about 450 to 550 with a shaded band; total herd flat about 1,700.
* Takeaway: anything fitted on the pre-2022 herd is a different farm; and for the last two years
  most of the forecast origins sit next to a gap.

## E5. Milk per month 2015 to 2024 (`05_milk_per_month_2015-2024.png`)

* Recorded milk: startup ramp from zero in Aug 2015, peak about 975k L/month (spring 2016), trough
  about 375k (Dec 2016 / Jan 2017), second peak about 830k (mid 2017), then a long fall through
  2018 to 2022, to about 100k in Aug 2022. After the break it resumes at about 80k to 130k.
* Total herd (grey) and milking cows (teal) fall much less than milk over 2021 to 2022: the same
  drop in litres per recorded cow that D1 shows (12 to 5 L, Aug 2020 to Jul 2022).
* Takeaway: one chart makes the three regimes visible (startup, shipment decline, DelPro), and
  explains why a pooled accuracy number hides the real story.

## E6. What the charts add to the task list

| Chart | Problem | Task |
|---|---|---|
| E1 | Implausible yield per cow (about 28 to 30 L) at the first development origins | T2 mask and per-cow target; T6 caveat on origins 2017-01 to 2017-03 |
| E2 | Culling wave not forecastable; yield per recorded cow doubles while milking cows halve | T2 quality features; T5 denominator and entry-lag items; T4 intervals |
| E3 | Whole herd on point but milking cows over-forecast, milk over-forecast about 27 % | T2 correction conditioned on cows in milk; mention milking-exit modelling as a known limit |
| E4 | Gaps cluster around the last two years of origins | T1 live outlook behaviour; T6 test-block wording |
| E5 | Regime changes visible in the raw series | T6 talk slide on regimes |

---

# Appendix F: the regime labels used so far are too coarse (checked 2026-10-21)

`pfoi/regimes.py` labels a forecast by the **target period's** `target_source` and calendar date
(`shipment`, `delpro_2022_2024`, `delpro_gap`, `delpro_from_2024_05`). Checked on the saved dev errors
of `milk_baseline_adaptive` (`..._kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3`, MAE ratio to persistence on
matched periods; origin source = `k_source`):

1. **Origin and target source differ near the break.** "delpro_2022_2024" mixes forecasts issued in the
   DelPro era with forecasts issued **before** Aug 2022 that land after it.

   | Grain, horizon | Same-source DelPro: n, ratio, bias | Cross-break (origin shipment, target DelPro): n, ratio, bias |
   |---|---|---|
   | daily h1 | 56, 1.32, +0.4 % | 3, 4.37, +67 % |
   | daily h14 | 54, 1.39, -0.3 % | 6, 1.63, +68 % |
   | weekly h4 | 46, 1.45, -2.2 % | 5, 1.26, +43 % |
   | weekly h8 | 42, 1.65, -5.8 % | 9, 1.69, +58 % |
   | weekly h13 | 40, 1.27, **-24 %** | 11, 1.93, **+55 %** |
   | monthly h3 | 6, 1.10, -23 % | 2, 4.36, +69 % |

   The two groups have **opposite-signed bias**, so the pooled DelPro bias (for example weekly h13
   -5 %) hides both. Same-source DelPro **under**-forecasts at long horizons; cross-break forecasts
   **over**-forecast heavily. Same-source DelPro is still worse than persistence (daily 1.17 to 1.39,
   weekly 1.15 to 1.65), so the weakness is real, but the earlier "DelPro regime over-forecasts" reading
   was wrong.
2. **The shipment era is not one regime.** Aug 2020 to Jul 2022 (yield 12 down to 5 L per recorded cow,
   identified share decaying) differs from 2017 to Jul 2020: monthly bias h6 +12.1 % vs +8.6 %, h12
   +23.7 % vs +3.6 %; weekly ratio h4/h8 0.80/0.79 vs 0.91/0.91.
3. **"Three sources" is really two record sources plus a data-state split.** The target has two sources
   (shipment, DelPro). The 2024-05 onward label is a restart after a gap, not a source change; and
   DelPro itself changes meaning through the identified share (0.998 to 0.001 to 0.90) and recorded
   milking cows.
4. **Boundaries were read from monthly aggregates, not tested.** `pfoi/breaks.py` and `break_eval.py`
   exist; use them (origin-known breaks only) before naming a regime.
5. **Sample sizes** in the same-source DelPro cells are small (monthly 8, 6, 5, 1 periods at h1/3/6/12;
   weekly about 40 to 50 overlapping periods). Treat as indicative.
