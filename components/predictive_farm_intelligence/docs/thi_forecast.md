# Experimental THI prediction for the simple-view heat chart

The milk/herd model consumes heat information; it does not itself predict THI.
`pfoi/thi_forecast.py` supplies a separate statistical baseline for daily maximum
THI. The simple view draws `heat.forecast.predictions` as a purple dashed line,
`heat.realised` as observed dots after the origin, and climatology separately.
THI is unitless, not temperature in degrees Celsius.

The forecast fits an intercept and annual/half-year sine and cosine terms using
least squares on up to three years of complete, finite daily maximum THI records.
Only dates on or before `origin - max(1, weather_lag_days)` may enter training.
The mean residual of the latest 14 calendar days is added to predictions and
decays exponentially with a fixed seven-day time constant. That decay is an
assumption, not a measured Farm X result. Long-horizon predictions approach the
fitted seasonal pattern and cannot anticipate individual future heat spells.

At least 365 distinct observations spanning 364 days are required. If the most
recent complete weather is over 14 days older than the availability cutoff, the
forecast is withheld. Missing/incomplete observations are excluded, never zero.
No forecast uncertainty interval or validated accuracy is supplied. The chart's
historical 10th–90th percentile band is not an interval for this prediction.

`heat_outlook` fits the baseline before later weather outcomes are loaded for
display. Neither the milk/herd model nor its heat assumption is changed by this
display-only experiment. Existing published run documents must be regenerated
and published using their original build-outlook configuration to include it.
Do not change the model version or build flags merely to refresh this chart.
AI agents must not execute real-data builds or database writes.

Synthetic verification from the repository root:

```sh
.venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_thi_forecast.py components/predictive_farm_intelligence/tests/test_drivers.py -q
```

For an existing published document lacking the new series, the owner can refresh
only its heat fields without rebuilding milk/herd forecasts. Run locally from
the repository root (AI agents must not run either command against real data):

```sh
# Read-only preview: aggregate counts only.
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.refresh_heat
# Persist only the heat fields of existing documents, then reload the frontend.
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.refresh_heat --write
```

Both commands print counts only: runs, predictions, observations, unavailable
forecasts, updates and concurrent-edit conflicts. By default observations stop
before frozen `DATA_END`; `--until YYYY-MM-DD` explicitly changes that exclusive
bound when the owner has later weather records. Optional `--origin YYYY-MM-DD`
restricts the refresh to one forecast date. Concurrent changes cause the update
to skip that document. The original seasonal heat outlook, milk/herd forecasts,
model version and publication ordering remain unchanged.

## v2: seasonal curve plus learned daily changes (`forecast_thi_daily`)

v1 assumes how fast a recent anomaly fades (seven days). v2 learns it:

- Seasonal part: three harmonics on up to five years, weighted so that each
  year back counts half as much (a warmer recent period moves the curve).
- Daily part: the anomaly (THI minus seasonal) of the last known day, the two
  days before, and the 7- and 30-day mean anomalies. For each lead time a ridge
  regression learns how much of each is still present that many days later.
- Per day it also returns a 10–90% band and the chance of exceeding the herd's
  heat knots (`p_above`), both from that lead's in-sample errors (calibration is
  checked by the back-test, not assumed), plus `persistence_by_lead`.

Two settings come from the first development back-test (owner's aggregates,
weather lag 6 and 1, 365 forecast dates):

- `taper_days = (20, 40)`: beyond 30 days ahead the daily terms made v2 worse than
  climatology (MAE skill −1.5%). A hard cut at 30 days (first version) left that gap
  (−1.7%; the cause was the mean-based seasonal curve, not the daily terms) and put a
  visible step in the line, so the daily part now fades out linearly between 20 and
  40 days ahead; band and hot-day chances blend the two error sets the same way.
- `error_scale = 1.1`: the 10–90% band held 75–78% of outcomes instead of 80%;
  errors are widened by 1.1 for the band and the hot-day chances. The back-test now
  also prints `band_scale_for_80`, the factor that would give exactly 80%.

New page documents (`page_run`) use v2. `heat_outlook` and `refresh_heat` still
default to v1 when called directly; pass `thi_method="v2"` / `--thi-method v2`.
The milk/herd model and its version are unaffected (the run label, e.g.
`pfoi-1.2.0-dev`, names that model); `heat.forecast.method` names the heat model. With v2 the
climatology days also carry `share_above_p75` / `share_above_p90` (the usual chance
of a hot day). The simple-view Heat tab then shows the prediction range instead of
the usual-range band, draws the line dotted after 14 days, shades days whose weather
was not yet published, and adds weekly expected hot days against the usual count.
Older runs without these fields keep the previous display.

## Back-test (`thi-backtest`)

Rolling weekly forecast dates, the same weather lag as a real forecast day, and
four models scored on identical days: persistence, climatology, v1, v2. It prints
MAE, RMSE, bias, skill vs climatology and 10–90% band coverage by lead band
(1–3, 4–7, 8–14, 15–30, 31–90 days), plus hot-day hit rate, false-alarm ratio and
Brier score at the herd's p75 and p90 knots. Aggregates only. Owner runs, from the
repository root (AI agents must not):

```sh
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli thi-backtest --block development --weather-lag 6
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli thi-backtest --block development --weather-lag 1
```

The second run shows what fresher weather would be worth. To put v2 on the page for
existing runs (heat fields only, counts printed):

```sh
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.refresh_heat --thi-method v2
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.refresh_heat --thi-method v2 --write
```

 Run `--block test` once,
only after the choice between v1 and v2 is fixed on development.

### Development results (owner's aggregates, 2017–2023, 365 weekly forecast dates)

With the settings above and weather lag 6 (the setting in use; the database is a
frozen copy ending 2026-08-20, so it cannot show the live publication delay):

| Days ahead | v2 MAE | MAE skill vs climatology | 10–90% band holds | Brier skill vs climatology, very hot (p90) | hot (p75) |
|---|---|---|---|---|---|
| 1–3 | 0.719 | +6.9% | 80.5% | +9.5% | +11.7% |
| 4–7 | 0.710 | +8.6% | 81.8% | +17.1% | +13.0% |
| 8–14 | 0.734 | +5.3% | 80.2% | +11.0% | +9.3% |
| 15–30 | 0.750 | +3.0% | 79.9% | +8.0% | +7.2% |
| 31–90 | 0.780 | −1.7% | 80.4% | +6.5% | +1.3% |

- v2 has the best hot-day Brier score of all four models at every lead; v1's point
  line is worse than climatology for hot-day chances at every lead.
- Point forecasts gain little: day-to-day anomalies fade within a week (median
  learned persistence 5% after 7 days), and with a 6-day lag most of it is gone.
- Beyond 30 days v2 is the recency-weighted seasonal mean; climatology's median
  has a slightly lower MAE (skewed THI), while v2's bias is lower (+0.04 vs +0.17).
- With weather lag 1 the 1–3 day MAE skill rises to +15.7% (0.626): fresher
  weather is worth more than further model changes.
- The test block (2024–2026) has not been run; run it once only.

On fictional synthetic weather (tests only, not a Farm X result), v2 clearly beats
v1 at 1–7 days when the weather lag is 1 day. With a 6-day lag most day-to-day
information has already faded and the point forecasts are similar. Individual hot
days beyond about a week were not predictable in either case.

Before operational use, the owner must evaluate historical rolling-origin
forecasts at the same weather lag, reporting aggregate MAE, RMSE and bias by
lead-time band against persistence and climatology. No real-data evaluation has
been run by the agent and no accuracy claim is made. Demo curves are fictional.
