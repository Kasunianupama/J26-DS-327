"""Synthetic-only tests for the PyTorch cow model (notebook 06).

PyTorch crashes on macOS in a process where LightGBM has trained, so these tests skip
themselves if LightGBM is already loaded. Run this file on its own:
    .venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_cow_torch.py
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.skipif("lightgbm" in sys.modules,
                                reason="run test_cow_torch.py in its own pytest process")


def _raw(start="2019-01-01", end="2020-12-31", cows=10):
    from components.predictive_farm_intelligence.tests.test_cow_accuracy import _dense_raw
    return _dense_raw(start=start, end=end, cows=cows)


def test_torch_models_fit_all_grains_without_lightgbm():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import score_models
    from components.predictive_farm_intelligence.pfoi.cow_torch import fit_torch_models

    m = fit_torch_models(_raw(), train_end=pd.Timestamp("2019-12-31").date(),
                         validation_end=pd.Timestamp("2019-12-31").date(),
                         params={"max_epochs": 5})
    assert "lightgbm" not in sys.modules
    assert {"torch_mlp_small", "torch_mlp_large", "torch_mlp_small_recal",
            "persistence_last_yield"} <= set(m.predictions)
    assert set(m.grain_predictions) == {"weekly", "monthly"}
    metrics, _ = score_models(m, blocks=("test",))
    assert set(metrics["status"]) == {"scored"}
    assert np.isfinite(metrics["accuracy_pct"]).all()


def test_torch_fit_can_limit_production_to_one_daily_architecture():
    from components.predictive_farm_intelligence.pfoi.cow_torch import fit_torch_models

    m = fit_torch_models(
        _raw(), train_end=pd.Timestamp("2019-12-31").date(),
        validation_end=pd.Timestamp("2019-12-31").date(),
        params={"max_epochs": 2, "min_epochs": 1},
        options={"ensemble": 1, "use_gru": False, "use_quantile": False},
        grains=("daily",), model_names=("torch_mlp_small",),
    )
    assert "torch_mlp_small_grp" in m.predictions
    assert "torch_mlp_large" not in m.predictions
    assert m.grain_predictions == {}


def test_torch_tuning_and_window_study_run():
    from components.predictive_farm_intelligence.pfoi.cow_runner import rolling_window_study
    from components.predictive_farm_intelligence.pfoi.cow_torch import (
        fit_torch_models, tune_torch,
    )
    from components.predictive_farm_intelligence.pfoi.cow_tuning import build_folds

    raw = _raw(start="2018-01-01", end="2020-12-31", cows=6)
    best, table = tune_torch(build_folds(raw, pd.Timestamp("2019-12-31").date()),
                             n_trials=2)
    assert table["setting"].tolist().count("default") == 1
    assert "hidden_large" in best
    metrics, cond = rolling_window_study(raw, None, exclude_gap=False, n_blocks=3,
                                         fit_fn=fit_torch_models,
                                         fit_kwargs={"params": {"max_epochs": 3}})
    assert metrics["window"].nunique() == 2
    assert "torch_mlp_large" in set(metrics["model"])
    assert "lightgbm" not in sys.modules


def test_training_never_stops_before_min_epochs_and_keeps_best_weights():
    from components.predictive_farm_intelligence.pfoi.cow_torch import train_net

    rng = np.random.default_rng(0)
    x = rng.normal(size=(3000, 8)).astype("float32")
    y = (0.05 * x[:, 0]).astype("float32")
    base = np.full(3000, 10.0)
    litres = base * np.exp(y)
    params = dict(dropout=0.3, lr=1e-3, weight_decay=1e-4, batch_size=512, max_epochs=70,
                  min_epochs=50, stop_drop_pp=0.5, stop_patience=15, lr_patience=5)
    _, info = train_net(x, y, np.arange(2700), np.arange(2700, 3000), (32, 16), params,
                        "cpu", base=base, litres=litres)
    assert info["epochs"] >= 50
    assert info["monitor"] == "accuracy_pct"
    assert info["best_monitor"] == max(info["history"])
    assert info["best_monitor"] > 95


def test_sequences_use_only_records_before_the_origin_and_partial_flag():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import prepare_accuracy_frame
    from components.predictive_farm_intelligence.pfoi.cow_torch import (
        _sequences, likely_partial_records,
    )
    raw = _raw(start="2019-01-01", end="2019-03-31", cows=3)
    f = prepare_accuracy_frame(raw, evaluation_mode="walk_forward", origin_grain="weekly")
    base = np.full(len(f), 10.0)
    seq = _sequences(f, base, 8)
    changed = f.copy()
    row = 40
    changed.loc[row, "litres"] = 17.0  # a later outcome
    seq2 = _sequences(changed, base, 8)
    later = (f["origin_date"] <= f.loc[row, "date"]).to_numpy()
    np.testing.assert_allclose(seq[later], seq2[later])
    assert (seq[:, :, 3] >= 0).all() and (seq[:, :, 3] <= 1).all()
    g = f.copy()
    g.loc[10, "litres"] = g.loc[10, "litres"] * 0.4
    assert likely_partial_records(g)[10]


def test_full_torch_fit_gives_ensemble_gru_quantile_and_intervals():
    from components.predictive_farm_intelligence.pfoi.cow_torch import (
        fit_torch_models, interval_coverage,
    )
    m = fit_torch_models(_raw(), train_end=pd.Timestamp("2019-12-31").date(),
                         validation_end=pd.Timestamp("2019-12-31").date(),
                         params={"max_epochs": 4, "min_epochs": 2},
                         options={"ensemble": 2, "seq_len": 6})
    assert {"kalman_state", "torch_gru", "torch_q50", "torch_gru_grp",
            "kalman_state_recal"} <= set(m.predictions)
    assert len(m.fitted["torch_mlp_small"]["members"]) == 2
    cov = interval_coverage(m)
    assert set(cov["grain"]) == {"daily", "weekly", "monthly"}
    assert cov["inside_10_90_pct"].between(0, 100).all()
    assert "lightgbm" not in sys.modules
