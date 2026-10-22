# Crisis Forecasting

## V3 final publication — staged, not activated automatically

The final two-domain **Climate and Operational Risk Model** has its own 3.0.0
contract and a user-run read-only verification / approval-gated append-only
publication workflow. Climate and calibrated indicator rules are retained from
stored V2; Operational averages the two alarm scores, Combined averages Climate
and Operational. Missing inputs remain unavailable. V1/V2/RF records are untouched.

Follow [V3 verification, publication, final dashboard activation and viva notes](docs/v3_finalization.md).
Published-only frontend mode remains disabled until the owner verifies publication
and explicitly enables it. No table, record, permission or database change runs
automatically; no dump export is part of this implementation.

## C1 forecast context integration

The new user-run read-only C1 adapter validates an explicitly selected real
`c1_output.outlook` run against the shared contract, daily dates/horizons, quality,
intervals, cutoff and provenance. It produces aggregate verification only, with
research-only context and validated warnings always withheld. No demo fallback,
RF retraining, publication, exports or assessment updates are enabled.
See [authorization, commands and limitations](docs/c1_integration.md) and the
[separate proposed Member 4 output table](docs/sql/PROPOSED_c1_forecast_context_v1.sql).
C1 read permission must be confirmed locally; it is not assumed. Existing 597
rule-based assessments and experimental RF predictions remain separate and untouched.

## Saved-model historical research predictions (inference only)

`prediction/predict_local.py` restores your trusted private artifact and uses the
existing feature builder, exact feature order and FITTED preprocessing without
training or changing model/threshold selection. Only t-7..t-1 enters X. Actual
outcomes are annotated separately where eligible; missing outcomes stay null.
Original split labels and purge rules are retained, with later dates explicitly
post-experiment research. Availability/completeness remain unknown and probabilities
are uncalibrated experimental scores, not reliable forecasts. Missing saved
thresholds produce no warning classification.

One default user-run READ-ONLY verification command:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.prediction.predict_local `
  --artifact-path (Read-Host 'Trusted private Random Forest .pkl path') `
  --trust-local-artifact `
  --start-date (Read-Host 'Historical assessment start YYYY-MM-DD') `
  --end-date (Read-Host 'Historical assessment end YYYY-MM-DD')
```

Output is aggregate-only; no row-level predictions are printed/saved. Read
[research prediction instructions](docs/research_predictions.md) for artifact
trust/version checks, contract, eligibility and the separately approval-gated
publication command. The proposed new table is
`c4_output.milk_decline_prediction_v1`, reviewed via
[separate proposed SQL](docs/sql/PROPOSED_milk_decline_prediction_v1.sql).
No SQL was executed and publication is NOT approved. The existing 597 assessments
in `c4_output.farm_risk_assessment_v1` are outside this workflow and untouched.

Manual synthetic verification:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

No tests, private model loading, real-data prediction, database access/writes,
ETL/permission changes, package installs, or retraining were performed by the agent.

## Optional private Random Forest artifact saving

The existing `prediction.train_local` CLI now accepts `--artifact-path`. It uses
the SAME approved read-only loader and `run_experiment` training, preprocessing,
feature ordering, validation-only model/threshold selection and evaluation.
Nothing is retrained or refit just for saving. Without this option, ordinary
evaluation-summary behavior is unchanged and no artifact is built or saved.
Direct callers can supply optional `artifact_callback` to receive the fitted
bundle; the return value remains the existing aggregate summary dictionary.

`prediction/model_artifact.py` allowlists artifact version 1.0.0 contents:

- The selected fitted RandomForestClassifier (not other candidates or Dummy).
- Fitted TrainingFeaturePreprocessor, including training medians, active-column
  mask and missing indicators; None explicitly denotes production-only identity
  preprocessing. No training matrices or raw records are included.
- Exact raw/transformed feature order, versioned definitions and t-7..t-1 window,
  experiment configuration, selected forest name/settings, and software versions.
- Selected threshold (possibly None), reference threshold, selection status and
  warning-policy status. No valid warning policy is invented when selection failed.
- `model_status=random_forest_experimental_not_live_validated`, research_only=true,
  live_warning_allowed=false, retrospective limitations and exploratory test status.

No farm rows, date-indexed feature matrices, labels, individual predictions,
passwords or connection settings are passed to the artifact builder. Learned
parameters still encode information derived from private data: keep the model
private/local and do not upload it, commit it, or treat it as an approved team
output. No prediction table or publication workflow is added by artifact saving.
Input publication version and historical availability remain unknown rather than
being inferred. An artifact does not improve or validate model performance.

Saving requires an EXISTING private directory outside the repository and a NEW
`.pkl` filename. The CLI checks the path before requesting credentials/loading
data; saving refuses overwrite using exclusive creation. No directories are
created. Serialization occurs before opening the destination. If training has
insufficient data, no model is saved; CLI reports `not_saved_no_fitted_model`.
Otherwise `artifact_save_status=saved_private_research_artifact` is added only
for opt-in CLI runs. The artifact itself is never printed. A failed save returns
the existing sanitized failure response; no database data is changed.

One exact user-run PowerShell command from the repository root. Use your original
preselected source, label threshold, weighting, comparison mode, threshold mode
and split dates to avoid changing methodology. Port defaults to 5432 and password
entry remains hidden:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.prediction.train_local `
  --acknowledge-retrospective-limitations `
  --feature-set integrated `
  --milk-source (Read-Host 'Original milk source: shipment or delpro') `
  --decline-threshold-pct (Read-Host 'Original experimental decline percentage') `
  --decision-threshold (Read-Host 'Original reference decision threshold') `
  --class-weight (Read-Host 'Original class weight: none or balanced_subsample') `
  --forest-comparison (Read-Host 'Original comparison: fixed or validation_small') `
  --threshold-selection (Read-Host 'Original selection: fixed, validation_f1, or validation_f1_legacy') `
  --train-end (Read-Host 'Original training end YYYY-MM-DD') `
  --validation-end (Read-Host 'Original validation end YYYY-MM-DD') `
  --test-end (Read-Host 'Original exploratory test end YYYY-MM-DD') `
  --artifact-path (Read-Host 'NEW private .pkl path outside the repository')
```

