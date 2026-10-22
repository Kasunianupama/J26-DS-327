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
    # bound parameters, never formatted into the SQL
    assert seen[-1][1] == {"o": date(2024, 1, 1), "skip": ["pfoi-1.7.0-dev", "pfoi-1.8.0-dev"]}
    assert client.get("/api/v1/predictive/pfoi/run").json()["origin_date"] == "2026-08-01"
    assert client.get("/api/v1/predictive/pfoi/run?origin=2025-03-01").status_code == 404
    assert client.get("/api/v1/predictive/pfoi/run?origin=not-a-date").status_code == 422


def _versioned_fake(builds):
    """In-memory run_document: (origin, version, created) -> document; mimics the queries."""
    class Fake(OutlookService):
        def _query(self, sql, **params):
            skip = set(params.get("skip") or [])
            rows = [(o, v, c, d) for (o, v, c), d in builds.items()]
            if "DISTINCT ON (model_version)" in sql:
                rows = sorted((r for r in rows if r[0] == params["o"]), key=lambda r: (r[1], -r[2]))
                seen, out = set(), []
                for o, v, c, d in rows:
                    if v not in seen:
                        seen.add(v)
                        out.append({"model_version": v, "created_at": c})
                return out
            if "WHERE model_version = :v" in sql:
                rows = [r for r in rows if r[1] == params["v"] and params["o"] in (None, r[0])]
            elif "WHERE origin_date = :o" in sql:
                rows = [r for r in rows if r[0] == params["o"] and r[1] not in skip]
            else:
                rows = [r for r in rows if r[1] not in skip]
            rows.sort(key=lambda r: (r[0], r[2]), reverse=True)
            return [{"document": rows[0][3]}] if rows else []
    return Fake(enabled=True)


def test_comparison_versions_never_replace_the_page_run(monkeypatch):
    o = date(2026, 8, 1)
    builds = {(o, "pfoi-1.2.0-dev", 1): {"source": "model", "model_version": "pfoi-1.2.0-dev"},
              (o, "pfoi-1.8.0-dev", 2): {"source": "model", "model_version": "pfoi-1.8.0-dev"}}
    monkeypatch.setattr(predictive, "outlook_service", _versioned_fake(builds))
    page = client.get("/api/v1/predictive/pfoi/run?origin=2026-08-01").json()
    assert page["model_version"] == "pfoi-1.2.0-dev"  # newer 1.8.0-dev build is comparison-only
    assert client.get("/api/v1/predictive/pfoi/run").json()["model_version"] == "pfoi-1.2.0-dev"
    exact = client.get("/api/v1/predictive/pfoi/run?origin=2026-08-01&model_version=pfoi-1.8.0-dev").json()
    assert exact["model_version"] == "pfoi-1.8.0-dev"
    assert client.get("/api/v1/predictive/pfoi/run?origin=2026-08-01&model_version=nope").status_code == 404
    versions = client.get("/api/v1/predictive/pfoi/run/versions?origin=2026-08-01").json()["versions"]
    assert {(v["model_version"], v["comparison_only"]) for v in versions} == {
        ("pfoi-1.2.0-dev", False), ("pfoi-1.8.0-dev", True)}


def test_versions_endpoint_without_database_is_empty():
    body = client.get("/api/v1/predictive/pfoi/run/versions?origin=2026-08-01").json()
    assert body["versions"] == []
