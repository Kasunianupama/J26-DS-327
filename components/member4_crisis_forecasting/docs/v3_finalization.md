# V3 finalization: verify, approve, publish, then activate

Nothing in this change publishes automatically or activates the final dashboard.
The existing working preview stays available until the owner completes the stages
below. No database, private records, credentials, configuration or dumps were read
by the agent. No ETL, C1, scoring thresholds, model training, V1/V2/RF writes or
Member 3 XAI changes occur. No database dump export is part of this task.

## Model and contract

Model: **Climate and Operational Risk Model**, scoring version
`c4-v3-climate-operational-1`, independent payload contract **3.0.0**.

- Climate is copied without rounding from the referenced validated stored V2
  assessment, with the identical evidence and calibrated rules.
- Operational = (blood alarm indicator score + conductivity alarm indicator score)/2.
  Exactly these two raw alarm rules are required, with nonnegative integer counts
  and indicator scores matching the source rules. No new thresholds are fitted.
- Combined = (Climate + Operational)/2 using full precision. No Biological domain,
  contribution, weight or unavailable-health penalty is used. Source V2 category
  boundaries are copied and applied inclusively to the new combined value.
- Missing either required domain withholds Combined; missing either required alarm
  withholds Operational. No zero filling or weight redistribution.
- Source assessment UUID, source object, scoring version and canonical SHA-256 of
  the full validated V2 payload retain lineage. V3 has new deterministic UUIDs in
  a separate namespace. Generation time is execution time, not historical availability.
- Records remain research_only=true, live_warning_allowed=false, recording quality
  unknown and model status provisional_two_domain_not_live_validated. Source core
  provenance remains exactly as supplied, including unknown values. It is not a
  clinical model, disease probability, future forecast or validated live warning.

The existing three-domain contracts cannot validate a two-domain result, so they
remain unchanged. V3 has its own strict calculation/evidence validator. Source
inputs come from frozen V2 output payloads rather than rereading potentially
corrected day_panel records: this reproduces the browser preview's actual inputs.
V2 evidence was derived from the authorized farm aggregates. No additional raw
data or private calibration file is needed by this workflow.

## Stage 1 — Synthetic verification

From repository root:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests/test_v3_publication.py backend/tests/test_member4_v3_api.py backend/tests/test_member4_v2_api.py backend/tests/test_member4_research_api.py -q
node --test frontend/src/pages/DairyCrisisForecasting/v3Preview.test.mjs frontend/src/pages/DairyCrisisForecasting/dashboardInsights.test.mjs frontend/src/pages/DairyCrisisForecasting/publishedV3.test.mjs
npm.cmd --prefix frontend run build
```

Tests use fictional payloads, fake database connections and a standalone FastAPI
test app; they do not import backend main/settings or read .env. The parity test
passes synthetic source JSON through both Python and the existing browser helper,
then validates the generated V3 in the published frontend adapter. No test trains
a model or opens a real connection.

## Stage 2 — USER-RUN real verification, read-only default

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.v3_local
```

The program prompts privately for the existing local farmx_c4 password, never
prints it, and uses a read-only repeatable-read snapshot of the fixed V2 table.
Defaults localhost:5432/farmx_app; C4_DB_HOST/C4_DB_PORT nonsecret overrides supported.
It reads validated complete V2 payloads, preserves original source values, rejects
duplicate dates/mixed calibration versions and generates V3 only in memory.
Stdout contains counts/distributions/categories only, never records or predictions.

Verify the 232 expected historical dates, zero missing calendar days, eligible
counts, unavailable scores, Climate equality, Operational mean and Combined mean.
Numerical equivalence is tested without rounding; the synthetic precision example
82.34567 Climate and 62.839 Operational gives 72.592335 Combined, shown as 72.6.
The agent has not inspected the real 2026-08-20 values or verified real results.

## Stage 3 — Explicit owner approval and manual table creation

Review `docs/sql/PROPOSED_c4_output_v3.sql`. It creates only the separate V3 table;
it does not alter/copy/delete V1, V2 or RF records. No automatic DDL/migration.
Only after approval, run as the existing authorized c4_output owner:

```powershell
psql -h localhost -p 5432 -U farmx_c4 -d farmx_app -W -v ON_ERROR_STOP=1 --single-transaction -f components/member4_crisis_forecasting/docs/sql/PROPOSED_c4_output_v3.sql
```

If the configured farmx_api backend reader lacks SELECT on the new table, the owner
must separately authorize that single-table access. Minimal owner-reviewed SQL:

```sql
GRANT SELECT ON c4_output.farm_risk_assessment_v3 TO farmx_api;
```

Existing schema USAGE/connection rights remain required. This document does not
execute grants or change default privileges. If farmx_c4 lacks schema CREATE,
consult the owner; do not escalate the application account or touch ETL permissions.

## Stage 4 — Explicit publication approval

