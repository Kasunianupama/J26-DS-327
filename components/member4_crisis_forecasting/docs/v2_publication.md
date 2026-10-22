# Separate V2 research assessments — manual verification and approval

The candidate file is read ONLY when YOU run the command. The agent has not opened
C:\FarmX_Private\member4_calibration_candidate.json or verified private contents.
Supply the ORIGINAL reviewed RetrospectiveResearchConfig as baseline. Validation
requires distinct configuration/scoring versions; identical climate settings,
biological rules, core provenance, weights, category boundaries and domain features;
only raw alarm upper bounds may change. No numeric threshold is invented. The
existing engine generates descriptive contract 1.1.0 outputs for 2026-01-01 through
2026-08-20 only, with unknown health recording quality and availability retained.

User-reported comparison: 232/232 old operational scores at 100 vs 137/232 proposed.
This is not independently verified and is not a claim of clinical improvement.
Current snapshots/configuration may differ; check the summary rather than force
the reported count. Missing days/inputs are reported, not filled with zeros.

## 1. Synthetic test command (agent has not executed)

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests/test_v2_outputs.py backend/tests/test_member4_v2_api.py backend/tests/test_member4_research_api.py -q
```

## 2. Real verification, read-only default

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.v2_local --config 'C:\FarmX_Private\member4_calibration_candidate.json' --baseline-config (Read-Host 'Original V1 research configuration JSON path')
```

Existing approved 14-column loader uses farmx_c4 on localhost:5432 (nonsecret C4_DB_*
overrides supported), hidden password, read-only snapshot. No .env reader or row
exports. Summary includes count/eligible count/missing calendar days, domain and
combined distributions, missing-input reasons, saturation and scoring-version
consistency. No publishing, SQL table creation or dump export is invoked by default.

Output UUIDs are deterministic within the NEW V2 namespace by farm/date/scoring
version, distinct from original V1 generation. Generated timestamps are genuine
execution times, NOT historical availability. Known candidate core provenance
is preserved; unknown remains unknown. Scoring version provides calibration
provenance; candidate assumptions/rationales retain reference-period metadata.

## 3. Manual table creation AFTER approval

Review docs/sql/PROPOSED_c4_output_v2.sql. It copies the V1 DEFINITION and checks,
not its rows, and adds a unique farm/date/scoring-version constraint. It never
alters V1 or RF. Confirm farmx_c4 is the authorized schema/table owner before use.

```powershell
psql -h localhost -p 5432 -U farmx_c4 -d farmx_app -W -v ON_ERROR_STOP=1 --single-transaction -f components/member4_crisis_forecasting/docs/sql/PROPOSED_c4_output_v2.sql
```

No schema/role creation or automatic grants occur. farmx_api must have authorized
SELECT on the new V2 table and existing schema USAGE. If not already supplied by
approved defaults, the owner must separately review the minimum permission:
`GRANT SELECT ON c4_output.farm_risk_assessment_v2 TO farmx_api;`
Nothing here executes it or changes existing permissions.

## 4. Publish ONLY after separate explicit approval

After reviewing the aggregate verification and approving V2 publication:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.v2_local --config 'C:\FarmX_Private\member4_calibration_candidate.json' --baseline-config (Read-Host 'Original V1 research configuration JSON path') --publish-approved --approved-object c4_output.farm_risk_assessment_v2
```

All records are validated before opening the publication connection. Only fixed
V2 INSERT and conflict-check SELECT statements are issued in one transaction.
Unique farm/date/scoring-version plus ON CONFLICT DO NOTHING prevents duplicates.
On repeat, existing payloads must match semantically (excluding output identifier
and generated timestamp); otherwise the entire transaction rolls back and requires
a NEW configuration version, never overwrite. There are no UPDATE/DELETE/upsert
replacement statements or V1 writes. No retries or silent changed-snapshot skips.

## 5. Verify aggregate counts

Run manually in the authorized database client, aggregates only:

```sql
SELECT scoring_version, count(*) AS assessments,
       count(DISTINCT assessment_date) AS distinct_dates,
       count(*) FILTER (WHERE operational_score = 100) AS operational_at_100,
       count(*) FILTER (WHERE combined_score IS NULL) AS combined_unavailable,
       min(operational_score) AS operational_min, avg(operational_score) AS operational_mean,
       max(operational_score) AS operational_max, avg(combined_score) AS combined_mean
FROM c4_output.farm_risk_assessment_v2
WHERE farm_id = 'FARM_X' GROUP BY scoring_version;
SELECT 'v1' AS object, count(*) AS records FROM c4_output.farm_risk_assessment_v1
UNION ALL SELECT 'rf', count(*) FROM c4_output.milk_decline_prediction_v1;
```

The latter should remain the user-reported 597 and 85, absent unrelated authorized
changes. A repeated identical publication should report inserted=0 and unchanged
existing equal to the previous batch count. Do not print/send individual payloads.

## 6. Dashboard verification

Restart the existing backend and frontend normally (or use the documented opt-in
local read-only launcher). No authentication/loopback restrictions changed.
The endpoint `/api/v1/risks/research/farms/FARM_X/assessments` defaults to V1 for
existing consumers. `?scoring_version=v2` reads ONLY the new fixed table, validates
payloads, one scoring version, unique dates and the fixed 2026 period. Missing V2
table/permission returns 503; empty table returns empty items. V1 remains usable.

Dashboard fetches each generation separately and automatically chooses V2 only
after a nonempty successful validation. V1/V2 selector never merges records or
trends; manual V2 selection shows unavailable if V2 failed. Select V1 to verify
historical results still match. RF endpoint and Early Warning Outlook are unchanged.
Biological zero remains dependent on unknown recording completeness, not absence
of disease. Changing the private candidate cannot change existing stored outputs.

## 7. Updated Member 4-only dump AFTER export approval

Use a NEW filename in an existing private directory; do not overwrite an earlier
dump. This exports exactly three Member 4 tables, including original reproducible
V1 and RF plus V2. No C1/core/ETL or private model/config files are included.

```powershell
pg_dump -h localhost -p 5432 -U farmx_c4 -d farmx_app -W --format=custom --no-owner --no-privileges --table=c4_output.farm_risk_assessment_v1 --table=c4_output.farm_risk_assessment_v2 --table=c4_output.milk_decline_prediction_v1 --file='C:\FarmX_Private\member4_outputs_v1_v2_rf.dump'
```

The recipient needs the existing c4_output schema and reviewed local access
setup. Do not use --clean or replace tables blindly on the recipient machine.
Only authorized teammates may receive component-output dumps. No dump, SQL,
publication, tests or real-data processing was executed by the agent.