This command trains/evaluates once on user execution and saves that run's selected
forest; it cannot recover an earlier in-memory model or an unavailable historical
snapshot. Use matching code and Python/scikit-learn/NumPy versions when restoring.
Pickle loading can execute code: only load your trusted local artifact, never an
untrusted downloaded model. Raw inputs must be rebuilt in saved feature order and
transformed by the saved preprocessing before model use. No live inference or
warning deployment is authorized or implemented by creating the artifact.

New tests use fictional rows and trusted synthetic temporary pickle files, with
mocked loading/password/file-saving for CLI tests. No test or training was run
by the coding agent for this task. Manual synthetic command:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

## 2025–2026 descriptive research outputs (current minimum workflow)

The new user-run CLI calculates descriptive provisional scores from the existing
approved 14-column read-only loader without inventing recording quality or
historical availability. It reuses the existing scoring ramps/maxima/weighted
sum with an explicit versioned research configuration and assumptions. Missing
values, unverified ratios and unsupported historical anomalies remain unavailable.
It neither trains nor invokes Random Forest.

Contract 1.1.0 explicitly labels descriptive outputs, recording quality unknown,
availability unknown, and a null historical assessment_cutoff. Legacy contract
1.0.0 and the metadata-gated verification path remain supported. Neither basis
allows reliable live warnings. Provisional categories are descriptive research
indices, not clinical diagnoses or validated forecasts.

One default READ-ONLY local command:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.research_outputs_local `
  --config (Read-Host 'Path to reviewed descriptive research configuration JSON') `
  --start-date 2025-01-01 --end-date 2026-12-31
```

Read [the workflow guide](docs/research_outputs_local.md) for the configuration
contract, aggregate-summary interpretation, and exact separately approved
publication and table-only pg_dump commands. These commands are NOT approval to
create tables, publish or export now. The optional new adapter has fixed-table,
parameterized, append-only insertion, accessible only via explicit approval flags.
No import/calculation automatically opens a write connection. The SQL proposal
was updated for 1.1.0 but never executed; existing older tables need separate review.

Synthetic suite, for manual execution only:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

No database access, tests, writes, publication, exports, permission changes,
commits, retraining, or private-file inspection were performed by the agent.

## Local read-only scoring verification

`services/verify_scoring_local.py` is a USER-RUN verification CLI using the existing
approved 14-column read-only loader, aggregate mapper, three domain assessments,
and scoring engine. It neither retrains Random Forest nor publishes outputs.

Two explicit private JSON documents are required: `VerificationConfig` (versioned
research rules, thresholds, weights and climate configuration) and
`VerificationMetadata` (versioned recording-quality policy and per-date provenance,
domain timing, recording declarations, assessment cutoff and availability evidence).
No missing metadata, scientific cutoffs or weights are invented. Unknown historical
availability remains unknown and withholds scoring. Domain scores require the
existing eligibility checks; missing domains withhold combined scores.

The local summary contains aggregate indicator-presence counts, eligibility counts,
unavailable reasons, eligible score means/min/max and category counts, with no
individual records/predictions. Detailed document formats, conservative defaults,
and interpretation: [scoring verification guide](docs/scoring_verification.md).

One local PowerShell command from the repository root (password prompt hidden;
port defaults to 5432):

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.verify_scoring_local `
  --config (Read-Host 'Path to reviewed versioned scoring JSON') `
  --metadata (Read-Host 'Path to reviewed recording-quality metadata JSON') `
  --start-date (Read-Host 'Verification start YYYY-MM-DD') `
  --end-date (Read-Host 'Verification end YYYY-MM-DD')
```

Synthetic suite for user execution:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

No tests, real-data processing, database access, publishing, schema/permission
changes or classifier training were performed by the coding agent for this step.

## Provisional Farm Risk scoring and team output preparation

Component-side scoring now reuses the existing climate, biological and operational
assessments through `services/scoring_service.py`. The engine is
`farm_risk/dairy_risk_score.py`; the versioned contract is
`schemas/risk_output.py` (1.0.0). Full definitions and integration procedure:
[output contract](docs/output_contract_v1.md).

Supply explicit research indicator ramps, directions, rationales, weights and
category boundaries using `ScoringConfig`. There are NO clinical thresholds or
default numerical scoring weights. A domain uses the maximum configured
indicator score, requiring all configured values to be usable. The combined
score uses the fixed weighted sum of all three complete domains. Missing scores
remain None, with combined score/category withheld rather than renormalized.
Outputs include separate indicators, contributions, completeness and calculation
explanations, with low/medium/high categories explicitly marked provisional.

Random Forest decline classification remains separate. Current exploratory
performance and false alarms do not justify reliable live warnings. Every
assessment carries research_only=true and live_warning_allowed=false. Existing
ML files/results are preserved; scoring neither trains nor invokes a classifier.

`output/publisher.py` prepares records without side effects and defines a fixed
object delivery seam requiring explicit approval plus a caller-supplied sink.
That interface has no automatic database adapter. The separately approval-gated
optional adapter is documented in the current research-output workflow above;
all automated publication tests use memory-only fake connections/sinks.
Proposed object requiring separate approval:
`c4_output.farm_risk_assessment_v1`. Review
[proposed SQL](docs/sql/PROPOSED_c4_output_v1.sql); it has NOT been executed.
Existing c4_output is assumed; no schema, role, privilege, or ETL changes are made.
Full output contains typed domain results plus reproducible configuration and
provenance, and serializes to JSON for eventual approved team consumption.

