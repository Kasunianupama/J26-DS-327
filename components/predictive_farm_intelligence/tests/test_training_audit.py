"""Training audit tests use fictional aggregate history and mocked loaders only."""
import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import training_audit as audit
from components.predictive_farm_intelligence.pfoi import forecast_experiments as exp


def synthetic():
    dates = pd.date_range("2015-01-01", "2023-12-31")
    target = pd.DataFrame(dict(date=dates, target_litres=100., is_scoreable=True,
                               target_source="shipment", identified_share=.9, data_gap=0))
    panel = pd.DataFrame(dict(date=dates, milking=10.))
    return target, panel


def test_audit_funnel_matches_runner_training_counts(monkeypatch):
    target, panel = synthetic()
    target.loc[target.date >= "2022-12-01", "target_source"] = "delpro"
    monkeypatch.setattr(audit, "HORIZONS", {"monthly": (1,)})
    start, end = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-01-01")
    tables = audit.audit(target, panel, start, end)
    f = tables["eligibility_funnel"].set_index("stage")
    assert f.loc["within_window", "min_examples"] > 24
    assert f.loc["same_source", "min_examples"] == 1
    assert f.loc["same_source", "max_examples"] == 12
    assert tables["minimum_training"].below_24.sum() == 12
    monkeypatch.setattr(exp, "fit_predict", lambda *a: pytest.fail("Audit/insufficient-history runner must not train"))
    monkeypatch.setattr(exp, "benchmark_forecasts", lambda *a: [])
    _, coverage = exp.rolling(exp.daily_frame(target, panel), exp._target_frame(target),
        "monthly", 1, start, end, ["ridge"], exp.ExperimentConfig())
    counts = [c["n_train"] for c in coverage]
    assert min(counts) == f.loc["usable_inputs", "min_examples"]
    assert np.mean(counts) == f.loc["usable_inputs", "mean_examples"]


def test_unusable_last_day_source_and_variants_are_visible(monkeypatch):
    target, panel = synthetic()
    target.loc[target.date.eq(pd.Timestamp("2022-12-31")), ["is_scoreable", "target_source"]] = [False, " DELPRO "]
    monkeypatch.setattr(audit, "HORIZONS", {"monthly": (1,)})
    tables = audit.audit(target, panel, pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"))
    q = tables["query_coverage"].iloc[0]
    assert q.source == "delpro_case_or_space_variant"
    assert q.last_scoreable_source == "shipment"
    f = tables["eligibility_funnel"].set_index("stage")
    assert f.loc["same_source", "max_examples"] == 0
    assert f.loc["within_window", "min_examples"] > 0


def test_funnel_is_monotone_and_residual_counts_only_saved_keys(monkeypatch):
    target, panel = synthetic()
    target.loc[(target.date >= "2021-02-01") & (target.date < "2021-04-01"), "is_scoreable"] = False
    monkeypatch.setattr(audit, "HORIZONS", {"monthly": (3,)})
    structural, _, _ = exp.examples(exp.daily_frame(target, panel), exp._target_frame(target),
                                    "monthly", 3, exp.ExperimentConfig())
    structural = structural.iloc[::2].assign(forecast=3000.)
    tables = audit.audit(target, panel, pd.Timestamp("2023-01-01"), pd.Timestamp("2024-01-01"), structural=structural)
    f = tables["eligibility_funnel"].set_index("stage").loc[list(audit.STAGES)]
    assert (f.mean_examples.diff().dropna() <= 0).all()
    assert f.loc["usable_inputs", "mean_examples"] > f.loc["structural_available", "mean_examples"]
    assert tables["query_coverage"].query_status.eq("target_incomplete").any()


def test_future_values_do_not_change_earlier_training_funnel(monkeypatch):
    target, panel = synthetic()
    monkeypatch.setattr(audit, "HORIZONS", {"monthly": (1,)})
    start, end = pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01")
    first = audit.audit(target, panel, start, end)["eligibility_funnel"]
    target.loc[target.date >= start, "target_litres"] = 1e9
    target.loc[target.date >= start, "target_source"] = "delpro"
    second = audit.audit(target, panel, start, end)["eligibility_funnel"]
    pd.testing.assert_frame_equal(first, second)


def test_opaque_source_labels_hide_unexpected_text():
    mapping = audit.source_labels(["shipment", "delpro", " DELPRO ", "fictional-private-label", None])
    assert mapping["fictional-private-label"].startswith("other_source_")
    assert "fictional-private-label" not in mapping.values()


def test_main_prints_aggregates_without_fitting_or_writing(monkeypatch, capsys, tmp_path):
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    target, panel = synthetic()
    class Source:
        def target_daily(self, start, end): return target
        def panel_daily(self, start, end): return panel
    monkeypatch.setattr(SqlHerdSource, "from_env", classmethod(lambda cls: Source()))
    monkeypatch.setattr(audit, "HORIZONS", {"monthly": (1,)})
    monkeypatch.setattr(exp, "fit_predict", lambda *a: pytest.fail("Must not fit"))
    monkeypatch.chdir(tmp_path)
    assert audit.main(["--start", "2023-01-01", "--end", "2024-01-01"]) == 0
    output = capsys.readouterr().out
    assert "eligibility_funnel" in output and "minimum_training" in output
    assert "2023-01-01" not in output
    assert not list(tmp_path.iterdir())


def test_posthoc_refused_before_loader(monkeypatch):
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    monkeypatch.setattr(SqlHerdSource, "from_env", classmethod(lambda cls: pytest.fail("No database access")))
    with pytest.raises(SystemExit):
        audit.main(["--end", "2025-01-01"])
