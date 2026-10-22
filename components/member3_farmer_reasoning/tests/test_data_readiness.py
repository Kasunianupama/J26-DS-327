"""Synthetic C3 readiness tests; no environment files or database connections."""
from unittest.mock import MagicMock

import pytest
from components.member3_farmer_reasoning.services import data_readiness as reader


def settings():
    return dict(APP_DB_NAME='farmx_app', APP_DB_C3_USER='farmx_c3',
                APP_DB_C3_PASSWORD='synthetic-only', APP_DB_PORT='5432')


@pytest.mark.parametrize('key,value', [('APP_DB_NAME', 'restricted_db'),
                                     ('APP_DB_C3_USER', 'postgres'),
                                     ('APP_DB_C3_PASSWORD', '')])
def test_rejects_wrong_database_role_or_missing_password(key, value):
    env = settings()
    env[key] = value
    with pytest.raises(ValueError):
        reader.connection_settings(env)


def test_read_only_settings_ignore_api_credentials():
    env = settings()
    env['APP_DB_API_USER'] = 'postgres'
    result = reader.connection_settings(env)
    assert result['user'] == 'farmx_c3'
    assert result['port'] == 5432
    assert 'default_transaction_read_only=on' in result['options']


def test_reads_only_aggregate_and_version_in_same_transaction(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(reader.psycopg, 'connect', connect)
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [dict(herd_days=12, missing_weather_days=2,
                                      can_create_outputs=True), dict(version='synthetic-v1')]
    result = reader.read_summary(reader.connection_settings(settings()))
    assert result['herd_days'] == 12
    assert result['missing_weather_days'] == 2
    assert result['core_version'] == 'synthetic-v1'
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert statements[0].endswith('READ ONLY')
    assert 'LEFT JOIN core.weather_day' in statements[1]
    assert len(statements) == 3
