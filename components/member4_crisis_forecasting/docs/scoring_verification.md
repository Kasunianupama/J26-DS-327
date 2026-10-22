# Local read-only Farm Risk scoring verification

User-run only. The coding agent must not run this program, read these private
metadata files, or access a database. It does not train a classifier, publish
outputs, write records, create tables, or change permissions. It reuses the
approved 14-column read-only loader, mapper, domain assessments and scoring engine.
It does not import the publishing interface or ML training workflow.

## Required local JSON documents

Keep both explicitly chosen files in a private local directory outside the
repository. They must be .json; no .env discovery, credential files, directory
search, or wildcard loading is supported. Duplicate JSON keys are rejected.
Do not paste files, records, credentials, or individual verification outputs into
chat. The CLI prints only aggregate results, never dates/rows or individual scores.

### Research scoring configuration

`schemas.scoring_verification.VerificationConfig` requires:

| Key | Required contents |
|---|---|
| version | Explicit nonblank version for this verification configuration |
| scoring | Complete existing ScoringConfig: version, rationale, three rule lists, explicit weights summing to one, explicit category boundaries |
| climate | Existing ClimateConfig; heat_stress_threshold may remain null, in which case absolute comparison is unavailable |
| climate_baseline | Optional existing ThiBaseline; absent means historical anomaly comparison unavailable |

No numerical research config is supplied as an approved default. Obtain reviewed
weights, ramp bounds/directions, threshold evidence, category assumptions and
rationales from your research protocol. The scoring configuration format is
documented in [output_contract_v1.md](output_contract_v1.md). Synthetic test values
are fictional and must not be promoted into scientific criteria.

A historical baseline must have been fitted solely on an earlier eligible
training window, with verified source/version and a fit cutoff no later than the
assessment cutoff. An ineligible baseline is withheld and counted; an independently
eligible absolute climate comparison is retained. No baseline is fitted here.

### Versioned recording-quality/provenance metadata

`VerificationMetadata` requires version, quality_policy_version, and days (a list).
The list can be empty if metadata are genuinely unknown: all loaded days then
remain unavailable rather than being assigned invented metadata.

Each days entry contains:

| Key | Meaning |
|---|---|
| metadata | Existing AggregateMetadata for exactly one observation_date |
| assessment_cutoff | Actual explicitly chosen timezone-aware assessment cutoff |
| availability_evidence | unknown (default) or verified; only verified permits scoring |

Inside metadata:

- observation_date: date key; duplicate metadata dates are rejected.
- source: published for this real-data CLI (synthetic only in unit tests).
- source_version: actual ETL/core publication version, or null when unknown.
- climate, biological, operational: separate DomainMetadata objects containing
  observation_end, available_at and quality (ok/partial/unavailable/unknown).
- health_recording: mastitis_episodes, udder_teat_episodes, other_health_episodes
  completeness declarations (complete/incomplete/unavailable/unknown).
- operational_recording: n_sessions, n_blood_alarms, n_conductivity_alarms declarations.
- blood_definition and conductivity_definition: count_unit
  (unknown/events/flagged_sessions) and denominator_compatible (false by default).
- production metadata may remain unknown: production is_scoreable and production
  availability are not required or borrowed for climate/health/operational scoring.

All domain metadata and recording declarations use their existing conservative
unknown defaults. A present count is not proof of completeness. Do not mark
availability_evidence=verified merely because you can supply a timestamp. It is
an explicit assertion backed by producer records; the software cannot establish
its truth. available_at must cover every indicator included in that domain.
Extraction time, ETL publication time and generated_at are not substitutes for
historical availability. Where evidence is absent, leave unknown and expect
unavailable scores. Future availability withholds only the affected domain.

quality_policy_version must identify the actual reviewed recording-quality policy;
do not invent a version just to satisfy validation. If no policy/config exists,
the CLI cannot proceed safely: finish those research decisions first. With an
explicit policy, unknown per-date declarations are allowed and reported as such.

## One PowerShell command

Run from the repository root in an interactive local terminal after preparing
the reviewed files. Use preselected verification dates. Port defaults to 5432;
the existing nonsecret C4_DB_HOST/C4_DB_PORT environment overrides are supported.
The password is requested with a hidden prompt, never a CLI argument or .env read.

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.verify_scoring_local `
  --config (Read-Host 'Path to reviewed versioned scoring JSON') `
  --metadata (Read-Host 'Path to reviewed recording-quality metadata JSON') `
  --start-date (Read-Host 'Verification start YYYY-MM-DD') `
  --end-date (Read-Host 'Verification end YYYY-MM-DD')
```

The reused loader reads only its approved columns up to end-date in a read-only,
repeatable-read transaction as farmx_c4. The verifier then restricts processing
to the requested inclusive start/end range; no data is exported. It does not query
publication metadata, other schemas, individual animals, or source records.

## Interpreting the aggregate summary

- Raw indicator counts: observed/missing/recorded-zero for all climate, biological
  and operational columns. thi_max/hours are inspected for presence but are not
  silently added to scoring rules that use only the existing THI comparisons.
- Mapped-domain counts: timestamps/provenance permit constructing inputs; this
  alone does not mean recording quality supports a score.
- Configured-indicator availability and eligible domain/combined score counts.
- Score count, mean, min/max over eligible scores only, plus provisional category
  counts. Missing scores never enter these summaries as zeros.
- Safe aggregate unavailable-reason counts: absent metadata/version/quality,
  unverified availability, late records, missing measurements, unconfigured heat
  comparisons, unavailable historical references, and unsupported ratios/recording.
  Reasons may overlap and do not necessarily sum to loaded days.

Weights, indicators, and categories remain provisional. If required inputs are
unavailable, the combined score and category are unavailable; fixed weights are
not redistributed. Exit 0 means verification completed, even if every score was
withheld. The status explicitly identifies when no combined scores are available.
Exit 2 means invalid documents/configuration/range or a sanitized local failure.
No private exception values or database details are printed. generated_at is the
actual execution clock, used only as an output-generation upper bound.

## Synthetic verification command

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

New tests use fictional aggregates and explicit fake metadata, a mocked password
prompt and loader. They cover unknown/missing quality and evidence, zero versus
missing, cutoff eligibility, missing thresholds/baselines, provenance, safe CLI
output, duplicate metadata, and invalid input documents. No real verification,
database access, publishing, or automated test execution is performed by the agent.
