# Minimum 2025–2026 research-output workflow

Current mode is explicitly **descriptive retrospective scoring**, not quality-
verified risk or reliable live warning. The 14 approved columns can describe
recorded climate, health and operational burden, but cannot establish completeness,
historical availability, episode semantics, diagnosis, or alarm causes. This mode
does not relabel them as verified, forge timestamps, call metadata-gated assessments
with counterfeit inputs, retrain Random Forest, or change its results.

## Required explicit research configuration

Create a private JSON file outside Git using
`services.retrospective_scoring.RetrospectiveResearchConfig`:

| Key | Contents |
|---|---|
| version | Nonblank reviewed research configuration version |
| assumptions | Explicit explanation of using recorded aggregates despite unknown completeness/semantics |
| scoring | Existing full ScoringConfig with version/rationale, indicator ramps/directions, three weights summing to one, medium/high boundaries |
| climate | Existing ClimateConfig; heat_stress_threshold may be null, withholding absolute exposure scoring |
| core_version | Actual known publication version or null; never invent one |

Use the existing reviewed scoring configuration; no numerical weights, clinical
cutoffs or production research defaults are provided here. The `.scoring` and
`.climate` objects can be reused from the quality-verification configuration,
with a new version/assumptions declaration for this different research basis.
Unknown `core_version` stays null and must limit downstream interpretation.

Descriptive rules reuse the existing clipped ramps, separate indicator scores,
MAX within each domain, and fixed weighted combination. Missing configured
indicators withhold their domain and combined score without weight redistribution.
Biological categories and alarm categories are never added together. Raw recorded
zero can map to a zero descriptive index; this is NOT proof of zero actual health
or operational risk. Counts are not incidence, prevalence or equipment diagnoses.
Positive alarms with zero sessions are withheld as inconsistent. No ratios are
calculated. Historical climate anomaly remains unavailable in this mode because
it requires independently established baseline provenance; an explicitly configured
absolute THI comparison can support a descriptive climate index.

`is_scoreable` remains a production eligibility flag, not a recording-quality
declaration for the three scoring domains. No domain completeness is inferred
from it. Session counts, health counts and THI values are taken exactly as supplied
by the approved aggregate validation contract.

## Calculate and verify locally now (READ ONLY)

From the repository root, in an interactive PowerShell terminal:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.research_outputs_local `
  --config (Read-Host 'Path to reviewed descriptive research configuration JSON') `
  --start-date 2025-01-01 --end-date 2026-12-31
```

The password prompt is hidden. Defaults are localhost:5432, farmx_app, farmx_c4;
only nonsecret C4_DB_HOST/C4_DB_PORT overrides are read, never .env. The existing
loader reads only its 14 approved columns in a read-only transaction. Processing
is restricted to 2025–2026 and excludes future observation dates beyond actual
execution date. No output records or raw data are printed or saved. Results stay
in memory; stdout contains eligible score counts/means/min/max, unavailable reasons
and provisional category distributions only. All clinical/availability limitations
remain explicit. No output publication connection is opened in default mode.

## Output distinction and contract version

Legacy quality-gated outputs remain contract 1.0.0 with their actual cutoff and
quality checks. They must not be described as quality-verified merely because
the contract exists: inspect actual provenance/evidence and recording declarations.
The quality-verification CLI remains unchanged and continues withholding scores
when required metadata are absent.

New descriptive outputs are contract **1.1.0**, validated by
`schemas.risk_output.DescriptiveRiskOutput`, with:

- `score_basis=descriptive_retrospective_unverified`;
- `recording_quality=unknown`, `provenance.availability=unknown`;
- `assessment_cutoff=null` (no midnight or retrospective cutoff invented);
- actual generated_at, recorded assessment_date, caller-declared research assumptions;
- `research_only=true`, `live_warning_allowed=false`, unchanged experimental RF status.

`data_completeness` denotes computational coverage of configured values ONLY,
not verified recording completeness. Each output retains all rules, weights,
contributions, indicator/domain explanations, provenance and nullable scores.
Consumers must dispatch by contract_version using `validate_research_output`.
Preparing an output never publishes it. Scores/categories are not forecasts.

## APPROVAL REQUIRED: table proposal and publication

**Do not execute the following publication or export commands until the user has
explicitly approved that step. This document is preparation, not approval.**

Review the updated `docs/sql/PROPOSED_c4_output_v1.sql`: one proposed table,
`c4_output.farm_risk_assessment_v1`, accepting payload contracts 1.0.0/1.1.0,
explicit score_basis, and nullable assessment_cutoff only for descriptive outputs.
No tables or migrations have been executed. If the table was already created
from an earlier proposal, STOP and review a separate compatibility migration;
the Python code does not create, alter or silently adapt tables.

After explicit DDL approval, the user may execute the proposed table SQL using
their authorised tooling. No schema/permission commands are supplied or run.
After the table exists in the reviewed shape and publication is separately approved:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.research_outputs_local `
  --config (Read-Host 'Path to approved descriptive research configuration JSON') `
  --start-date 2025-01-01 --end-date 2026-12-31 `
  --publish-approved --approved-object c4_output.farm_risk_assessment_v1
```

Only this explicit command opts into writes. It recalculates using the CURRENT
input snapshot; if data/config have changed since verification, verify again
before approval. Optional `output/local_publication.py` prevalidates the batch,
uses fixed parameterized INSERT statements to that table only, and commits one
transaction. Any failure rolls back through psycopg's connection context. It
performs no DDL, grants, upserts, updates, deletes, retries, c1_output or ETL writes.
Every invocation has new UUIDs and appends a new assessment run: repeated execution
is NOT an idempotent retry. Do not rerun blindly after uncertain client/network
failure; check aggregate row counts locally. No records are logged or dumped.

## APPROVAL REQUIRED: table-only dump export

Only after publication and explicit export approval, and only to an authorised
teammate using the existing output-exchange process:

```powershell
pg_dump --host=localhost --port=5432 --username=farmx_c4 --dbname=farmx_app `
  --password --format=custom --strict-names `
  --table=c4_output.farm_risk_assessment_v1 `
  --no-owner --no-privileges `
  --file (Read-Host 'New private destination path for approved Member 4 table-only dump')
```

Use a NEW private destination to avoid overwriting an existing artifact. This
exports only the named output table, not the database/core/model_input/c1_output.
Keep the dump private and outside Git; do not send it to the coding agent or a
public/cloud service. The command requires pg_dump and existing authorised read
access; this implementation installs nothing and changes no permissions. No restore
command is run or required here. Consumers retain research/provisional labels,
check contract/configuration versions, reject live-warning use, and treat unknown
core provenance as unknown. Shared frontend/backend integration remains separate.

## Synthetic verification

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

New tests use fictional rows/configurations, fake connections and denied-by-default
publication paths. The coding agent has not run tests, real calculation, publishing,
DDL, exports, classifier training, package installation, or database connections.
