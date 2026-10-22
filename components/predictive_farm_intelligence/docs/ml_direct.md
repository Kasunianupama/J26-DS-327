# pfoi-1.4.0-dev: direct ML forecaster (experiment)

A pure machine-learning alternative to the herd engine + lactation curve. It has the same
inputs (`model_input.day_panel`, `day_cell`, `core` gestation clocks) and produces the same
outputs (forecast per series x grain x horizon, intervals from its own past errors,
attribution). It's an experiment, not a published model: nothing is written to
`c1_output`. The current model stays pfoi-1.2.0-dev unless the keep rule below passes.

Code: `pfoi/ml_features.py`, `pfoi/ml_direct.py`, command `backtest-ml` in `pfoi/cli.py`.
Tests: `tests/test_ml_direct.py` (synthetic only).

## How it differs from the earlier ML runs (`forecast_experiments.py`)

The earlier ridge / boosted / TCN runs lost to the structural model. They used only 84 days
of milk and cow-count history, fitted a separate model per grain x horizon x origin (so 2023
had too few rows to forecast at all), predicted litres directly and covered milk only.

| | Earlier runs | This model |
|---|---|---|
| Rows per fit | one grain x horizon, ≥ 24 | all grains and horizons pooled per series (horizon = `lead_days`, `period_days`); thousands of rows |
| Target | litres per day | log ratio to the level at the origin (milk, stocks); Poisson counts boosted from the trailing rate (events) |
| Inputs | milk and cow history | history, plus herd composition and the **pregnancy pipeline** (calvings due in each future period from recorded conceptions), trailing event rates, data quality, same window last year |
| Series | milk | milk, milking, total herd, calvings, dry-offs, abortions, deaths, culls, sales |
| Explanation | none | TreeSHAP, summed into factor groups; the parts add up exactly to the model output (test) |

## Features (all known at the origin)

| Group | Features |
|---|---|
| recent milk | 28-day level; log ratios 7/28, 28/91, 91/365 days; scoreable share |
| yield per cow | 28-day litres per milking cow and its change against 3–4 months earlier |
| herd counts | each stock on the day before the origin, change over 28 and 91 days |
| recent event rates | each event per day over 91 and 365 days |
| parity / lactation-stage mix | shares of milking cows by parity group and DIM band, mean DIM |
| pregnancy pipeline | cows and heifers due to calve inside the target period, due before it and in the 60 days before its start (fresh cows); pregnant share of milking cows |
| season | month of the period (sin/cos), weekday for daily rows, last year's change over the same window (clipped to days before the origin) |
| data quality | source, days since a source change, days since the last unscoreable day, identified share |

The pipeline uses the same as-of snapshots as the engine (`day_cell` on the day before the
origin, gestation clocks with the pregnancy-check lag) through `check_before`. Defaults are
the pfoi-1.1 / 1.2 snapshot settings: `day_cell_known`, `recorded`, lag 90 days, so pregnancy
states carry no hindsight. Expected calving = conception + 280 days (fixed, external).

## Training and leakage

- Refits every 3 months (`--refit-months`). A refit at date *r* trains on rows whose origin is
  before *r* **and** whose target period ended by *r*. Forecasts at an origin use the latest
  refit on or before it. Training rows are weighted by recency (half-life 730 days).
- Milk training rows must come from the source in use at the origin (shipments vs DelPro).
- A synthetic test multiplies every day from a cutoff by 5. Forecasts issued before the
  cutoff stay identical.
- Development reads data only before 2024-01-01. `--block posthoc` replays 2024–26 as
  post-hoc evidence. It never runs the run-once final test.
- Settings are fixed in `MLConfig` before any real run; no tuning on development scores.
  LightGBM: 300 trees, learning rate 0.03, 15 leaves, ≥ 40 rows per leaf, subsample 0.8,
  seed 17. Ridge: median impute + missing flags + scaling, alpha 10.

## Commands (run on your own machine; I never run these)

```bash
# 1. Development backtest, both origin grains, with benchmarks
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli backtest-ml --block development

# 2. Ablation: same model without composition / pipeline features
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli backtest-ml --block development --pipeline off --benchmarks off

# 3. Milk hit rate (trusted vs unverified) against pfoi-1.2.0-dev, with the fixed keep rule
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli hit-rate --block-name development \
  --files logs/pfoi/ml/ml_backtest_errors_monthly_ml_r3_hl730.csv \
          logs/pfoi/ml/ml_backtest_errors_weekly_ml_r3_hl730.csv \
          logs/pfoi/milk_backtest_errors_monthly_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3.csv \
          logs/pfoi/milk_backtest_errors_weekly_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3.csv \
  --models milk_baseline_adaptive ml_lgbm ml_ridge persistence \
  --keep-rule milk_baseline_adaptive ml_lgbm
```

Files go to `logs/pfoi/ml/` (gitignored): error tables in the backtest format, a summary
(n, accuracy = 1 − WAPE, share within ±10 %, bias %, skill against persistence on the same
periods) and `ml_importance_*.csv` (mean |SHAP| per feature group, herd level). Please send
back the printed tables only.

## Keep rule (proposed; agree it before the first real run)

`ml_lgbm` replaces pfoi-1.2.0-dev's milk forecast only if it passes the existing 1.2.1-dev
rule (`hit_rate.keep_rule`): on development origins 2017–2023, trusted periods, the share
within ±10 % rises at week 13 and months 3, 6 and 12, doesn't fall at week 1 or month 1,
and no forecast year gets worse by more than 5 points. For herd series:
accuracy and skill per `targets.md`, compared on the same periods. Otherwise it's recorded
as tested and dropped, with the code kept and off.

## Expectations (before seeing real numbers)

Likely to help at weeks 1–4 and month 1, and with yield per cow. Months 6–12 are dominated
by the 2021–22 yield decline and the 2023 rebound, one-off changes the model hasn't seen in
training, so it may lag them as the adaptive correction did. Event series are unlikely to
beat the engine unless the pipeline features carry the signal; the ablation run shows
how much they do.
