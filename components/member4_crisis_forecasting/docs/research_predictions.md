# Saved Random Forest research prediction outputs

This is inference-only, user-run retrospective research. No model or threshold
is trained, selected, recalibrated, refit or saved by prediction. The existing
597 rule-based assessments are not read, updated, deleted, or referenced by SQL.
The separate proposed prediction object has not been created or approved.

## Trusted artifact and compatibility

Use the private .pkl created by `prediction.train_local --artifact-path`, outside
the repository. The CLI requires `--trust-local-artifact`: pickle can execute
code while loading, BEFORE schema checks. Use only your own trusted locally
created artifact, never an untrusted download. Do not upload it to the agent.
It must have been trained on published historical data, not synthetic fixtures.

Checks require artifact version 1.0.0, research-only flags, a fitted Random Forest,
matching saved model parameters, exact raw/transformed feature order and feature
definitions, correct fitted preprocessing, and identical Python/scikit-learn/NumPy
versions. No compatibility bypass/retraining or new dependency is added. A SHA-256
of the private artifact identifies provenance without storing its path/password.
This fingerprint does not identify the training dataset/core publication, whose
version remains unknown in existing artifacts.

## Eligibility, features, outcomes and partitions

The saved configuration supplies milk source, target definition, threshold and
original train/validation/test boundaries. CLI arguments cannot change them.
Each requested historical origin must have the matching source, nonmissing
production and ETL eligibility. All t-7..t-1 calendar dates must exist and be ETL
eligible, with complete same-source milk history and positive historical baseline.
The saved integrated (or original production-only) feature builder is reused.
Auxiliary missingness is handled by the SAVED training-only preprocessing; it
is never refitted or filled using future observations. No t or t+1..t+7 values
enter X. Source switches and calendar gaps are not repaired.

Selection by historical ETL scoreability is a retrospective cohort rule, NOT
proof that eligibility/quality flags were known at the historical origin. Entry
delays and corrections remain unknown. These are experimental model scores,
not calibrated risks, diagnoses, or reliable future forecasts.

Original split rules and seven-day boundary purges are preserved:

- train_in_sample: original training origins with outcomes inside train_end;
- validation_model_selection: original validation origins with outcomes inside
  validation_end, already used for model/policy selection;
- test_exploratory: original test origins with outcomes inside test_end; the
  examined 2022 period remains exploratory;
- post_experiment_research: dates strictly after original test_end, separately
  labelled research, never silently turned into a new untouched test set.

Original boundary-purged origins are excluded. Later observations cannot change
the saved experiment boundaries, forest, preprocessing or threshold.

The existing retrospective target function attaches the actual outcome AFTER
features/eligibility have been built. It may use t+1..t+7 actual production only
for that annotation. It requires all 15 same-source scoreable dates with a
positive reference. If future outcomes are missing/unusable, actual_outcome is
null with a reason; an eligible probability remains available. Loader reads
through requested end+7 (capped at the actual execution date), solely to support
these retrospective annotations. No historical availability time is invented.

If the saved threshold is null, predicted_decline is null and status is
no_saved_threshold. No 0.5 fallback or new policy search occurs. Legacy zero-grid
thresholds are labelled legacy_not_warning_policy. All other classifications
are experimental only; every output forbids live warning use.

## Default READ-ONLY verification command

Run from the repository root in an interactive PowerShell terminal:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.prediction.predict_local `
  --artifact-path (Read-Host 'Trusted private Random Forest .pkl path') `
  --trust-local-artifact `
  --start-date (Read-Host 'Historical assessment start YYYY-MM-DD') `
  --end-date (Read-Host 'Historical assessment end YYYY-MM-DD')
```

The existing fixed 14-column loader uses a read-only transaction as farmx_c4 in
farmx_app. Port defaults to 5432 with nonsecret C4_DB_HOST/C4_DB_PORT overrides.
Password input is hidden and .env is never read. Default execution does not
open a write connection, save private predictions, print rows, export files,
touch the assessment table, or invoke any prediction publication method.

Stdout is a concise aggregate summary: eligible/excluded counts, probability
count/mean/min/max, missing-classification counts, actual-outcome availability,
class counts and original partition distributions. No individual dates, scores,
predictions, outcomes, model bytes, file paths or credentials are printed.

## Prediction contract and proposed object

`prediction.research_prediction.ResearchPrediction` is contract 1.0.0 for the
SEPARATE prediction object, not rule-based assessment contract 1.0.0/1.1.0.
Fields include UUID, FARM_X, assessment date, generation timestamp, model artifact
version/fingerprint, experimental probability interpretation, saved threshold,
nullable classification and outcome/reason, original partition, source and
original configuration. research_only=true and live_warning_allowed=false are
literal enforced flags. Historical availability/recording completeness are unknown.

Review `docs/sql/PROPOSED_milk_decline_prediction_v1.sql` independently. It proposes
ONLY `c4_output.milk_decline_prediction_v1`. It contains no assessment-table,
ETL, core, c1_output, schema, permission, migration, or restore changes. The Python
code never executes DDL. Do not execute it until explicit approval.

## Future publication — DO NOT RUN WITHOUT SEPARATE EXPLICIT APPROVAL

After independent approval and manual creation of the proposed table, and after
reviewing default verification, publication itself needs separate explicit approval:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.prediction.predict_local `
  --artifact-path (Read-Host 'Same trusted private Random Forest .pkl path') `
  --trust-local-artifact `
  --start-date (Read-Host 'Same approved historical start YYYY-MM-DD') `
  --end-date (Read-Host 'Same approved historical end YYYY-MM-DD') `
  --publish-approved --approved-object c4_output.milk_decline_prediction_v1
```

Both flags must identify this exact prediction object; approval for the assessment
table cannot be reused. The dedicated adapter revalidates records and performs
fixed-table parameterized INSERTs in one transaction, with rollback on failure.
No upsert, update, delete, drop, migration, permission change, or retries exist.
It never writes farm_risk_assessment_v1. Repeated calls append fresh UUIDs and are
not idempotent: do not retry blindly after an uncertain commit. Publication
recalculates on the current snapshot, which can differ from earlier verification;
review again if inputs/artifact changed. No row-level export/dump is added here.

## Synthetic tests (manual only)

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

Tests use existing synthetic fitted-artifact fixtures, fictional aggregates,
trusted temporary synthetic pickle files, and fake database connections/loaders.
Prediction paths are tested with fit methods forbidden. The agent has not run
tests, loaded private artifacts, accessed data, predicted on real records,
published outputs, or executed SQL. Existing assessment records remain untouched.
