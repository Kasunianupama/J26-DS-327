"""Synthetic-only tests for notebook 08: notebook 06 per-cow predictions as a herd input.

Run on its own (PyTorch must not share a process with LightGBM on macOS):
    .venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_herd_cow_link.py
"""
from __future__ import annotations

import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import herd_cow_link as L
from components.predictive_farm_intelligence.pfoi import herd_torch as h

needs_torch = pytest.mark.skipif("lightgbm" in sys.modules,
                                 reason="run test_herd_cow_link.py in its own pytest process")


def test_prediction_blocks_are_disjoint_and_ordered():
    blocks = L.prediction_blocks([pd.Timestamp("2021-03-01"), pd.Timestamp("2021-01-01"),
                                  pd.Timestamp("2021-03-01")], date(2021, 6, 30))
    assert blocks == [(date(2021, 1, 1), date(2021, 3, 1)), (date(2021, 3, 1), date(2021, 6, 30))]


def _daily():
    return h.exclude_gap(h.synthetic_herd_daily(7), h.gap_for("clean"))


@needs_torch
def test_cow_predictions_only_after_their_training_end():
    from components.predictive_farm_intelligence.pfoi.cow_runner import synthetic_inputs

    raw, ev = synthetic_inputs(n_cows=20, seed=3)
    raw = raw[pd.to_datetime(raw["date"]) <= pd.Timestamp("2021-06-30")]
    cuts = [pd.Timestamp("2020-12-31"), pd.Timestamp("2021-03-31")]
    fk = {**L.LIGHT_COW_FIT, "params": {"max_epochs": 2, "min_epochs": 1}, "device": "cpu"}
    tab = L.cow_herd_predictions(raw, ev, cuts, date(2021, 6, 30), L.NB06_FARM_X_WINNERS, fk,
                                 min_cows=3)
    assert set(tab["grain"]) == {"daily", "weekly", "monthly"}
    assert (pd.to_datetime(tab["period_start"]) > pd.to_datetime(tab["train_end"])).all()
    assert not tab.duplicated(["grain", "period_start"]).any()
    assert not {"animal", "cow_id", "animal_key"} & set(tab.columns)
    s = L.cow_prediction_summary(tab)
    assert set(s["block"]) == {"block_2", "block_3"}
    series = L.cow_pred_series(tab)
    assert (series["monthly"].index.day == 1).all()
    assert (series["weekly"].index.weekday == 0).all()


@needs_torch
def test_herd_models_with_cow_input_add_candidates_on_common_periods():
    d = _daily()
    split = h.chronological_split(pd.Series(d.index[d["ok"]]), (0.75, 0.05, 0.20))
    days = d.index[d.index > pd.Timestamp("2021-01-01")]
    cow = {"daily": pd.Series(9.0, index=days),
           "weekly": pd.Series(9.0, index=days[days.weekday == 0]),
           "monthly": pd.Series(9.0, index=days[days.day == 1])}
    m = h.fit_herd_models(d, split.train_end, split.validation_end,
                          params={"max_epochs": 2, "min_epochs": 1},
                          options={"ensemble": 1, "use_gru": False, "use_quantile": False},
                          min_coverage=0.8, cow_preds=cow)
    for name in ("cow06_structural", "torch_mlp_cow06", "cow06_structural_recal"):
        assert "daily" in m.predictions[name], name
    meta = m.tables["daily"]
    expect = 9.0 * meta["milking_projected"].to_numpy()
    got = m.predictions["cow06_structural"]["daily"]
    have = meta["period_start"].to_numpy() > np.datetime64("2021-01-01")
    assert np.allclose(got[have], expect[have]) and np.isnan(got[~have]).all()
    s = h.score_herd(m, ("validation",))
    assert (s.groupby("grain")["periods"].nunique() == 1).all()
    # Without cow input nothing new appears.
    m0 = h.fit_herd_models(d, split.train_end, split.validation_end,
                           params={"max_epochs": 2, "min_epochs": 1},
                           options={"ensemble": 1, "use_gru": False, "use_quantile": False},
                           min_coverage=0.8)
    assert not any(k.startswith(("cow06", "torch_mlp_cow06")) for k in m0.predictions)


def test_pooling_uses_only_parts_where_every_candidate_exists():
    def part(name, models, acc):
        return pd.DataFrame({"block": name, "grain": "daily", "model": models, "periods": 10,
                             "actual_sum": 1000.0, "abs_err_sum": [10 * (100 - a) for a in acc],
                             "within_10pct": 90.0})
    full = part("validation", ["a", "b"], [95, 96])
    partial = part("window_1", ["a"], [80])   # b missing here: this part is left out
    pooled = h.pool_common_parts([full, partial]).set_index("model")
    assert pooled.loc["a", "parts"] == 1 and np.isclose(pooled.loc["a", "accuracy_pct"], 95)
    assert pooled.index[0] == "b"
