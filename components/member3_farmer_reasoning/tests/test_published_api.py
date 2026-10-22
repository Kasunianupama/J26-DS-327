"""Synthetic API checks for explicitly selected C3 published aggregates."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes import agent


def client():
    app = FastAPI()
    app.include_router(agent.router, prefix='/api/v1')
    return TestClient(app)


def test_published_brief_is_separate_from_demo_chat(monkeypatch):
    expected = dict(source='published_core_aggregates', demo=False,
                    core_version='synthetic-v1', warnings=['Synthetic gap warning'])
    monkeypatch.setattr(agent, 'load_published_brief', lambda: expected)
    monkeypatch.setattr(agent, 'answer_query', lambda *args: (_ for _ in ()).throw(AssertionError('No demo fallback')))
    response = client().get('/api/v1/agent/briefing')
    assert response.status_code == 200
    assert response.json() == expected


def test_database_failure_returns_safe_error_without_demo(monkeypatch):
    def fail():
        raise RuntimeError('synthetic-private-diagnostic')
    monkeypatch.setattr(agent, 'load_published_brief', fail)
    monkeypatch.setattr(agent, 'answer_query', lambda *args: (_ for _ in ()).throw(AssertionError('No demo fallback')))
    response = client().get('/api/v1/agent/briefing')
    assert response.status_code == 503
    assert 'synthetic-private-diagnostic' not in response.text
    assert 'Published data unavailable' in response.text


def test_demo_query_does_not_open_published_reader(monkeypatch):
    monkeypatch.setattr(agent, 'load_published_brief', lambda: (_ for _ in ()).throw(AssertionError('No published read')))
    monkeypatch.setattr(agent, 'answer_query', lambda *args: dict(demo=True, answer='Synthetic only'))
    response = client().post('/api/v1/agent/query', json=dict(query='Summary', farm_id='FARM_01'))
    assert response.status_code == 200
    assert response.json()['demo'] is True
