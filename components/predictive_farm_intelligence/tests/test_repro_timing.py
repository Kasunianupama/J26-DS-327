"""M7 (docs/pp1_plan.md): reproductive timing with censoring and competing exits, and the
within-band conception shape of the engine. SYNTHETIC data only."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs
from components.predictive_farm_intelligence.pfoi.freeze import (
    config_hash, v11_config_hash, version_label,
)
from components.predictive_farm_intelligence.pfoi.herd_engine import project
from components.predictive_farm_intelligence.pfoi.rates import (
    conception_dim_shape, estimate_rates,
)
from components.predictive_farm_intelligence.pfoi.repro_timing import (
    aalen_johansen, compare_engine, engine_conception_cif, pregnancy_outcomes, repro_table,
    step_summary,
)

from .synthetic import FakeHerdSource

ORIGIN = date(2021, 10, 1)


def _counts(rows):
    return pd.DataFrame(rows, columns=["day", "status", "n"])


def test_aalen_johansen_by_hand():
    aj = aalen_johansen(_counts([(50, "event", 4), (60, "left_herd", 2), (70, "censored", 4)]), 100)
    assert aj.loc[50, "cif_event"] == pytest.approx(0.4)
    assert aj.loc[60, "cif_left"] == pytest.approx(0.2)
    assert aj.loc[100, "cif_event"] == pytest.approx(0.4)  # censoring is not a failure
    assert aj.loc[100, "survival"] == pytest.approx(0.4)


def test_censored_cows_are_not_counted_as_failures():
    """6 cows still open at day 30, 4 conceive at day 50: all cows still at risk conceived."""
    aj = aalen_johansen(_counts([(30, "censored", 6), (50, "event", 4)]), 100)
    assert aj.loc[50, "cif_event"] == pytest.approx(1.0)  # naive 4 / 10 would say 0.4


def test_step_summary_and_outcomes():
    s = step_summary(_counts([(40, "event", 5), (80, "event", 5), (90, "censored", 10)]))
    assert s["n"] == 20 and s["median_days"] == 80 and s["censored_share"] == pytest.approx(0.5)
    assert s["by_60d"] == pytest.approx(0.25) and s["by_100d"] == pytest.approx(0.5)
    o = pregnancy_outcomes(pd.DataFrame({"status": ["calved", "lost", "censored"], "n": [8.0, 1.0, 1.0]}))
    assert o["calved_share"] == pytest.approx(0.8) and o["lost_share"] == pytest.approx(0.1)
    # pending pregnancies are not failures: shares over known outcomes
    assert o["n_resolved"] == 9 and o["calved_of_resolved"] == pytest.approx(8 / 9)
    assert o["lost_of_resolved"] == pytest.approx(1 / 9)


def test_repro_table_has_every_step_per_group():
    t = repro_table(FakeHerdSource().repro_steps(ORIGIN), ("period", "parity_group"))
    assert set(t["step"]) == {"first_ai", "conception", "calving_interval", "pregnancy"}
    assert len(t) == 3 * 3 * 4
    assert "animal_key" not in t.columns


def test_engine_cif_constant_hazard():
    class R:
        conc_cow = np.full((4, 4), 0.01)
        conc_dim_shape = None
        exit = {"milking": {"deaths": 0.0}, "dry_open": {"deaths": 0.0}}
        dry_open_cow = np.zeros(4)
        conc_dry = 0.0
    eng = engine_conception_cif(R(), "2", 100)
    assert eng.loc[99, "cif_event"] == pytest.approx(1 - 0.99 ** 100)


# ------------------------------------------------------------------ within-band shape

def test_shape_keeps_each_band_rate_and_the_waiting_period():
    co = FakeHerdSource().cow_open_dim(date(2020, 1, 1), ORIGIN)
    shape = conception_dim_shape(co)
    assert shape[:40].max() == 0.0  # no conceptions before 40 days in the synthetic record
    bins = co.assign(lo=co["dim_band"].astype(int))
    for lo, hi in ((0, 60), (61, 150), (151, 305)):
        days = np.zeros(1000)
        for r in bins.itertuples():
            a, b = r.lo, (r.lo + 9 if r.lo < 400 else 999)
            days[a:b + 1] = r.open_days / (b - a + 1)
        seg = slice(lo, hi + 1)
        assert np.average(shape[seg], weights=days[seg]) == pytest.approx(1.0)


def test_sparse_band_stays_flat():
    co = pd.DataFrame({"dim_band": ["0", "10", "400"], "open_days": [100.0, 100.0, 100.0],
                       "conceptions": [1.0, 2.0, 1.0]})
    assert np.allclose(conception_dim_shape(co), 1.0)


def test_engine_option_changes_only_cow_conception_timing():
    src = FakeHerdSource()
    flat = EngineConfig()
    shaped = EngineConfig(conception_dim_shape=True)
    r0 = estimate_rates(load_origin_inputs(src, ORIGIN, flat).rate_inputs, flat)
    inputs = load_origin_inputs(src, ORIGIN, shaped)
    r1 = estimate_rates(inputs.rate_inputs, shaped)
    assert r0.conc_dim_shape is None and r1.conc_dim_shape is not None
    assert np.array_equal(r0.conc_cow, r1.conc_cow)
    a = project(inputs.state, r0, 120).daily
    b = project(inputs.state, r1, 120).daily
    assert a["n_herd"].to_numpy() == pytest.approx(b["n_herd"].to_numpy())  # nobody created or lost
    assert not np.allclose(a["milking"], b["milking"]) or not np.allclose(a["dry_offs"], b["dry_offs"]) \
        or not np.allclose(a["calvings"], b["calvings"])  # timing moves something
    assert config_hash() == "3cbd28787fcb" and v11_config_hash() == "2a865a0c2687"
    assert version_label(shaped).startswith("experiment-")


def test_compare_engine_reports_both_curves():
    src = FakeHerdSource()
    r = estimate_rates(load_origin_inputs(src, ORIGIN, EngineConfig()).rate_inputs, EngineConfig())
    c = compare_engine(src.repro_steps(ORIGIN), r, "2")
    assert {"recorded_conceived", "engine_conceived", "recorded_left", "engine_left"} <= set(c.columns)
    assert (c["recorded_conceived"].diff().dropna() >= 0).all()


def test_command_runs_on_synthetic_data(monkeypatch, tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli, data

    monkeypatch.setattr(data.SqlHerdSource, "from_env", classmethod(lambda cls, **kw: FakeHerdSource()))
    rc = cli.main(["repro-timing", "--asof", "2021-10-01", "--out", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "censored, not failures" in out and "engine" in out
    assert len(list((tmp_path / "repro").iterdir())) == 3
