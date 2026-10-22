# Stability gate and specialists (1.2.1-dev, G-series)

Design agreed with the user on 2026-10-22: **pfoi-1.2.0-dev stays the forecaster in stable
conditions. A gate judges at each forecast date whether Farm X is in an unstable position, and
only then does a specialist make its own forecast.** Persistence is never a specialist (benchmark
only). Models must be free (open licence, local weights). Code: `pfoi/gate.py`; tests:
`tests/test_gate.py` (synthetic, no database).

Why a gate rather than another correction layer: a correction learns from finished errors, and a
12-month error is only known 13 months later, by when the yield trend has often turned (week-13
yield error +21 % in 2022, −21 % in 2023). The gate reads signals that are fresh at the forecast
date (last weeks' short-horizon errors, record quality, yield volatility), and its labels are
mostly short-horizon ones, which close within days.

## G1: can unstable positions be recognised? (go/no-go, implemented)

* **Label** (training only): 1.2.0-dev's forecast was more than 10 % from the record. Trusted
  periods only (band normal or degraded). For fold year Y only labels whose period ended by
  1 January Y are used; the test block (2024 onward) is never read.
* **Signals** (all from days before the forecast date): the base model's finished errors over the
  last 6 weeks and the 6 months before (size, sign, jump, count); litres per recorded milking cow on
  trusted days (28-day change, its size, volatility); trusted-day share (28/90 days), days since
  the last trusted day; identified share; age of the current milk source; 90-day change in milking
  cows; age of the latest break found by `breaks.detect_breaks`; **filtered** probability of the
  high-variance regime of a two-regime Markov-switching model of weekly yield-per-cow changes
  (parameters refitted each quarter on earlier weeks; the smoothed probability is never used).
  Missing stays missing.
* **Gates**, refitted once per fold year 2019–2023 with fixed settings (no selection in G1):
  the horizon's training miss rate (no-skill reference), logistic regression, shallow LightGBM.
  Both learned gates start from the reference (LightGBM `init_score`, logistic input) so they only
  explain why an origin is riskier or safer than usual for its horizon.
* **Scores:** Brier skill against the reference, AUC **within each grain × horizon cell** (the
  horizon alone predicts misses, so a pooled AUC would overstate skill), single-signal AUCs.
* **Switching check:** when the LightGBM gate says unstable (p > 0.5), use the existing
  non-persistence alternative (`milk_baseline` raw, ETS, SARIMA, seasonal naive) that hit best on
  1.2.0-dev's earlier misses. A lower bound for the specialists of G2; the hindsight best-of
  ceiling is printed and labelled as not a forecast.

**Pre-registered rules (fixed 2026-10-22, before any real-data run):**

1. *G1 go rule:* a learned gate has Brier skill > 0 and within-cell AUC ≥ 0.65 over 2019–2023, and
   Brier skill > 0 in at least 3 of the 5 fold years. Otherwise NO-GO: instability is not
   recognisable from these signals, and the path changes (more or different signals, or cow-level
   data) instead of building specialists.
2. *AUC target (user):* within-cell AUC about **0.80**, especially at long horizons (week 13,
   months 6 and 12). Reported per gate × cell with n, misses, months and a 5–95 % bootstrap
   interval over origin months; "reaches" = estimate ≥ 0.80, "lower end reaches" = interval's lower
   end ≥ 0.80.

**Known limits (synthetic evidence, not Farm X results):**

* With episodes whose onset is not visible at the forecast date (synthetic yield ramps), most
  long-horizon misses come from origins *before* the change starts; no signal at the origin can
  flag them. There the gates failed the go rule, and single signals even flipped sign between
  episodes. Only origins inside an ongoing episode are catchable.
* Monthly cells have about 50 forecasts and under 10 misses per cell over 2019–2023. Even when
  every miss is detectable by construction (true AUC ≈ 0.85), month-12 estimates came out
  0.72–0.74 with intervals about 0.53–0.90. **A monthly AUC of 0.80 can be neither confirmed nor
  ruled out at that n**; week 13 (about 250 forecasts) can.

### Command (user-run; reads saved development error files and herd-level daily aggregates)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli gate-audit
```

Defaults: base `milk_baseline_adaptive` from the pfoi-1.2.0-dev tag, alternatives from the raw
tag. `--no-markov` skips the Markov signal if it is slow. Prints and saves (in `logs/pfoi/`)
herd-level aggregate tables only, plus `gate_probs_*.csv` (herd-level gate probabilities per
forecast, input for G2).

### G1 result (user run, 2026-10-22; development, fold years 2019–2023, trusted labels)

**Verdict by the pre-registered rule: GO** (both gates). Logistic: Brier skill 0.124, within-cell
AUC 0.776, skill in 3 of 5 fold years (2019, 2022, 2023). LightGBM: 0.085, 0.677, 3 of 5.
1,790 scored forecasts, 445 misses. The simpler logistic gate beats LightGBM, as expected with
about five instability episodes.

**User AUC target 0.80 (logistic, estimate and 5–95 % interval):** reached as a point estimate at
day 1 / 7 / 14 (0.85 / 0.83 / 0.82) and week 1 / 4 (0.81 / 0.80); lower end of the interval never
reaches 0.80. **Not reached at long horizons:** week 13 0.70 (0.59–0.80); month 6 0.41 and month
12 0.38 (below chance; LightGBM 0.60 / 0.64, intervals from about 0.43 to 0.81). Monthly cells have
34–45 forecasts.

What the gate does and does not learn:

* **Regime, not timing.** Within a single fold year the gates barely rank forecasts (logistic
  within-year AUC 0.53 / 0.29 / 0.56 / 0.54 in 2020–2023; 0.84 in 2019 on 16 misses). The pooled
  0.776 comes mostly from recognising *which periods are unstable* (2022–2023 miss rates 0.53 and
  0.57 against about 0.15 in training): Brier skill 2023 +0.34, 2022 +0.11. It got the 2020 source
  switch wrong (−0.53) and in 2021 the signals flipped direction (AUC 0.29).
* **Strongest single signals (within-cell AUC, all years):** size of 1.2's errors over the last 6
  weeks 0.83, yield-per-cow volatility 0.82, **Markov filtered high-variance probability 0.82**, size
  of earlier errors 0.81, size of the 28-day yield change 0.74; low identified share (0.23, i.e.
  0.77 in the other direction) and low 90-day trusted share (0.25). Per year all are much weaker.
* **Long horizons are not a gating problem.** At month 12, 25 of 34 forecasts (74 %) miss and at
  week 13 105 of 218 (48 %): failure is the norm in 2019–2023, so there is little "stable" to keep.
* **Switching to existing models does not help.** Week 13 0.518 → 0.523; month 3 0.581 → 0.605;
  month 6 0.450 → 0.400; month 12 0.265 → 0.235. Even the hindsight best of 1.2, raw structural,
  ETS, SARIMA and seasonal naive reaches only 0.716 (week 13), 0.600 (month 6), 0.382 (month 12).

**Consequence (path change):** the gate is used where it works, short and medium horizons (day 1 to
week 8, month 1 to 3), to send unstable regimes to a specialist. Weeks 13 and months 6–12 need a
**different long-horizon forecaster scored on all periods**, not a gate; no existing model, even
chosen with hindsight, gets there.

## G2: specialists (implemented and tested, real-data runs pending)

Code `pfoi/specialists.py`, tests `tests/test_specialists.py` (synthetic, stand-in model; no
database, no download). Rules below were fixed 2026-10-22, before any real-data run.

**Track A: day 1 to week 8, month 1 to 3, gated.** S1 `s1_relevel` = raw structural forecast
(`milk_baseline`) x exp(mean log error of its own finished forecasts with lead at most 14 days whose
period ended in the 14 days before the forecast date; trusted periods only; at least 2 such errors,
level capped at a factor of 2). The engine's cow path and curve stay; this is not persistence.
`gated_s1` uses S1 only where the G1 logistic gate (fitted on earlier years) gives p > 0.5 and only in
Track A cells; elsewhere it is 1.2.0-dev unchanged. Scored on the periods the gate scored (trusted,
fold years 2019–2023). **Keep rule:** mean share within ±10 % over the Track A cells rises by at
least 2 points, no Track A cell falls by more than 1 point, 2019 (stable) falls by at most 1 point.

**Track B: week 13 and months 6–12, every period, no gate.** Zero-shot Chronos-2 (`amazon/chronos-2`,
Apache-2.0, 478 MB `model.safetensors`, run locally on CPU) forecasts weekly litres per recorded
milking cow (weeks with at least 4 trusted days; weeks of the current milk source only; weeks that
mix two sources or have no trusted days are missing and masked by the model; weeks that ended
before the forecast date only). `chronos2_ypc_x_engine` = engine-projected mean milking cows of the
target period (saved herd backtest, `herd_engine`, series `milking`) x the forecast yield summed
over the period's days. `chronos2_milk` (direct herd litres per day) is reported beside it. Nothing is
fitted on Farm X, so all development origins 2017–2023 are scored, matched with 1.2.0-dev on trusted
periods. **Keep rule:** share within ±10 % rises at week 13, month 6 and month 12, and no development
year falls by more than 5 points (a year's share = mean of those three cells).

Synthetic smoke test of the real model (no farm data): 450 series x 60 weeks in 1.7 s on CPU;
seasonal continuation MAE 0.017; missing weeks handled; **a steady decline is extended** (7.9 → 4.9
over 60 weeks), so it may follow a 2021–22-type decline but overshoot a turn like 2023.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli specialist-a
python -m components.predictive_farm_intelligence.pfoi.cli specialist-b
```

Both read saved development error files (and, for B, the saved herd backtest
`herd_backtest_errors_{monthly,weekly}_w24_ck_kn_rk_lag90_hl6.csv`) plus herd-level daily aggregates;
print aggregate tables only; write new error files tagged `_gs1` / `_chronos2`; no database writes.

### G2 results (user runs, 2026-10-22, development): both DROPPED by their pre-set rules

**Track A, gated S1: DROP.** Mean share within ±10 % over Track A cells +0.010 (rule ≥ +0.02); worst
cell −0.009 (weekly 1); 2019 unchanged. The logistic gate switched only in 2022 (16.5 % of Track A
forecasts) and 2023 (32.5 %). Where it switched it helped: Track A mean 2023 0.417 → 0.487, 2022
0.508 → 0.515; month 3 0.581 → 0.628 (n 43), week 8 0.628 → 0.659 (n 223), week 4 0.771 → 0.789.
Too few unstable periods for the overall gain to reach 2 points. S1 *ungated* is worse than 1.2.0-dev
in almost every cell (month 6 0.462 → 0.205), so the gate is what made S1 safe.

**Track B, zero-shot Chronos-2: DROP.** Matched trusted periods, development 2017–2023:

| Cell | n | 1.2.0-dev | Chronos-2 yield x engine cows | Chronos-2 direct milk |
|---|---|---|---|---|
| week 13 | 291 | 0.598 | 0.447 | 0.495 |
| month 6 | 58 | 0.552 | 0.293 | 0.310 |
| month 12 | 56 | 0.429 | 0.214 | 0.268 |
| week 1 | 312 | 0.933 | 0.936 | 0.946 |
| week 4 | 307 | 0.818 | 0.824 | 0.788 |

Worst year (mean of the three long cells) −0.425 (2017: 0.536 → 0.111). Chronos-2 was better only in
2022 (direct milk 0.118 against 0.018, n 29) and 2023 (yield x cows 0.278 against 0.111, n 18). The
smoke test's trend extension shows in the stable years (2017, 2021), where it carried short-run moves
far forward. Issued 88–95 % of the trusted periods (current-source context needs 26 known weeks).

**What G1 + G2 establish (development data, Farm X):**

1. The structural model is the best long-horizon forecaster tested: no gate, re-level or zero-shot
   foundation model beats it at week 13 or months 6–12 over 2017–2023.
2. Every challenger wins only inside 2022–2023, the regime where 1.2.0-dev fails most (month 12 hit
   rate 0.018 in 2022). Those are also the years with the recording problems documented in
   `accuracy_plan_prompt.md` (litres per recorded milking cow 3–5 against 10–19 before, low
   identified share, late event entry). With 18–29 long-horizon periods there, a "gated long-horizon
   specialist" would be a hypothesis formed after seeing these results, not a tested model.

## Later

* More free pretrained models as further Track B rungs (Granite TTM r2.1 few-shot fine-tuned per fold;
  TimesFM 2.5 after confirming its licence on the official card; Chronos-Bolt), and Chronos-2 with the
  engine path as a known future input.
* G3 combination and intervals once a specialist is kept.

## Record check (user query, 2026-10-22; monthly herd-level aggregates, 2020-01 to 2024-02)

* **The milk target switched from shipment to DelPro in August 2022, not August 2020.** Every month to
  July 2022 has `target_source = shipment`; from August 2022 it is `delpro`. August 2020 is when DelPro
  identified-share data starts. Labels saying "source switched Aug 2020" (forecast-year tables,
  `handoff_1_2_1_dev.md`) are wrong; the stage-2 "DelPro 2020-08" split in `neural.py` actually trains on
  shipment targets until July 2022 (that GRU result is confounded). Target gaps: September–October
  2022 and most of November 2022.
* **Recorded milking cows** fell 1,553 (Jan 2020) → 1,062 (Jan 2022) → about 850 (2023) → 697 (Feb 2024).
* **Litres per recorded milking cow-day:** 14.6 (Jan 2020) → 12.0 (Jan 2021) → 10.3 (Jan 2022), then
  **halved in six months to 5.1 (Jul 2022) while recorded cows held at about 1,030–1,175** (shipment
  era). Herd litres per day (derived, litres per cow x cows): about 22,700 (Jan 2020), 10,900
  (Jan 2022), 5,500 (Jul 2022).
* **At the switch to DelPro the level steps down again,** 5.07 (Jul 2022, shipment) → 3.18 (Aug 2022,
  DelPro), and stays 2.9–4.8 through 2023 while identified share falls 0.79 → 0.39. A change of
  measurement at the switch, not only biology.
* Public context (not farm data): Sri Lanka's 2022 economic crisis brought feed, fuel and veterinary
  input shortages; the dairy industry association reported feed shortages in April 2022. A hypothesis
  for the first half of 2022, not established by these aggregates.
* User hypothesis (2026-10-22): the fall is linked to the shrinking herd and slowing calvings (later
  lactation stages lower litres per cow). Checked by the herd-structure query in the session notes
  (DIM-band shares, calvings, dry-offs, exits per month).

## Nested hyperparameter tuning (implemented and tested, real-data runs pending)

Code `pfoi/tuning.py`, tests `tests/test_tuning.py`. For each fold year 2019–2023 the settings are chosen
on labels ended by 1 January only: inner chronological 80:20 split by forecast date, training labels
ending at least the grain's longest horizon before validation starts (14 / 91 / 365 days), best setting
refitted on all inner data and used unchanged for the year. The keep rules are the G2 rules, unchanged.

* **Gate:** 23 settings (logistic C 0.02 / 0.1 / 0.5 / 2; LightGBM leaves x depth 2x1 / 4x2 / 8x3,
  50 / 150 / 400 trees, minimum leaf 20 / 50; G1 defaults first), by validation Brier score.
* **Track A switch:** S1 window 7 / 14 / 28 days x gate threshold 0.3–0.7, by validation share within
  ±10 % over Track A cells.
* **Track B (Chronos-2):** context current source / all sources x 520 / 260 / 104 weeks x median / mean,
  by validation share within ±10 % over week 13, month 6, month 12. Each fixed setting's 2019–2023
  score is printed as hindsight, to show the optimism of tuning.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli tune-gate
python -m components.predictive_farm_intelligence.pfoi.cli specialist-b --tune
```

### Tuning results (user runs, 2026-10-22, development): no verdict changes

* **Gate tuning made it worse overall:** tuned Brier skill 0.082, within-cell AUC 0.710 against the G1
  logistic gate's 0.124 and 0.776. Inner validation was too small to choose reliably (validation
  misses 12 / 1 / 34 / 11 / 118 for 2019–2023; 2020 could not be tuned and kept the default). Long
  cells: month 6 0.707 (G1 logistic 0.407), week 13 0.555 (0.702), month 12 0.551 (0.378); none reaches
  0.80.
* **Track A tuning chose the default (14 days, p > 0.5) in every year;** rule still fails (+0.006,
  rule +0.02). DROP.
* **Track B tuning:** shorter context chosen in 2020–2021 (104 weeks), 260 weeks in 2022, all sources in
  2023. Still far worse than 1.2.0-dev (fold years 2019–2023, matched): week 13 0.431 vs 0.554, month 6
  0.324 vs 0.459, month 12 0.125 vs 0.250; worst year −0.253. DROP. Even the best fixed setting with
  hindsight (current source, 104 weeks: 0.335 mean over long cells) is below 1.2.0-dev (about 0.42).
  Chronos-2's "mean" output equals its median here, so the grid had 6 distinct settings, not 12.

## Herd-structure check (user query, 2026-10-22; monthly herd-level aggregates 2019-01 to 2024-02)

User hypothesis: the yield-per-cow fall comes from the shrinking herd and slowing calvings (later
lactation stages). Findings:

* **It does not explain the 2022 halving.** January to July 2022, when litres per recorded milking cow
  fell 10.3 → 5.1, calvings stayed 93–175 a month (2021: 66–144), the share of milking cows past 305 days
  in milk *fell* (32–33 % in Sep–Nov 2021 → 21–25 %) and the 0–60-day share rose to 16–23 %: a
  *fresher* herd, which should have raised yield per cow.
* **Partly consistent with the slower 2021 decline** (12.0 → 9.2): the 305-days-plus share was 29–35 %
  from August 2020 to November 2021. But the same share in late 2020 came with about 12 litres, so
  stage mix is a weak explanation there too.
* **First-parity share** rose 20 % (2019) → 33 % (2022), then fell to 8 % (2024). First calvers give less
  milk, but a 12-point rise moves herd yield per cow by a few percent at most (assumed first-calver yield
  about 80 % of older cows), not by half.
* **The herd shrank after the crash, not before:** mean herd about 3,300 (2019–2021) → 3,040 (Jan 2022)
  → 2,580 (Dec 2022) → 2,420 (2023); exits 150–220 a month from August 2022. Milking cows fell earlier
  (1,550 in 2020 → 1,060 in Jan 2022) while total herd held, and dry-offs were high in late 2021.
* Reading (opinion): the 2022 crash is not a herd-structure effect the engine could have projected; it
  fits an external shock (feed) or a change in what was shipped. Whether production or only shipment
  fell needs the shipped / internal / DelPro comparison.

## DelPro-only check (user queries, 2026-10-22; herd-level aggregates)

* **Availability (days with DelPro litres):** 2020 133 (from August), 2021 365, 2022 219 (none in May,
  September, October; partial April, June, July, November), 2023 361. Test block: 2024 198 days but none
  with identified share ≥ 0.6; 2025 only 4 days with share ≥ 0.2; 2026 106 days with share ≥ 0.2.
  Shipments stop after July 2022 (2022: 208 shipment days; none from 2023).
* **DelPro captures 65–106 % of shipped litres, drifting:** ratio 0.69 (Aug 2020) → 0.76–0.85 (2021) →
  0.83–1.06 (2022). Not a fixed share, so the two series are not interchangeable.
* **Corrections to earlier notes:**
  1. Production really fell in 2022: DelPro litres per day 10,217 (Jan 2022) → 7,703 (Jun) → 3,931 (Jul)
     → 3,142 (Aug), with no source change inside the series. The mid-2022 step is **not** mainly a
     measurement change at the switch, as stated above; it is in DelPro too.
  2. **The 2021 decline is much milder in DelPro.** DelPro litres per recorded milking cow 9.05 (Jan 2021)
     → 8.70 (Dec 2021), about −4 %; shipment litres per recorded cow 11.99 → 9.88, about −18 %, over the
     same months. From Aug 2020 to Jun 2022 shipments fell about 59 % (17,857 → 7,295 litres a day) and
     DelPro about 32 % (11,344 → 7,703). Part of the shipment decline that broke the 2021 forecasts was
     not production.

## DelPro-only target experiment (implemented and tested, real-data run pending)

Code `pfoi/delpro_target.py` (target rules, source wrapper, rule), `SqlHerdSource.delpro_daily`
(read-only), `backtest-milk --target delpro` (tag suffix `_tdp`, development block only) and
`compare-target`; tests `tests/test_delpro_target.py` (synthetic). The engine, curve, `MilkConfig` and
frozen hashes are unchanged; only the target and therefore the level k change.

Daily target: `milk_delpro_total` where above zero (else missing); scoreable when no gap, identified
share ≥ 0.2, ≤ 20 L per recorded milking cow, and not below half the mean of the previous 28 days'
scoreable days (past only). Origins before DelPro records exist are withheld and counted.

**Pre-registered rule (2026-10-22):** on periods trusted under both targets (development origins from
2020-08), the DelPro-target 1.2.0-dev model's share within ±10 % rises at week 13, month 6 and month
12; no forecast year falls by more than 5 points (mean of those cells); and 2021 rises. The two
targets measure different things, so this tests which is more forecastable; changing the published
target remains the user's decision.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --target delpro --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli adapt --family milk --tags herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_tdp --q30 0.1 --tau 365
python -m components.predictive_farm_intelligence.pfoi.cli compare-target
```

### Result (user run, 2026-10-22): not shown better, so the recorded target stays

Backtest: 44 of 84 monthly and 191 of 365 weekly origins were withheld (no trusted DelPro days before
them, as expected before 2020-08 and in gaps). Periods trusted under both targets, origins from
2020-08, share within ±10 % (DelPro-only vs recorded):

| Cell | n | DelPro-only | Recorded |
|---|---|---|---|
| day 1 / 7 / 14 | 147–148 | 0.689 / 0.649 / 0.503 | 0.824 / 0.764 / 0.714 |
| week 1 / 4 / 8 / 13 | 118–129 | 0.760 / 0.444 / 0.303 / 0.254 | 0.829 / 0.675 / 0.549 / 0.458 |
| month 1 / 3 / 6 / 12 | 13–21 | 0.714 / 0.200 / 0.294 / 0.154 | 0.762 / 0.400 / 0.294 / 0.077 |

By forecast year (mean of week 13, month 6, month 12): 2020 0.593 vs 0.481; **2021 0.160 vs 0.352**;
2022 0.083 vs 0.125; 2023 0.299 vs 0.211. Rule: fails (week 13 −0.203, month 6 0, 2021 −0.192).

The DelPro target is **less** forecastable at almost every horizon, and the 2021 hypothesis fails:
although monthly DelPro litres per cow drifted only about −4 % in 2021, the model missed DelPro more
often. Likely reason (opinion, not tested): DelPro days are noisier (system outages, identification
swings), so the 14-day anchor of k and the short-horizon targets move more. Monthly cells have only
13–21 periods. Code kept, off; the recorded target stays.

## pfoi-1.2.1-dev: gate confidence flag and gate-conditional ranges (kept and built)

User decision (2026-10-22): the new development version is **pfoi-1.2.1-dev = pfoi-1.2.0-dev forecasts,
unchanged, plus the stability gate's confidence flag and ranges calibrated separately for low- and
normal-confidence forecasts**. (The 1.2.1-dev name was first used for the damped-trend candidate, which
was dropped.) Code `pfoi/gate_intervals.py` (backtest), `pfoi/gate_outlook.py` (page documents);
tests `tests/test_gate_intervals.py`, `tests/test_gate_outlook.py`.

* Flag: G1 logistic gate probability of a miss beyond ±10 % above 0.5 = `low`, else `normal`; gate
  fitted on labels ended by the forecast date. Herd rows take the mean of the milk probabilities of
  the same grain (flag only).
* Milk range (5–95 %): conformal quantiles of 1.2.0-dev's own past log errors (finished by the forecast
  date) at that grain and horizon, from past forecasts with the same flag (≥ 19), else all past errors.
