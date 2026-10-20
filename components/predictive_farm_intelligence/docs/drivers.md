# Layer 2: driver layer (H2, step C)

Code: `pfoi/drivers.py`; loader `SqlHerdSource.driver_daily` (herd-level daily
`day_panel` columns only); tests: `tests/test_drivers.py` (synthetic).

## What it does

The milk forecast (raw baseline, or the Layer 1 adaptive one) is multiplied by exp(p),
where p is a ridge regression of the remaining error log(actual ÷ forecast) on drivers.
It is fitted again at every forecast date, on forecasts whose period had ended,
weighted towards recent years (half-life 2 years), separately per grain × horizon, and
the adjustment is capped at ±30 %.

| Feature | Group | Built from (all before the forecast date) |
|---|---|---|
| thi_28d, hours_thi_28d | weather | mean THI and hours above the THI threshold, last 28 days |
| thi_anom_28d | weather | thi_28d minus the same-season THI of earlier years |
| thi_clim_target | weather | usual THI of the target period's season (earlier years) |
| rain_30d, rain_90d | weather | rainfall totals (90 days ≈ drought signal) |
| mastitis_per_cow_28d, udder_per_cow_28d | health | episodes per milking cow, last 28 days |
| sessions_per_cow_28d | sensor | milking sessions per milking cow |
| blood_per_session_28d, conductivity_per_session_28d | sensor | alarms per session |
| identified_share_28d | quality | share of milk tied to a cow |
| season_sin, season_cos | season | day of year of the target period |

Weather is used only on days with complete weather records.

## Cautious onboarding (feature registry)

At every forecast date each feature has a status:

* **shadow**: fewer than 24 training rows have it, so it is not used (coefficient 0);
* **probation**: 24–71 rows, used with a 10 times stronger pull towards zero;
* **active**: 72+ rows.

Sparse records (health episodes, sensors) are **missing, not zero** before their first
record and after recording stops (no record in the last 180 days). So the 2025 sensors
enter in shadow and are promoted only as evidence accumulates, and the post-2023 mastitis
recording gap is not read as "no mastitis". The command prints, per feature, how many
forecast dates were in each status, and the coefficients at the last forecast date.

## Tests (synthetic)

No feature changes when days on or after the forecast date change; later outcomes do
not change an adjustment; a planted heat effect is learned (more than half of the error
removed, negative heat coefficient); a sensor that starts late stays in shadow, then
probation; zeros after recording stops are missing; with pure noise all coefficients
stay under 0.01 and accuracy is unchanged.

## Commands (development block)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_ka_w12_ck
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_ka_w12_ck_adpq0.1t365z3 --base milk_baseline_adaptive
python -m components.predictive_farm_intelligence.pfoi.cli nested-cv --family milk
```

The tags are those of your milk backtest files (`milk_backtest_errors_weekly_<tag>.csv`);
the second needs `adapt` to have run. Each writes a new candidate `<tag>_dr` and
`drivers_coefficients_<tag>_dr.csv`; `nested-cv` keeps it only if it wins year by year.
Coefficients describe associations in this herd, not causes.
