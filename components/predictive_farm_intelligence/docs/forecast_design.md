# Forecast design: herd dynamics and milk yield (Component 1, PFOI)

Purpose: the rules for the forecasting layer built on `core`. Written before any
model so that targets, leakage rules and evaluation are fixed in advance.
All outputs are herd-level aggregates; nothing here prints or stores row-level data.

## 1. Research framing

Prior work already forecasts herd milk from herd structure (St-Pierre et al.
2001, Markov herd cells; Gong et al. 2025, lactation-curve calibration). This
component uses that as its foundation. The contribution under test is:

- every past and future monthly value is **explained by construction**
  (herd flow, lactation biology, conditions, unexplained remainder);
- forecast **uncertainty reflects record quality** (identified share, gaps,
  source disagreement);
- evaluated on a tropical government farm with degraded, changing records.

Hypotheses:

| | Hypothesis | Evidence |
|---|---|---|
| H1 | Structural herd baseline beats persistence and seasonal-naive at 3–6 month horizons | Rolling-origin MAE |
| H2 | A learned deviation layer (THI, mastitis, events) improves on the baseline at short horizons | MAE on identical origins |
| H3 | Quality-aware intervals keep 85–95% coverage in low-quality periods | Coverage by quality band |
| H4 | Error triage (data fault / transient shock / persistent change) with selective updating beats always-refit and never-refit | MAE across change periods |

PP1 covers H1 plus attribution. H2–H4 follow.

## 2. Targets, grain, horizons

- The engine runs at **daily** resolution and sums to weeks and months, so the
  three grains are always consistent (week = Σ days, month = Σ days).
- Grains and horizons:

  | Grain | Horizons | Series |
  |---|---|---|
  | Daily | 1, 7, 14 days | herd milk only |
  | Weekly | 1, 4, 8, 13 weeks | milk, herd counts, calvings, dry-offs |
  | Monthly | 1, 3, 6, 12 months | all targets |

- Targets:
  - herd counts: calves, heifers (open/pregnant), milking, dry (open/pregnant), total herd;
  - events: calvings, AIs, real abortions, dry-offs, deaths, culls, sales;
  - herd milk (litres per month);
  - mastitis and udder/teat episodes (herd-level expected counts, low confidence).
- Forecast origins: monthly forecasts every month, weekly forecasts every week,
  daily forecasts once a week (each covering days 1–14).

## 2a. Time blocks

| Block | Period | Use |
|---|---|---|
| Burn-in | 2015-08 – 2016-12 | Training only (restocking years; seasonal-naive needs 12 months) |
| Development | origins 2017-01 – 2023-12 | All design choices: windows, curve form, features, generation factor |
| Final test | 2024-01 – 2026-08 | Held out; run once on the frozen model |

The final test includes the Oct 2024 – Aug 2025 milk gap (not scored), so it
also tests missing-data resilience. About 20 scoreable milk months (~600 days)
and all 32 herd months. Split ≈ 70/30 by time.

## 2b. Training at each origin (rolling origin)

| Part | Trained on | Options compared in development |
|---|---|---|
| Herd rates | trailing window before origin | 12 / 24 (default) / 36 months, expanding |
| Lactation curve | reliable cow-days before origin | see below |
| Calibration *k* | last 12 months of target series | 6 / 12 months |
| Intervals | model's own past errors at that horizon | needs 12 past errors; coverage scored from 2018 |

Curve leakage rule: no reliable per-cow data exists before Aug 2020. For
origins before 2020-09 the main result uses a published Jersey curve shape
(external knowledge) with *k* calibrated on shipments. A sensitivity run using
the 2020–22 fitted shape everywhere is reported separately and labelled as
using later information; it is not used for the H1 claim.

Weather: forecasts use THI climatology (training-year mean for the calendar
date). Actual THI is used only to explain past values.

## 3. No-leakage rule

A forecast issued at origin month *m* uses only facts dated before the first
day of *m*. This applies to rates, curve parameters, the calibration factor *k*,
interval quantiles and feature selection. Exception (allowed, documented): a
calving already scheduled by a conception recorded before *m* is known at *m*.
Pregnancies confirmed after *m* are not.

## 4. Herd counts

- Counts come from presence/state intervals, which balance exactly. Summed
  entry/exit events do not balance in 90 months (`05_herd_balance`, documented
  source mismatch), so events are not used to reconstruct stock.
- Herd engine cells: `state × parity group (0, 1, 2, 3+) × lactation stage
  (0–60, 61–150, 151–305, 305+ days in milk) × pregnancy stage × generation (0, 1, 2, 3+)`.
