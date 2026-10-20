# PFOI (Component 1): results for Progress Presentation 1

Predictive Farm Outlook Intelligence for **Farm X**, herd level only. Frozen model
`pfoi-1.0.0` (configuration `3cbd28787fcb`), core version `p20261018T125214Z`.
All numbers below are herd-level aggregates from rolling-origin backtests; no animal-level
data. "Ratio" = model MAE ÷ persistence MAE (below 1 = the model is better).

---

## 1. Method in brief

**Question.** Can a structural herd model forecast herd milk and herd events better than
simple benchmarks, while explaining every number?

1. **Herd engine (Step 3).** A daily, cohort-based Markov herd model (after St-Pierre et
   al. 2001). It starts from the recorded herd on the day before the forecast date and
   moves animals through calf → heifer → pregnant → calving → milking → dry, with
   births, abortions, deaths, culls, sales and purchases. Rates are learned from the
   **12 months** before each forecast date, with small groups shrunk toward the herd rate
   (beta-binomial). Male and female calves are separate, and exits are calibrated to the
   daily herd totals.
2. **Milk model (Step 4).** Herd milk = *k* × Σ (cows by parity, days in milk and pregnancy
   stage × lactation-curve yield). Wood curves per parity are fitted on the farm's own
   reliable cow-days (from Sep 2020). Before that, the curve **shape is fitted to past
   herd shipments**, with a published Jersey-crossbred curve (Mandal et al. 2026) kept as
   the sensitivity run. *k* is anchored on the last 14 recorded days.
3. **Explanation (Step 5).** Every month-to-month milk change is split by **Shapley
   values** into herd size, parity mix, lactation-stage mix, pregnancy mix and yield
   level. The parts add up **exactly**; for past months the residual is reported
   separately. Herd changes are split into flows, and calvings into *already determined*
   (pregnancies recorded before the forecast date) vs *rate-driven*.
4. **Honest evaluation.**
   - **No future data:** every input is dated before the forecast date, enforced by code
     and tested.
   - **Design choices on the development block only:** origins 2017–2023.
   - **One final test on the frozen model:** origins 2024 – Aug 2026, enforced to run once.
   - **Intervals:** 5–95 % ranges come from the model's own past errors.

**Benchmarks.** Persistence (same as last period), seasonal naive (same period last
year), ETS and SARIMA.

---

## 2. Development block (origins 2017–2023): H1 supported

**Herd milk, monthly.** Every model is scored on the same periods (common periods).

| Months ahead | 1 | 3 | 6 | 12 |
|---|---|---|---|---|
| **PFOI milk baseline** | **0.62** | **0.63** | **0.61** | **0.75** |
| PFOI, bias-corrected | 0.61 | 0.55 | 0.51 | 0.61 |
| ETS | 1.38 | 1.63 | 2.02 | 2.05 |
| Seasonal naive | 3.78 | 1.62 | 1.09 | 1.00 |
| Persistence | 1.00 | 1.00 | 1.00 | 1.00 |
| *periods scored* | *53* | *50* | *49* | *46* |

**SARIMA** could run on only 24 months, because it needs 36 unbroken months. On those
months it scored 1.12 / 1.01 / 1.00 / 0.99, against 0.69 / 0.90 / 0.82 / 0.81 for the
PFOI baseline.

**Other grains:**
- **Weekly milk** (4 / 8 / 13 weeks ahead): 0.83 / 0.77 / 0.68.
- **Daily milk** (1 / 7 / 14 days): 1.14 / 1.03 / 0.94. That's about a tie, because herd
  milk barely moves within two weeks.
- **Month-1 error:** 5.2 % MAPE, the lowest of all models.

**Herd events, monthly** (12-month window):

| Months ahead | 1 | 3 | 6 | 12 |
|---|---|---|---|---|
| Calvings | 0.73 | **0.23** | **0.16** | 0.67 |
| Milking cows | 0.85 | 0.75 | 0.80 | 0.67 |
| Total herd | 1.16 | 1.27 | 1.22 | 0.86 |
| Real abortions | 1.08 | 1.01 | 0.78 | 0.80 |

**H1 is supported in development:** the structural baseline beats persistence and seasonal
naive at 3–6 months, by about 37–39 % for milk. Calvings are forecast 4–6 times better than
persistence at 3–6 months, because pregnancies already recorded fix most of them.

**Development decisions** (recorded in `herd_engine.md` and `milk_model.md`):
- **Window:** 12 months, mean ratio 0.82 against 0.87 for 24 months.
- **Early curve:** herd-fitted shape, better than the published one at 3–12 months.
- **k:** anchored, which removed a ~20 % starting-level error.

---

## 3. Final test (origins 2024 – Aug 2026, frozen model, run once)

**Herd: partly confirmed.**

| Monthly ratio | 1 | 3 | 6 | 12 |
|---|---|---|---|---|
| Calvings | 1.97 | **0.87** | **0.48** | **0.89** |
| Calvings, bias-corrected | 0.79 | 0.63 | 0.61 | 0.92 |
| Dry-offs | **0.62** | **0.77** | **0.64** | **0.74** |
| Milking cows, bias-corrected | **0.89** | **0.86** | **0.91** | **0.86** |
| Total herd | 1.02 | 1.21 | 1.48 | 2.24 |
| Real abortions | 1.33 | 0.97 | 1.13 | 1.01 |

