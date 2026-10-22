-- USER REVIEW/APPROVAL REQUIRED. Never executed by the agent.
-- Run as the authorized c4_output owner only AFTER approval.
-- LIKE copies definitions/constraints/indexes, NOT V1 rows. No V1 alteration.
CREATE TABLE c4_output.farm_risk_assessment_v2
    (LIKE c4_output.farm_risk_assessment_v1 INCLUDING ALL);
ALTER TABLE c4_output.farm_risk_assessment_v2
    ADD CONSTRAINT c4_v2_unique_farm_date_version UNIQUE (farm_id, assessment_date, scoring_version),
    ADD CONSTRAINT c4_v2_retrospective_scope CHECK
      (contract_version = '1.1.0' AND assessment_date BETWEEN DATE '2026-01-01' AND DATE '2026-08-20');
-- No GRANT, source rows, schemas, functions, permissions, V1 or RF changes here.
