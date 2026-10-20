"""PFOI outlook routes: demo fallback without a database, model rows when published.
No database connection is opened (PFOI_OUTLOOK_DB is off; the service is replaced)."""
from datetime import date

from fastapi.testclient import TestClient

from backend.app.api.routes import predictive
from backend.app.main import app
from components.predictive_farm_intelligence.services.outlook_service import OutlookService

client = TestClient(app)


def test_outlook_falls_back_to_labelled_demo():
    r = client.get("/api/v1/predictive/pfoi/outlook?grain=monthly&series=herd_milk")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "demo" and len(body["outlook"]) == 12


def test_run_document_404_without_published_run():
    assert client.get("/api/v1/predictive/pfoi/run").status_code == 404


def test_model_rows_are_served_when_published(monkeypatch):
    class Fake(OutlookService):
        def _query(self, sql, **params):
            if "run_document" in sql:
                return [{"document": '{"source": "model", "origin_date": "2026-08-01"}'}]
            if "SELECT origin_date, model_version" in sql:
                return [{"origin_date": date(2026, 8, 1), "model_version": "pfoi-1.0.0"}]
            if "c1_output.outlook" in sql:
                return [{"origin_date": date(2026, 8, 1), "target_period": date(2026, 8, 1),
                         "grain": "monthly", "horizon": 1, "series": "herd_milk", "forecast": 1.0,
                         "lower": 0.9, "upper": 1.1, "quality_flag": "ok",
                         "model_version": "pfoi-1.0.0", "core_version": "v1"}]
            return []

    monkeypatch.setattr(predictive, "outlook_service", Fake(enabled=True))
    assert client.get("/api/v1/predictive/pfoi/run").json()["source"] == "model"
    body = client.get("/api/v1/predictive/pfoi/outlook").json()
    assert body["source"] == "model" and body["outlook"][0]["core_version"] == "v1"


def test_runs_list_404_without_published_run():
    assert client.get("/api/v1/predictive/pfoi/runs").status_code == 404


def test_run_by_forecast_date(monkeypatch):
    docs = {date(2024, 1, 1): '{"source": "model", "origin_date": "2024-01-01", "realised_through": "2026-08-20"}',
            date(2026, 8, 1): '{"source": "model", "origin_date": "2026-08-01", "realised_through": "2026-08-20"}'}
    seen = []

    class Fake(OutlookService):
        def _query(self, sql, **params):
            seen.append((sql, params))
            if "DISTINCT ON (origin_date)" in sql:
                return [{"origin_date": o, "model_version": "pfoi-1.0.0", "realised_through": "2026-08-20"}
                        for o in sorted(docs)]
            if "run_document WHERE origin_date" in sql:
                o = params["o"]
                return [{"document": docs[o]}] if o in docs else []
            if "run_document" in sql:
                return [{"document": docs[max(docs)]}]
            return []

    monkeypatch.setattr(predictive, "outlook_service", Fake(enabled=True))
    runs = client.get("/api/v1/predictive/pfoi/runs").json()
    assert [r["origin_date"] for r in runs["runs"]] == ["2024-01-01", "2026-08-01"]
    assert client.get("/api/v1/predictive/pfoi/run?origin=2024-01-01").json()["origin_date"] == "2024-01-01"
    assert seen[-1][1] == {"o": date(2024, 1, 1)}  # bound parameter, never formatted into the SQL
    assert client.get("/api/v1/predictive/pfoi/run").json()["origin_date"] == "2026-08-01"
    assert client.get("/api/v1/predictive/pfoi/run?origin=2025-03-01").status_code == 404
    assert client.get("/api/v1/predictive/pfoi/run?origin=not-a-date").status_code == 422
