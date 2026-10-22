# Risk outlook readiness and remaining calibration evidence

No numerical scoring rules, published payloads, API/authentication, ETL or models
changed. Preserve all 597 assessments and Member 3 XAI references. The 85 historical
RF predictions remain separate. Frontend summaries are presentation only, based
on stored indicators/scores and weighted contributions; metadata remains intact.

## Calibration findings

As documented in calibration_review.md, a complete domain uses MAX of clipped
configured indicator scores. Recorded zero health counts can score zero, as can
values below a configured lower bound. This does not establish surveillance
completeness or absence of disease. Unavailable values are not zero. In descriptive
outputs computational completeness does not prove recording completeness.

The user-reported operational upper bound of 12 makes a higher-is-riskier alarm
rule saturate at 100 for counts >=12. One saturated alarm is enough for MAX=100.
The actual selected stored rule is authoritative, not an engine-wide default.
Without distributions and event definitions, mismatch with alarm volume remains
a plausible hypothesis rather than a verified reason for frequent saturation.

A September 2025 combined-score rise may reflect coverage/source/session volume,
encoding or rule changes as well as changed recorded burden. No verified monthly
coverage aggregates or confirmed change date are present in the reviewed Member 4
documentation. Do not report this as a real crisis or an established sensor change.

## Minimal manual read-only checks (owner runs; aggregates only)

These queries use only approved aggregates/published outputs, never raw records.
No query was executed by the agent. Stay within your existing authorized access;
if denied, stop and consult the owner rather than requesting broader data access.

Monthly coverage and separate distributions across the suspected transition:

```sql
SELECT date_trunc('month', date)::date AS month,
       target_source,
       count(*) AS recorded_days,
       count(n_sessions) AS session_days,
       count(*) FILTER (WHERE n_sessions = 0) AS zero_session_days,
       count(n_blood_alarms) AS blood_observed_days,
       count(n_conductivity_alarms) AS conductivity_observed_days,
       count(*) FILTER (WHERE n_blood_alarms = 0) AS blood_zero_days,
       count(*) FILTER (WHERE n_conductivity_alarms = 0) AS conductivity_zero_days,
       percentile_cont(ARRAY[0.5,0.9,0.95,0.99]) WITHIN GROUP
           (ORDER BY n_blood_alarms) AS blood_percentiles,
       percentile_cont(ARRAY[0.5,0.9,0.95,0.99]) WITHIN GROUP
           (ORDER BY n_conductivity_alarms) AS conductivity_percentiles,
       count(*) FILTER (WHERE mastitis_episodes IS NULL) AS mastitis_missing,
       count(*) FILTER (WHERE mastitis_episodes = 0) AS mastitis_zero,
       count(*) FILTER (WHERE mastitis_episodes > 0) AS mastitis_positive,
       count(*) FILTER (WHERE udder_teat_episodes IS NULL) AS udder_missing,
       count(*) FILTER (WHERE udder_teat_episodes = 0) AS udder_zero,
       count(*) FILTER (WHERE other_health_episodes IS NULL) AS other_missing,
       count(*) FILTER (WHERE other_health_episodes = 0) AS other_zero
FROM model_input.day_panel
WHERE date >= DATE '2025-01-01' AND date < DATE '2027-01-01'
GROUP BY 1, 2 ORDER BY 1, 2;
```

Stored-rule and saturation comparison without exposing payloads or individual dates:

```sql
SELECT date_trunc('month', assessment_date)::date AS month,
       scoring_version,
       count(*) AS publications,
       count(DISTINCT assessment_date) AS distinct_days,
       count(*) FILTER (WHERE biological_score = 0) AS biological_zero,
       count(*) FILTER (WHERE operational_score = 100) AS operational_saturated,
       count(*) FILTER (WHERE combined_score IS NULL) AS combined_unavailable,
       avg(combined_score) AS combined_mean,
       min((payload->'scoring_config'->>'operational_weight')::numeric) AS min_operational_weight,
       max((payload->'scoring_config'->>'operational_weight')::numeric) AS max_operational_weight
FROM c4_output.farm_risk_assessment_v1
WHERE farm_id = 'FARM_X'
GROUP BY 1, 2 ORDER BY 1, 2;
```

