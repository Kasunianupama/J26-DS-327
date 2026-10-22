"""Fictional passwords, in-memory requests; no settings, .env or database access."""
import hashlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes import member4_session as session, member4_research as research


@pytest.fixture
def client(monkeypatch):
    salt = b'fictional-salt123'
    digest = hashlib.pbkdf2_hmac('sha256', b'fictional-password-123', salt, 600000).hex()
    for k, v in dict(C4_LOCAL_AUTH_ENABLED='on', C4_LOCAL_USERNAME='fictional',
                     C4_LOCAL_PASSWORD_HASH=f'{salt.hex()}:{digest}', C4_LOCAL_SIGNING_KEY='a'*64).items():
        monkeypatch.setenv(k, v)
    session._attempts.clear()
    class Fake:
        def read(self, kind, farm_id):
            return dict(source='published', contract_version='1.0.0', items=[])
    monkeypatch.setattr(research, 'published_output_service', Fake())
    app = FastAPI()
    @app.middleware('http')
    async def fictional_loopback(request, call_next):
        request.scope['client'] = ('127.0.0.1', 12345)
        return await call_next(request)
    app.include_router(session.router, prefix='/api/v1/risks')
    app.include_router(research.router, prefix='/api/v1/risks')
    return TestClient(app, base_url='http://localhost:8000')


def login(client, **changes):
    body = dict(username='fictional', password='fictional-password-123'); body.update(changes)
    return client.post('/api/v1/risks/research/session', json=body, headers={'Origin': 'http://localhost:5173'})


def test_login_cookie_unlocks_only_research_reads(client):
    path = '/api/v1/risks/research/farms/FARM_X/assessments'
    assert client.get(path).status_code == 403
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    assert client.get(path).status_code == 200
    assert client.get(path.replace('FARM_X', 'OTHER')).status_code == 404


def test_bad_credentials_origin_and_rate_limit(client):
    assert login(client, password='wrong').status_code == 401
    assert client.post('/api/v1/risks/research/session', json=dict(username='fictional', password='fictional-password-123')).status_code == 403
    for _ in range(4): login(client, password='wrong')
    assert login(client).status_code == 429


def test_disabled_and_tampered_session(client, monkeypatch):
    assert login(client).status_code == 200
    client.cookies.set(session.COOKIE, '1.bad.bad', domain='localhost.local', path=session.PATH)
    assert client.get('/api/v1/risks/research/farms/FARM_X/assessments').status_code == 403
    monkeypatch.setenv('C4_LOCAL_AUTH_ENABLED', 'off')
    assert login(client).status_code == 403


def test_role_headers_and_expired_cookie_rejected(client, monkeypatch):
    path = '/api/v1/risks/research/farms/FARM_X/assessments'
    assert client.get(path, headers={'X-Role': 'board_management', 'Authorization': 'Bearer fictional'}).status_code == 403
    assert login(client).status_code == 200
    current = session.time.time()
    monkeypatch.setattr(session.time, 'time', lambda: current + session.TTL + 1)
    assert client.get(path).status_code == 403
