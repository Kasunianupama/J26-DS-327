from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_health(): assert client.get('/api/v1/health').json()['status'] == 'healthy'
def test_agent_query():
    response = client.post('/api/v1/agent/query', json={'query':'Why?', 'farm_id':'FARM_01','role':'farm_manager','language':'en'})
    assert response.status_code == 200 and response.json()['demo'] is True

def test_agent_query_supports_roman_sinhala():
    response = client.post('/api/v1/agent/query', json={'query':'ada 312 cow ge health eka kohomada?', 'farm_id':'FARM_01','role':'farm_manager','language':'si-Latn'})
    assert response.status_code == 200 and response.json()['language'] == 'si-Latn'

def test_agent_query_changes_guidance_by_role():
    worker = client.post('/api/v1/agent/query', json={'query':'How is cow 312 health?', 'farm_id':'FARM_01','role':'farm_worker','language':'en'}).json()
    veterinarian = client.post('/api/v1/agent/query', json={'query':'How is cow 312 health?', 'farm_id':'FARM_01','role':'veterinarian','language':'en'}).json()
    assert worker['answer'] != veterinarian['answer']
    assert worker['recommendations'][0]['owner'] == 'farm_worker'
    assert veterinarian['recommendations'][0]['owner'] == 'veterinarian'
def test_intervention_demo(): assert client.post('/api/v1/interventions/simulate', json={'farm_id':'FARM_01','intervention':'feed','change_percent':5}).status_code == 200
def test_behavior_demo(): assert client.get('/api/v1/behavior/FARM_01').status_code == 200
def test_farm_risk_demo(): assert client.get('/api/v1/risks/farms/FARM_01').json()['level'] == 'medium'
def test_national_risk_demo(): assert client.get('/api/v1/risks/national').json()['farms_considered'] == 3

def test_predictive_snapshot_is_backend_backed_and_horizon_aware():
    response = client.get('/api/v1/predictive/farms/FARM_01/snapshot?horizon=30d')
    assert response.status_code == 200
    data = response.json()
    assert data['source'] == 'deterministic_synthetic_backend'
    assert data['overview']['days'] == 30
    assert data['overview']['average_daily_milk'] > 0
    assert len(data['findings']) == 6

def test_predictive_workspace_contracts_and_animal_lookup():
    assert client.get('/api/v1/predictive/farms/FARM_01/milk?horizon=90d').status_code == 200
    assert client.get('/api/v1/predictive/farms/FARM_01/reproduction').json()['pregnant'] > 0
    assert client.get('/api/v1/predictive/farms/FARM_01/finance').json()['expected_revenue_lkr_thousands'] > 0
    assert client.get('/api/v1/predictive/farms/FARM_01/evidence').json()['coverage'][0]['coverage'] == 97
    assert client.get('/api/v1/predictive/farms/FARM_01/animals/LK-2100').status_code == 200

def test_predictive_unknown_farm_returns_404():
    assert client.get('/api/v1/predictive/farms/UNKNOWN/snapshot').status_code == 404
