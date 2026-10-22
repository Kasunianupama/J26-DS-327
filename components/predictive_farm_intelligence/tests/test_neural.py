"""Neural milk model (pfoi/neural.py) on SYNTHETIC data: split, leakage, masking, training."""
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from components.predictive_farm_intelligence.pfoi import neural as N
from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.milk_baseline import MilkConfig

from .synthetic import SYNTHETIC_END, SYNTHETIC_START, FakeHerdSource

STATIC_IDX = {name: i for i, name in enumerate(N.STATIC)}


@pytest.fixture(scope="module")
def frame():
    return N.daily_frame(FakeHerdSource(), SYNTHETIC_START, SYNTHETIC_END)


def _paths(f: pd.DataFrame, scale: float = 1.1, start=date(2016, 1, 4), end=date(2024, 1, 1)):
    """Fake engine runs: every Monday, the true litres times ``scale`` (synthetic)."""
    rows = []
    lit = f["litres"].ffill()
    for run in N.mondays(start, end):
        for h in range(N.ENGINE_H):
            d = run + timedelta(days=h)
            if d in lit.index:
                rows.append((run, d, scale * float(lit[d])))
    return pd.DataFrame(rows, columns=["run", "date", "litres"])


def test_split_is_ordered_and_disjoint():
    N.check_split()
    s1, s2 = N.STAGES
    assert N.part_bounds(s1, "train") == (date(2015, 8, 1), date(2017, 7, 1))
    assert N.part_bounds(s1, "test") == (date(2018, 1, 1), date(2020, 1, 1))
    assert N.part_bounds(s2, "train")[0] == date(2020, 8, 1)
    assert N.part_bounds(s2, "test")[0] == date(2023, 1, 1)
    bad = replace(s2, train_start=date(2019, 6, 1))  # overlaps the stage-1 test years
    with pytest.raises(ValueError, match="overlap"):
        N.check_split((s1, bad))


def test_inputs_use_only_days_before_the_origin(frame):
    o = date(2019, 3, 4)
    paths = _paths(frame)
    a = N.build_samples(frame, paths, [o], "shipment", date(2020, 1, 1))
    future = frame.copy()
    future.loc[future.index >= o, ["litres", "milking", "dry_pregnant", "calvings"]] *= 7.0
    b = N.build_samples(future, paths, [o], "shipment", date(2020, 1, 1))
    assert np.allclose(a.seq, b.seq) and np.allclose(a.stat, b.stat) and np.allclose(a.ref, b.ref)
    assert not np.allclose(a.y, b.y)  # only the targets moved


def test_engine_run_after_the_origin_is_never_used(frame):
    o = date(2019, 3, 6)  # a Wednesday: the latest run is Monday 2019-03-04
    paths = _paths(frame)
    late = paths[paths["run"] == date(2019, 3, 11)].assign(litres=1e6)
    a = N.build_samples(frame, paths, [o], "shipment", date(2020, 1, 1))
    b = N.build_samples(frame, pd.concat([paths[paths["run"] != date(2019, 3, 11)], late]),
                        [o], "shipment", date(2020, 1, 1))
    assert np.allclose(a.eng, b.eng)


def test_training_targets_stop_at_validation_and_test(frame):
    paths = _paths(frame)
    s1 = N.STAGES[0]
    for part in ("train", "val"):
        s = N.stage_samples(frame, paths, s1, part)
        _, end = N.part_bounds(s1, part)
        assert len(s) > 0
        for o, m in zip(s.origin, s.m):
            last = max((h for h in range(N.H) if m[h]), default=None)
            if last is not None:
                assert o + timedelta(days=last) < end


def test_stages_never_mix_record_sources(frame):
    paths = _paths(frame)
    s2 = N.STAGES[1]
    s = N.stage_samples(frame, paths, s2, "train")
    assert len(s) and min(s.origin) >= date(2020, 8, 1) + timedelta(days=N.MIN_REF)
    # a stage-1 origin just before the source change: DelPro days are masked, not learned
    t = N.build_samples(frame, paths, [date(2020, 7, 20)], "shipment", date(2021, 1, 1))
    assert t.m[0][12:].sum() == 0 and t.m[0][:12].sum() > 0