Neither query proves completeness; absent calendar days, surveillance processes,
device definitions and documentation still need review. Duplicated publications
are not independent days. Verify the actual upper/lower rules locally against
the dashboard Detailed View before interpreting a threshold of 12.

Concrete next calibration decision: define comparable recording regimes and an
eligible PRIOR reference period; predeclare candidate percentile bounds and
minimum support, then review saturation/missingness and stability on later data.
Do not fit a percentile baseline using dates it will score retrospectively.
Sparse/zero-inflated health recording may require unavailable scores or better
indicators rather than stronger scaling. Alarm rates remain deferred until event
unit, multiple-event behavior, shared day/population and complete session/alarm
coverage are verified. Any accepted configuration needs a NEW version and separate
publication/XAI compatibility approval. No new numeric candidates are invented.

## Actual early-warning implementation status

`early_warning/warning_engine.py` and `risk_classifier.py` are deferred extension
points. `early_warning/c1_integration.py` already validates a selected real C1 run,
daily target dates/horizons, quality flag, core/model provenance, intervals and
publication cutoff. It supplies context only, always with research flags and
warning withheld. C1 horizon 1 is its origin; assessment+1..+7 uses horizons 2..8
when origins match. created_at is not verified original forecast availability.
The shared API client targets pfoi-1.2.0-dev but cannot prove historical vintages.

Missing pieces before research-level future-risk outlook calculation:

1. An explicit forecast origin/cutoff and immutable real C1 run selection with
   publication/availability evidence, not latest-run substitution. Require seven
   matching eligible future daily forecasts, consistent units/version/core and
   known quality; incomplete runs remain unavailable.
2. A documented positive herd-level reference baseline using prior complete,
   compatible observed herd milk ONLY, with consistent source/coverage and known
   availability. The approved per-cow target times a current animal count is not
   automatically a compatible herd-milk baseline. A producer-approved reference
   may be needed; no new permission is presumed. Never compare C1 herd litres/day
   directly to the RF per-cow target.
3. A separately versioned research outlook method comparing a seven-day mean
   forecast against that compatible historical mean, carrying intervals/uncertainty
   without calling them calibrated warning probability. No ad hoc threshold is
   selected here; proposed percentage/drop decision rules need explicit approval
   and evidence. Missing/zero baseline means unavailable, not a zero-risk outlook.
4. Member 4 observed climate, health and alarm indicators remain dated context.
   They are not future measurements. No future domain score may be imputed from
   them, C1 milk forecasts or the historical RF classifier. Persistence assumptions
   would require separate labelled validation, not silent carry-forward.
5. Chronological rolling-origin evaluation on stored forecast vintages with
   realized compatible outcomes: precision/recall, false alarms per eligible day,
   lead time, coverage, seasonal/source stability and interval calibration.
   Tune approved policies using development/validation periods only, preserve an
   untouched later evaluation, and disclose retrospective availability limitations.
6. Human-reviewed alert policy with evidence-based decision thresholds, handling
   of repeat alerts, expiry, withheld conditions and provenance. Research outlooks
   must remain distinct from operational action warnings until prospective review.

The UI now has a separate unavailable Early Warning / Risk Outlook section in
Detailed View. It makes no C1 request and fabricates no forecasts/baselines/alerts.
It does not relabel the selected historical assessment date as a future origin.
Historical scores, 2022 experimental RF predictions and future forecast context
are three separate products. Enabling computed research outlooks is a future task
requiring the above evidence, policy and a reviewed API contract.

## Local synthetic checks (not executed)

```powershell
node --test frontend/src/pages/DairyCrisisForecasting/dashboardInsights.test.mjs
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests/test_scoring_output.py components/member4_crisis_forecasting/tests/test_c1_integration.py -q
npm.cmd --prefix frontend run build
```
