"""Fictional aggregate time series only; database loader is mocked."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import forecast_experiments as exp


def data():
    days = pd.date_range("2015-01-01", "2020-12-31")
    target = pd.DataFrame(dict(date=days, target_litres=100+5*np.sin(np.arange(len(days))/30),
        is_scoreable=True, target_source="delpro", identified_share=.9, data_gap=0))
    panel = pd.DataFrame(dict(date=days, milking=10.))
    return target, panel


def test_features_ignore_future_and_expose_missingness():
    target, panel = data()
    f = exp.daily_frame(target, panel)
    origin = pd.Timestamp("2019-01-01")
    expected = exp.features(f, origin, origin, exp.ExperimentConfig())
    changed = f.copy()
    changed.loc[changed.index >= origin, "milk"] = 1e9
    actual = exp.features(changed, origin, origin, exp.ExperimentConfig())
    np.testing.assert_array_equal(expected[0], actual[0])
    changed.loc[origin-pd.Timedelta(days=1), "milk"] = np.nan
    seq, _ = exp.features(changed, origin, origin, exp.ExperimentConfig())
    assert seq[-1, 0] == 0 and seq[-1, 2] == 1


def test_examples_reject_partial_and_mixed_source_targets():
    target, panel = data()
    t = exp._target_frame(target)
    rows, _, _ = exp.examples(exp.daily_frame(target, panel), t, "monthly", 12, exp.ExperimentConfig())
    assert rows.period_end.max() <= pd.Timestamp("2021-01-01")
    assert rows.origin.max() == pd.Timestamp("2020-01-01")
    target.loc[target.date.eq(pd.Timestamp("2019-01-02")), "target_source"] = "shipment"
    rows, _, _ = exp.examples(exp.daily_frame(target, panel), exp._target_frame(target), "monthly", 1, exp.ExperimentConfig())
    assert not rows.origin.eq(pd.Timestamp("2019-01-01")).any()


def test_rolling_training_excludes_unfinished_labels(monkeypatch):
    target, panel = data()
    origin = pd.Timestamp("2019-01-01")
    observed = []
    def fit(name, seq, static, y, query_seq, query_static, cfg):
        observed.append(y.copy())
        return float(y.mean())
    monkeypatch.setattr(exp, "fit_predict", fit)
    monkeypatch.setattr(exp, "benchmark_forecasts", lambda *a: [])
    cfg = exp.ExperimentConfig(min_train=8)
    f = exp.daily_frame(target, panel)
    a, _ = exp.rolling(f, exp._target_frame(target), "monthly", 3, origin,
                      pd.Timestamp("2019-04-01"), ["ridge"], cfg)
    first_training = observed[0].copy()
    changed = target.copy()
    changed.loc[changed.date >= origin, "target_litres"] = 1e8
    observed.clear()
    b, _ = exp.rolling(exp.daily_frame(changed, panel), exp._target_frame(changed), "monthly", 3,
                      origin, pd.Timestamp("2019-04-01"), ["ridge"], cfg)
    np.testing.assert_array_equal(first_training, observed[0])
    assert a.iloc[0].forecast == b.iloc[0].forecast


@pytest.mark.parametrize("model", exp.MODELS)
def test_estimators_fit_finite_synthetic_prediction(model):
    rng = np.random.default_rng(3)
    seq = rng.normal(size=(28, 84, 5)).astype(np.float32)
    static = rng.normal(size=(28, 6)).astype(np.float32)
    y = 100+seq[:, -1, 0]*3
    value = exp.fit_predict(model, seq, static, y, seq[0], static[0], exp.ExperimentConfig(epochs=2))
    assert np.isfinite(value)


def test_residual_needs_structural_forecasts(monkeypatch):
    target, panel = data()
    monkeypatch.setattr(exp, "benchmark_forecasts", lambda *a: [])
    rows, coverage = exp.rolling(exp.daily_frame(target, panel), exp._target_frame(target),
        "monthly", 1, pd.Timestamp("2019-01-01"), pd.Timestamp("2019-03-01"),
        ["tcn_residual"], exp.ExperimentConfig())
    assert rows.empty
    assert {x["status"] for x in coverage} == {"missing_structural_forecast"}


def test_matched_reports_do_not_rank_unmatched_periods():
    base = pd.DataFrame(dict(origin=pd.to_datetime(["2019-01-01", "2019-02-01"]),
        period_start=pd.to_datetime(["2019-01-01", "2019-02-01"]),
        period_end=pd.to_datetime(["2019-02-01", "2019-03-01"]), grain="monthly", horizon=1,
        target_year=2019, model="ridge", actual=100., forecast=[110., 200.]))
    reference = base.iloc[:1].assign(model="ets", forecast=105.)
    report = exp.matched_reports(pd.concat([base, reference]), ["ridge"])
    pair = report[report.reference.eq("ets")]
    assert pair.n.tolist() == [1, 1]
    assert pair.mae.tolist() == [10., 5.]


def test_posthoc_contract_separate_from_frozen_test():
    from components.predictive_farm_intelligence.pfoi.backtest_herd import check_block
    check_block([date(2026, 10, 1)], date(2026, 11, 1), "posthoc")
    with pytest.raises(ValueError):
        check_block([date(2026, 10, 1)], date(2026, 11, 1), "test")
    with pytest.raises(ValueError):
        check_block([date(2023, 1, 1)], date(2026, 11, 1), "posthoc")


def test_target_coverage_counts_unfinished_horizons():
    target, _ = data()
    coverage = exp.target_coverage(exp._target_frame(target), ["monthly"],
        pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01"), pd.Timestamp("2021-01-01"))
    h12 = coverage[coverage.horizon.eq(12)].set_index("status")
    assert h12.loc["scoreable", "n"] == 1
    assert h12.loc["target_not_complete_within_cutoff", "n"] == 11


def test_structural_posthoc_replay_uses_fixed_config_and_prior_only(monkeypatch):
    from types import SimpleNamespace
    from components.predictive_farm_intelligence.pfoi import backtest_milk, error_diagnostics
    target, panel = data()
    prior, _, _ = exp.examples(exp.daily_frame(target, panel), exp._target_frame(target),
                               "monthly", 1, exp.ExperimentConfig())
    prior = prior.assign(model="milk_baseline", forecast=lambda x: x.actual*1.1)
    monkeypatch.setattr(error_diagnostics, "load_tag", lambda *a: prior)
    calls = []
    def fake_backtest(source, grain, cfg, milk, **kwargs):
        assert kwargs["block"] == "posthoc"
        assert cfg.cell_table == "day_cell_known" and cfg.pregnancy_check_lag_days == 90
        assert min(kwargs["origins"]) >= date(2024, 1, 1)
        calls.append(grain)
        new = prior.iloc[:1].copy()
        new["origin"] = new["period_start"] = pd.Timestamp("2024-01-01")
        new["period_end"] = pd.Timestamp("2024-02-01")
        return SimpleNamespace(errors=new)
    monkeypatch.setattr(backtest_milk, "run_milk_backtest", fake_backtest)
    result = exp.generate_structural(object(), "unused", ["monthly"], pd.Timestamp("2024-03-01"))
    assert calls == ["monthly"]
    assert result.model.eq("milk_baseline_adaptive").all()
    assert result.origin.max() == pd.Timestamp("2024-01-01")


def test_residual_prediction_adds_to_structural_and_never_trains_on_itself(monkeypatch):
    target, panel = data()
    cfg = exp.ExperimentConfig(min_train=8)
    frame, t = exp.daily_frame(target, panel), exp._target_frame(target)
    structural, _, _ = exp.examples(frame, t, "monthly", 1, cfg)
    structural["forecast"] = structural.actual+100
    monkeypatch.setattr(exp, "benchmark_forecasts", lambda *a: [])
    def fit(name, seq, static, y, *a):
        assert (y < 0).all()
        return -2.
    monkeypatch.setattr(exp, "fit_predict", fit)
    result, _ = exp.rolling(frame, t, "monthly", 1, pd.Timestamp("2019-01-01"),
                           pd.Timestamp("2019-02-01"), ["tcn_residual"], cfg, structural)
    residual = result[result.model.eq("tcn_residual")].iloc[0]
    assert residual.forecast == pytest.approx(residual.structural-62)
    structural.loc[0, "actual"] += 1
    with pytest.raises(ValueError, match="data versions"):
        exp.rolling(frame, t, "monthly", 1, pd.Timestamp("2019-01-01"),
                    pd.Timestamp("2019-02-01"), ["ridge"], cfg, structural)


def test_main_uses_mocked_source_and_saves_only_aggregates(tmp_path, monkeypatch, capsys):
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    target, panel = data()
    class SyntheticSource:
        def target_daily(self, *a): return target
        def panel_daily(self, *a): return panel
    monkeypatch.setattr(SqlHerdSource, "from_env", classmethod(lambda cls: SyntheticSource()))
    monkeypatch.setattr(exp, "HORIZONS", {"monthly": (1,)})
    monkeypatch.setattr(exp, "benchmark_forecasts", lambda *a: [("persistence", 1, 3000.)])
    out = tmp_path/"experiment"
    assert exp.main(["--block", "development", "--start", "2019-01-01", "--end", "2019-03-01",
                     "--models", "ridge", "--out", str(out)]) == 0
    assert (out/"experiment.json").is_file()
    report = pd.read_csv(out/"by_target_year.csv")
    assert "origin" not in report and "actual" not in report
    assert "matched" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        exp.main(["--block", "development", "--start", "2024-01-01", "--end", "2025-01-01", "--out", str(out)])
