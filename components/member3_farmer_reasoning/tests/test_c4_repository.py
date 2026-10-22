"""Fictional C4 fixtures verify research flags, provenance and local-only routing."""
from datetime import date
from unittest.mock import MagicMock, Mock
import pytest

from components.member3_farmer_reasoning.schemas.tool_contracts import RiskArguments
from components.member3_farmer_reasoning.orchestration.tool_router import Adapter, ToolRouter
from components.member3_farmer_reasoning.services import c4_repository as repository


def result(**updates):
    evidence = dict(kind='c4_risk', demo=False, contract_version='1.1.0',
        score_basis='descriptive_retrospective_unverified',
        scoring_version='provisional-equal-weight-v1',
        model_status='random_forest_experimental_not_live_validated',
        research_only=True, live_warning_allowed=False,
        reference_date='2020-01-10', assessment_date='2020-01-08',
        generated_at='2020-02-01T00:00:00Z', assessment_count=1,
        climate_score=20, biological_score=30, operational_score=None, combined_score=25)
    evidence.update(updates)
    return evidence


def router(raw=None):
    return ToolRouter(dict(c4_risk=Adapter(lambda args: result() if raw is None else raw, False)))


def call(**updates):
    args = dict(reference_date='2020-01-10')
    args.update(updates)
    return dict(tool='c4_risk', arguments=args)


def test_research_evidence_retains_limits_and_unknown_source_version():
    outcome = router().execute(call())
    assert outcome.status == 'success'
    evidence = outcome.evidence
    assert evidence.demo is False and evidence.research_only is True
    assert evidence.live_warning_allowed is False
    assert evidence.source_core_version is None
    assert evidence.generated_at.date() > evidence.assessment_date
    assert any('not a current alert' in warning for warning in evidence.warnings)
    assert any('unverified' in warning for warning in evidence.warnings)


def test_live_warning_request_never_invokes_adapter_or_requests_date():
    invoke = Mock()
    outcome = ToolRouter(dict(c4_risk=Adapter(invoke, False))).execute(
        dict(tool='c4_risk', arguments=dict(purpose='live_warning')))
    assert outcome.status == 'unavailable'
    invoke.assert_not_called()


@pytest.mark.parametrize('updates', [dict(assessment_date='2020-01-11'),
    dict(reference_date='2020-01-09'), dict(assessment_count=2),
    dict(contract_version='unknown'), dict(combined_score=float('nan')),
    dict(source_core_version='invented-local-version')])
def test_mismatched_or_unsupported_evidence_is_rejected(updates):
    assert router(result(**updates)).execute(call()).status == 'invalid_result'


def test_missing_scores_remain_null():
    outcome = router(result(combined_score=None)).execute(call())
    assert outcome.evidence.combined_score is None
    assert any('missing' in warning for warning in outcome.evidence.warnings)


def test_no_reference_date_requests_clarification_without_connection():
    invoke = Mock()
    outcome = ToolRouter(dict(c4_risk=Adapter(invoke, False))).execute(
        dict(tool='c4_risk', arguments={}))
    assert outcome.status == 'needs_input'
    assert outcome.missing_fields == ['reference_date']
    invoke.assert_not_called()


def database_row(**updates):
    row = result()
    for field in ('kind', 'demo', 'reference_date'):
        row.pop(field)
    row.update(assessment_date=date(2020, 1, 8), farm_count=1, missing_farm_count=0)
    row.update(updates)
    return row


def fake_cursor(monkeypatch, rows):
    connect = MagicMock()
    monkeypatch.setattr(repository.psycopg, 'connect', connect)
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    return connect, cursor


def test_reader_uses_parameterized_aggregate_query_and_read_only_transaction(monkeypatch):
    connect, cursor = fake_cursor(monkeypatch, [database_row()])
    evidence = repository.read_risk({}, RiskArguments(reference_date='2020-01-10'))
    assert evidence['combined_score'] == 25
    assert 'farm_count' not in evidence and 'farm_id' not in evidence and 'payload' not in evidence
    calls = cursor.execute.call_args_list
    assert calls[0].args[0].endswith('READ ONLY')
    assert calls[1].args[1] == dict(reference_date=date(2020, 1, 10))
    assert 'assessment_date <= %(reference_date)s' in calls[1].args[0]


@pytest.mark.parametrize('rows', [[], [database_row(), database_row()],
    [database_row(farm_count=2)], [database_row(missing_farm_count=1)],
    [database_row(assessment_count=2)]])
def test_reader_does_not_silently_merge_or_select_ambiguous_records(monkeypatch, rows):
    fake_cursor(monkeypatch, rows)
    with pytest.raises(repository.RiskUnavailable):
        repository.read_risk({}, RiskArguments(reference_date='2020-01-10'))


def test_reader_rejects_live_purpose_before_connecting(monkeypatch):
    connect = Mock(side_effect=AssertionError('No connection'))
    monkeypatch.setattr(repository.psycopg, 'connect', connect)
    with pytest.raises(repository.RiskUnavailable):
        repository.read_risk({}, RiskArguments(reference_date='2020-01-10', purpose='live_warning'))
    connect.assert_not_called()