Run the synthetic suite yourself (not executed by the agent for this task):

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

Before publishing: approve scoring rules/metadata, review DDL, separately implement
and review a restricted append-only adapter, agree reader access/output exchange,
and coordinate shared/backend/frontend contracts. No permission or database
changes, publishing, real-data processing, or test execution occur in this task.

## Diagnostic Random Forest comparison (current improvement)

The user-reported all-alert result is not useful discrimination: threshold 0
turns every nonnegative class probability into an alert. The former 0.01 grid
cannot resolve separation below 0.01. Neither the supplied all-alert metrics nor
low probabilities alone establish a class-column bug. The implementation now
maps the positive probability using `classes_` and explicitly requires normal=0,
decline=1, finite probabilities summing to one, and fitted feature dimensions
matching the transformed feature-name order. Date-based feature assembly, target,
source checks, training-only preprocessing, and purge boundaries are unchanged.

Only 17 positive training labels and substantially different validation/test
class frequencies were reported by the user. Sparse events, temporal population
shift, filtering of severe declines, missing domains, and poor generalization
are possible explanations, not verified causes. Reweighting or deeper trees may
overfit the few events. No real rows were inspected and no new performance exists.

Current `--threshold-selection validation_f1` uses validation ONLY and a fixed
fine grid 0.0001..0.0099 by 0.0001, then 0.01..1.00 by 0.01, plus the reference.
Zero is excluded. A candidate must alert on SOME but not all validation samples,
detect at least one positive, have precision above validation prevalence, and
F1 strictly above the naive all-alert F1. Maximize eligible F1, then precision,
then highest threshold. These are research sanity checks, not clinical policy
requirements. Single-class validation or no eligible candidate gives a NULL
selected threshold and `no_warning_policy` instead of success metrics. It does
not automatically deploy a fixed fallback. Reference-threshold metrics and AP
remain available to expose the failure; no metrics are fabricated. The constant
Dummy benchmark has no discriminating policy, but its reference metrics remain.
These rejection rules do not guarantee useful generalization or calibrated risk.

`--forest-comparison validation_small` predefines just three Random Forest
configurations (the only main ML family):

| Candidate | max_depth | min_samples_leaf | Class weight |
|---|---|---|---|
| reference | 5 | 5 | Supplied --class-weight (none by default) |
| weighted_regularized | 4 | 10 | balanced_subsample |
| weighted_flexible | 8 | 2 | balanced_subsample |

All use 200 trees, sqrt feature sampling, bootstrap, seed 0, n_jobs=1. Every
candidate fits TRAINING only with the same frozen training preprocessing. Choose
eligible settings by validation F1 then precision; model ties retain predefined
order. No candidate test predictions enter selection, and only the chosen forest
and Dummy receive test metrics AFTER settings and threshold are frozen. If no
candidate qualifies, retain the reference estimator for diagnostic metrics and
report no meaningful validation warning policy. There is no refitting afterward.

Aggregate report additions: split positive fractions, per-candidate training and
validation reference metrics, validation precision/recall policy tradeoffs, and
probability means/quantiles, zero/distinct-score counts, and fixed-bin distributions
overall and conditional on actual class. No individual prediction/record arrays
are returned. Existing per-feature coverage, dropped columns, and feature importance
remain. In-sample training metrics are optimistic; compare them with validation
to investigate overfitting without inspecting exploratory test to tune settings.

Original reproduction: use `--forest-comparison fixed` (default) with original
class weight, splits, features, snapshot/software versions and
`--threshold-selection validation_f1_legacy`. This retains the old grid including
zero and explicitly labels its results LEGACY REPRODUCTION, NOT A WARNING POLICY.
Fixed 0.5 remains available via `--threshold-selection fixed`. Previously reported
21.18% accuracy/precision, 100% recall, 34.95% F1, and 67 false alarms among 85
test samples are user-supplied exploratory results, not new measurements. They
remain a historical comparison; no private result files are read or overwritten.
The examined 2022 test is still exploratory, never an untouched final holdout.
The small search and threshold selection can themselves overfit validation.

Exact synthetic command (agent must not execute in this task):

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

One USER-RUN local read-only comparison/evaluation; select source, label threshold,
and split dates in advance, keeping them identical to the comparison experiment:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.prediction.train_local `
  --acknowledge-retrospective-limitations `
  --feature-set integrated `
  --milk-source (Read-Host 'Milk source: shipment or delpro') `
  --decline-threshold-pct (Read-Host 'Previously selected experimental decline percentage') `
  --decision-threshold 0.5 `
  --class-weight (Read-Host 'Original class weight: none or balanced_subsample') `
  --forest-comparison validation_small `
  --threshold-selection validation_f1 `
  --train-end (Read-Host 'Original training end YYYY-MM-DD') `
  --validation-end (Read-Host 'Original validation end YYYY-MM-DD') `
  --test-end (Read-Host 'Original exploratory test end YYYY-MM-DD')
```

The hidden password prompt and port 5432 are unchanged. This program only reads
the existing 14-column allowlist. No schemas, permissions, ETL state, or private
records are written. No test, training, package installation, or DB connection
was performed by the agent for this change.

## Integrated four-factor Random Forest (current default)

`--feature-set integrated` is now the default: ONE RandomForestClassifier combines
milk, climate, biological, and operational signals. DummyClassifier remains the
only benchmark. The loader, permissions, target, purging, class-weight options,
and validation-only threshold rules are preserved. This is a RETROSPECTIVE
EXPERIMENT, not validated live forecasting. Historical availability and recording
completeness remain unknown. The inspected 2022 evaluation remains exploratory.

`prediction/integrated_features.py` reads ONLY t-7..t-1. Origin t and future
t+1..t+7 never enter X. It creates 29 raw features:

