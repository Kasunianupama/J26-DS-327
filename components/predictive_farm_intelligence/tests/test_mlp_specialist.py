"""Synthetic-only tests for the simple herd/health/milk MLP."""
from datetime import date, timedelta

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from components.predictive_farm_intelligence.pfoi.mlp_specialist import (  # noqa: E402
    FEATURES, MLPConfig, SequenceScaler, fit, make_net, predict,
)
from components.predictive_farm_intelligence.pfoi.tcn_specialist import (  # noqa: E402
    CELLS, LOOKBACK, SEQ, STATIC, Samples,
)


def _samples(n: int = 192, seed: int = 7) -> tuple[Samples, np.ndarray]:
    """Fictional regimes: herd/milk collapse plus high recorded mastitis lowers the target."""
    rng = np.random.default_rng(seed)
    seq = rng.normal(0.0, 0.03, (n, LOOKBACK, len(SEQ)))
    changed = np.arange(n) % 2 == 1
    recent = slice(-21, None)
    seq[changed, recent, 0] -= 0.9   # milk level
    seq[changed, recent, 2] -= 0.3   # milk change
    seq[changed, recent, 3] -= 0.2   # yield per cow
    seq[changed, recent, 4] -= 0.8   # milking cows
    seq[changed, recent, 5] -= 1.0   # total herd
    seq[changed, recent, 10] += 1.5  # mastitis rate
    seq[:, :, 11] = 1.0              # health is recorded
    y = np.where(changed[:, None], -0.50, 0.0) * np.ones((n, len(CELLS)))
    origins = np.asarray([date(2018, 1, 1) + timedelta(days=i) for i in range(n)], dtype=object)
    samples = Samples(origins, seq, np.zeros((n, len(STATIC))), y,
                      np.ones_like(y), np.ones(n), changed.astype(float))
    return samples, changed


def _take(samples: Samples, index: np.ndarray) -> Samples:
    return Samples(*(getattr(samples, name)[index]
                     for name in ("origin", "seq", "stat", "y", "m", "w", "shock")))


def test_mlp_uses_only_requested_herd_health_and_milk_features():
    assert FEATURES == ("log_milk_rel", "log_milk_change", "log_ypc_rel", "log_milking_rel",
                        "log_herd_rel", "mastitis_rate", "health_recorded")
    net = make_net(MLPConfig(hidden=(16, 8), seeds=(0,)))
    out = net(torch.zeros(3, LOOKBACK, len(FEATURES)))
    assert out.shape == (3, len(CELLS))


def test_mlp_learns_a_fictional_herd_milk_and_mastitis_regime():
    samples, changed = _samples()
    train_i, val_i = np.arange(144), np.arange(144, 192)
    train, val = _take(samples, train_i), _take(samples, val_i)
    cfg = MLPConfig(hidden=(32, 16), dropout=0.0, lr=3e-3, batch=32,
                    max_epochs=60, patience=10, seeds=(0,), device="cpu")
    torch.manual_seed(0)
    net = make_net(cfg)
    scaler = SequenceScaler(train.seq)
    fit(net, train, val, scaler, 0, cfg)
    forecast = predict([net], val, scaler)[:, 0]
    val_changed = changed[val_i]
    assert forecast[val_changed].mean() < forecast[~val_changed].mean() - 0.25