- Monthly flows: births, calf → heifer, conception, calving, dry-off, real
  abortion, death, cull, sale, external entry.
- Rates: estimated from a trailing window before the origin (default 24 months,
  tested against 12 and expanding). Small cells are shrunk toward the herd rate
  (beta-binomial, as in St-Pierre et al.).
- Rationale for the trailing window: abortion rates rose in 2023–26 for every
  generation (gen 0: 3.3% in 2020–22 → 11.2% in 2023–26), a persistent shift
  that an all-history average would miss.

## 5. Milk

- Baseline: `milk(m) = k × Σ_cells cows(cell, m) × curve(parity, lactation stage) × days(m)`.
- Curves: Wood curve per parity group, fitted on reliable cow-days only
  (`core.cow_day.is_reliable`). These are mostly Aug 2020 – early 2022
  (~270k cow-days); 2026 cow-days are a check. Fallback: an empirical mean-yield
  table by parity × lactation stage.
- *k*: calibration of the curve total to recorded herd milk, fitted before each
  origin. It absorbs differences between curve yield and recorded or shipped milk.
- Target series by period: shipments (2015-08 – 2020-07), DelPro total
  (identified + animal 0) from 2020-08. Every day carries its source label.
  Shipments measure milk sold and DelPro milk produced, so *k* is fitted per
  source; the 2020-08 – 2022-07 overlap measures source disagreement (H3).
  Gap days (Oct 2024 – Aug 2025) and months with no DelPro milk (May 2022,
  Sep–Oct 2022, Apr 2024) are not scored and not imputed.
- Generation is not a milk multiplier by default. G3 (reliable cow-days,
  matched parity × lactation stage) shows no consistent generational
  difference. It is tested as an optional factor and kept only if the backtest
  improves.

## 6. Benchmarks and evaluation

- Benchmarks: persistence, seasonal-naive (same month last year), SARIMA if available.
- Rolling origin: refit at each origin, forecast all horizons.
- Metrics: MAE, RMSE, bias (forecast − actual), by horizon and by data-quality band.
- Intervals: 5%/95% quantiles of the model's own past errors per horizon,
  computed only from errors observed before the origin; report coverage and width.

## 7. Attribution

- Milk: Shapley values over the factors {herd size, lactation-stage mix,
  parity mix, THI, mastitis, residual}. Each factor's share is averaged over
  all orders of switching it from last month's value to this month's. The
  shares sum exactly to the change; a unit test enforces this.
- Herd: each month's change in a state count is split into flows (calvings
  in, dry-offs out, exits out, …). For forecasts, each flow is split into
  already determined (from known pregnancies) and rate-driven (projected).

## 8. Health

- `core.health_episode.health_group` (reviewed mapping, 2026-10-18).
- Mastitis records are concentrated in 2015–18. Since 2023 almost no diagnoses
  are recorded, while 2025–26 session sensors raise about 1,000 blood alarms a
  month. This is treated as a recording gap, not an absence of mastitis.
- Forecast: expected episodes = cows at risk × rate, labelled with the period
  the rate comes from. Herd-level alarm rate (2025–26 sessions) is a candidate
  explanatory signal only. Individual detection belongs to Component 3.

## 9. Generation profile

- `core.animal.generation` = number of farm-born generations in the maternal
  line (0 = base/purchased; AI bulls count as 0). It is not crossbreeding.
  Exotic fraction is unusable (69% unknown, no intermediate values).
- Report fertility and survival by generation within calving period. The
  pooled comparison reverses within periods: services per conception in
  2023–26 are gen 0 = 3.76, gen 1 = 5.50, gen 2 = 5.87, against a pooled
  decline from 6.12 to 5.40. Generation is confounded with time and parity, so
  results are observed associations only.
- Projection: a calf's generation = its dam's generation + 1, so composition
  is projected inside the herd engine.

## 10. Output contract (`c1_output.outlook`)

`origin_date, target_period, grain, horizon, series, forecast, lower, upper,
quality_flag, model_version, core_version`, plus `c1_output.attribution`
(`origin_date, target_period, grain, series, factor, contribution, model_version,
core_version`). `core_version` is the `publish.publish_log` version the run used, so a
teammate can check it matches their own `core` before using the outputs.
Herd-level only; no animal keys. Consumed by Components 2–4.

## 11. Commands (planned)

- `build-forecast --step panel|herd|curve|outlook`
- `backtest-forecast`
- `report-forecast` (aggregate charts to `logs/report/`)