| Domain | Seven-day historical features |
|---|---|
| Milk | Last/mean/std/recent-minus-earlier summaries plus seven individual per-cow lags |
| Climate | Mean daily thi_mean, maximum daily thi_max, sum of hours_thi_above |
| Biological | Separate mastitis, udder/teat, and other-health sums |
| Operational | Separate sessions, blood-alarm, and conductivity-alarm sums |
| Coverage | Observed-day count (0..7) for each of the nine auxiliary indicators |

No categories are combined and no animal/session rates are derived. Alarms do
not establish equipment failures or disease. Episode definitions/overlap remain
unverified. Hours use the supplied ETL-configured THI threshold; its numerical
value/version remain unknown, so this is not validated biological exposure.
Comparability across changes in settings requires producer verification. Cow
counts are retained in inputs but not used for new ratios or target recalculation.

Milk history remains mandatory, complete, and single-source. Each auxiliary
summary requires all seven values; otherwise it stays NaN and its observed-days
feature reports coverage. Partial sums/means are not substituted for complete
summaries. Recorded zero remains observed, distinct from missing.

`prediction/feature_preprocessing.py` fits median imputation on TRAINING only.
All-missing training value columns are dropped and listed, never given artificial
zero disease/alarm values. A binary missingness indicator is appended for EVERY
raw feature, including those first missing in validation/test. Later splits use
frozen training medians and columns. Coverage counts are retained. If a domain
has no training observations, its value effect cannot be learned: a four-domain
contract does not imply usable data in all domains. Recording patterns may drive
missingness features, rather than health or operational conditions.

Reports include raw names, per-split observed/missing counts and fractions,
observed-day/possible-day totals for auxiliary windows, dropped columns, transformed
names, and training-derived impurity feature importance. Coverage totals describe
overlapping sample windows, not unique days. Importance is noncausal and sensitive
to correlation/feature distributions; it does not explain an individual alert.
Metrics include precision, recall, F1, accuracy, average precision, confusion
matrices, reference-threshold metrics, and the Dummy comparison. No performance
is promised or inferred from synthetic tests.

Reproduce the prior four-feature model with `--feature-set production_only` and
its original class weight, threshold, snapshot, software versions, and split
settings. That mode bypasses added preprocessing and missingness indicators.
Integrated mode has a new experiment version and different predictions.

Synthetic suite (not run by the agent for this change):

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

Exact user-run local integrated command, from the repository root. Enter
preselected split dates and an experimental target percentage, not choices tuned
against the examined test. The database password prompt is hidden:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.prediction.train_local `
  --acknowledge-retrospective-limitations `
  --feature-set integrated `
  --milk-source (Read-Host 'Milk source: shipment or delpro') `
  --decline-threshold-pct (Read-Host 'Preselected experimental decline percentage') `
  --decision-threshold 0.5 `
  --class-weight balanced_subsample `
  --threshold-selection validation_f1 `
  --train-end (Read-Host 'Preselected training end YYYY-MM-DD') `
  --validation-end (Read-Host 'Preselected validation end YYYY-MM-DD') `
  --test-end (Read-Host 'Preselected exploratory test end YYYY-MM-DD')