After reviewing Stage 2 and approving V3 publication:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.v3_local --publish-approved --approved-object c4_output.farm_risk_assessment_v3
```

This invocation requires complete 232-date source coverage. Unavailable domain
scores remain unavailable rather than filling missing measurements. All outputs
validate before any write connection is opened. The fixed-table adapter performs
INSERT only with a unique farm/date/scoring-version key. Identical repeated
publication skips existing rows; changed source hashes/evidence or different
semantic output under the same version rolls back the whole transaction, never
updates or deletes rows. Generated execution timestamps/IDs are excluded from
semantic repeat comparison, but source provenance/evidence/calculations are not.

## Stage 5 — Verify stored publication BEFORE enabling final mode

Run read-only comparison of published V3 against regeneration from stored V2:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.v3_local --verify-published
```

Require published_verification.complete_match=true and expected count 232. A
mismatch returns a nonzero exit status; do not activate final mode. This verifies
source linkage/evidence, rules, precision, scores and provenance, not clinical
validity. Optionally run these aggregate-only SQL checks manually:

```sql
SELECT count(*) AS records, count(DISTINCT assessment_date) AS dates,
       count(DISTINCT scoring_version) AS scoring_versions,
       count(*) FILTER (WHERE NOT research_only OR live_warning_allowed) AS invalid_flags,
       count(*) FILTER (WHERE combined_score IS NOT NULL AND
           abs(combined_score-(climate_score+operational_score)/2)>1e-8) AS formula_mismatches,
       count(*) FILTER (WHERE combined_score IS NULL) AS unavailable_combined,
       avg(operational_score) AS operational_mean,
       count(*) FILTER (WHERE operational_score=100) AS operational_at_100
FROM c4_output.farm_risk_assessment_v3;
SELECT count(*) AS missing_sources_or_changed_climate
FROM c4_output.farm_risk_assessment_v3 v3
LEFT JOIN c4_output.farm_risk_assessment_v2 v2 ON v2.output_id=v3.source_output_id
WHERE v2.output_id IS NULL OR v3.climate_score IS DISTINCT FROM v2.climate_score;
SELECT 'V1' AS output, count(*) AS records FROM c4_output.farm_risk_assessment_v1
UNION ALL SELECT 'V2', count(*) FROM c4_output.farm_risk_assessment_v2
UNION ALL SELECT 'RF', count(*) FROM c4_output.milk_decline_prediction_v1;
```

V1/V2/RF should remain the user-reported 597/232/85, absent unrelated authorized
changes. Do not send response items or private payloads to the agent.

## Stage 6 — Activate the permanent published-only dashboard

Only after successful publication/verification, restart the existing backend using
its current authorized configuration/local loopback workflow. Existing API auth
and read-only safeguards remain unchanged. The assessment endpoint's default V1
behavior is preserved for other consumers; `?scoring_version=v3` selects only V3.

Frontend terminal after verification:

```powershell
$env:VITE_C4_RESEARCH_API_ENABLED = 'true'
$env:VITE_C4_PUBLISHED_V3_ENABLED = 'true'
$env:VITE_API_BASE_URL = 'http://localhost:8000/api/v1'
npm.cmd --prefix frontend run dev -- --host localhost --port 5173 --strictPort
```

For a final production frontend artifact, use the same Vite settings and:

```powershell
npm.cmd --prefix frontend run build
```

No .env editing is necessary. This explicit activation setting defaults OFF, so
implementing these files does not prematurely remove working preview warnings.
In final mode, V1/V2 assessment requests are disabled, the scoring selector and
comparison disappear, and only stored contract-3.0.0 V3 records are accepted. No
fallback to V1/V2 or local preview calculation occurs if V3 is missing/invalid.
The UI shows unavailable until authorized published data succeeds. Preview notices
are removed; provisional badges, provenance and Model Information remain. Two
factor cards, date selector/history/contributors and the separate 2022 RF section
are preserved; no Early Warning Outlook is rendered.

## Publication checklist and viva explanation

- Synthetic backend/frontend tests pass and frontend build succeeds.
- Read-only source verification produces 232 unique dates under one source version.
- Climate evidence/scores/rules match V2; two raw alarm indicators are compatible.
- Missing inputs stay unavailable; category boundaries are applied to V3 Combined.
- User approves the new V3 table and publication; backend reader access is confirmed.
- Stored verification complete_match=true; SQL checks show no formula/source errors.
- Original 597/232/85 records and Member 3 V1 references remain unchanged.
- Only then enable final frontend mode; verify no selector, preview comparison or
  biological factor, and no older-version fallback on V3 failure.

Viva explanation: “Member 4 V3 is an explainable historical Climate and Operational
Risk model. It preserves the calibrated Climate score and alarm-indicator rules,
averages the two alarm scores for Operational Risk, and gives Climate and
Operational equal weight in the Farm Risk Score. This avoids allowing one alarm
indicator alone to determine the operational domain maximum. All inputs, rules,
source record references and calculation evidence are retained for traceability.
Missing inputs remain unavailable. It is a provisional research index, not a
clinically validated risk probability or live early warning. The Random Forest
milk-decline experiment is a separate retrospective research output.”

Biological Risk was excluded from V3 because the available recorded health counts
and unknown completeness cannot support a defensible health-risk interpretation.
This design decision does not establish absence of disease or invalidate the
preserved historical V1/V2 research records. MAX-versus-average research comparison
is retained in v3_preview.md and v2_publication.md; the final dashboard is not a
comparison tool.
