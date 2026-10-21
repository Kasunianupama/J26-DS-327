"""Fictional aggregate sequences only; no database or environment-file access."""
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import hybrid as h
from components.predictive_farm_intelligence.pfoi import hybrid_runner as runner


def history():
    days = pd.date_range("2016-01-01", "2021-12-31")
    return pd.DataFrame(dict(milk=100., milking=10., abortions=0., trusted=True,
                             source="delpro"), index=days)


def projected(start="2020-01-01", end="2020-02-01"):
    days = pd.date_range(start, end, inclusive="left")
    return pd.DataFrame(dict(date=days, herd_milk=100., milking=10.,
                             calvings=.1, dry_offs=.05))


def test_features_ignore_future_and_old_sources():
    frame = history()
    cfg = h.HybridConfig()
    origin = pd.Timestamp("2020-01-01")
    expected, status = h.milk_context(frame, origin, projected(), cfg)
    assert status == "ok" and expected["anchor"] == 100
    frame.loc[frame.index >= origin, ["milk", "milking"]] = 1e10
    frame.loc[frame.index < origin-pd.Timedelta(days=28), "milk"] = 1e8
    actual, _ = h.milk_context(frame, origin, projected(), cfg)
    np.testing.assert_array_equal(expected["pipeline_x"], actual["pipeline_x"])
    frame.loc["2019-12-20": "2019-12-31", "source"] = "shipment"
    assert h.milk_context(frame, origin, projected(), cfg)[1] == "insufficient_trusted_recent_milk"


def test_trust_gate_withholds_stale_or_untrusted_records():
    cfg = h.HybridConfig()
    frame = history()
    frame.loc["2019-12-20": "2019-12-31", "trusted"] = False
    assert h.milk_context(frame, pd.Timestamp("2020-01-01"), projected(), cfg)[1] == "stale_milk"
    frame.loc["2019-12-01": "2019-12-31", "trusted"] = False
    assert h.milk_context(frame, pd.Timestamp("2020-01-01"), projected(), cfg)[0] is None


def test_change_model_learns_planted_relationship_not_current_outcome():
    rng = np.random.default_rng(17)
    dates = pd.date_range("2017-01-01", periods=36, freq="MS")
    x = rng.normal(size=36)
    records = [dict(origin=o, period_end=o+pd.offsets.MonthBegin(1), source="delpro",
                    anchor=100., days=30, actual=3000*(1+.2*v), pipeline_x=np.array([v]))
               for o, v in zip(dates, x)]
    cfg = h.HybridConfig(ridge=.001)
    context = dict(source="delpro", anchor=100., pipeline_x=np.array([1.]))
    value = h.change_forecast(records, context, pd.Timestamp("2020-02-01"), 30, "pipeline_x", cfg)
    assert value == pytest.approx(3600, rel=.001)
    records.append(dict(origin=pd.Timestamp("2020-02-01"), period_end=pd.Timestamp("2020-03-01"),
        source="delpro", anchor=100., days=30, actual=1e20, pipeline_x=np.array([1.])))
    assert h.change_forecast(records, context, pd.Timestamp("2020-02-01"), 30, "pipeline_x", cfg) == value
    assert h.change_forecast(records, dict(context, source="shipment"),
        pd.Timestamp("2020-02-01"), 30, "pipeline_x", cfg) is None


def test_gate_uses_matched_completed_forecasts_and_can_keep_persistence():
    dates = pd.date_range("2017-01-01", periods=24, freq="MS")
    rows = [dict(origin=o, period_end=o+pd.offsets.MonthBegin(1), actual=100.,
                 persistence=100., specialist=150.) for o in dates]
    cfg = h.HybridConfig()
    w, n = h.choose_weights(rows, pd.Timestamp("2020-01-01"), ("persistence", "specialist"), cfg, "persistence")
    assert n == 24 and w == dict(persistence=1., specialist=0.)
    for r in rows:
        r.update(actual=150.)
    w, _ = h.choose_weights(rows, pd.Timestamp("2020-01-01"), ("persistence", "specialist"), cfg, "persistence")
    assert w["specialist"] == 1
    future = [dict(origin=pd.Timestamp("2020-01-01"), period_end=pd.Timestamp("2020-02-01"),
                   actual=1e30, persistence=1e30, specialist=0.)]
    assert h.choose_weights(rows+future, pd.Timestamp("2020-01-01"),
        ("persistence", "specialist"), cfg, "persistence")[0] == w
    assert h.choose_weights(rows[:5], pd.Timestamp("2020-01-01"),
        ("persistence", "specialist"), cfg, "persistence")[0]["persistence"] == 1