**Milk: not confirmable monthly, worse than persistence at short range.**
- **Monthly:** only 5 / 3 / 2 / 1 months could be scored. The reasons:
  - the Oct 2024 – Aug 2025 data gap, which is never scored;
  - 12 forecast dates with no clean months left to calibrate *k* after the gap;
  - SARIMA never had 36 unbroken months.

  The monthly ratios (1.09 / 2.00 / 0.93 / 2.04) are **not interpretable** on 1–5 points.
- **Weekly:** 1.32 / 1.48 / 1.24 / 1.67 on 35 / 30 / 24 / 16 periods.
- **Daily:** 1.27 / 1.25 / 1.45 on about 40 periods.

**What the test tells us.**
1. **Calvings and dry-offs hold up** out of sample, because they come mostly from the
   recorded pregnancy pipeline.
2. **Total herd is under-forecast** by about 260 animals at 12 months. The herd recovered
   after the 2023 fertility drop: pregnant heifers −133, dry pregnant cows −95 at 12
   months. Meanwhile the 12-month window was still learning from the bad year. This is a
   **regime change**, the case that H4 (updating after errors) targets.
3. **Milk is fragile after long data gaps.** The 11-month gap left too few clean months to
   recalibrate. Short-range forecasts lose to persistence.

These results are reported as they are. Any fix (for example faster recalibration after a
gap) will be a new version, `pfoi-1.1`, and its results on 2024–26 will be labelled
post-hoc.

---

## 4. The 2026 outlook (forecast date 1 Aug 2026)

| Month | Herd milk (L/month) | ≈ L/day | 5–95 % range |
|---|---|---|---|
| Aug 2026 | 130,600 | 4,210 | 116k – 150k |
| Oct 2026 | 143,600 | 4,630 | 96k – 167k |
| Dec 2026 | 167,800 | 5,410 | 103k – 189k |
| Jan 2027 (peak) | 168,300 | 5,430 | 104k – 190k |
| Apr 2027 | 150,400 | 5,010 | 60k – 167k |
| Jul 2027 | 146,900 | 4,740 | 59k – 163k |

**The story, explained by construction:**
- **Milk rises about 29 % to the Dec–Jan peak** because more cows come into milk. Herd size
  adds +70 to +378 L/day in each month from Sep to Dec, and the stage mix adds +35 to +80
  as more cows are fresh.
- **Calvings outpace dry-offs:** 55–78 calvings a month against 37–44 dry-offs, so milking
  cows grow by 11–33 a month until December.
- **All calvings to Feb 2027 are already determined** by pregnancies recorded before
  August 2026. Rate-driven calvings only take over from May 2027, at about 41–46 a month.
- **Then a slow decline in 2027,** as calvings fall (only 12–16 in April). The 2027 ranges
  are wide and lopsided, because past long-horizon forecasts were often too high: read
  the range, not the line.

---

## 5. Supporting findings

- **Fertility by generation** (descriptive; generation is confounded with time):
  - services per conception in 2023–26: generation 0 = 3.76, 1 = 5.50, 2 = 5.87;
  - abortions, generation 0: 3.3 % (2020–22) → 11.2 % (2023–26).

  This is a within-period reversal of the pooled trend (Simpson's paradox).
- **Mastitis recording gap.** At the last-12-months rate, expected mastitis episodes are
  **0** a month, against 6.7–8.2 at the 2016–18 rate. Diagnoses have stopped being
  recorded; this is not an absence of mastitis.
- **Record consistency.** Milking cow-days rebuilt from lactations match the daily herd
  within ~1 % up to 2023, but are 8.6 % higher in 2025–26. This is a data-quality issue
  to raise with the ETL.

---

## 6. Limitations

1. **Total herd** is under-forecast after the 2023→2025 fertility recovery (regime change).
2. **Milk after long gaps:** *k* recalibration and SARIMA both need clean history; the
   final test could score only 1–5 months.
3. **Intervals are too narrow:** monthly 90 % ranges covered 42–77 % in development (H3).
4. **Heat (THI) and mastitis are not factors yet.** They sit in the past-month residual
   (planned H2 layer).
5. **The published curve's time unit is assumed** (per fortnight). This now affects only
   the sensitivity run.

**Next (H2–H4):** a learned deviation layer for heat, mastitis and events (H2);
quality-aware intervals (H3); and error-triggered updating for regime changes and gaps
(H4).

---

## 7. Two-minute talk outline

1. **(15 s) Problem.** Forecast Farm X's herd and milk, with every number explained.
2. **(30 s) Method.** Daily herd engine plus lactation curves. Learned only from data
   before each forecast date. Shapley explanation that adds up exactly.
3. **(30 s) Development result.** Milk is about 40 % better than persistence at 3–6
   months; calvings are 4–6 times better.
4. **(25 s) Honest final test.**
   - Calvings and dry-offs confirmed.
   - Milk can't be judged monthly after an 11-month data gap.
   - The herd recovered faster than the model learned.
5. **(20 s) Outlook and next steps.** Milk peaks at about 5,400 L/day in Dec 2026–Jan 2027,
   driven by recorded pregnancies. Next: H2–H4 for heat, data quality and regime
   changes.
