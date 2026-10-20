"""Rate estimation and starting-herd construction on SYNTHETIC aggregates."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs
from components.predictive_farm_intelligence.pfoi.origin_state import build_origin_state
from components.predictive_farm_intelligence.pfoi.rates import (
    eb_shrink, estimate_rates, hazard_from_counts, rate_summary,
)

from .synthetic import FakeHerdSource

ORIGIN = date(2020, 1, 1)


def test_eb_shrink_keeps_large_cells_and_pulls_small_ones():
    events = np.array([500.0, 100.0, 1.0])
    exposure = np.array([50_000.0, 50_000.0, 10.0])
    out = eb_shrink(events, exposure)
    pooled = events.sum() / exposure.sum()
    assert out[0] == pytest.approx(0.01, rel=0.05)
    assert out[1] == pytest.approx(0.002, rel=0.05)
    assert abs(out[2] - pooled) < abs(0.1 - pooled)  # raw 0.1 pulled toward pooled


def test_eb_shrink_zero_exposure_gets_pooled_rate():
    out = eb_shrink(np.array([10.0, 0.0]), np.array([1000.0, 0.0]))
    assert out[1] == pytest.approx(0.01)


def test_hazard_from_counts_delta():
    counts = np.zeros(10)
    counts[6] = 5
    h = hazard_from_counts(counts, smooth_days=1)
    assert h[6] == pytest.approx(1.0)
    assert h[:6].sum() == 0


def test_estimate_rates_on_synthetic_source():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    r = estimate_rates(inputs.rate_inputs)
    assert r.calf_to_heifer == pytest.approx((1 / 365) / 0.75, rel=1e-6)  # per female calf-day
    assert r.conc_heifer == pytest.approx(1 / 120, rel=1e-6)
    months = set(inputs.rate_inputs.transitions["month"])
    tr, pm = inputs.rate_inputs.transitions, inputs.rate_inputs.panel
    factor = pm[pm["month"].isin(months)]["sales"].sum() / tr[tr["to_state"] == "sold"]["n_moved"].sum()
    assert r.exit["milking"]["sales"] == pytest.approx(0.0003 * factor, rel=1e-6)  # calibrated
    assert 0 < r.abortion < 0.01
    assert r.births_per_calving == pytest.approx(0.5)
    assert r.conc_cow[:, 0].max() == 0.0  # no conceptions in the first 60 days
    assert 270 < rate_summary(r).set_index("rate").loc["mean_gestation_days", "value"] < 290
    assert not any(n.startswith("exits") for n in r.notes)


def test_missing_transitions_fall_back_and_are_noted():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    ri = inputs.rate_inputs
    ri.transitions = ri.transitions.iloc[0:0]
    r = estimate_rates(ri)
    assert any(n.startswith("exits") for n in r.notes)
    assert any(n.startswith("calf_to_heifer") for n in r.notes)
    days = ri.exposure["animal_days"].sum()
    assert r.exit["calf"]["deaths"] == pytest.approx(ri.panel["deaths"].sum() / days)


def test_origin_state_totals_equal_day_cell_totals():
    src = FakeHerdSource()
    inputs = load_origin_inputs(src, ORIGIN, EngineConfig())
    cells = src.cells_on(date(2019, 12, 31))
    want = cells.groupby("state")["n"].sum()
    got = inputs.state.state_totals()
    for state, n in want.items():
        assert got[state] == pytest.approx(n)


def test_origin_state_splits_milking_pregnancy_from_clock():
    cells = pd.DataFrame([("milking", "2", "151-305", "1", 10.0)],
                         columns=["state", "parity_group", "dim_band", "generation_group", "n"])
    clock = pd.DataFrame({"parity_group": ["2", "2"], "generation_group": ["1", "1"],
                          "dim": [200, 220], "gest": [np.nan, 100.0], "n": [1.0, 3.0]})
    empty = pd.DataFrame(columns=["parity_group", "generation_group", "gest", "n"])
    s, notes = build_origin_state(ORIGIN, cells, clock, empty,
                                  pd.DataFrame(columns=["generation_group", "gest", "n"]))
    assert s.milk_open.sum() == pytest.approx(2.5)
    assert s.milk_preg.sum() == pytest.approx(7.5)
    assert s.milk_preg[1, 1, 12, 100] == pytest.approx(7.5)  # conceived at DIM 120
    assert notes == []


def test_origin_state_uniform_fallback_is_noted():
    cells = pd.DataFrame([("heifer_pregnant", "0", "na", "0", 6.0)],
                         columns=["state", "parity_group", "dim_band", "generation_group", "n"])
    empty_m = pd.DataFrame(columns=["parity_group", "generation_group", "dim", "gest", "n"])
    empty_d = pd.DataFrame(columns=["parity_group", "generation_group", "gest", "n"])
    empty_h = pd.DataFrame(columns=["generation_group", "gest", "n"])
    s, notes = build_origin_state(ORIGIN, cells, empty_m, empty_d, empty_h)
    assert s.heifer_preg.sum() == pytest.approx(6.0)
    assert any("heifer_pregnant" in n for n in notes)


def test_stale_conceptions_are_not_live_pregnancies():
    cells = pd.DataFrame([("milking", "2", "305+", "1", 4.0), ("dry_pregnant", "2", "na", "1", 6.0)],
                         columns=["state", "parity_group", "dim_band", "generation_group", "n"])
    mclock = pd.DataFrame({"parity_group": ["2", "2"], "generation_group": ["1", "1"],
                           "dim": [450, 400], "gest": [380.0, 120.0], "n": [1.0, 1.0]})
    dclock = pd.DataFrame({"parity_group": ["2", "2"], "generation_group": ["1", "1"],
                           "gest": [420.0, 250.0], "n": [5.0, 1.0]})
    hclock = pd.DataFrame(columns=["generation_group", "gest", "n"])
    s, notes = build_origin_state(ORIGIN, cells, mclock, dclock, hclock)
    assert s.milk_open.sum() == pytest.approx(2.0)  # the 380-day "pregnancy" is open
    assert s.milk_preg[:, :, :, 300:].sum() == 0
    assert s.dry_preg[1, 1, 250] == pytest.approx(6.0)  # shape uses live pregnancies only
    assert sum("older than" in n for n in notes) == 2


def test_unconfirmed_recent_service_is_pregnant_with_conception_probability():
    cells = pd.DataFrame([("milking", "1", "61-150", "0", 10.0)],
                         columns=["state", "parity_group", "dim_band", "generation_group", "n"])
    clock = pd.DataFrame({"parity_group": ["1"], "generation_group": ["0"], "dim": [90],
                          "gest": [np.nan], "recent_ai_gest": [20.0], "n": [1.0]})
    empty_d = pd.DataFrame(columns=["parity_group", "generation_group", "gest", "n"])
    empty_h = pd.DataFrame(columns=["generation_group", "gest", "n"])
    s, _ = build_origin_state(ORIGIN, cells, clock, empty_d, empty_h, conception_per_ai=0.3)
    assert s.milk_preg.sum() == pytest.approx(3.0)
    assert s.milk_preg[0, 0, 7, 20] == pytest.approx(3.0)  # conceived at DIM 70
    assert s.milk_open[0, 0, 90] == pytest.approx(7.0)
    s0, _ = build_origin_state(ORIGIN, cells, clock, empty_d, empty_h)
    assert s0.milk_preg.sum() == 0  # without a conception probability: all open


def test_conception_per_ai_and_live_gestation_cap():
    from components.predictive_farm_intelligence.pfoi.rates import (
        conception_per_ai, max_live_gestation,
    )
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    p = conception_per_ai(inputs.rate_inputs)
    assert 0.05 <= p <= 0.9
    gest = pd.DataFrame({"gest": np.arange(270, 300), "n": np.ones(30)})
    assert max_live_gestation(gest) == 299
    assert max_live_gestation(gest.head(5)) == 300  # too few records: default


def test_extra_pregnancy_loss_from_transitions():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    ri = inputs.rate_inputs
    base = estimate_rates(ri)
    assert base.heifer_loss == 0.0
    months = sorted(set(ri.transitions["month"]))
    extra = pd.DataFrame({"month": months, "from_state": "heifer_pregnant",
                          "to_state": "heifer_open", "n_moved": 5.0})
    ri.transitions = pd.concat([ri.transitions, extra], ignore_index=True)
    r = estimate_rates(ri)
    e = ri.exposure
    days = e[(e["state"] == "heifer_pregnant") & e["month"].isin(months)]["animal_days"].sum()
    assert r.heifer_loss == pytest.approx(5.0 * len(months) / days - r.abortion)


def test_one_off_purchases_are_not_projected_forward():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    ri = inputs.rate_inputs
    ri.panel["external_entries"] = 0.0
    ri.panel.loc[ri.panel.index[0], "external_entries"] = 120.0  # one restocking month
    assert estimate_rates(ri).entry_per_day == 0.0


def test_calf_split_keeps_measured_totals():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    ri = inputs.rate_inputs
    r = estimate_rates(ri)
    months = set(ri.transitions["month"])
    e = ri.exposure
    calf_days = e[(e["state"] == "calf") & e["month"].isin(months)]["animal_days"].sum()
    days = {"female": calf_days * 0.75, "male": calf_days * 0.25}  # 6000 vs 2000 young days
    tr = ri.transitions
    died = tr[(tr["from_state"] == "calf") & (tr["to_state"] == "dead")]["n_moved"].sum()
    model_died = sum(r.calf_exit_by_sex[x]["deaths"] * days[x] for x in days)
    assert model_died == pytest.approx(died)  # total calf deaths preserved
    assert r.calf_exit_by_sex["male"]["deaths"] / r.calf_exit_by_sex["female"]["deaths"] == \
        pytest.approx((8 / 2) * 3)  # 80% of young deaths are male, males have 1/3 the days
    assert r.female_share == pytest.approx(0.52)
    assert r.calf_to_bull == 0.0  # no calf -> bull moves in the synthetic data


def test_calf_split_falls_back_without_sex_data():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    ri = inputs.rate_inputs
    ri.young_days = ri.young_days.iloc[0:0]
    r = estimate_rates(ri)
    assert r.calf_exit_by_sex is None and r.female_share == 1.0
    assert r.calf_to_heifer == pytest.approx(1 / 365, rel=1e-6)
    assert any(n.startswith("calves") for n in r.notes)


def test_starting_calves_split_by_sex():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    calf = inputs.state.calf
    total = calf.sum()
    assert calf[1, 0] / calf[:, 0].sum() == pytest.approx(0.25)  # gen 0: 3 of 12 male
    assert calf[1, 1] == pytest.approx(0.0)  # gen 1: only females
    assert total == pytest.approx(inputs.state.state_totals()["calf"])


def test_exit_calibration_matches_panel_totals():
    inputs = load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig())
    ri = inputs.rate_inputs
    months = set(ri.transitions["month"])
    pm = ri.panel[ri.panel["month"].isin(months)]
    tr = ri.transitions
    got = {k: tr[tr["to_state"] == v]["n_moved"].sum()
           for k, v in (("deaths", "dead"), ("culls", "culled"), ("sales", "sold"))}
    # make the panel show more culls and more deaths than the transition table
    ri.panel.loc[ri.panel["month"].isin(months), "culls"] *= 2 * got["culls"] / pm["culls"].sum()
    ri.panel.loc[ri.panel["month"].isin(months), "deaths"] *= (got["deaths"] + 10) / pm["deaths"].sum()
    base = estimate_rates(load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig()).rate_inputs)
    r = estimate_rates(ri)
    assert r.exit["milking"]["culls"] / base.exit["milking"]["culls"] == pytest.approx(
        2.0 / (pm["culls"].sum() / got["culls"]), rel=1e-6)
    assert r.early_deaths_per_calving == pytest.approx(10 / pm["calvings"].sum())
    assert r.exit["milking"]["deaths"] == pytest.approx(base.exit["milking"]["deaths"])
    assert any(n.startswith("exit calibration") for n in r.notes)
