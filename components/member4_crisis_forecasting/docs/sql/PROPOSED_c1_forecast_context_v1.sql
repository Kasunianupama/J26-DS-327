-- REVIEW ONLY. No execution, grants, migration or publication approved.
-- Separate Member 4 research context; never alters existing assessments or C1.
CREATE TABLE c4_output.c1_forecast_context_v1 (
    context_id uuid PRIMARY KEY,
    farm_id text NOT NULL CHECK (farm_id = 'FARM_X'),
    assessment_date date NOT NULL,
    assessed_at timestamptz NOT NULL,
    contract_version text NOT NULL CHECK (contract_version = '1.0.0'),
    research_only boolean NOT NULL CHECK (research_only),
    live_warning_allowed boolean NOT NULL CHECK (NOT live_warning_allowed),
    warning_status text NOT NULL CHECK (warning_status = 'withheld_no_approved_warning_policy'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
);
