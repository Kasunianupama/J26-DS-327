# Member 4 research assessment contract 1.0.0

This is the legacy metadata-gated contract. The separate descriptive 1.1.0
extension and optional approval-gated local adapter are documented in
[research_outputs_local.md](research_outputs_local.md). No DDL or publication
has been approved or executed by creating these files.

This document describes component-side preparation only. No database object or
permission has been created or changed. The Random Forest remains experimental
and separate from deterministic scoring. Its excessive false alarms do not
support reliable live-warning deployment.

## Scoring API

`services.scoring_service.assess_and_score` takes explicit validated climate,
biological and operational inputs, the existing climate configuration/baseline,
and these required output arguments:

- output_id: caller-supplied UUID, unique for each append-only assessment.
- assessment_date, timezone-aware assessment_cutoff, and generated_at.
- config: `schemas.risk_output.ScoringConfig`.
- provenance: `schemas.risk_output.Provenance`.

The service reuses the existing three assessment modules. Alternatively,
`farm_risk.dairy_risk_score.build_farm_risk_output` accepts their assessment objects.
All supplied assessments must match output date, cutoff, source, and core version.
No timestamps, quality, baseline, or production metadata are inferred. Omit a
domain when its inputs cannot be mapped safely. The output records unavailable
scores rather than bypassing the existing mapper or assessment checks.

## Research rules: explicit, provisional, no numerical defaults

The user supplies a versioned configuration with a rationale, one or more
indicator rules per domain, three positive weights summing to one, and category
boundaries `0 < medium_starts_at < high_starts_at < 100`. Each rule supplies an
allowed feature, lower/upper ramp bounds, explicit direction and rationale.
Bounds and categories are research assumptions requiring review, not clinical
thresholds or calibrated probabilities. Increment configuration version when
changing any rule, bounds, direction, category, or weight. The complete config
is serialized in every output. No unverified numerical production defaults ship.
Synthetic tests contain fictional choices that must not be adopted as evidence.

For a higher-is-riskier rule:

`indicator_score = 100 * clip((value - lower)/(upper - lower), 0, 1)`

For lower-is-riskier, replace the clipped fraction with one minus that fraction.
Rules are monotonic and clipped at 0/100. A measured zero is an actual value;
absent/unusable measurements are None, never zero risk.

Allowed features:

| Domain | Features |
|---|---|
| Climate | absolute_exceedance; historical_exceedance |
| Biological | mastitis_episodes; udder_teat_episodes; other_health_episodes |
| Operational | n_sessions; n_blood_alarms; n_conductivity_alarms; blood_alarms_per_session; conductivity_alarms_per_session |

Climate features come directly from the quality-gated climate assessment, so
heat-threshold and historical-anomaly comparisons remain distinct. Biological
counts require the existing per-category availability/completeness checks.
Operational counts with consistency warnings are withheld. Operational ratios
are reused ONLY when the existing assessment has confirmed numerator semantics,
compatible sessions and recording completeness. No new rates or denominators
are calculated. Counts are unnormalized burden indicators, not disease incidence.
Session count direction/range must reflect an explicit research hypothesis, not
an unsupported diagnosis of downtime or worker performance.

The domain score is MAX(configured indicator scores), requiring all configured
indicators to be available. This avoids summing overlapping health/alarm events;
it does not prove independence or clinical validity. Each output retains separate
indicator values, scores, explanations and available/configured counts. Rules
not configured do not silently enter the score; configuration itself defines
coverage and must be considered when comparing results.

`combined = climate_weight * climate_score + biological_weight * biological_score
          + operational_weight * operational_score`

All three domains are required. Missing domains withhold the combined score and
category; known contributions remain visible and weights are not renormalized.
Cross-domain biological/operational overlap can remain: provisional weights need
sensitivity analysis and review before interpretation. Low/medium/high categories
are explicitly suffixed `_provisional`; category boundaries are inclusive at
medium/high starts. Missing combined scores have category `unavailable`.

## Serialized output

`schemas.risk_output.FarmRiskOutput` contains:

- Literal contract version 1.0.0, output UUID, farm identifier FARM_X, assessment
  date/cutoff and generation timestamp.
- Three typed domain results (nullable score, status, separate indicators and
  counts), combined nullable score, weighted contributions and category.
- `data_completeness`: complete when all configured indicators are usable;
  partial when some are usable; unavailable when none are usable.
- `available_domains`: number of fully scored domains, not recording completeness.
- Full scoring configuration, explanations and provenance. Unknown provenance
  fields remain unknown. Input source_version must match supplied core_version;
  no assessment with an unknown/mismatched version is silently merged.
- Literal research_only=true, live_warning_allowed=false, and
  model_status=random_forest_experimental_not_live_validated.

Completeness means declared input usability, not proof of accurate farm recording.
Changing rules can change apparent completeness, so never compare scores without
their scoring configuration. Random Forest probabilities are intentionally NOT
fields of this assessment: consumers must not mistake a deterministic score for
decline probability, or assume this contract validates the current classifier.

Round-trip JSON validates bounds, category, contributions, indicator alignment,
and completeness. Publication preparation revalidates model copies. Metadata and
rationales must obey Farm X confidentiality and contain no names/private free text.
Do not log whole payloads or source records during validation errors.

## Proposed publication and team use

Proposed object (NOT approved or created):

`c4_output.farm_risk_assessment_v1`

Review `docs/sql/PROPOSED_c4_output_v1.sql` separately. It assumes the existing
c4_output schema, adds one append-only research table, and contains no schema,
role, privilege, ETL, core, or c1_output changes. It is never loaded by Python.
SQL includes typed score/status columns and the complete versioned JSON payload.
The Python contract is authoritative for detailed scoring consistency; the SQL
proposal supplies coarse bounds/research/missing-combination constraints.

`output.publisher.prepare_publication(output)` returns a serializable record
without I/O. `publish_to_approved_sink` refuses delivery unless approved_object
exactly equals the proposed object name. It exposes only a fixed Member 4 insert
method on a caller-supplied sink, not arbitrary SQL or object selection. There
is no automatic database connection, migration runner, background publisher,
upsert, delete, overwrite, or retry implementation. A separate optional local
append-only adapter now requires explicit object approval; see the current guide.
Tests supply memory sinks or fake connections only.
A custom sink is executable user code; its eventual implementation must be
reviewed and restricted independently. Naming the object is an explicit caller
gate, not a substitute for team approval or database permissions.

Remaining team steps:

1. Review and approve research rule configuration, quality metadata and category
   interpretation. Current retrospective inputs without verified quality may
   legitimately produce unavailable scores.
2. Approve the proposed object/DDL and contract ownership before the user creates
   anything. No SQL should be run automatically by tests, imports, or scoring.
3. Separately approve and implement a parameterized, transaction-scoped append-only
   adapter restricted to this object. Check duplicate UUIDs explicitly rather
   than overwriting results; never alter ETL tables or another component output.
4. Agree authorised reader access using existing team procedures (no grants here).
   Teammates consume the producer's contract/version and matching core version,
   preserve research/provisional labels, and refuse live-warning use.
5. Agree approved component-output exchange; do not send core/model_input, real
   datasets, credentials, or an entire database. Existing output exchange tools
   are not modified or executed by this work.
6. Backend/shared/frontend integration is a separate team-approved change, not
   part of this component-only implementation. No production warning is enabled.
