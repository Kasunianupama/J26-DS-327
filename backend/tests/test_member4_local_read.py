"""Synthetic request scopes only. No settings, credentials or database access."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from backend.app.api.routes.member4_local_read import local_read_allowed
from backend.app.api.routes.member4_research import require_member4_read


def request(*, host='localhost:8000', peer='127.0.0.1', origin='http://localhost:5173',
            method='GET', path='/api/v1/risks/research/farms/FARM_X/assessments', extra=()):
    headers = [(b'host', host.encode()), *extra]
    if origin is not None: headers.append((b'origin', origin.encode()))
    return Request(dict(type='http', method=method, scheme='http', path=path,
                        query_string=b'', headers=headers, client=(peer, 1234), server=('127.0.0.1', 8000)))


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('C4_LOCAL_READ_ONLY', 'on')
    monkeypatch.setenv('APP_ENV', 'development')


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv('C4_LOCAL_READ_ONLY', raising=False)
    monkeypatch.setenv('C4_LOCAL_AUTH_ENABLED', 'off')
    assert local_read_allowed(request()) is False
    with pytest.raises(HTTPException) as error: require_member4_read(request())
    assert error.value.status_code == 403


@pytest.mark.parametrize('host,peer,origin', [
    ('localhost:8000', '127.0.0.1', 'http://localhost:5173'),
    ('127.0.0.1:8000', '127.0.0.1', 'http://127.0.0.1:5173'),
    ('[::1]:8000', '::1', None),
])
def test_explicit_local_reads_without_session(enabled, host, peer, origin):
    req = request(host=host, peer=peer, origin=origin)
    assert local_read_allowed(req) is True
    assert require_member4_read(req) is None


@pytest.mark.parametrize('changes', [
    {'peer': '192.168.1.2'}, {'peer': '8.8.8.8'}, {'host': 'evil.example:8000'},
    {'host': 'localhost.evil.example:8000'}, {'host': 'localhost:9000'},
    {'origin': 'https://evil.example'}, {'origin': 'null'}, {'origin': 'http://localhost:9999'},
    {'method': 'POST'}, {'path': '/api/v1/risks/research/farms/OTHER/assessments'},
    {'path': '/api/v1/risks/research/session'},
    {'extra': [(b'x-forwarded-for', b'127.0.0.1')]},
    {'extra': [(b'forwarded', b'for=127.0.0.1')]},
    {'extra': [(b'sec-fetch-site', b'cross-site')]},
])
def test_nonlocal_or_unsafe_requests_rejected(enabled, changes):
    with pytest.raises(HTTPException) as error: local_read_allowed(request(**changes))
    assert error.value.status_code == 403


def test_production_rejected_even_when_flag_enabled(enabled, monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    with pytest.raises(HTTPException): local_read_allowed(request())


def test_second_read_endpoint_enabled(enabled):
    assert local_read_allowed(request(path='/api/v1/risks/research/farms/FARM_X/milk-decline-predictions'))


def test_launcher_requires_explicit_flag_without_starting_server(monkeypatch):
    from components.member4_crisis_forecasting.services.start_local_api import main
    with pytest.raises(SystemExit): main([])