def test_abortion_counts_respond_to_surge_ignore_future_and_keep_missing_missing():
    frame, cfg = history(), h.HybridConfig()
    origin = pd.Timestamp("2020-01-01")
    baseline = h.abortion_posterior(frame, origin, cfg)
    frame.loc["2019-11-01": "2019-12-31", "abortions"] = 2
    surge = h.abortion_posterior(frame, origin, cfg)
    assert surge.daily_mean > baseline.daily_mean
    frame.loc[frame.index >= origin, "abortions"] = 1e9
    assert h.abortion_posterior(frame, origin, cfg) == surge
    mean, lo, hi = surge.predictive(31)
    assert 0 <= lo <= mean <= hi and hi < 1000
    frame.loc["2019-10-01": "2019-12-31", "abortions"] = np.nan
    assert h.abortion_posterior(frame, origin, cfg) is None


def test_zero_counts_produce_finite_count_intervals_not_multiplicative_explosion():
    posterior = h.abortion_posterior(history(), pd.Timestamp("2020-01-01"), h.HybridConfig())
    mean, lo, hi = posterior.predictive(31)
    assert 0 <= lo <= hi < 10 and 0 <= mean < 1


def test_abortion_coupling_changes_calvings_without_creating_animals():
    from components.predictive_farm_intelligence.tests.synthetic import synthetic_state, synthetic_rates
    from components.predictive_farm_intelligence.pfoi.herd_engine import project
    from dataclasses import replace
    state, rates = synthetic_state(), synthetic_rates()
    before = state.heifer_preg.copy()
    hazard = h.coupled_hazard(state, rates.abortion, h.AbortionPosterior(10., 10., 90), 1.)
    assert hazard > rates.abortion
    a = project(state, rates, 120).daily
    b = project(state, replace(rates, abortion=hazard), 120).daily
    assert b.real_abortions.sum() > a.real_abortions.sum()
    assert b.calvings.sum() < a.calvings.sum()
    for f in (a, b):
        np.testing.assert_allclose(f.n_herd, f[["calves", "heifers_open", "heifers_pregnant",
            "milking", "dry_open", "dry_pregnant", "bulls", "unknown_state"]].sum(axis=1))
    np.testing.assert_array_equal(state.heifer_preg, before)
    assert h.coupled_hazard(state, rates.abortion, None, 1.) == rates.abortion


def test_reconciliation_and_intervals_are_zero_safe_and_past_only():
    daily = projected()
    adjusted = h.reconcile_milk(daily, {pd.Timestamp("2020-01-01"): 6200.})
    assert adjusted.herd_milk.sum() == pytest.approx(6200)
    np.testing.assert_array_equal(adjusted.milking, daily.milking)
    zero = h.reconcile_milk(daily.assign(herd_milk=0.), {pd.Timestamp("2020-01-01"): 3100.})
    assert (zero.herd_milk == 100).all()
    with pytest.raises(ValueError, match="complete"):
        h.reconcile_milk(daily.iloc[:-1], {pd.Timestamp("2020-01-01"): 3100.})
    rows = [dict(origin=o, period_end=o+pd.offsets.MonthBegin(1), actual=2., fused=0., scale=1.)
            for o in pd.date_range("2017-01-01", periods=24, freq="MS")]
    cfg = h.HybridConfig()
    lo, hi, n = h.residual_interval(rows, pd.Timestamp("2020-01-01"), 0., 1., cfg)
    assert (lo, hi, n) == (0., 2., 24)
    assert h.residual_interval(rows[:5], pd.Timestamp("2020-01-01"), 0., 1., cfg) == (None, None, 5)


def test_base_recipe_is_explicit_and_versioned():
    engine, milk, manifest = runner.base_recipe()
    assert engine.cell_table == "day_cell_known" and engine.conception_known == "recorded"
    assert engine.rate_half_life_months == 6 and engine.fast_half_life_months is None
    assert milk.k_mode == "anchor_first"
    cfg = h.HybridConfig()
    _, _, other = runner.base_recipe("lactation")
    assert cfg.identity(manifest) != cfg.identity(other)


def synthetic_run():
    from components.predictive_farm_intelligence.pfoi.outlook import FrozenRun
    from components.predictive_farm_intelligence.pfoi.herd_engine import project, MilkCurveArrays, N_PAR, N_GEN, N_DIM
    from components.predictive_farm_intelligence.tests.synthetic import synthetic_state, synthetic_rates
    state, rates = synthetic_state(), synthetic_rates()
    arrays = MilkCurveArrays.from_yield(np.ones((N_PAR, N_GEN, N_DIM))*5)
    proj = project(state, rates, 366, milk_curve=arrays)
    daily = proj.daily.assign(herd_milk=proj.daily.curve_litres)
    return FrozenRun(date(2020, 1, 1), None, SimpleNamespace(k=1., arrays=arrays),
        SimpleNamespace(state=state), rates, proj, daily,
        dict(monthly=date(2020, 1, 1), daily=date(2020, 1, 1), weekly=date(2020, 1, 6)), 366, "ok")


