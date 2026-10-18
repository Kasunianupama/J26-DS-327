"""Herd engine on a SYNTHETIC herd: conservation, non-negativity, timing, generation."""
from datetime import date, timedelta

import numpy as np
import pytest

from components.predictive_farm_intelligence.pfoi.categories import (
    EXIT_TYPES, GENERATIONS, STATES,
)
from components.predictive_farm_intelligence.pfoi.herd_engine import (
    N_GEST, OriginState, project, step_day,
)

from .synthetic import synthetic_rates, synthetic_state

ORIGIN = date(2020, 1, 1)


def _no_flows(**overrides):
    calve = np.zeros(N_GEST)
    base = dict(
        exit={s: {k: 0.0 for k in EXIT_TYPES} for s in STATES},
        calf_to_heifer=0.0, conc_heifer=0.0, conc_dry=0.0,
        conc_cow=np.zeros((4, 4)), dry_open_cow=np.zeros(4),
        dry_preg_by_gest=np.zeros(N_GEST), calve_by_gest=calve, abortion=0.0,
        births_per_calving=0.0, ai_open=0.0, entry_per_day=0.0,
    )
    base.update(overrides)
    return synthetic_rates(**base)


def test_conservation_every_day():
    s0 = synthetic_state(ORIGIN)
    proj = project(s0, synthetic_rates(), 500)
    d = proj.daily
    prev = np.concatenate([[s0.total()], d["n_herd"].to_numpy()[:-1]])
    expected = prev - d["exits"] + d["births"] + d["external_entries"]
    np.testing.assert_allclose(d["n_herd"], expected, rtol=0, atol=1e-9)
    assert (d["exits"] - d[list(EXIT_TYPES)].sum(axis=1)).abs().max() < 1e-12


def test_no_negative_counts_with_extreme_rates():
    calve = np.full(N_GEST, 0.9)
    rates = synthetic_rates(
        exit={s: {k: 0.6 for k in EXIT_TYPES} for s in STATES},  # sums to 1.8, gets capped
        calf_to_heifer=1.0, conc_heifer=1.0, conc_dry=1.0,
        conc_cow=np.ones((4, 4)), dry_open_cow=np.ones(4),
        dry_preg_by_gest=np.ones(N_GEST), calve_by_gest=calve, abortion=1.0,
        births_per_calving=2.0, ai_open=5.0, entry_per_day=3.0,
    )
    s = synthetic_state(ORIGIN).copy()
    for _ in range(60):
        step_day(s, rates)
        for name in ("calf", "heifer_open", "heifer_preg", "milk_open", "milk_preg",
                     "dry_open", "dry_preg"):
            assert getattr(s, name).min() >= -1e-12, name
        assert s.bull >= 0 and s.unknown >= 0


def test_scheduled_calving_lands_on_expected_day():
    s = OriginState(origin=ORIGIN)
    s.heifer_preg[0, 270] = 10.0  # known conception: gestation day 270 on the day before origin
    calve = np.zeros(N_GEST)
    calve[280] = 1.0
    proj = project(s, _no_flows(calve_by_gest=calve), 30)
    d = proj.daily.set_index("date")
    expected_day = ORIGIN + timedelta(days=9)  # clock 271 on the origin, 280 nine days later
    assert d.loc[expected_day, "calvings"] == pytest.approx(10.0)
    assert d["calvings"].sum() == pytest.approx(10.0)
    assert d.loc[expected_day, "milking"] == pytest.approx(10.0)
    assert proj.final_state.milk_open[0].sum() == pytest.approx(10.0)  # parity "1"


@pytest.mark.parametrize("dam_gen, calf_gen", [("0", "1"), ("1", "2"), ("2", "3+"), ("3+", "3+"),
                                               ("unknown", "unknown")])
def test_calf_generation_is_dam_plus_one(dam_gen, calf_gen):
    s = OriginState(origin=ORIGIN)
    s.dry_preg[1, GENERATIONS.index(dam_gen), 279] = 4.0
    calve = np.zeros(N_GEST)
    calve[280] = 1.0
    proj = project(s, _no_flows(calve_by_gest=calve, births_per_calving=0.5), 3)
    calves = proj.final_state.calf.sum(0)
    assert calves[GENERATIONS.index(calf_gen)] == pytest.approx(2.0)
    assert calves.sum() == pytest.approx(2.0)
    # the dam (parity "2") moves to parity "3+", keeping her generation
    assert proj.final_state.milk_open[2, GENERATIONS.index(dam_gen)].sum() == pytest.approx(4.0)