def test_untrained_net_returns_the_engine_path(frame):
    paths = _paths(frame)
    s = N.build_samples(frame, paths, [date(2019, 3, 4)], "shipment", date(2020, 1, 1))
    pred = N.predict([N.make_net()], s, N.Scaler(s.stat))
    assert np.allclose(pred, s.eng[:, :, 0], atol=1e-6)


def test_two_stage_run_learns_and_scores_test_only(frame):
    """Short synthetic stages; the engine is biased +10 %, the net should learn it away."""
    stages = (
        N.Stage("s1", "shipment", date(2016, 1, 1), date(2017, 1, 1), date(2017, 4, 1),
                date(2017, 4, 1), date(2017, 10, 1)),
        N.Stage("s2", "delpro", date(2020, 9, 1), date(2021, 9, 1), date(2021, 12, 1),
                date(2021, 12, 1), date(2022, 6, 1)),
    )
    res = N.run_neural(frame, _paths(frame), seeds=(0,), max_epochs=60, patience=10, stages=stages)
    assert set(res.errors["stage"]) == {"s1", "s2"}
    for st in stages:  # scored periods lie inside the test part
        e = res.errors[res.errors["stage"] == st.name]
        assert (pd.to_datetime(e["period_start"]).dt.date >= st.test_start).all()
        assert (pd.to_datetime(e["period_end"]).dt.date <= st.test_end).all()
    models = set(res.errors["model"])
    assert {"neural", "neural_transfer", "neural_scratch", "milk_baseline", "persistence"} <= models
    s = res.summary
    s2 = s[(s["stage"] == "s2") & (s["grain"] == "weekly")].set_index(["horizon", "model"])["mae"]
    assert s2.loc[(1, "neural_transfer")] < s2.loc[(1, "milk_baseline")]
    assert set(res.counts["part"]) == {"train", "val", "test"}
    assert (res.fits["epochs"] >= 1).all()


def test_engine_paths_on_the_synthetic_herd():
    src = FakeHerdSource()
    p = N.engine_paths(src, [date(2019, 3, 4), date(2019, 3, 11)], EngineConfig(),
                       MilkConfig(k_mode="anchor_first"))
    assert set(p["run"]) == {date(2019, 3, 4), date(2019, 3, 11)}
    assert (p["litres"] > 0).all()
    assert (p.groupby("run").size() == N.ENGINE_H).all()
    assert p.groupby("run")["date"].min().tolist() == sorted(set(p["run"]))  # starts at its run