def test_forecast_origin_has_no_labels_and_monthly_path_is_coherent():
    run = synthetic_run()
    frame = history()
    path, records, abortions, decisions = runner.forecast_origin(run, frame, [], [], h.HybridConfig())
    assert len(records) == 12 and all(np.isnan(r["actual"]) for r in records)
    assert np.isnan(abortions["actual"]) and abortions["weight"] == 0
    assert {r["status"] for r in decisions} == {"issued"}
    for r in records:
        part = runner._part(path, r["period_start"], r["period_end"])
        assert part.herd_milk.sum() == pytest.approx(r["fused"])
    frame.loc[frame.index >= pd.Timestamp("2020-01-01"), ["milk", "abortions"]] = 1e12
    other = runner.forecast_origin(run, frame, [], [], h.HybridConfig())[0]
    pd.testing.assert_frame_equal(path, other)


def test_replay_scores_after_issuance_without_any_database(monkeypatch):
    from components.predictive_farm_intelligence.pfoi import outlook
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    monkeypatch.setattr(SqlHerdSource, "from_env", lambda **kw: pytest.fail("No database access"))
    run = synthetic_run()
    monkeypatch.setattr(outlook, "run_model", lambda *a, **kw: run)
    days = pd.date_range("2016-01-01", "2020-02-29")
    target = pd.DataFrame(dict(date=days, target_litres=100., target_source="delpro",
                              is_scoreable=True, identified_share=.9, data_gap=0))
    panel = pd.DataFrame(dict(date=days, milking=10., n_herd=100., real_abortions=0.,
                             calvings=.1, dry_offs=.05))
    source = SimpleNamespace(target_daily=lambda *a: target.copy(),
        panel_daily=lambda *a: panel.copy(), milking_cowdays=lambda *a: pd.DataFrame())
    cfg = h.HybridConfig()
    engine, milk, _ = runner.base_recipe()
    scores, decisions = runner.evaluate(source, [date(2020, 1, 1)], date(2020, 3, 1),
                                      engine, milk, None, cfg)
    assert len(scores) > 0 and decisions.status.eq("issued").all()
    assert set(runner.reports(scores, decisions)) == {
        "metrics", "matched", "decisions", "recovery", "by_origin_year"}
    panel.loc[panel.date >= pd.Timestamp("2020-01-01"), "real_abortions"] = 4.
    other, _ = runner.evaluate(source, [date(2020, 1, 1)], date(2020, 3, 1),
                              engine, milk, None, cfg)
    pd.testing.assert_series_equal(scores.forecast, other.forecast)
    assert not scores.actual.equals(other.actual)


def test_matched_reports_count_withheld_and_do_not_reward_missing_forecasts():
    rows = []
    for o in pd.date_range("2020-01-01", periods=2, freq="MS"):
        for model, forecast in ((h.VERSION, 100. if o.month == 1 else np.nan),
                                ("persistence", 110.), ("base_1_2_code_reference", 120.)):
            rows.append(dict(model=model, forecast=forecast, actual=100., series="herd_milk",
                grain="monthly", horizon=1, band="verified", lower=np.nan, upper=np.nan,
                origin=o, period_start=o))
    decisions = pd.DataFrame([dict(horizon=1, status="issued", gate_n=0)])
    out = runner.reports(pd.DataFrame(rows), decisions)
    metric = out["metrics"].loc[lambda f: f.model.eq(h.VERSION)].iloc[0]
    assert metric.scheduled == 2 and metric.scoreable == 2 and metric.issued == 1
    assert out["matched"].n.tolist() == [1, 1]
    assert not out["matched"].interpretable.any()


def test_cli_rejects_invalid_block_and_missing_inputs_before_database(monkeypatch, tmp_path):
    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    monkeypatch.setattr(SqlHerdSource, "from_env", lambda **kw: pytest.fail("Database must not open"))
    with pytest.raises(SystemExit):
        runner.main(["--block", "development", "--end", "2026-01-01", "--out", str(tmp_path/"a")])
    with pytest.raises(SystemExit):
        runner.main(["--block", "development", "--end", "2024-01-01",
                     "--backtests", str(tmp_path), "--out", str(tmp_path/"a")])


def test_changed_data_version_is_not_silently_compared():
    frame = history()
    frame["is_scoreable"] = True
    errors = pd.DataFrame([dict(period_start=pd.Timestamp("2020-01-01"),
        period_end=pd.Timestamp("2020-02-01"), series="herd_milk", actual=3100.)])
    runner.validate_base_actuals(errors, frame)
    errors["actual"] = 6200.
    with pytest.raises(ValueError, match="regenerate matching base errors"):
        runner.validate_base_actuals(errors, frame)
