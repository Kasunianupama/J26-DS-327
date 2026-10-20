# Experimental monthly milk calibration

This candidate addresses persistent long-horizon bias by fitting a multiplier to
completed forecast errors at the same monthly horizon. It minimises recency-weighted
absolute error in litres: the weighted median of actual/forecast, with weights equal
to forecast litres times a recency weight. Settings are fixed for this experiment:
365-day half-life, three-year history, at least six completed target periods,
multiplier bounded to 0.5–1.5. Only monthly horizons >=3 are adjusted.

At each origin, only outcomes whose periods have ended are eligible. The milk source
known at issuance must match the completed training outcomes. With quality enabled,
only normal/degraded history is used. Daily, weekly, and monthly h1 forecasts retain
the base values. Intervals from the base are removed and recomputed by selection
reporting. Calibration acts independently by horizon; it is a research candidate,
not yet a coherent daily production trajectory for serving or attribution.

The user runs this from the repository root, using saved development backtests:

```bash
python -m components.predictive_farm_intelligence.pfoi.cli calibrate-milk --tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 --base milk_baseline_adaptive --quality on --out logs/pfoi_1_1_clean
```

Quality on reads quality aggregates from the configured database on the user's
machine; agents must not execute it. Quality off uses saved forecasts alone.
The command prints aggregate comparisons against actual milk: MAE/RMSE in litres,
WAPE, signed bias, p90 absolute percentage error, and percentage of errors exceeding
20%. Percentage errors exclude zero actuals and report their eligible count.
Positive signed bias means overprediction. Source files stay unchanged; candidate
files use a separate `_maecalv1_qon` or `_maecalv1_qoff` tag.

Review those tables before rerunning nested selection and selection reports, which
recognise `milk_baseline_calibrated`. Do not choose quality off/on based on which
scores better. Expanding the candidate set after reviewing development results makes
this exploratory research; nested results cannot undo that research-level selection.
A prospective holdout is still required. Real-data improvement is not established by
synthetic tests. No frozen configuration, database publication, or frontend changes
are made by this command.
