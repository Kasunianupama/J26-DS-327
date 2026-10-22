# C1 forecast integration: research context, not validated early warnings

Inspected producer contract: `shared/schemas/pfoi_outlook.py` version 1.0,
producer SQL `components/predictive_farm_intelligence/docs/sql/c1_output_tables.sql`,
and producer period-start logic. Only the shared contract is imported; C1 internal
code is never imported or modified. No real forecasts were inspected by the agent.

The user-run loader reads real `c1_output.outlook` rows, never demo responses or
synthetic replacements. Fixed database/account: farmx_app/farmx_c4, port 5432.
C1 SELECT permission is NOT assumed. Before running, the owner must confirm
authorized read access and an installed producer dump. Access denial stops the
workflow; this code does not request broader roles or change permissions.

The user selects an exact origin/model/core version and timezone-aware cutoff.
Daily herd_milk forecasts are litres/day, not litres/milking cow. They are not
converted to the RF target or compared directly with per-cow production. C1 horizon
1 starts on its origin date: assessment+1..+7 uses horizons 2..8 for a same-day
origin. Older origins must cover all seven requested dates with matching horizons.
No weekly/monthly disaggregation, interpolation, latest-version guessing or missing
value substitution occurs. Duplicates, missing dates, unknown/mixed core versions,
negative/nonfinite values, inverted/partial intervals and quality other than exactly
`ok` withhold the context. Absent paired intervals remain absent, not invented.

`created_at <= cutoff` verifies only the restored row's recorded publication time.
It is NOT proof of original historical availability, immutable forecast vintages,
training-data cutoff, recording completeness, or out-of-sample validation. C1 can
replace a run's rows. Historical reconstructions therefore remain research-only,
even with quality_flag=ok. Genuine availability and completeness stay unknown.

There is deliberately NO approved warning policy, decline threshold, risk band,
clinical diagnosis or validated warning. Every output has research_only=true,
live_warning_allowed=false, warning_status=withheld_no_approved_warning_policy.
C1 context, experimental RF probabilities and rule-based Farm Risk Scores remain
separate evidence streams; none is summed into another or used to overwrite scores.
The existing 597 assessments are untouched. Warning deployment requires a separately
reviewed policy, operational provenance/availability, compatible units, prospective
evaluation and an approved false-alarm/recall tradeoff.

## User-run verification after authorization

From repository root, supply the actual published run identifiers locally. Missing
core provenance may be omitted and will result in unavailable context. Nothing
prints individual forecasts, forecast dates, run identifiers or output payloads.
Credentials are requested through hidden terminal input; no .env file is loaded.

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.early_warning.verify_c1_local `
  --acknowledge-authorized-c1-read `
  --assessment-date (Read-Host 'Assessment YYYY-MM-DD') `
  --origin-date (Read-Host 'Exact C1 origin YYYY-MM-DD') `
  --model-version (Read-Host 'Exact C1 model version') `
  --core-version (Read-Host 'Verified C1 core version') `
  --assessed-at (Read-Host 'Cutoff ISO datetime with timezone')
```

Local summary contains only assessment/status/reason counts and zero validated
warnings. Errors are sanitized. No model loading, retraining, publication, row-level
file export or table creation is reachable from this CLI.

## Future Member 4 dump preparation

`C1ResearchContext` is the versioned component-side output contract. It retains
assessment/cutoff, exact C1 run/core provenance, quality-validation reasons, seven-day
coverage, optional mean herd-milk forecast and explicit unknown metadata/flags.
The mean is descriptive forecast context, not a calibrated decline probability.
The separate proposed SQL is `sql/PROPOSED_c1_forecast_context_v1.sql`. It is a
review artifact only; no creation or publishing code is enabled in this step.
Future approval must cover this object, an append-only validated publisher and
table-only dump scope. Never include C1 tables, raw inputs or private artifacts in
a Member 4 output dump. Existing assessment/prediction contracts stay unchanged.

Manual synthetic tests (not executed by agent):

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```
