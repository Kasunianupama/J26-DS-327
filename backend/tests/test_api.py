from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_health(): assert client.get('/api/v1/health').json()['status'] == 'healthy'
def test_agent_query():
    response = client.post('/api/v1/agent/query', json={'query':'Why?', 'farm_id':'FARM_01','role':'farm_manager','language':'en'})
    assert response.status_code == 200 and response.json()['demo'] is True
def test_intervention_demo(): assert client.post('/api/v1/interventions/simulate', json={'farm_id':'FARM_01','intervention':'feed','change_percent':5}).status_code == 200
def test_behavior_demo(): assert client.get('/api/v1/behavior/FARM_01').status_code == 200
def test_farm_risk_demo(): assert client.get('/api/v1/risks/farms/FARM_01').json()['level'] == 'medium'
def test_national_risk_demo(): assert client.get('/api/v1/risks/national').json()['farms_considered'] == 3