def test_cli_runs_end_to_end_on_the_synthetic_herd(tmp_path, monkeypatch, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    monkeypatch.setattr(cli, "_source", lambda args: FakeHerdSource())
    rc = cli.main(["neural", "--seeds", "1", "--epochs", "3", "--patience", "2", "--out", str(tmp_path)])
    assert rc == 0
    names = {p.name.split("_")[1] for p in tmp_path.iterdir()}
    assert {"engine", "errors", "summary", "fits", "counts", "weights"} <= names
    printed = capsys.readouterr().out
    assert "Test accuracy" in printed and "previously viewed" in printed


def _doc(origin: date) -> dict:
    """A tiny SYNTHETIC page document: milk at every grain, one herd row, recorded weeks."""
    from components.predictive_farm_intelligence.pfoi.outlook import period_starts
    from components.predictive_farm_intelligence.pfoi.periods import period_bounds

    rows = []
    starts = period_starts(origin)
    for grain, gm, hs in (("day", "daily", range(1, 15)), ("week", "weekly", range(1, 14)),
                          ("month", "monthly", range(1, 13))):
        for h in hs:
            s, e = period_bounds(starts[gm], gm, h)
            rows.append(dict(origin_date=origin.isoformat(), target_period=s.isoformat(), grain=grain,
                             horizon=h, series="milk_litres", forecast=1.0, lower=0.5, upper=2.0))
    rows.append(dict(origin_date=origin.isoformat(), target_period=origin.isoformat(), grain="month",
                     horizon=1, series="milking", forecast=30.0, lower=28.0, upper=32.0))
    weeks = [dict(series="milk_litres", grain="week", period=(origin - timedelta(days=7 * k)).isoformat(),
                  value=700.0 + k, scoreable=True) for k in range(2, 5)]
    return dict(origin_date=origin.isoformat(), model_version="pfoi-1.2.0-dev", outlook=rows,
                actuals=weeks, realised=[], corrections=[dict(series="milk_litres", grain="day")])


def test_neural_and_persistence_documents_replace_only_milk():
    from components.predictive_farm_intelligence.pfoi import neural_outlook as NO

    o = date(2023, 3, 1)
    path = pd.Series(100.0, index=[o + timedelta(days=h) for h in range(N.H)])
    doc = NO.neural_document(_doc(o), path)
    milk = pd.DataFrame([r for r in doc["outlook"] if r["series"] == "milk_litres"])
    assert set(milk.loc[milk["grain"] == "month", "horizon"]) == {1, 2, 3}  # path covers 3 months only
    assert (milk.loc[milk["grain"] == "day", "forecast"] == 100.0).all()
    assert (milk.loc[milk["grain"] == "week", "forecast"] == 700.0).all() and len(milk[milk["grain"] == "week"]) == 13
    assert milk.loc[(milk["grain"] == "month") & (milk["horizon"] == 1), "forecast"].item() == 3100.0
    assert any(r["series"] == "milking" and r["forecast"] == 30.0 for r in doc["outlook"])
    assert doc["model_version"] == NO.NEURAL_VERSION and not doc["corrections"]

    per = NO.persistence_document(_doc(o))
    pm = pd.DataFrame([r for r in per["outlook"] if r["series"] == "milk_litres"])
    # last complete week before the date = the one starting 14 days before (value 702)
    assert per["persistence"]["litres_per_day"] == pytest.approx(702.0 / 7)
    assert pm.loc[(pm["grain"] == "month") & (pm["horizon"] == 12), "forecast"].item() == pytest.approx(702.0 / 7 * 29)


def test_neural_outlook_command_writes_compare_ready_files(tmp_path):
    import json

    from components.predictive_farm_intelligence.pfoi import cli

    o = date(2023, 3, 1)
    src = tmp_path / "outlook" / "pfoi-1.2.0-dev"
    src.mkdir(parents=True)
    (src / "run_202303.json").write_text(json.dumps(_doc(o)))
    nd = tmp_path / "neural"
    nd.mkdir()
    pd.DataFrame(dict(stage="stage2_delpro", model="neural_transfer", origin=o,
                      date=[o + timedelta(days=h) for h in range(N.H)], litres=100.0)
                 ).to_csv(nd / "neural_paths_x.csv", index=False)
    assert cli.main(["neural-outlook", "--out", str(tmp_path), "--neural-dir", str(nd)]) == 0
    for v in ("pfoi-neural-dev", "persistence"):
        assert (tmp_path / "outlook" / v / "run_202303.json").exists()


def test_correction_is_bounded_even_for_absurd_inputs(frame):
    import torch

    paths = _paths(frame)
    s = N.build_samples(frame, paths, [date(2019, 3, 4)], "shipment", date(2020, 1, 1))
    net = N.make_net()
    for prm in net.parameters():  # a badly trained net: large random weights
        torch.nn.init.normal_(prm, std=5.0)
    scaler = N.Scaler(np.zeros((10, len(N.STATIC))))  # nearly constant training features
    s.stat[:] = 1e9
    pred = N.predict([net], s, scaler)
    assert np.abs(pred - s.eng[:, :, 0]).max() <= N.MAX_CORRECTION + 1e-6


def test_implausible_engine_level_is_left_out(frame):
    paths = _paths(frame, scale=50.0)  # engine 50x the recorded level
    s = N.build_samples(frame, paths, [date(2019, 3, 4)], "shipment", date(2020, 1, 1))
    assert s.eng[0, :, 1].sum() == 0 and s.stat[0, STATIC_IDX["engine_available"]] == 0
