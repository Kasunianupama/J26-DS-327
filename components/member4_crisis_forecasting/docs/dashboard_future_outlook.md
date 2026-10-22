# Dashboard Early Warning Outlook

The visible compact outlook section is separate from historical farm assessments
and the 2022 experimental RF section. It reuses the existing C1 read-only API and
requires source=model, shared contract 1.0 and pfoi-1.2.0-dev. No backend/C1/auth
code, output records or scoring rules changed. Simple combined summaries now omit
weighted-point calculations; detailed weights/contributions remain available.

Tomorrow and Next 7 Days start at tomorrow's UTC calendar date. Users may select
another future start date explicitly. Historical assessment selection does not
change this origin or substitute a historical forecast. Target dates, available
run origin and status are shown even when future coverage/timing is insufficient.

Before displaying numeric forecasts, require exactly one daily row per selected
future date, consistent origin/model/core provenance, quality exactly ok, finite
nonnegative production, correct horizon offsets and internally consistent supplied
intervals. C1 daily horizon 1 corresponds to origin itself, so tomorrow relative
to a same-day origin is horizon 2. Missing seven-day coverage is not averaged,
interpolated or filled. Missing intervals remain unavailable. Display supplied
intervals per day only: adding quantiles would not yield a valid seven-day interval.
No forecast is converted into tomorrow's Biological/Operational score or RF output.

## Real current API limitation

`shared/schemas/pfoi_outlook.py::OutlookRow` does not expose created_at or verified
historical availability. FastAPI's response_model therefore removes the table's
created_at from normal C1 API responses. The frontend accepts optional genuine
publication metadata if later exposed, but never fabricates it. Current responses
can supply real origin/target context while numerical future outlooks remain
withheld with a precise publication-timing explanation.

Changing C1/shared contracts is outside this task. Producer/team review is needed
to expose original publication/availability evidence with immutable forecast-vintage
semantics, explicit date timezone and appropriate contract version compatibility.
An updated response contract requires coordinated client support, not silent
metadata fabrication. A database created_at alone proves recorded publication,
not original forecasting availability, immutable inputs or quality completeness.

Even when optional publication metadata exists, post-origin or future publication
times are rejected. The current conservative client compares UTC dates and labels
selection accordingly; agreement on the producer's origin-day timezone remains a
deployment requirement. Outputs passing these checks are forecast CONTEXT, not a
verified point-in-time backtest, calibrated warning probability or live warning.

## Remaining requirements for genuine early warnings

- Real current eligible C1 run covering the selected dates with verifiable timing.
- Compatible prior herd-level production baseline, source/coverage and day boundaries.
  Never compare herd litres/day directly to the per-cow RF target.
- A separately versioned, approved warning policy and thresholds chosen without
  inspecting held-out outcomes, plus withholding and alert-expiry rules.
- Chronological forecast-vintage evaluation of lead time, false alarms,
  precision/recall, missingness and interval calibration; prospective review before
  operational use. No Low/Medium/High warning is assigned in this UI.

Model Information retains these research limitations. Original 597 assessments,
85 predictions, Biological zero and Operational 100 values remain unchanged.

Manual synthetic verification (not executed by agent):

```powershell
node --test frontend/src/pages/DairyCrisisForecasting/dashboardInsights.test.mjs frontend/src/pages/DairyCrisisForecasting/forecastOutlook.test.mjs
npm.cmd --prefix frontend run build
```

Tests use fictional fixed-date forecasts and Node's built-in runner; no API,
private records, credentials or database connections are used.
