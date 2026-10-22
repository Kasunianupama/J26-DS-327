-- PROPOSAL ONLY: NOT APPROVED, NOT EXECUTED. Owner review required before use.
-- Existing c4_output schema is assumed. No schemas, roles, grants, or ETL changes.
-- Append-only research outputs. Do not turn research_only into a UI-only label.
CREATE TABLE c4_output.farm_risk_assessment_v1 (
    output_id uuid PRIMARY KEY,
    contract_version text NOT NULL CHECK (contract_version IN ('1.0.0', '1.1.0')),
    score_basis text NOT NULL CHECK (score_basis IN ('quality_gated', 'descriptive_retrospective_unverified')),
    farm_id text NOT NULL CHECK (farm_id = 'FARM_X'),
    assessment_date date NOT NULL,
    assessment_cutoff timestamptz,
    generated_at timestamptz NOT NULL CHECK (generated_at >= assessment_cutoff),
    scoring_version text NOT NULL CHECK (length(btrim(scoring_version)) > 0),
    research_only boolean NOT NULL CHECK (research_only),
    live_warning_allowed boolean NOT NULL CHECK (NOT live_warning_allowed),
    model_status text NOT NULL CHECK (model_status = 'random_forest_experimental_not_live_validated'),
    climate_score double precision CHECK (climate_score BETWEEN 0 AND 100),
    biological_score double precision CHECK (biological_score BETWEEN 0 AND 100),
    operational_score double precision CHECK (operational_score BETWEEN 0 AND 100),
    combined_score double precision CHECK (combined_score BETWEEN 0 AND 100),
    risk_category text NOT NULL CHECK (risk_category IN
        ('low_provisional', 'medium_provisional', 'high_provisional', 'unavailable')),
    data_completeness text NOT NULL CHECK (data_completeness IN ('complete', 'partial', 'unavailable')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    CHECK ((contract_version = '1.0.0' AND score_basis = 'quality_gated' AND assessment_cutoff IS NOT NULL)
           OR (contract_version = '1.1.0' AND score_basis = 'descriptive_retrospective_unverified' AND assessment_cutoff IS NULL)),
    CHECK (
        (combined_score IS NULL AND risk_category = 'unavailable' AND data_completeness <> 'complete'
         AND (climate_score IS NULL OR biological_score IS NULL OR operational_score IS NULL))
        OR
        (combined_score IS NOT NULL AND risk_category <> 'unavailable' AND data_completeness = 'complete'
         AND climate_score IS NOT NULL AND biological_score IS NOT NULL AND operational_score IS NOT NULL)
    )
);
-- Consumers use contract_version and research_only and must refuse live-warning
-- use. Full payload semantic consistency is checked by the Python contract.
-- Adapter approval and reader-role grants are separate decisions; none provided.
