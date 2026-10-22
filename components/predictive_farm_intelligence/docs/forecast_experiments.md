# Rolling milk model experiments

These are experimental point forecasts, not deployed models. Run real-data commands
yourself on your machine; AI agents only run synthetic tests. No model-output database
writes or final-test marker changes occur. Outputs are aggregate metric tables and
configuration metadata in a new directory, never individual animal records.

## Implemented candidates

- Linear: plain least squares on 7 compact inputs (level, 7/28/84-day ratios, cows, month);
  the simple-regression baseline. Results: `linear_baseline.md`.
- Ridge: direct regression, standardized within each training fold, alpha=100.
- Boosted: histogram gradient-boosted regression, 100 iterations, seven leaves,
  minimum ten samples per leaf, L2=10, no random validation or early stopping.
- TCN: five causal convolution layers (16 channels, dilations 1/2/4/8/16), direct
  daily-rate output multiplied by the target period's length.
- Residual TCN: same architecture, learns daily-rate errors of the named structural
  forecast and adds the predicted error to that forecast. Missing structural forecasts
  are counted, never replaced by zero. This is a point model; quantile intervals and
  masked pretraining are not implemented.

All use 84 days of historical milk/count sequences, explicit missingness masks, milk
source indicators, recent scale, and target calendar features. Only dates before each
origin enter inputs. A separate model is fitted for each grain/horizon and origin,
using up to five years of completed same-source outcomes, minimum 24 examples.
TCN settings are fixed: 60 epochs, AdamW, seed 17, CPU. These are initial research
settings rather than optimised winners. Missing-value placeholders have explicit masks;
target labels are never imputed. Milk targets require complete scoreable same-source
periods. Reports retain normal/degraded quality bands, with exclusion counts printed.
Training labels use scoreability, not the retrospective reporting quality band.

Chronological fitting prevents future outcomes entering estimation, but published ETL
history may contain retrospective revisions. This is a historical replay, not proof
that every stored observation was available in exactly that form at the time.

## Commands

### Audit training eligibility before rerunning experiments

This user-run command performs no fitting and writes no files. It reads only the
development aggregate inputs and the explicitly named saved structural forecasts:

```bash
python -m components.predictive_farm_intelligence.pfoi.training_audit \
  --start 2019-01-01 --end 2024-01-01 --grain monthly \
  --structural-tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 \
  --saved logs/pfoi_1_1_clean
```

Return all five printed tables:

- `source_inventory`: daily counts by year/source, including scoreable and missing-count days.
- `query_coverage`: forecast-origin counts by year, horizon, current source, latest
  scoreable source and eligibility status. Source selection matches the runner's
  last non-null label before issuance, even if that day was unscoreable.
- `eligibility_funnel`: minimum/mean/maximum examples per eligible origin after
  successive filters: historical origins, completed outcomes, scoreable targets,
  five-year window, exact source match, usable historical inputs, and (optionally)
  saved structural predictions. The last two stages reproduce direct/residual model
  training counts. The initial origin grid begins after the configured 84-day context.
- `minimum_training`: how many origins lack the unchanged 24 examples; residual
  model columns also show missing structural forecasts at the query origin.
- `historical_source_mix`: counts of historical example exposures by current and
  historical source before source/input filtering. Reuse across forecast origins means
  these totals are not numbers of independent examples.

No source labels are normalized for eligibility. Exact `shipment`/`delpro` and
case/space variants are identified separately; arbitrary other labels receive opaque
codes instead of exposing database text. Missing source history retains the runner's
existing no-source-filter behavior and is explicitly counted. This is diagnostic,
not authorization to combine different measurements or lower the minimum sample size.

### Run experiments

Install experiment dependencies if needed, in the Python environment you use for PFOI:

```bash
python -m pip install -r components/predictive_farm_intelligence/requirements-experiments.txt
```

Start with monthly development results (including TCN direct/residual comparisons):

```bash
python -m components.predictive_farm_intelligence.pfoi.forecast_experiments \
  --block development --start 2019-01-01 --end 2024-01-01 \
  --grain monthly --models ridge boosted tcn tcn_residual \
  --structural-tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 \
  --saved logs/pfoi_1_1_clean --out logs/pfoi_experiments/dev_monthly_v1
```

Separately, evaluate recent years 2024–2026. The exclusive end 2027-01-01 selects
those calendar years; scoring stops wherever the actual published data ends. It does
not imply that all 2026 data exist. This explicit option regenerates the fixed w12
known-data adaptive structural candidate too, using raw development errors for its
past correction history. That structural replay can take hours:

```bash
python -m components.predictive_farm_intelligence.pfoi.forecast_experiments \
  --block posthoc --start 2024-01-01 --end 2027-01-01 \
  --grain monthly --models ridge boosted tcn tcn_residual \
  --structural-tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 \
  --generate-structural \
  --saved logs/pfoi_1_1_clean --out logs/pfoi_experiments/posthoc_monthly_v1
```

Without `--generate-structural`, only existing explicitly named development and `_test`
files are read. The selected adaptive tag often has no `_test` files; absence means
no recent current-model comparison/residual forecast, and is reported in coverage.
Regeneration is confined to posthoc mode and this explicitly fixed tag/configuration.
It does not change the frozen pfoi-1.0.0 test contract. It does not republish results.

For weekly and daily experiments, use `--grain weekly` or `--grain daily`, with a new
output directory. `--grain both` includes all three grains and is more expensive.
Output directories cannot be reused or overwritten. No model choice is automatically
made from these reports. No random row split or hyperparameter search is used.

The original `pfoi.error_diagnostics` command now additionally prints existing
benchmark comparisons grouped by both issue year and target year.

## Interpreting the reports

- `target_coverage`: complete scoreable targets versus incomplete or missing targets.
- `training_coverage`: fitted/skipped forecasts and training sample counts.
- `quality`: reporting bands before filtering.
- `by_target_year` and `by_origin_year`: MAE/RMSE litres, WAPE, bias, p90 APE, large misses.
- `matched`: each new candidate versus the structural model and four statistical
  benchmarks on the same target periods, by year. Compare within each pair; other
  pairs may have different coverage. Missing models produce n=0, not a fabricated score.
- `recovery`: errors by latest labelled disruption at the forecast issue date.

Return these aggregate tables, especially `matched`, `by_target_year`, and both
coverage tables. Monthly h12 is the twelfth target month, not the cumulative next
12 months. A 2026 h12 forecast often cannot yet be evaluated; h12 targets in 2026 can
come from 2025 origins. Rolling refits may use earlier completed posthoc outcomes;
they never train on the target being forecast. Architecture/settings stay fixed for
the run. Data ending part-way through a month cannot score that entire month.

Keep development and posthoc results separate. Since 2024–2026 have already been
examined, they cannot establish untouched test performance. Repeated tuning against
them is exploratory and still requires genuinely prospective confirmation.