```

Run each source separately. Port defaults to 5432. The coding agent must never
execute this command or inspect private outputs. The 0.5 reference and selected
threshold remain experimental decision rules, not clinically established cutoffs.

## User-run retrospective ML experiment (PP1)

This separate research workflow is authorized for the 14 approved daily aggregate
columns only. It does not create timestamp-aware inputs, change mapper safeguards,
or fabricate quality or publication metadata. Its outputs explicitly mark historical
availability, recording completeness, and publication version as unknown.
Observation-date lags cannot rule out delayed entries or retrospective corrections.
Results are NOT operational point-in-time validation, a clinical crisis model, or
a validated composite Farm Risk Score.

Modules:

- `data_access/local_training_loader.py`: user-run read-only loading of exactly
  the approved columns from `model_input.day_panel`, ordered by date up to the
  configured test end. Uses a repeatable-read, read-only transaction and the fixed
  `farmx_c4` role in `farmx_app`. No other table, .env, schema, or record export.
- `prediction/decline_target.py`: existing timestamp-aware generator remains
  protected. Shared `comparison_dates` and `decline_statistics` helpers now provide
  its exact windows and inclusive percentage arithmetic to both research paths.
- `prediction/retrospective.py`: explicitly named snapshot targets reuse those
  helpers, not forged ProductionDay metadata. Requires origin eligibility,
  all 15 calendar dates, a single source, nonmissing production, positive historical
  baseline, and ETL scoreability for all dates. Does NOT assert recording quality.
- `prediction/historical_features.py`: retained production-only builder for prior
  experiment reproduction. `prediction/integrated_features.py` is the current
  four-domain default. Neither uses origin/future values or quality/scoreability
  flags as predictors. No calendar-gap filling or milk-source mixing.
- `prediction/chronological_training.py`: RandomForestClassifier is the single
  main ML model, fit on training data only; a constant training-prior
  DummyClassifier is the sole evaluation benchmark. Fixed settings are 200 trees,
  max_depth=5, min_samples_leaf=5, max_features="sqrt", bootstrap=True,
  class_weight=None by default (optional balanced_subsample), random_state=0,
  and n_jobs=1. These are reproducible initial
  engineering settings, not tuned or validated optimal parameters. No feature
  scaling, additional ML models, resampling, calibration, model-setting search, or
  post-test refitting is performed.
- `prediction/train_local.py`: CLI orchestration, hidden password prompt, aggregate
  JSON reporting, sanitized errors. Importing modules does not connect or train.

Shipment and DelPro must be run separately with source-appropriate split dates.
All actual rows remain in local memory. Models remain in memory during evaluation
and are discarded afterward; no private dataset, row-level prediction, or model
artifact is written. NumPy is scikit-learn's required dependency; scikit-learn and
psycopg are already declared in backend requirements. No requirements files change.

### Target and split protocol

Target reference is t-7..t-1, origin t is separately eligible and excluded from
both averages, and outcome is t+1..t+7. Threshold is mandatory and configurable.
5/10/15 percent are experimental choices, not clinically validated crisis cutoffs.
Source labels are used directly; no switch date is inferred.

Choose `train_end < validation_end < test_end` BEFORE reviewing final test results:

- Training: origins no later than train_end, with outcome_end <= train_end.
- Validation: origins after train_end, with outcome_end <= validation_end.
- Test: origins after validation_end, with outcome_end <= test_end.

The final seven origin dates in each block are thus purged when outcomes cross
the end boundary. Uses calendar dates, not row-index gaps. Past feature dates
may legitimately lie in the preceding block. Snapshot delay/correction history
remains unknown even with this purge. Adjacent outcome windows overlap; daily
metrics are correlated and are not independent-event or lead-time evidence.

Both models are fit once on training only and never refit on validation/test.
The original mode remains `--feature-set production_only --class-weight none --threshold-selection fixed`
with the same decision threshold (original experiment: 0.5), source, dates,
target threshold, dataset snapshot, and software versions. It retains the same
Random Forest settings and predictions; the report now has additional metadata.
The updated experiment version distinguishes this implementation from the prior
version. Exact real-data reproduction also requires the same historical snapshot,
which this workflow neither saves nor reconstructs.

`--class-weight balanced_subsample` is an experimental alternative, selected by
the user before evaluation. Weights are computed by RandomForestClassifier from
each training bootstrap sample, never validation/test labels. It does not change
class counts or justify calibrated probabilities. No class-weight search is run.

Legacy `--threshold-selection validation_f1_legacy` chooses a separate threshold for each model
(Random Forest and Dummy benchmark) using ONLY that model's validation predictions
and labels. It searches a predeclared 0.00..1.00 grid in steps of 0.01, plus the
supplied reference threshold, maximizing validation F1. Equal F1 chooses the
highest threshold deterministically. Comparisons are inclusive (`p >= threshold`).
Endpoints can produce all/no alerts and are not clinically justified policies.
Empty/single-class validation cannot select F1 robustly and returns an explicit
reference-threshold fallback. The existing experiment guard still stops fitting
when validation or test has no usable samples.

Reports include aggregate validation precision, recall, F1, and predicted-alert
counts for every candidate threshold, the selected value/status per model, and
`reference_models` metrics at the original supplied decision threshold. `models`
contains metrics at the frozen selected thresholds. Both modes retain the Dummy
comparison. Thresholds are frozen before test predictions are obtained. No test
metrics choose class weights, forest settings, target cutoffs, or thresholds.
Validation F1 after selection is an optimistic development result, not independent
evaluation. A constant Dummy predictor can select an all-alert threshold; its
reported precision/recall makes that tradeoff visible.

The user-reported original experiment had train 2,105/17 positives, validation
73/12 positives, and test 85/18 positives, with reported test recall/F1 of zero
at 0.5. These are user-supplied aggregates, not independently verified results
or new-model performance. The previously inspected 2022 test period is explicitly
EXPLORATORY, not an untouched final test. All current reports label test results
exploratory; validation-only tuning does not undo prior test inspection. A future
final evaluation needs a new, prespecified holdout or prospective study. Overlap,
few positive training events, and changing class frequencies limit interpretation.

Imbalance is described through counts/fractions and precision/recall/AP, with
optional class weighting, never automatic oversampling. At least two training classes,
nonempty validation/test blocks, and a configurable minimum training count are
required. Default 30 is a computational guard, NOT sample-size justification.
Insufficient data yields aggregate diagnostics and no fitted models. Assess
positive-event support and recording coverage before interpreting any results.

Report contains split class counts, excluded-origin reason counts, configuration,
feature names, confusion matrices (rows actual 0/1, columns predicted 0/1),
precision, recall, F1, and `pr_auc_average_precision` (AP summary, NOT trapezoidal
PR area). Undefined metrics are null, including AP for a single-class evaluation
block. Includes predicted-alert counts and a training-prior baseline comparison.
No model performance is assumed. No calibrated-probability claim is made.
Metric definition: [scikit-learn average precision](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html).

ETL scoreability is used only to select retrospective labels, never as X or as
a claim that recording was complete. It may remove genuine severe declines;
reported performance applies only to retained windows. Health/alarm quality and
episode semantics remain unverified. Integrated mode uses separate raw historical
counts experimentally with explicit missingness, not as confirmed diagnoses,
causal drivers, or verified equipment/procedure failures.

### Manual local execution (user only)

Run in an interactive PowerShell terminal from the repository root. Do not paste
passwords into commands or chat. The program uses a hidden prompt and does not
read .env. Set only non-secret connection settings if your local defaults differ:

```powershell
$env:C4_DB_HOST = 'localhost'
$env:C4_DB_PORT = '5432'
```

Exact runnable command below prompts for your PRESELECTED split dates. This uses
an illustrative 10% target and 0.5 decision threshold; change these only as part
of the declared development protocol. It performs real local training when YOU
execute it. Run DelPro separately by changing `--milk-source` and split dates.

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.prediction.train_local `
  --acknowledge-retrospective-limitations `
  --milk-source shipment `
  --decline-threshold-pct 10 `
  --decision-threshold 0.5 `
  --train-end (Read-Host 'Preselected training end YYYY-MM-DD') `
  --validation-end (Read-Host 'Preselected validation end YYYY-MM-DD') `
  --test-end (Read-Host 'Preselected test end YYYY-MM-DD')
