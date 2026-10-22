"""pfoi-1.8.0-dev neural milk predictor and document, on SYNTHETIC data only (no database).

Uses PyTorch: run in its own pytest process (LightGBM must not be loaded):
    .venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_neural_milk.py
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import cow_milk_predictor as m
from components.predictive_farm_intelligence.pfoi.neural_milk_outlook import (
    MILK, compose_document, milk_periods, stage_decomposition)

pytestmark = pytest.mark.skipif("lightgbm" in sys.modules,
                                reason="run test_neural_milk.py in its own pytest process")
ORIGIN = date(2020, 6, 1)  # a Monday and the 1st: weeks and months align simply
FAST = {"max_epochs": 3, "min_epochs": 1}


def _raw(cows=14, end="2020-12-31"):
    from components.predictive_farm_intelligence.tests.test_cow_accuracy import _dense_raw
    return _dense_raw(start="2019-01-01", end=end, cows=cows)


def _selection(model="torch_mlp_small_grp", **kw):
    family, variant = m.split_model_name(model)
    return m.Selection(grain="monthly", model=model, base_model=model, family=family,
                       variant=variant, params=dict(FAST),
                       options={**m.NOTEBOOK6_OPTIONS, "ensemble": 2}, data_scope="clean", **kw)


def _fit(raw, model="torch_mlp_small_grp", tmp_path=None, origin=ORIGIN):
    hist = m.origin_history(raw, origin)
    future, counts = m.origin_cohort(hist, origin, m.supported_end(origin))
    allr = m.inference_input(hist, future)
    pred, frame, final = m.fit_predictor(allr, None, origin, _selection(model), device="cpu")
    return pred, frame, final, allr, counts


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    folder = tmp_path_factory.mktemp("predictor")
    pred, frame, final, allr, counts = _fit(_raw())
    pred.save(folder)
    loaded, fx, stages, audit = m.verify_reload(folder, allr, None, frame, final)
    return dict(pred=pred, frame=frame, final=final, allr=allr, counts=counts, folder=folder,
                loaded=loaded, fx=fx, stages=stages, audit=audit)


# ------------------------------------------------------------------ cohort and inputs

def test_cohort_advances_dim_drops_late_lactation_and_short_history():
    raw = _raw(cows=4, end="2020-05-31")
    hist = m.origin_history(raw, ORIGIN)
    future, counts = m.origin_cohort(hist, ORIGIN, m.supported_end(ORIGIN))
    assert counts["cohort_cows"] == 4 and future["litres"].isna().all()
    assert future["is_future"].all() and future["date"].min() == pd.Timestamp(ORIGIN)
    assert future["date"].max() == pd.Timestamp("2020-06-30")
    last = hist.sort_values("date").groupby("cow_id").tail(1).set_index("cow_id")
    first = future[future["date"] == pd.Timestamp(ORIGIN)].set_index("cow_id")
    lead = (pd.Timestamp(ORIGIN) - pd.to_datetime(last["date"])).dt.days
    assert np.allclose(first["dim"], (last["dim"] + lead).loc[first.index])
    assert future["dim"].max() <= m.MAX_DIM
    short = hist.groupby("cow_id").head(2)  # two records only: not a known cow
    _, c2 = m.origin_cohort(short.assign(date=pd.Timestamp("2020-05-20")
                                         + pd.to_timedelta(short.groupby("cow_id").cumcount(), "D")),
                            ORIGIN, m.supported_end(ORIGIN))
    assert c2["cohort_cows"] == 0 and c2["cows_excluded_short_history"] == 4


def test_origin_inside_recording_gap_has_no_cohort():
    raw = _raw(cows=4, end="2020-12-31")
    shifted = raw.assign(date=pd.to_datetime(raw["date"]) + pd.DateOffset(years=3))  # 2022-2023
    hist = m.origin_history(shifted, date(2023, 6, 1))
    _, counts = m.origin_cohort(hist, date(2023, 6, 1), m.supported_end(date(2023, 6, 1)))
    assert counts["cohort_cows"] == 0 and counts["cows_recorded_in_window"] == 0


def test_events_cut_at_origin_and_availability_carried_forward():
    events = {"health": pd.DataFrame({"cow_id": [1, 1], "event_date": ["2020-05-30", "2020-06-02"]}),
              "treatments": None,
              "availability": pd.DataFrame({"source": ["health_episode"] * 2,
                                            "year": [2019, 2020], "records": [500, 20]})}
    out = m.origin_safe_events(events, ORIGIN)
    assert len(out["health"]) == 1
    a = out["availability"].set_index("year")["records"]
    assert a.loc[2020] == 500 and a.loc[2019] == 500  # 2020 takes 2019's count
    later = dict(events, availability=pd.DataFrame({"source": ["health_episode"] * 3,
                                                    "year": [2019, 2020, 2021],
                                                    "records": [5, 900, 900]}))
    b = m.origin_safe_events(later, ORIGIN)["availability"].set_index("year")["records"]
    assert 2021 not in b.index and b.loc[2020] == 5  # no hindsight from the rest of 2020


def test_supported_window_is_the_origin_month():
    assert m.supported_end(date(2024, 2, 1)) == date(2024, 3, 1)
    with pytest.raises(ValueError):
        m.supported_end(date(2024, 2, 2))


# ------------------------------------------------------------------ predictor

def test_reload_reproduces_predictions_without_storing_cow_effects(fitted):
    assert fitted["audit"]["passed"] and fitted["audit"]["max_abs_diff_litres"] < 1e-6
    spec = json.loads((fitted["folder"] / "predictor.json").read_text())
    text = json.dumps(spec)
    assert "cow_effect" not in text and '"animal"' not in text
    assert spec["train_end"] == (ORIGIN - timedelta(days=1)).isoformat()
    assert spec["selection"]["model"] == "torch_mlp_small_grp"
    assert len(spec["training"]["members"]) == 2 and spec["scaler"]["columns"]
    assert "not held-out" in spec["training"]["monitor_note"]


def test_blup_intercepts_equal_statsmodels_random_effects(fitted):
    from components.predictive_farm_intelligence.pfoi.cow_torch import fit_torch_models

    pred = fitted["loaded"]
    wood, _ = pred._wood(pred.frame(fitted["allr"], None))
    allr = fitted["allr"]
    models = fit_torch_models(allr, train_end=ORIGIN - timedelta(days=1),
                              validation_end=ORIGIN - timedelta(days=1), params=dict(FAST),
                              device="cpu", options={"ensemble": 1, "use_gru": False,
                                                     "use_quantile": False},
                              grains=("monthly",), model_names=())
    ref = models.fitted["wood_mixed"].cow_effect
    assert np.allclose(wood.cow_effect.reindex(ref.index).to_numpy(), ref.to_numpy(), atol=1e-6)


def test_tampered_weights_are_rejected(fitted, tmp_path):
    import shutil

    copy_dir = tmp_path / "p"
    shutil.copytree(fitted["folder"], copy_dir)
    (copy_dir / "weights.pt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        m.Predictor.load(copy_dir)


def test_future_outcomes_cannot_change_the_forecast(fitted):
    raw = _raw()
    changed = raw.copy()
    after = pd.to_datetime(changed["date"]) >= pd.Timestamp(ORIGIN)
    changed.loc[after, "litres"] = 17.5  # outcomes on/after the origin
    hist = m.origin_history(changed, ORIGIN)
    future, _ = m.origin_cohort(hist, ORIGIN, m.supported_end(ORIGIN))
    allr = m.inference_input(hist, future)
    fx, stages = fitted["loaded"].predict(allr, None)
    fut = fx["is_future"].to_numpy(bool)
    assert np.allclose(stages["final"][fut], fitted["stages"]["final"][fitted["fx"]["is_future"].to_numpy(bool)])
    bad = allr.copy()
    bad.loc[~bad["is_future"], "date"] = pd.Timestamp(ORIGIN)
    with pytest.raises(ValueError, match="on or after"):
        m.fit_predictor(bad, None, ORIGIN, _selection(), device="cpu")


def test_notebook6_defaults_unchanged_by_production_hooks():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import prepare_accuracy_frame
    from components.predictive_farm_intelligence.pfoi.cow_torch import fit_torch_models

    raw = _raw(cows=4, end="2020-03-31")
    assert "is_future" not in prepare_accuracy_frame(raw, evaluation_mode="walk_forward").columns
    mods = fit_torch_models(raw, train_end=date(2019, 12, 31), validation_end=date(2019, 12, 31),
                            params=dict(FAST), device="cpu",
                            options={"ensemble": 1, "use_gru": False, "use_quantile": False},
                            grains=("daily",), model_names=("torch_mlp_small",))
    assert "state" not in mods.fitted["torch_mlp_small"]


# ------------------------------------------------------------------ herd adapter

def _milking_csv(origin=ORIGIN, daily=300.0, month=310.0):
    rows = [{"target_period": (origin + timedelta(days=h - 1)).isoformat(), "grain": "daily",
             "horizon": h, "series": "milking", "forecast": daily} for h in range(1, 15)]
    rows.append({"target_period": origin.isoformat(), "grain": "monthly", "horizon": 1,
                 "series": "milking", "forecast": month})
    rows.append({"target_period": origin.isoformat(), "grain": "weekly", "horizon": 1,
                 "series": "milking", "forecast": daily})
    rows.append({"target_period": origin.isoformat(), "grain": "daily", "horizon": 1,
                 "series": "herd_milk", "forecast": 1.0})
    return pd.DataFrame(rows)


def test_milking_path_matches_published_days_and_month_mean():
    path, audit = m.milking_path(_milking_csv(), ORIGIN, m.supported_end(ORIGIN))
    assert len(path) == 30 and (path["milking"].iloc[:14] == 300.0).all()
    assert abs(path["milking"].mean() - 310.0) < 1e-9
    assert audit["weekly_mean_max_abs_diff_cows"] == 0.0 and audit["filled_days"] == 16


def test_herd_daily_is_milking_times_mean_cow_yield(fitted):
    path, _ = m.milking_path(_milking_csv(), ORIGIN, m.supported_end(ORIGIN))
    daily = m.herd_daily(fitted["fx"], fitted["stages"], path)
    fx = fitted["fx"]
    fut = (fx["is_future"] & fx["score_eligible"]).to_numpy()
    day1 = fut & (fx["date"] == pd.Timestamp(ORIGIN)).to_numpy()
    expected = 300.0 * fitted["stages"]["final"][day1].mean()
    assert np.isclose(daily.loc[0, "herd_litres"], expected)
    assert "animal" not in daily.columns and (daily["cohort_cows"] == 14).all()
    few = m.herd_daily(fitted["fx"], fitted["stages"], path, min_cows=15)
    assert few["herd_litres"].isna().all()


# ------------------------------------------------------------------ document

def _structural_doc():
    def row(grain, h, target, series, f):
        return {"origin_date": ORIGIN.isoformat(), "target_period": target, "grain": grain,
                "horizon": h, "series": series, "forecast": f, "lower": f * .9, "upper": f * 1.1,
                "quality_flag": "high", "model_version": "pfoi-1.2.0-dev",
                "core_version": "synthetic"}
    return {
        "source": "model", "model_version": "pfoi-1.2.0-dev", "origin_date": ORIGIN.isoformat(),
        "core_version": "synthetic", "generated_at": "synthetic",
        "outlook": [row("day", 1, "2020-06-01", MILK, 999.0), row("month", 1, "2020-06-01", MILK, 9e4),
                    row("month", 1, "2020-06-01", "milking", 310.0),
                    row("month", 2, "2020-07-01", "calvings", 12.0),
                    row("month", 1, "2020-06-01", "mastitis_episodes", 3.0)],
        "corrections": [{"series": MILK, "correction": 5.0}, {"series": "milking", "correction": 1.0}],
        "attribution": [{"series": MILK, "factor": "herd_size", "contribution": 3.0},
                        {"series": "calvings", "factor": "determined", "contribution": 4.0}],
        "backtest": [{"series": MILK, "mae": 1.0}, {"series": "milking", "mae": 2.0}],
        "qualityBands": [{"band": "a"}], "replay": [{"series": MILK}],
        "blend": {"x": 1}, "outage_simulation": [{}], "evidence_ladder": [{}],
        "heat": {"status": "synthetic heat"}, "moves": [{"from": "a"}],
        "actuals": [{"series": MILK, "value": 1.0}], "realised": [],
        "withheld": [{"series": MILK, "reason": "old"}],
        "interval_method": {"milk": "aci_quality_band", "staleness_scale": "x"},
        "scenarios": [{"series": MILK}, {"series": "milking"}],
    }


@pytest.fixture(scope="module")
def artifact(fitted):
    path, audit = m.milking_path(_milking_csv(), ORIGIN, m.supported_end(ORIGIN))
    daily = m.herd_daily(fitted["fx"], fitted["stages"], path)
    a = m.build_forecast_artifact(ORIGIN, fitted["loaded"], daily, fitted["counts"], audit,
                                  fitted["audit"])
    return json.loads(json.dumps(a))


def test_document_replaces_milk_and_keeps_every_non_milk_section(artifact):
    src = _structural_doc()
    before = copy.deepcopy(src)
    doc = compose_document(src, artifact)
    assert src == before  # the 1.2.0-dev document is never modified
    keep = lambda d: {(r["grain"], r["horizon"], r["series"]): r["forecast"]  # noqa: E731
                      for r in d["outlook"] if r["series"] != MILK}
    assert keep(doc) == keep(src)
    for key in ("heat", "moves", "actuals", "realised"):
        assert doc[key] == src[key]
    assert [r["series"] for r in doc["attribution"]] == ["calvings"]
    assert [r["series"] for r in doc["corrections"]] == ["milking"]
    assert [r["series"] for r in doc["backtest"]] == ["milking"]
    assert [r["series"] for r in doc["scenarios"]] == ["milking"]
    for key in ("qualityBands", "replay", "blend", "outage_simulation", "evidence_ladder"):
        assert key not in doc
    assert doc["model_version"] == m.NEURAL_MILK_VERSION and doc["provenance"]["milk_litres"]
    milk = {(r["grain"], r["horizon"]): r for r in doc["outlook"] if r["series"] == MILK}
    assert 999.0 not in [r["forecast"] for r in milk.values()]
    assert set(g for g, _ in milk) == {"day", "week", "month"}
    assert max(h for g, h in milk if g == "month") == 1  # only the supported month
    assert max(h for g, h in milk if g == "week") == 4   # weeks ending by 2020-06-30
    reasons = {w["reason"] for w in doc["withheld"] if w["series"] == MILK}
    assert reasons == {"unsupported_horizon"}
    assert all(r["lower"] == r["upper"] == r["forecast"] and r["interval_status"] == "uncalibrated"
               for r in milk.values())


def test_milk_covers_every_supported_day_the_structural_document_publishes(artifact):
    src = _structural_doc()
    src["outlook"] += [dict(src["outlook"][2], grain="day", horizon=h,
                            target_period=(ORIGIN + timedelta(days=h - 1)).isoformat())
                       for h in range(1, 366)]
    doc = compose_document(src, artifact)
    days = sorted(r["horizon"] for r in doc["outlook"] if r["series"] == MILK and r["grain"] == "day")
    assert days == list(range(1, 31))  # all of June, nothing after
    gap = next(w for w in doc["withheld"] if w["grain"] == "day")
    assert gap["reason"] == "unsupported_horizon" and gap["horizons"][0] == 31


def test_weeks_and_month_reconcile_to_the_daily_path(artifact):
    rows, _ = milk_periods(ORIGIN, artifact)
    daily = {r["date"]: r["herd_litres"] for r in artifact["daily"]}
    month = next(r for r in rows if r["grain"] == "month")
    assert np.isclose(month["forecast"], sum(daily.values()), atol=1e-2)
    for w in (r for r in rows if r["grain"] == "week"):
        s = date.fromisoformat(w["target_period"])
        part = [daily[(s + timedelta(days=i)).isoformat()] for i in range(7)]
        assert np.isclose(w["forecast"], sum(part), atol=1e-2)


def test_stage_decomposition_is_exact_and_labels_baseline(artifact):
    parts = stage_decomposition(ORIGIN, artifact)
    month = [p for p in parts if p["grain"] == "month"]
    total = next(r for r in milk_periods(ORIGIN, artifact)[0] if r["grain"] == "month")["forecast"]
    assert np.isclose(sum(p["contribution_litres"] for p in month), total, atol=0.05)
    assert {p["kind"] for p in month if p["stage"] == "wood_curve"} == {"baseline"}


def test_missing_prediction_is_explicit_not_silent(artifact):
    missing = dict(artifact, status="missing", reason="no_clean_cow_records_before_origin",
                   daily=[{**r, "herd_litres": None, "yield_per_cow": None} for r in artifact["daily"]])
    doc = compose_document(_structural_doc(), missing)
    assert not [r for r in doc["outlook"] if r["series"] == MILK]
    reasons = {w["reason"] for w in doc["withheld"] if w["series"] == MILK}
    assert "missing_prediction:no_clean_cow_records_before_origin" in reasons
    assert doc["milk_model"]["status"] == "missing"


def test_compose_cli_fails_loudly_without_milk(tmp_path, artifact):
    from components.predictive_farm_intelligence.pfoi import cli

    src = tmp_path / "outlook" / "pfoi-1.2.0-dev"
    dest = tmp_path / "outlook" / m.NEURAL_MILK_VERSION
    src.mkdir(parents=True)
    dest.mkdir(parents=True)
    (src / "run_202006.json").write_text(json.dumps(_structural_doc()))
    (dest / "neural_milk_202006.json").write_text(json.dumps(dict(artifact, status="missing",
                                                                  reason="cohort_below_minimum")))
    args = ["neural-milk-compose", "--origins", ORIGIN.isoformat(), "--out", str(tmp_path)]
    assert cli.main(args) == 3
    assert cli.main(args + ["--allow-missing-milk"]) == 0
    (dest / "neural_milk_202006.json").write_text(json.dumps(artifact))
    assert cli.main(args) == 0
    assert cli.main(["milk-panel-check", "--origins", ORIGIN.isoformat(), "--out", str(tmp_path),
                     "--versions", "pfoi-1.2.0-dev", m.NEURAL_MILK_VERSION]) == 0


# ------------------------------------------------------------------ selection

def _nb6_dir(tmp_path, monthly="torch_mlp_large_grp"):
    d = tmp_path / "pfoi-cow-yield-torch-1.6.0-dev" / "cow-yield-test-clean-75-5-20" / "torch_v3"
    d.mkdir(parents=True)
    pd.DataFrame({"grain": ["daily", "weekly", "monthly"],
                  "model": ["blend", "kalman_state_recal", monthly],
                  "pooled_base": ["torch_mlp_small", "kalman_state_recal", monthly],
                  "accuracy_pct": [80.0, 82.0, 84.0], "wape_pct": [20.0, 18.0, 16.0]}
                 ).to_csv(d / "winners.csv", index=False)
    pd.DataFrame({"cv_accuracy_pct": [70.0, 75.0], "hidden": ["(64, 32)", "(128, 64)"],
                  "dropout": [0.2, 0.4], "lr": [1e-3, 2e-3], "weight_decay": [1e-4, 1e-5],
                  "batch_size": [512, 1024], "max_epochs": [10, 10], "min_epochs": [1, 1],
                  "stop_drop_pp": [1.0, 1.0], "stop_patience": [2, 2], "lr_patience": [5, 5],
                  "min_lr": [1e-6, 1e-6]}).to_csv(d / "tuning_torch_trials.csv", index=False)
    return d


def test_selection_reads_monthly_winner_and_notebook_settings(tmp_path):
    from components.predictive_farm_intelligence.pfoi import cow_accuracy  # noqa: F401
    d = _nb6_dir(tmp_path)
    sel = m.selection_from_notebook6(d)
    assert (sel.model, sel.family, sel.variant) == ("torch_mlp_large_grp", "torch_mlp_large", "_grp")
    assert sel.params["hidden_large"] == [128, 64] and sel.params["dropout"] == 0.4
    assert sel.params["max_epochs"] == 250 and sel.params["stop_patience"] == 15
    assert sel.architectures() == ("torch_mlp_large",)
    assert sel.fit_options()["use_gru"] is False and "winners.csv" in sel.sources
    with pytest.raises(ValueError, match="blend"):
        m.selection_from_notebook6(d, grain="daily")
    syn = tmp_path / "x" / "cow-yield-test-clean-75-5-20" / "synthetic_only"
    syn.mkdir(parents=True)
    with pytest.raises(ValueError, match="synthetic"):
        m.selection_from_notebook6(syn)


def test_selection_cli_saves_monthly_selection(tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    d = _nb6_dir(tmp_path)
    assert cli.main(["nb6-selection", "--run-dir", str(d), "--out", str(tmp_path)]) == 0
    saved = json.loads((tmp_path / "models" / m.NEURAL_MILK_VERSION / "selection_monthly.json").read_text())
    assert saved["model"] == "torch_mlp_large_grp"
    out = capsys.readouterr().out
    assert "fixed-origin" in out and "ERROR" in out  # the daily blend lacks its weight table


# ------------------------------------------------------------------ backtest

def _bt_inputs(raw):
    from components.predictive_farm_intelligence.pfoi.cow_milk_backtest import monthly_milking_projection

    d = pd.to_datetime(raw["date"]).dt.date
    days = pd.DataFrame({"date": d, "litres": raw["litres"]}).groupby("date")["litres"]
    target = pd.DataFrame({"date": days.sum().index, "target_litres": days.sum().to_numpy() * 10.0,
                           "is_scoreable": True})
    milking = pd.Series(days.size().to_numpy() * 10.0, index=days.size().index)
    herd = pd.DataFrame([{"origin": f"2020-{m:02d}-01", "grain": "monthly", "horizon": h,
                          "series": "milking", "model": "herd_engine", "forecast": 140.0}
                         for m in range(1, 13) for h in range(1, 4)])
    return target, milking, monthly_milking_projection(herd)


def test_backtest_is_aggregate_origin_safe_and_scores_identical_periods():
    from components.predictive_farm_intelligence.pfoi import cow_milk_backtest as bt

    raw = _raw()
    target, milking, proj = _bt_inputs(raw)
    sel = _selection("kalman_state")
    rows, cows, audit = [], [], []
    for o in (date(2020, 3, 1), date(2020, 4, 1), date(2020, 5, 1)):
        r, c, a = bt.backtest_origin(raw, None, target, milking, proj, o, sel, max_months=3)
        rows += r; cows += c; audit.append(a)
    e = pd.DataFrame(rows)
    assert not {"animal", "cow_id"} & set(e.columns) and not {"animal", "cow_id"} & set(pd.DataFrame(cows).columns)
    own = e[e["model"] == bt.MODEL]
    assert own["forecast"].notna().all() and (own["cohort_cows_min"] >= 10).all()
    # herd forecast = projected cows x summed cohort mean yield
    first = own.iloc[0]
    assert np.isclose(first["forecast"], 140.0 * first["yield_per_cow_forecast"] * 31, rtol=1e-3)
    # outcomes after the origin cannot change its forecast
    changed = raw.copy()
    changed.loc[pd.to_datetime(changed["date"]) >= pd.Timestamp("2020-03-01"), "litres"] = 17.0
    r2, _, _ = bt.backtest_origin(changed, None, target, milking, proj, date(2020, 3, 1), sel, max_months=3)
    f1 = [x["forecast"] for x in rows[:12] if x["model"] == bt.MODEL]
    f2 = [x["forecast"] for x in r2 if x["model"] == bt.MODEL]
    assert np.allclose(f1, f2)
    summary = bt.summarise(e, [bt.MODEL, "persistence", "seasonal_naive"])
    assert set(summary["n"]) == {summary["n"].iloc[0]}  # identical cells for every model
    cs = bt.summarise_cows(pd.DataFrame(cows))
    assert set(cs["horizon"]) == {1, 2, 3} and (cs["cow_days"] > 0).all()


def test_intervals_use_only_earlier_origins():
    from components.predictive_farm_intelligence.pfoi import cow_milk_backtest as bt

    rows = []
    for k in range(14):
        o = date(2019 + (k // 12), k % 12 + 1, 1)
        s, e = bt._month_bounds(o, 1)
        rows.append({"origin": o.isoformat(), "grain": "monthly", "horizon": 1,
                     "period_start": s.isoformat(), "period_end": e.isoformat(),
                     "model": bt.MODEL, "forecast": 100.0, "actual": 100.0 + k})
    out = bt.add_intervals(pd.DataFrame(rows), min_samples=8)
    assert out.iloc[:8]["lower"].isna().all()  # fewer than 8 finished errors: no range
    assert out.iloc[8]["interval_n"] == 8      # the 8 months that ended by this origin
    assert out.iloc[13]["interval_n"] == 13    # errors from the 13 earlier origins only


def test_multi_month_support_and_fixed_origin_features():
    hist = m.origin_history(_raw(), ORIGIN)
    future, _ = m.origin_cohort(hist, ORIGIN, m.supported_end(ORIGIN, 3))
    allr = m.inference_input(hist, future, ORIGIN)
    assert m.supported_end(ORIGIN, 3) == date(2020, 9, 1)
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import prepare_accuracy_frame
    f = prepare_accuracy_frame(allr, train_end=ORIGIN - timedelta(days=1),
                               validation_end=ORIGIN - timedelta(days=1),
                               evaluation_mode="walk_forward", origin_grain="monthly")
    fut = f[f["is_future"]]
    assert (pd.to_datetime(fut["origin_date"]) == pd.Timestamp(ORIGIN)).all()
    assert fut["date"].max() >= pd.Timestamp("2020-08-01")



def test_verify_passes_for_composed_document_and_catches_tampering(artifact):
    from components.predictive_farm_intelligence.pfoi.neural_milk_outlook import verify_document

    src = _structural_doc()
    doc = compose_document(src, artifact)
    assert all(c["ok"] for c in verify_document(src, doc, artifact))
    bad = copy.deepcopy(doc)
    next(r for r in bad["outlook"] if r["series"] == "milking")["forecast"] += 1
    failed = {c["check"] for c in verify_document(src, bad, artifact) if not c["ok"]}
    assert failed == {"non-milk forecasts identical to source"}
