-- PROPOSAL ONLY. Do not execute without separate explicit approval.
-- New prediction object only: no references/writes to farm_risk_assessment_v1.
-- Existing c4_output schema assumed. No schema, grants, permissions or ETL changes.
CREATE TABLE c4_output.milk_decline_prediction_v1 (
    prediction_id uuid PRIMARY KEY,
    contract_version text NOT NULL CHECK (contract_version = '1.0.0'),
    farm_id text NOT NULL CHECK (farm_id = 'FARM_X'),
    assessment_date date NOT NULL,
    generated_at timestamptz NOT NULL,
    artifact_version text NOT NULL CHECK (artifact_version = '1.0.0'),
    artifact_sha256 text NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    model_status text NOT NULL CHECK (model_status = 'random_forest_experimental_not_live_validated'),
    research_only boolean NOT NULL CHECK (research_only),
    live_warning_allowed boolean NOT NULL CHECK (NOT live_warning_allowed),
    predicted_decline_probability double precision NOT NULL CHECK (predicted_decline_probability BETWEEN 0 AND 1),
    saved_threshold double precision CHECK (saved_threshold BETWEEN 0 AND 1),
    predicted_decline boolean,
    classification_status text NOT NULL CHECK (classification_status IN
        ('no_saved_threshold', 'experimental_classification', 'legacy_not_warning_policy')),
    actual_outcome boolean,
    outcome_reason text NOT NULL,
    experiment_partition text NOT NULL CHECK (experiment_partition IN
        ('train_in_sample', 'validation_model_selection', 'test_exploratory', 'post_experiment_research')),
    milk_source text NOT NULL CHECK (milk_source IN ('shipment', 'delpro')),
    historical_availability text NOT NULL CHECK (historical_availability = 'unknown'),
    recording_completeness text NOT NULL CHECK (recording_completeness = 'unknown'),
    probability_interpretation text NOT NULL CHECK (probability_interpretation = 'uncalibrated_experimental_model_score'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    CHECK ((saved_threshold IS NULL AND predicted_decline IS NULL AND classification_status = 'no_saved_threshold')
           OR (saved_threshold IS NOT NULL AND predicted_decline IS NOT NULL
               AND predicted_decline = (predicted_decline_probability >= saved_threshold)
               AND classification_status <> 'no_saved_threshold'))
);
-- Append-only adapter uses parameterized INSERTs only. No DDL is run by Python.
