# Milk error diagnosis and next-model protocol

Run on the user's machine from the repository root:

```bash
python -m components.predictive_farm_intelligence.pfoi.error_diagnostics \
  --tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 \
  --model milk_baseline_adaptive \
  --herd-tag w12_ck_kn_rk_lag90 \
  --quality on --out logs/pfoi_1_1_clean
```

This reads saved development error files and, with quality on, development quality
aggregates from the database. AI agents must not run it against real data. It prints
only grouped metrics and makes no writes. Return all printed tables, not input files.
The herd tag must identify the raw engine underlying the milk candidate, rather than
a separately selected herd model. Daily milk may have no corresponding saved daily
herd forecast; the count association table only includes matching keys.

The report groups by issue year, target year, and latest known break at issuance.
Breaks are descriptive labels; a later break supersedes an earlier one, and long
forecast horizons may cross a break that had not happened at issuance. Neither the
break comparisons nor error correlations establish causality. Small groups are
unstable and overlapping horizons are not independent samples.

Each persistence, seasonal-naive, ETS, and SARIMA comparison uses exactly the same
periods for that benchmark and the current model. Missing fits are counted. Pairwise
scores with different sample coverage must not be used as an overall leaderboard.
Scores compare to actual milk production; benchmarks provide additional context.
Monthly h3 means the third forecast month, not total production over three months.

Cow counts are mean daily counts across a whole period. Milk totals may omit
unscoreable days. Therefore saved outputs support matched count-error comparisons,
but not an exact daily count/yield decomposition. That further diagnostic requires
projected and actual milking cow-days and milk on the same scored days; any resulting
effective yield must distinguish source changes and record completeness from biology.

## Model identity

The specified research candidate is the 12-month-window herd engine with known-data
cutoffs, herd-fitted lactation curves, anchored milk scaling, and horizon-specific
adaptive local-level correction (q30=.1, tau=365). It is a structural/statistical
hybrid. The driver layer is a ridge regression of residual log ratios; it is a
separate candidate. The recent MAE multiplier experiment is another separate
candidate and has not earned promotion. A research report does not establish which
model is currently published in the prototype; check its run metadata separately.

## Proposed comparisons, not implemented by this diagnostic

1. Audit existing persistence, seasonal-naive, ETS, and SARIMA errors and coverage.
2. Add direct Ridge/Elastic Net forecasting with historical milk lags, rolling
   statistics, seasonality, and origin-known herd features. Fit scaling and feature
   transformations inside each time fold. Compare with the existing residual ridge.
3. Add gradient-boosted trees with the same origin-known inputs and direct horizons.
4. Compare a compact causal TCN with a direct milk output and a separate residual
   output added to the structural forecast. Report both and their ablation.
5. Only then consider larger transformers or a locally executed pretrained time-series
   model. Evaluate model size and data requirements before committing to training.

Freeze targets, evaluation dates, quality rules, and metrics before experiments.
Use chronological rolling evaluation; train only on labels completed before the
forecast date. Future weather must be archived forecasts or climatology, never future
observations. Compare MAE litres, WAPE, bias, p90 absolute percentage error, large-miss
rates, recovery, and interval coverage/width. Quantile losses provide prediction
interval candidates, whose coverage still needs evaluation. Keep 2024–26 explicitly
post-hoc if already examined and reserve a genuinely prospective period for final
confirmation. Repeated development tuning is exploratory.

For the attached capability roadmap, sequence models and probabilistic forecasting
are the closest fit. Masked self-supervised learning is a later option if enough
historical sequences exist, with pretraining confined to each training period.
Cross-modal video/table alignment requires a separate aligned video dataset and is
outside this component's current evidence. Multitask milk/count/yield training is an
experiment, not an assumed benefit. Track configurations, dataset versions, seeds,
and origin cutoffs locally; do not send farm records to external tracking services.
Use offline/shadow comparisons before any operational A/B experiment.

References: [rolling-origin evaluation](https://otexts.com/fpp3/toolbox.html),
[TCN research](https://arxiv.org/abs/1803.01271),
[logistic regression classification](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html).