def test_dim_moves_between_bands():
    s = OriginState(origin=ORIGIN)
    s.milk_open[0, 0, 55] = 5.0
    proj = project(s, _no_flows(), 10, record_cells=True)
    last = proj.cells[proj.cells["date"] == proj.cells["date"].max()]
    milk = last[last["state"] == "milking"].set_index("dim_band")["n"]
    assert milk.get("61-150", 0.0) == pytest.approx(5.0)
    assert milk.get("0-60", 0.0) == pytest.approx(0.0)


def test_abortion_returns_to_open_and_counts():
    s = OriginState(origin=ORIGIN)
    s.milk_preg[0, 0, 5, 40] = 10.0
    proj = project(s, _no_flows(abortion=0.5), 1)
    fs = proj.final_state
    assert proj.daily["real_abortions"].iloc[0] == pytest.approx(5.0)
    assert fs.milk_open.sum() == pytest.approx(5.0)
    assert fs.milk_preg.sum() == pytest.approx(5.0)
    # aborted cow keeps her DIM: bin 5 (~55) + gestation 41
    assert fs.milk_open[0, 0, 96] == pytest.approx(5.0)


def test_cells_match_state_totals():
    s = synthetic_state(ORIGIN)
    cells = s.cells()
    by_state = cells.groupby("state")["n"].sum()
    for state, total in s.state_totals().items():
        assert by_state.get(state, 0.0) == pytest.approx(total)


def test_projection_is_deterministic():
    a = project(synthetic_state(ORIGIN), synthetic_rates(), 120).daily
    b = project(synthetic_state(ORIGIN), synthetic_rates(), 120).daily
    assert a.equals(b)


def test_project_does_not_modify_start_state():
    s = synthetic_state(ORIGIN)
    before = s.total()
    project(s, synthetic_rates(), 50)
    assert s.total() == pytest.approx(before)


def test_extra_heifer_loss_is_not_an_abortion():
    s = OriginState(origin=ORIGIN)
    s.heifer_preg[0, 100] = 10.0
    proj = project(s, _no_flows(heifer_loss=0.1), 1)
    d = proj.daily.iloc[0]
    assert d["pregnancy_losses"] == pytest.approx(1.0)
    assert d["real_abortions"] == 0
    assert proj.final_state.heifer_open[0] == pytest.approx(1.0)


def test_calf_split_by_sex():
    s = OriginState(origin=ORIGIN)
    s.calf[0, 0] = 10.0  # female
    s.calf[1, 0] = 10.0  # male
    s.dry_preg[1, 0, 279] = 4.0
    calve = np.zeros(N_GEST)
    calve[280] = 1.0
    rates = _no_flows(
        calve_by_gest=calve, births_per_calving=1.0, female_share=0.25,
        calf_to_heifer=0.1, calf_to_bull=0.05,
        calf_exit_by_sex={"female": {"deaths": 0.0, "culls": 0.0, "sales": 0.0},
                          "male": {"deaths": 0.2, "culls": 0.0, "sales": 0.1}},
    )
    proj = project(s, rates, 1)
    fs, d = proj.final_state, proj.daily.iloc[0]
    # males: 10 * 0.7 survive exits; 3 newborn males (generation 1) join; then 5% of
    # all male calves become bulls. Females: none exit, 1 newborn joins, 10% -> heifer.
    assert fs.calf[1, 0] == pytest.approx(10 * 0.7 * 0.95)
    assert fs.calf[1, 1] == pytest.approx(3 * 0.95)
    assert fs.bull == pytest.approx((7 + 3) * 0.05)
    assert fs.calf[0, 0] == pytest.approx(9.0) and fs.calf[0, 1] == pytest.approx(0.9)
    assert fs.heifer_open.sum() == pytest.approx(1.1)
    assert d["deaths"] == pytest.approx(2.0) and d["sales"] == pytest.approx(1.0)
    assert d["calves_female"] + d["calves_male"] == pytest.approx(d["calves"])


def test_early_calf_deaths_count_as_births_and_deaths_only():
    s = OriginState(origin=ORIGIN)
    s.dry_preg[1, 0, 279] = 10.0
    calve = np.zeros(N_GEST)
    calve[280] = 1.0
    proj = project(s, _no_flows(calve_by_gest=calve, births_per_calving=1.0,
                                early_deaths_per_calving=0.2), 1)
    d = proj.daily.iloc[0]
    assert d["births"] == pytest.approx(10.0)
    assert d["deaths"] == pytest.approx(2.0) and d["exits"] == pytest.approx(2.0)
    assert d["calves"] == pytest.approx(8.0)
    assert d["n_herd"] == pytest.approx(10.0 - 2.0 + 10.0)  # conservation holds