```

That command preserves the original unweighted, fixed-threshold mode. For the
approved experimental improvement, add these two options to the same command:

```text
--class-weight balanced_subsample --threshold-selection validation_f1
```

Keep `--decision-threshold 0.5` as the reported reference. Safe validation policy
selection does not fall back to it when no meaningful policy exists.
The actual selected threshold is reported after validation selection; do not
substitute a threshold chosen from the exploratory test. Do not interpret a lower
threshold or weighted fitting as a guaranteed improvement in detection.

Only aggregate JSON is printed. Exit code 2 means insufficient data,
invalid configuration, or a sanitized local failure; no traceback,
credentials, or rejected row is printed. Do not enable debug logging or share
private exception locals. Record the local ETL publication/version separately
when known; it is not queried under the 14-column permission. No real-data
training or resulting metrics have been produced by the coding agent.

Automated tests use fictional inputs only and inject a fake database connection:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

## Approved daily aggregate mapper (Phase 1)

The user confirmed read-only authorization for these 14 `model_input.day_panel`
columns. This is an explicit Member 4 input agreement, not an assumption that
other components or roles can access that schema. No permissions are changed.

| Approved column | Meaning and mapping |
|---|---|
| date | Observation date -> observation_date |
| target_source | shipment/delpro or NULL -> ProductionDay.milk_source |
| target_litres_per_cow | Daily litres / recorded milking cows -> production target, unchanged |
| is_scoreable | ETL production eligibility; excludes suspicious low/high/implausible records -> unchanged |
| milking | Milking-state animal count supplied as the per-cow denominator; retained, not used to recompute target |
| thi_mean | Daily mean THI -> climate input |
| thi_max | Daily maximum THI; retained in aggregate only |
| hours_thi_above | Hours above the ETL-configured threshold; retained, threshold value not inferred |
| mastitis_episodes | Separate daily count; episode semantics unverified |
| udder_teat_episodes | Separate daily count; overlap unverified |
| other_health_episodes | Separate daily count; category semantics unverified |
| n_sessions | Daily session count; detailed semantics unverified |
| n_blood_alarms | Separate blood-alarm count; event definition unverified |
| n_conductivity_alarms | Separate conductivity-alarm count; event definition unverified |

`schemas/historical_dataset.py` defines `ApprovedAggregate`: all 14 keys are
required even when their permitted value is None. Extra columns are rejected.
Counts are strict nonnegative integers, numeric measurements must be finite,
production/population values nonnegative, and hours must be within 0..24.
No gaps are filled and no source is inferred from the date. The mapper preserves
the supplied milking value; whether its population exactly matches the recorded
cows underlying the target still needs producer confirmation.

Separately supplied `AggregateMetadata` is bound to an observation date and
requires explicit synthetic/published provenance. Source version may remain
unknown, which prevents mapping. Each domain has its own observation_end,
available_at, and quality (ok, partial, unavailable, unknown). Missing timing or
unknown quality leaves that domain unmapped. No timestamp, timezone, publication
version, or quality is inferred. Inconsistent timestamp order or observation
date leaves the affected domain unmapped with a safe issue code.

Known partial/unavailable quality is preserved in mapped objects so existing
assessments can withhold use. Health and operational recording metadata default
to unknown, and alarm semantics/denominator compatibility remain unconfirmed.
Production is_scoreable does not establish any other domain's quality.

`data_access/aggregate_mapper.py` separates operations:

1. `validate_aggregate(mapping)` validates the approved input columns.
2. `validate_metadata(mapping)` validates explicit external metadata.
3. `map_aggregate(row, metadata)` creates separate production, climate,
   biological, and operational inputs when their metadata supports mapping.
4. `map_aggregates(rows, metadata)` joins by date, rejects duplicates/unmatched
   metadata, sorts chronologically, and preserves gaps and source switches.

Validation failures raise generic `MappingError` codes without rejected values.
Mapped results retain approved values and metadata for local processing, so they
must never be printed, uploaded, or included in error reports. The module itself
does no logging, database access, environment loading, file reading, assessment,
label generation, or training. Existing assessment implementations are unchanged.

Later authorized local execution (user-run, not agent-run):

1. Confirm the publication/source version and genuine per-domain availability
   and quality metadata with the producer. These are absent from the 14 columns.
   Unknown metadata must remain unknown; publication/extraction time cannot be
   substituted for historical availability. Metadata for a combined domain must
   cover every included indicator; do not supply a timestamp that precedes any
   included indicator's availability.
2. Use a separately reviewed local loader to obtain only the allowlisted daily
   aggregates under authorized read-only access. That loader is not implemented
   here. Keep real inputs and outputs in an approved private local location.
3. Validate columns and metadata, map them, and report aggregate counts of
   unmapped domains and reason codes only. Do not print rows or exception inputs.
4. Pass mapped production objects separately to `HistoricalLabelRequest` and
   `generate_decline_labels`. Retain the dates/reasons for unmapped records in
   local quality accounting; never reinterpret them as negative labels. Gaps and
   source switches remain visible to the existing label checks.
5. Call the climate, biological, and operational assessments independently with
   their domain-specific inputs and actual assessment cutoffs. Feature building,
   chronological splits, and model training remain separate future work. Never
   expose future outcome production to the feature path.

Unresolved metadata: exact publication version, domain quality criteria, genuine
historical availability, timezone/day boundaries, health recording completeness,
alarm count semantics, denominator compatibility, and the ETL THI-hours threshold.
If unavailable, the mapper does not silently supply them.

Synthetic tests only:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

## Historical seven-day production-decline labels (Phase 1)

`schemas/production_inputs.py` extends `DailyRiskInput` with finite, nonnegative
daily `target_litres_per_cow`, explicit `is_scoreable`, and `milk_source`
(shipment/delpro or missing). The inherited source field distinguishes synthetic
from published inputs; it is not the milk measurement source. No database
mapping, connection, data loading, or model training is implemented.

`prediction/decline_target.py` exposes `generate_decline_labels(request)`.
`HistoricalLabelRequest` supplies daily records, timezone-aware prediction
cutoffs, a retrospective `labels_as_of` cutoff, and a required positive decline
threshold in percent (at most 100). No scientific crisis threshold is supplied.

For origin date t (the date of the prediction cutoff), the historical window is
t-7 through t-1 inclusive and the outcome is t+1 through t+7 inclusive. Origin
day t is excluded from both averages but must separately be present, scoreable,
quality-ok, have nonmissing valid production and milk source, and be available
by the prediction cutoff. Its source/provenance must match both windows.
Zero origin production is permitted when otherwise eligible. The cutoff
must represent a completed origin day in the agreed farm timezone; supplied
observation-end/availability timestamps determine what was actually known.
Dates must be aligned to that timezone by the producer. This matches the
user-confirmed SQL window convention; the SQL itself was not accessed.

Each window contains exactly seven consecutive calendar days. Each mean is the
arithmetic average of seven daily litres-per-recorded-milking-cow values, not
total litres divided by summed cow counts. This implements the approved daily
per-cow target and gives each day equal weight. It does not remove herd-composition
effects or guarantee that recorded cows represent all milking cows.

`change_pct = 100 * (future_mean - historical_mean) / historical_mean`.
The label is true when change_pct is less than or equal to the negative configured
threshold (inclusive "at least" comparison). Decimal arithmetic based on input
decimal representations avoids binary-float threshold-boundary errors.

All 14 comparison days plus the separately eligible origin day (15 dates total)
must have known identical milk sources, provenance/source versions,
ok daily quality, scoreable production, and nonmissing values. A source switch
even at the boundary between the two windows makes the label unavailable.
Missing days are not filled with later observations. Nonpositive historical
means are unavailable. Recorded zero future production is valid when declared
scoreable and reliable. Negative/nonfinite or incorrectly typed values are
rejected by input validation; missing/unusable windows instead return label=None
and an explicit reason, never a negative label. Duplicate dates/origins are
rejected, and results are ordered chronologically.

Historical and origin records must have been available by the prediction cutoff. All
outcome records must be available by labels_as_of. Future actuals are used only
for retrospective supervised targets; this function is not an inference or
feature-building API. It returns no raw future-day records. Missing future
actuals at live inference time produce unavailable labels. Availability
timestamps must reflect genuine recording history, not retrospective dates.

Training remains deferred. Later chronological splits must purge training
examples whose outcome intervals or label availability cross the fitting cutoff.
Adjacent seven-day labels overlap and are correlated; they are not independent
events. Development and evaluation must account for repeated warnings and
temporal dependence. No model performance follows from these synthetic tests.

User-supplied aggregate findings (not independently reproduced): 3,300 scoreable
days and 2,774 complete comparison windows; shipment has 2,277 windows with
211/47/25 declines at illustrative 5/10/15 percent thresholds, and DelPro has
497 windows with 96/34/9 respectively. These thresholds are descriptive checks,
not validated crisis cutoffs. ETL source selection is reported as shipment before
2022-08-01 and DelPro afterward. The generator checks explicit source labels
rather than guessing sources from dates or overriding producer metadata.

Important limitations: is_scoreable can exclude genuine severe declines, creating
selection bias. Report excluded-window counts/reasons and assess source-specific
coverage before training. The reference-anchor convention is fixed above; quality policy,
cutoff timezone, data availability history, and substantive threshold choice need
agreement before real-data use. These supplied counts are not test expectations.

Run all isolated synthetic Member 4 tests:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

## PP1 operational input assessment (Phase 1)

`schemas/operational_inputs.py` wraps `DailyRiskInput` with independent session,
blood-alarm, and conductivity-alarm recording quality (complete, incomplete,
unavailable, unknown). Quality defaults to unknown. Alarm definitions default
to unknown and denominator compatibility defaults to false. These are proposed
producer declarations, not verified database mappings.

`operational_risk/operational_consistency.py` exposes
`assess_operational_inputs(inputs, assessment_cutoff)`. Missing counts remain
missing; present counts, including zeros and inconsistencies, are preserved.
Non-ok daily quality or non-complete field recording withholds raw-input use.
Per-indicator status is available, missing, or unavailable, with separate quality
and explanations. Overall available/partial/unavailable describes raw-input
usability only, not severity, consistency, or normalization readiness.

Ratios are deferred unless the producer explicitly confirms alarm count units
(events or flagged sessions), compatible denominator population/day/coverage,
complete recording for numerator and denominator, and ok daily quality.
Missing/zero sessions withhold ratios. Positive alarms with zero sessions raise
a review warning; confirmed compatible flagged-session counts above sessions
raise a warning and withhold that ratio. Event counts may exceed sessions.
Ratios are labelled events per session or fraction of flagged sessions. They
use the existing `rate_per_session()` helper and never combine alarm categories.

These signals do not establish equipment failure, worker error, or disease.
No thresholds, weights, risk levels, operational score, or trained prediction
are implemented. Worker reliability and human error modules remain deferred.

Unresolved definitions before further development:

- Are alarm counts events, flagged sessions, or sub-session detections?
- What qualifies as a session, including retries and incomplete milkings?
- Do each alarm numerator and session denominator cover identical records?
- How are recording completeness, sensor availability, and device changes known?
- Can blood and conductivity alarms overlap in a session? How should related
  signals be allocated between biological and operational scoring?
- Are entry/correction times distinguishable from session times? Cutoff checks
  rely on genuine producer-supplied availability, not retrospective dates.
- What expected activity, verified disruption outcomes, historical references,
  and evidence would justify later operational assessment criteria?

Run the operational suite with all preceding synthetic tests:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests -q
```