* Synthetic check (perfect gate, unstable errors ±15 %, stable ±3 %): low-confidence 90 % coverage 0.585
  (pooled) → 0.795; normal ranges 64 % narrower at 0.888 coverage. Cold start: rows with fewer than 19
  earlier low-confidence errors fall back to pooled ranges.

**Keep rule (fixed 2026-10-22, before any real run; milk, trusted, forecast years 2020–2023, 90 %):**
low-confidence coverage closer to 0.90 than pooled and ≥ 0.80; normal coverage ≥ 0.85 with width at
most 10 % above pooled; all forecasts 0.85–0.95. Herd stocks reported, not ruled on.

The comparison documents were initially kept under `logs/pfoi/outlook/pfoi-1.2.1-dev/`. After reviewing
the comparison, the user kept the gated `pfoi-1.2.1-dev` version and built it.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli gate-intervals
python -m components.predictive_farm_intelligence.pfoi.cli gate-outlook
python -m components.predictive_farm_intelligence.pfoi.cli compare-runs --origins 2019-09-01 2020-08-01 2022-09-01 2023-06-01 2023-11-01 2024-07-01 --base pfoi-1.1.0 --candidate pfoi-1.2.0-dev --also pfoi-1.2.1-dev persistence
```

### pfoi-1.2.1-dev result (user run, 2026-10-22): gated version kept; interval rule failed

Milk, trusted periods, forecast years 2020–2023, 90 % range coverage (gate-conditional vs pooled):
all 0.681 vs 0.664 (n 1,338); low confidence 0.466 vs 0.319 (n 204); normal 0.720 vs 0.726 (n 1,134).
Rule: low closer to 0.90 than pooled **passed**; low ≥ 0.80 failed; normal ≥ 0.85 failed; all in
0.85–0.95 failed. By year (both methods): 2020 0.763, 2021 0.899, **2022 0.420**, 2023 0.563 (gate) vs
0.492 (pooled). Monthly low-confidence rows (n 19) had too few earlier flagged errors and kept pooled
ranges. Herd stocks (reported only): milking low 0.671 vs 0.619, normal 0.770 vs 0.772.

Reading: the gate moves ranges the right way (low-confidence coverage +15 points, wider ranges where
unstable, normal unchanged), but every 1.2.0-dev range is too narrow from 2022 on, flagged or not:
ranges are built from past errors, and the 2022–2023 errors were far larger than any earlier ones.
The under-coverage is a regime problem of the error history, not of the gate. The pre-registered
interval-calibration rule failed, but that result did **not** drop the gated model version: the user
kept and built `pfoi-1.2.1-dev`. The earlier damped-trend candidate that first used the 1.2.1-dev
name remains tested and dropped (code kept, off).

## G2 Track A2: LSTM-attention specialist behind the 1.2.1-dev confidence flag (tested, dropped)

User request (2026-10-22): where pfoi-1.2.1-dev's confidence is `low` (G1 logistic gate p > 0.5,
`gate_intervals.attach_gate`), a deep-learning model makes the milk forecast; elsewhere 1.2.0-dev is unchanged.
Code `pfoi/lstm_specialist.py`, command `specialist-lstm`; tests `tests/test_lstm_specialist.py` (synthetic,
no database). This differs from the rejected GRU (`neural.py`, 2026-10-21): it is used only on low-confidence
forecasts, trained on the whole history with both sources pooled, refitted per fold year, and it does not
correct the engine path.

* **Model `lstm_attn`:** LSTM over the 56 days before the forecast date (litres relative to the 28-day level R,
  trusted mask, day-on-day change, yield per cow and milking cows relative to their 28-day level, identified
  share), additive attention over those days (query = last hidden state), static features (source, source age,
  trusted share, season, 7-vs-28-day change and its size, 28-day volatility, yield-per-cow level, 90-day change
  in milking cows). Output: 98-day daily log path, |log(forecast / R)| <= 1. Covers day 1-14, week 1-13,
  month 1-3. Months 6 and 12 stay 1.2.0-dev.
* **Sensitive to major changes:** attention, change channels, and a loss weight
  `1 + |log(L7 / L28)| / 0.05` (capped at 4) on windows whose last week moved away from the 28-day level.
* **Not fed in order:** every past day is an independent window; windows shuffled every epoch.
* **Leakage:** fold year Y (2019-2023): training origins before 1 July Y-1 with targets masked from then;
  validation (early stopping only) origins 1 July Y-1 to 1 January Y, targets masked from 1 January Y.
  Test block never read. Synthetic test: a jump after the fold start leaves earlier forecasts identical.
* **Settings fixed before any real run** (`LSTMConfig`): hidden 32, attention 16, dropout 0.1, Adam 1e-3,
  weight decay 1e-4, batch 64, at most 150 epochs, patience 15, 5 seeds averaged.

**Keep rule (fixed 2026-10-22, before any real-data run):** the G2 Track A rule unchanged (mean over Track A
cells +2 points, no Track A cell -1 point, 2019 -1 point at most) **plus week 13 falls by at most 1 point**;
periods the gate scored (trusted, fold years 2019-2023). Also printed: hits on the replaced low-confidence
periods only, the LSTM ungated (descriptive) and attention on the last 7 days.

Expectation (before real numbers): G2's re-level helped only where the gate switched (2022-2023, about 16-33 %
of Track A forecasts), so the same +2-point bar is hard; a deep model has few unstable windows to learn from
(about five episodes).

```bash
python -m components.predictive_farm_intelligence.pfoi.cli specialist-lstm
```

**User-run result (2026-10-22): DROP.** Mean Track A hit-rate change +0.005 (rule +0.02),
worst cell -0.022 (rule no worse than -0.01), stable 2019 unchanged, and week 13 +0.060.
The LSTM alone was worse than the structural baseline in every displayed cell; attention on the
last 7 of 56 days was 0.125 in every fold (uniform after rounding). Code kept, off. The 2024+
final test block was not read.

## G2 Track C: structural gated TCN, direct weekly and monthly horizons (implemented, real-data run pending)

User request (2026-10-22): a deep-learning candidate that is highly sensitive to recent herd,
milk-per-cow and health changes, updates causally, and directly forecasts weekly and monthly cells.
Code `pfoi/tcn_specialist.py`, command `specialist-tcn`; tests `tests/test_tcn_specialist.py`
(fictional synthetic herd aggregates, no database).

* **Structure is retained:** the model predicts a bounded log correction to
  `milk_baseline_adaptive`, not unconstrained litres. Zero correction reproduces the baseline exactly,
  so a baseline change driven by projected milking cows passes through proportionally.
* **Direct outputs:** weeks 1, 4, 8 and 13; months 1, 3, 6 and 12. It does not create a daily path and
  sum it. Week 13 and months 6/12 have a tighter correction bound (x0.67 to x1.5); the other cells are
  bounded to x0.5 to x2.
* **Recent-change encoder:** a causal TCN reads the 112 days before the origin. Channels include
  trusted milk and yield per cow relative to their recent levels, changes in milking and total-herd
  counts, exits and real abortions per herd exposure, mastitis per milking-cow exposure, THI,
  identified share, and explicit recording/weather masks. Static features contain signed and
  absolute 7-vs-28-day changes plus the structural forecast at every output horizon.
  An isolated greater-than-twofold stock jump is masked until a second observation confirms the
  new level; two consecutive observations are retained as a real candidate break.
* **Continuous shock gate:** separate stable and shock experts are blended by a learned probability
  for each horizon. There is no hard p=0.5 switch. Training windows with large recent milk/cow/herd
  changes receive up to 4x loss weight.
* **Sparse health is not zero:** mastitis is usable only from the first positive record through 180
  days after the latest positive record. Outside that interval it is masked as not recorded.
* **Causal update:** after the TCN forecast, a small per-horizon adapter uses exponentially weighted
  log errors from this candidate's target periods that ended before the new origin (last 180 days,
  at least 3, 60-day half-life, capped at x0.8 to x1.25). This gives walk-forward updating without
  changing the encoder on one new observation.
* **Leakage:** fold year Y is trained only on origins before July Y-1 whose target periods ended by
  then. Validation origins are July--December Y-1 and only targets ended by 1 January Y count.
  The network is then frozen for origins in Y; only the completed-error adapter updates. The 2024+
  final test block is never read. Five deterministic seeds are averaged.
* **Fixed settings:** 112 days, six causal blocks with dilations 1/2/4/8/16/32, 32 channels,
  kernel 3, dropout 0.1, Adam 1e-3, weight decay 1e-4, batch 64, at most 150 epochs, patience 15.
  `--device auto` selects CUDA, then Apple MPS, then CPU; a forced unavailable backend fails rather
  than silently changing devices. CPU remains the exact reproducibility reference because GPU kernels
  can differ slightly even with identical seeds.

**Keep rule (fixed 2026-10-22, before the first real-data run):** over the eight weekly/monthly cells,
mean share within +/-10 % rises by at least 2 points; no cell falls by more than 1 point; stable 2019
falls by at most 1 point; and the observation-weighted hit rate on shock origins (maximum absolute
milk/yield-per-cow/milking/total-herd 7-vs-28-day log change at least 0.10, at least 16 matched cell
observations) rises. All checks must pass. No tuning follows the result; a failed candidate is recorded
and kept off.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli specialist-tcn
# Apple-silicon GPU explicitly (fails with a clear message if MPS is unavailable to Python):
python -m components.predictive_farm_intelligence.pfoi.cli specialist-tcn --device mps
```
