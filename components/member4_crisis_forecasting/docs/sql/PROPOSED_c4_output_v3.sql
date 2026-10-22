-- MANUAL REVIEW AND APPROVAL ONLY. No source-table alterations or copied rows.
CREATE TABLE c4_output.farm_risk_assessment_v3 (
    output_id uuid PRIMARY KEY,
    farm_id text NOT NULL CHECK (farm_id='FARM_X'),
    assessment_date date NOT NULL CHECK (assessment_date BETWEEN DATE '2026-01-01' AND DATE '2026-08-20'),
    contract_version text NOT NULL CHECK (contract_version='3.0.0'),
    generated_at timestamptz NOT NULL,
    scoring_version text NOT NULL CHECK (scoring_version='c4-v3-climate-operational-1'),
    source_output_id uuid NOT NULL,
    source_payload_sha256 text NOT NULL CHECK (source_payload_sha256 ~ '^[0-9a-f]{64}$'),
    research_only boolean NOT NULL CHECK (research_only),
    live_warning_allowed boolean NOT NULL CHECK (NOT live_warning_allowed),
    model_status text NOT NULL CHECK (model_status='provisional_two_domain_not_live_validated'),
    climate_score double precision CHECK (climate_score BETWEEN 0 AND 100),
    operational_score double precision CHECK (operational_score BETWEEN 0 AND 100),
    combined_score double precision CHECK (combined_score BETWEEN 0 AND 100),
    risk_category text NOT NULL CHECK (risk_category IN ('low_provisional','medium_provisional','high_provisional','unavailable')),
    data_completeness text NOT NULL CHECK (data_completeness IN ('complete','partial','unavailable')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
    UNIQUE (farm_id, assessment_date, scoring_version),
    CHECK ((climate_score IS NULL OR operational_score IS NULL) AND combined_score IS NULL AND risk_category='unavailable' AND data_completeness<>'complete'
        OR climate_score IS NOT NULL AND operational_score IS NOT NULL AND combined_score IS NOT NULL AND data_completeness='complete' AND risk_category<>'unavailable'
           AND abs(combined_score-(climate_score/2+operational_score/2)) <= 1e-8)
);
-- No grants/migrations execute automatically. Reader permission is owner-reviewed.