## PP1 biological input assessment (Phase 1)

`schemas/biological_inputs.py` wraps the existing `DailyRiskInput` with explicit
per-category recording quality: complete, incomplete, unavailable, or unknown
(the default). Completeness is supplied by the producer, never inferred from
zero counts or the general daily quality flag. This is a proposed interface,
not a verified mapping of database fields.

`biological_risk/biological_assessment.py` exposes
`assess_biological_inputs(inputs, assessment_cutoff)`. It validates availability
using `DailyInputBatch`, then assesses mastitis, udder/teat, and other health
counts separately. Counts retain strict nonnegative integer validation.

Each result retains the recorded count, recording quality, and explanation.
A missing count has status `missing`, including when quality is also unknown;
both limitations are explained. A present count has status `unavailable` when
daily quality is not ok or category recording is not complete. Otherwise it
is `available`. Present counts, including zero, remain visible even when use
is withheld. Zero is not evidence of absence of disease.

Overall status describes input availability only: available when all three
indicators are available, partial when some are available, and unavailable
when none are available. It is not health severity. No category totals,
incidence rates, thresholds, Low/Medium/High bands, biological scores,
diagnoses, or trained predictions are generated.

Remaining producer/research questions before further development:

- Do counts represent new episodes, active episodes, diagnoses, treatments,
  or records entered that day? How are recurring episodes distinguished?
