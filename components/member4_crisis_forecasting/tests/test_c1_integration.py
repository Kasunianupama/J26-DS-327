"""Fictional forecasts only; all database connections injected/mocked."""
from datetime import date, datetime, timedelta, timezone
import json
import pytest

from components.member4_crisis_forecasting.early_warning.c1_integration import assess_c1_context, aggregate_summary
from components.member4_crisis_forecasting.data_access.c1_forecast_loader import load_c1_forecasts

ORIGIN = date(2025, 1, 1)
CUTOFF = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)


def forecasts():
    return [dict(origin_date=ORIGIN, target_period=ORIGIN + timedelta(days=i),
                 grain="daily", horizon=i + 1, series="herd_milk", forecast=100.,
                 lower=80., upper=120., quality_flag="ok", model_version="synthetic-model",
                 core_version="synthetic-core", created_at=CUTOFF) for i in range(1, 8)]


def assess(rows, **kwargs):
    return assess_c1_context(rows, assessment_date=ORIGIN, assessed_at=CUTOFF,
                            origin_date=ORIGIN, model_version="synthetic-model",
                            core_version=kwargs.get("core_version", "synthetic-core"))


def test_complete_context_still_never_authorizes_warning():
    context = assess(forecasts())
    assert context.status == "research_context_available"
    assert context.mean_daily_herd_milk_forecast == 100
    assert context.live_warning_allowed is False
    assert context.historical_availability == "unknown"
    assert type(context).model_validate_json(context.model_dump_json()) == context


@pytest.mark.parametrize("field,value,reason", [
    ("horizon", 1, "date_horizon_mismatch"),
    ("quality_flag", "ok;low_recording", "quality_not_ok_or_unknown"),
    ("core_version", "different", "mixed_core_provenance"),
    ("created_at", CUTOFF + timedelta(seconds=1), "publication_after_cutoff"),
    ("forecast", -1., "invalid_forecast"),
    ("upper", 90., "invalid_interval"),
    ("grain", "weekly", "unexpected_run_or_series"),
])
def test_invalid_evidence_withholds_context(field, value, reason):
    rows = forecasts()
    rows[0][field] = value
    result = assess(rows)
    assert result.status == "unavailable"
    assert result.mean_daily_herd_milk_forecast is None
    assert reason in result.reasons


def test_missing_duplicate_and_unknown_provenance():
    assert assess(forecasts()[:-1]).status == "unavailable"
    assert "duplicate_target_date" in assess(forecasts() + [forecasts()[0]]).reasons
    assert "core_provenance_unknown" in assess(forecasts(), core_version=None).reasons
    assert assess([]).eligible_forecast_days == 0


def test_summary_does_not_expose_forecast_rows():
    result = aggregate_summary([assess(forecasts())])
    assert result["validated_warnings"] == 0
    text = json.dumps(result)
    assert "2025-01-01" not in text
    assert "synthetic-model" not in text
    assert "mean_daily_herd_milk_forecast" not in text


def test_loader_uses_only_fixed_read_only_queries():
    calls = []
    class Fake:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return self
        def execute(self, sql, params=None): calls.append((sql, params))
        def __iter__(self): return iter(forecasts())
    def connect(**kwargs):
        assert kwargs["user"] == "farmx_c4"
        assert kwargs["options"] == "-c default_transaction_read_only=on"
        return Fake()
    rows = load_c1_forecasts(host="fictional", port=5432, password="synthetic",
                            origin_date=ORIGIN, model_version="synthetic-model", connect=connect)
    assert len(rows) == 7
    assert len(calls) == 2
    assert "READ ONLY" in calls[0][0]
    assert "FROM c1_output.outlook" in calls[1][0]
    assert calls[1][1] == (ORIGIN, "synthetic-model")
