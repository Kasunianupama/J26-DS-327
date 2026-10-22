"""Read C4 historical research aggregates locally; never inspect payloads or IDs."""
import argparse
import json
import os
from datetime import date
from pathlib import Path

import psycopg

from components.member3_farmer_reasoning.orchestration.tool_router import Adapter, ToolRouter
from .data_readiness import connection_settings

# Aggregate exactly the latest eligible assessment date. Multiple groups/records
# are rejected, not averaged into a new score or selected by an arbitrary tie-break.
RISK_SQL = """
WITH chosen AS (
    SELECT max(assessment_date) AS assessment_date
    FROM c4_output.farm_risk_assessment_v1
    WHERE assessment_date <= %(reference_date)s
)
SELECT r.contract_version, r.score_basis, r.scoring_version, r.model_status,
       r.research_only, r.live_warning_allowed,
       max(r.assessment_date) AS assessment_date,
       max(r.assessment_cutoff) AS assessment_cutoff,
       max(r.generated_at) AS generated_at,
       count(*)::integer AS assessment_count,
       count(DISTINCT r.farm_id)::integer AS farm_count,
       count(*) FILTER (WHERE r.farm_id IS NULL)::integer AS missing_farm_count,
       max(r.climate_score) AS climate_score,
       max(r.biological_score) AS biological_score,
       max(r.operational_score) AS operational_score,
       max(r.combined_score) AS combined_score
FROM c4_output.farm_risk_assessment_v1 r
JOIN chosen c ON r.assessment_date = c.assessment_date
GROUP BY r.contract_version, r.score_basis, r.scoring_version, r.model_status,
         r.research_only, r.live_warning_allowed
"""

CHECK_SQL = """
SELECT count(*) AS assessments,
       min(assessment_date) AS first_assessment,
       max(assessment_date) AS last_assessment,
       count(*) FILTER (WHERE research_only) AS research_only_count,
       count(*) FILTER (WHERE live_warning_allowed) AS live_warning_allowed_count,
       count(*) FILTER (WHERE combined_score IS NULL) AS missing_combined_scores
FROM c4_output.farm_risk_assessment_v1
"""


class RiskUnavailable(RuntimeError):
    """An unambiguous assessment cannot be selected from the published export."""


def read_risk(settings, arguments):
    """Return C3's field-mapped evidence only, without assuming core compatibility."""
    if arguments.purpose != 'historical_explanation':
        raise RiskUnavailable('Historical explanation only.')
    with psycopg.connect(**settings) as conn:
        with conn.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute(RISK_SQL, dict(reference_date=arguments.reference_date))
            groups = cursor.fetchall()
    if len(groups) != 1:
        raise RiskUnavailable('No unique historical assessment group.')
    row = dict(groups[0])
    if row.pop('farm_count') != 1 or row.pop('missing_farm_count') != 0 or row['assessment_count'] != 1:
        raise RiskUnavailable('Multiple or unidentified assessment records.')
    return dict(kind='c4_risk', demo=False, reference_date=arguments.reference_date, **row)


def private_settings():
    """Only a human-run CLI or explicitly invoked local adapter loads settings."""
    from dotenv import dotenv_values
    values = dict(dotenv_values(Path(__file__).resolve().parents[3] / '.env', interpolate=False))
    values.update(os.environ)
    return connection_settings(values)


def local_c4_router():
    """Register only the C4 local reader; no LLM or network provider is invoked."""
    return ToolRouter(dict(c4_risk=Adapter(lambda args: read_risk(private_settings(), args), synthetic=False)))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local C4 historical research check; no cloud processing.')
    parser.add_argument('--reference-date', type=date.fromisoformat,
                        help='Latest eligible assessment date; all output is aggregate evidence.')
    args = parser.parse_args(argv)
    if args.reference_date is not None:
        result = local_c4_router().execute(dict(tool='c4_risk', arguments=dict(
            reference_date=args.reference_date.isoformat(), purpose='historical_explanation')))
        print(result.model_dump_json())
        return 0 if result.status == 'success' else 1
    try:
        settings = private_settings()
        with psycopg.connect(**settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute(CHECK_SQL)
                summary = dict(cursor.fetchone())
    except Exception:
        print('C4 check unavailable. Check local C3 settings, grants and the restored output table privately.')
        return 1
    print(json.dumps(dict(source='c4_output', **summary), default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