- Are mastitis and udder/teat categories nested or overlapping, and does
  other health exclude them? A unique total cannot yet be established.
- Which animal population contributes to each count? Which verified population
  or animal-time denominator matches it?
- What establishes complete recording, and are category-specific completeness
  declarations available? Unknown quality must not silently become complete.
- Are onset, entry, and correction dates distinguishable? Availability must
  reflect when information was genuinely known, not a retrospective onset date.
- Which window, coverage requirements, historical reference, and evidence-backed
  action criteria should any later assessment use?

Run all isolated synthetic Member 4 tests:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests/test_daily_inputs.py components/member4_crisis_forecasting/tests/test_climate_risk.py components/member4_crisis_forecasting/tests/test_biological_risk.py -q
```

Architecture for climate, operational, biological and text-derived risk inputs, farm scores, NDRI and early warnings. The service currently provides only deterministic scaffold risk outputs.

## PP1 daily input boundary

PP1 concerns Farm X only. `schemas/daily_inputs.py` defines a proposed daily
aggregate contract, not verified database field mappings. It performs no I/O,
loads no environment files, and imports no backend services.

Each record carries its observation date, timezone-aware observation-end and
availability timestamps, source version, source label, and quality status.
The observation date is interpreted in the timezone offset on observation_end;
the producer must agree the farm timezone and day-end convention before use.
Availability must be no earlier than observation end and no later than the
batch assessment cutoff. A batch rejects duplicate observation dates.

Daily counts are nonnegative integers. Missing values remain None, distinct
from recorded zero. THI is dimensionless and must be finite when supplied;
its formula and aggregation need producer confirmation. Episode category
meanings and overlap remain unverified. Session alarm rates are events per
session, not probabilities; absent or zero denominators produce None.
Quality is preserved as metadata: this contract does not decide scoreability.

No weights, risk bands, production-decline targets, database access, or trained
prediction are implemented by this boundary. Real use requires agreement on
ETL publication/access, timestamp availability, units, category meanings,
completeness rules, and provenance. Feed and national risk remain outside PP1.

Run the isolated synthetic tests explicitly (root discovery does not yet include
Member 4):

```powershell
python -m pytest components/member4_crisis_forecasting/tests/test_daily_inputs.py -q
```

## PP1 climate prototype

`climate/environmental_risk.py` exposes `assess_climate(day,
assessment_cutoff, config, baseline=None)`. This is deterministic assessment,
not trained prediction, a diagnosis, or an estimate of milk loss. It reuses
`DailyRiskInput` and `DailyInputBatch` without database or environment access.

`ClimateConfig.heat_stress_threshold` has no numerical default. When supplied,
the assessment returns whether daily mean THI strictly exceeds it and the
nonnegative excess in THI units. Equality is not exceedance. Daily means cannot
establish hours above a threshold or within-day heat intensity. Zero is valid.

`climate/climate_features.py` exposes `fit_thi_baseline(batch, config)`.
`BaselineConfig` requires explicit training start/end dates, percentile, and
minimum usable days (at least two; this is a computational floor, not a claim
of adequate research sample size). The percentile uses linear interpolation
at index `(n - 1) * percentile / 100`. Only quality-ok, nonmissing daily means
within the inclusive training window contribute. Other days are counted as
excluded. Insufficient history returns no threshold and is never padded with
future observations. This reference is not seasonally adjusted.

Fit once on the approved training window and reuse that baseline for validation
and test days. The training end must precede each assessed day, and the baseline
fit cutoff must not follow the assessment cutoff. Source and source version
must match; mixed baseline provenance is rejected. Producers must establish
the meaning of source versions and genuine availability timestamps. Date
checks cannot detect falsely labelled training periods or retrospective records.

The result separates absolute heat-threshold exceedance from unusually high
THI relative to the configured historical percentile. It includes the input,
cutoff, thresholds, baseline sample counts/window/provenance, and explanations.
Missing THI or non-ok input quality withholds both comparisons. Missing threshold
configuration or insufficient history makes the relevant comparison unavailable
while preserving the other. Availability status is not a Low/Medium/High risk
band. No composite score or scientifically validated threshold is supplied.

Before research use, confirm the THI formula and daily aggregation, biological
threshold evidence, baseline training window/percentile/sample adequacy,
seasonality policy, and input quality policy. Test thresholds are fictional.
`thi_forecast.py` remains deferred; no future weather forecast is generated.

Run the isolated synthetic suite:

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests/test_daily_inputs.py components/member4_crisis_forecasting/tests/test_climate_risk.py -q
```

