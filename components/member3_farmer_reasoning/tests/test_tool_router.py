"""Synthetic-only tool contract and orchestration tests; no database or network."""
from datetime import date
from unittest.mock import Mock
import pytest

from components.member3_farmer_reasoning.orchestration.synthetic_tools import synthetic_router
from components.member3_farmer_reasoning.orchestration.tool_router import Adapter, ToolRouter


def forecast_call(**updates):
    arguments = dict(reference_date='2020-01-01', target_period='2020-01-02',
                     grain='daily', series='herd_milk')
    arguments.update(updates)
    return dict(tool='c1_forecast', arguments=arguments)


def forecast_result(**updates):
    result = dict(kind='c1_forecast', demo=True, core_version='synthetic-v1',
                  model_version='pfoi-1.2.0-dev', origin_date='2020-01-01',
                  target_period='2020-01-02', grain='daily', series='herd_milk',
                  forecast=100, lower=80, upper=120, quality_flags=['synthetic'])
    result.update(updates)
    return result


def test_unknown_tool_cannot_execute_a_path():
    adapter = Mock()
    router = ToolRouter(dict(core_summary=Adapter(adapter, True)))
    assert router.execute(dict(tool='python.exe', arguments={})).status == 'invalid_request'
    adapter.assert_not_called()


def test_missing_scenario_fields_request_clarification_without_execution():
    adapter = Mock()
    router = ToolRouter(dict(c2_simulation=Adapter(adapter, True)))
    result = router.execute(dict(tool='c2_simulation', arguments=dict(intervention='synthetic')))
    assert result.status == 'needs_input'
    assert result.missing_fields == ['change_percent', 'horizon_days']
    adapter.assert_not_called()


@pytest.mark.parametrize('arguments', [dict(topic='herd', sql='select anything'),
                                      dict(topic='herd', model_path='anything'),
                                      dict(topic='unknown')])
def test_extra_or_unsupported_arguments_never_reach_adapter(arguments):
    adapter = Mock()
    result = ToolRouter(dict(core_summary=Adapter(adapter, True))).execute(
        dict(tool='core_summary', arguments=arguments))
    assert result.status == 'invalid_request'
    adapter.assert_not_called()


def test_live_c2_unavailable_without_registry_entry():
    result = ToolRouter().execute(dict(tool='c2_simulation', arguments=dict(
        intervention='synthetic', change_percent=10, horizon_days=7)))
    assert result.status == 'unavailable'
    assert result.evidence is None


def test_synthetic_registry_is_explicitly_labelled():
    result = synthetic_router().execute(dict(tool='core_summary', arguments=dict(topic='herd')))
    assert result.status == 'success'
    assert result.evidence.demo is True
    assert 'Synthetic' in result.message


@pytest.mark.parametrize('updates', [dict(model_version='other-model'),
    dict(origin_date='2020-01-03'), dict(target_period='2020-01-04'),
    dict(grain='monthly'), dict(series='milking'), dict(demo=False),
    dict(forecast=float('nan')), dict(lower=150, upper=50)])
def test_mismatched_or_invalid_forecast_is_rejected(updates):
    router = ToolRouter(dict(c1_forecast=Adapter(lambda args: forecast_result(**updates), True)))
    assert router.execute(forecast_call()).status == 'invalid_result'


def test_missing_bounds_remain_null_and_flags_are_preserved():
    router = ToolRouter(dict(c1_forecast=Adapter(lambda args: forecast_result(lower=None), True)))
    result = router.execute(forecast_call())
    assert result.status == 'success'
    assert result.evidence.lower is None
    assert result.evidence.quality_flags == ['synthetic']
    assert any('incomplete' in w for w in result.evidence.warnings)


def test_point_outside_bounds_is_flagged_not_repaired():
    router = ToolRouter(dict(c1_forecast=Adapter(lambda args: forecast_result(forecast=125), True)))
    result = router.execute(forecast_call())
    assert result.evidence.forecast == 125
    assert any('outside' in w for w in result.evidence.warnings)


def test_future_origin_request_rejected_before_invocation():
    adapter = Mock()
    router = ToolRouter(dict(c1_forecast=Adapter(adapter, True)))
    assert router.execute(forecast_call(origin_date='2020-01-03')).status == 'invalid_request'
    adapter.assert_not_called()


def test_adapter_exception_is_sanitized():
    adapter = Mock(side_effect=RuntimeError('synthetic-private-message'))
    result = ToolRouter(dict(core_summary=Adapter(adapter, True))).execute(
        dict(tool='core_summary', arguments=dict(topic='herd')))
    assert result.status == 'error'
    assert 'synthetic-private-message' not in result.model_dump_json()


def test_scenario_mismatch_cannot_be_presented_as_requested_result():
    raw = synthetic_router().execute(dict(tool='c2_simulation', arguments=dict(
        intervention='synthetic', change_percent=10, horizon_days=7))).evidence.model_dump()
    raw['horizon_days'] = 14
    router = ToolRouter(dict(c2_simulation=Adapter(lambda args: raw, True)))
    assert router.execute(dict(tool='c2_simulation', arguments=dict(
        intervention='synthetic', change_percent=10, horizon_days=7))).status == 'invalid_result'
