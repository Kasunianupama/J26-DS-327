"""Synthetic tests for C3 source separation, historical dates and gap handling."""
from datetime import date
from unittest.mock import MagicMock
import pytest
from components.member3_farmer_reasoning.services.aggregate_brief import build_brief
from components.member3_farmer_reasoning.services import aggregate_repository as repository


def context():
    return dict(core_version='synthetic-v1', balance_failing_months=2,
                herd=dict(observed_date=date(2020, 1, 14), total_animals=20),
                current_period=dict(start=date(2020, 1, 8), end=date(2020, 1, 14),
                    observed_days=7, gap_days=0, delpro_days=7, delpro_litres=770,
                    shipment_days=7, shipment_litres=350),
                previous_period=dict(start=date(2020, 1, 1), end=date(2020, 1, 7),
                    observed_days=7, gap_days=0, delpro_days=7, delpro_litres=700,
                    shipment_days=7, shipment_litres=350),
                weather=dict(observed_days=7, complete_days=7, mean_daily_thi=75))


def test_separates_sources_and_labels_historical_reconstruction():
    brief = build_brief(context(), today=date(2020, 2, 1))
    assert brief['milk']['delpro']['change_pct'] == 10
    assert brief['milk']['shipments']['change_pct'] == 0
    assert brief['demo'] is False
    assert any('Historical' in w for w in brief['warnings'])
    assert any('2 months fail' in w for w in brief['warnings'])
    assert 'Not connected' in brief['teammate_models']


@pytest.mark.parametrize('field,value', [('gap_days', 1), ('observed_days', 6),
                                        ('delpro_days', 6), ('delpro_litres', None)])
def test_incomplete_current_period_never_produces_delpro_change(field, value):
    data = context()
    data['current_period'][field] = value
    assert build_brief(data)['milk']['delpro']['change_pct'] is None


@pytest.mark.parametrize('baseline', [0, None])
def test_missing_or_zero_baseline_does_not_fabricate_growth(baseline):
    data = context()
    data['previous_period']['delpro_litres'] = baseline
    assert build_brief(data)['milk']['delpro']['change_pct'] is None


def test_missing_shipment_stays_null_without_using_delpro():
    data = context()
    data['current_period'].update(shipment_litres=None, shipment_days=0)
    data['weather']['complete_days'] = 6
    brief = build_brief(data)
    assert brief['milk']['shipments']['current_litres'] is None
    assert brief['milk']['delpro']['change_pct'] == 10
    assert any('Weather coverage' in w for w in brief['warnings'])


def test_repository_uses_date_anchored_windows_and_read_only_snapshot(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(repository.psycopg, 'connect', connect)
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    data = context()
    cursor.fetchone.side_effect = [data['herd'], data['current_period'],
        data['previous_period'], data['weather'], dict(failing_months=2), dict(version='synthetic-v1')]
    cursor.fetchall.return_value = [dict(day=date(2020,1,14),source_rows=1,data_gap=False,delpro_litres=110,shipments_litres=50)]
    result = repository.read_context({})
    assert result['core_version'] == 'synthetic-v1'
    assert result['milk_daily'][0]['delpro_litres'] == 110
    assert 'GROUP BY date' in repository.DAILY_MILK_SQL
    assert cursor.execute.call_args.args[1] == dict(start=date(2020,1,1),end=date(2020,1,14))
    calls = cursor.execute.call_args_list
    assert calls[0].args[0].endswith('READ ONLY')
    assert calls[2].args[1] == dict(start=date(2020, 1, 8), end=date(2020, 1, 14))
    assert calls[3].args[1] == dict(start=date(2020, 1, 1), end=date(2020, 1, 7))
