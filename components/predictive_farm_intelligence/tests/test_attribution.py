"""Explanations on SYNTHETIC data: exact Shapley sums, flow balance, calving split."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.attribution import (
    MILK_FACTORS, calving_split, expected_mastitis, explain_forecast_milk, explain_past_milk,
    generation_composition, herd_flows, mastitis_rates, milk_shapley, mix_from_cowdays, shapley,
    yield_table,
)
from components.predictive_farm_intelligence.pfoi.herd_engine import (
    N_DIM_BIN, STATE_TO_STOCK, project,
)
from components.predictive_farm_intelligence.pfoi.lactation_curve import published_curve

from .synthetic import FakeHerdSource, synthetic_rates, synthetic_state

ORIGIN = date(2021, 1, 1)


def _mix(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    m = np.zeros((4, N_DIM_BIN, 4))
    m[:3, :40, :] = rng.uniform(0, 5, size=(3, 40, 4))
    return m


def test_shapley_sums_exactly_and_is_symmetric():
    # v(S) = (2 if a in S else 1) * (3 if b in S else 1): product of two equal-size changes
    def v(s):
        return (2 if "a" in s else 1) * (2 if "b" in s else 1)
    phi = shapley(v, ("a", "b"))
    assert sum(phi.values()) == pytest.approx(v({"a", "b"}) - v(set()))
    assert phi["a"] == pytest.approx(phi["b"])


def test_milk_shapley_sums_to_model_change():
    y = yield_table(published_curve())
    m0, m1 = _mix(1), _mix(2) * 1.1
    contrib, v0, v1 = milk_shapley(m0, 31, 0.9, m1, 30, 0.95, y)
    assert set(contrib) == set(MILK_FACTORS)
    assert sum(contrib.values()) == pytest.approx(v1 - v0, rel=1e-12, abs=1e-9)


def test_only_herd_size_changes():
    y = yield_table(published_curve())
    m0 = _mix(3)
    contrib, v0, v1 = milk_shapley(m0, 30, 1.0, 2 * m0, 30, 1.0, y)
    assert contrib["herd_size"] == pytest.approx(v1 - v0)
    for f in ("parity_mix", "stage_mix", "pregnancy_mix", "yield_level"):
        assert contrib[f] == pytest.approx(0.0, abs=1e-9)


def test_past_explanation_residual_closes_the_actual_change():
    src = FakeHerdSource()
    cd = src.milking_cowdays(date(2019, 1, 1), ORIGIN)
    months = sorted(set(cd["month"]))
    actual = pd.DataFrame({"litres_per_day": np.linspace(900, 1000, len(months)),
                           "source": "shipment"}, index=months)
    out = explain_past_milk(cd, actual, published_curve(), ORIGIN, months=6)
    for m, g in out.groupby("target_period"):
        c = g.set_index("factor")["contribution"]
        parts = c[list(MILK_FACTORS) + ["residual"]].sum()
        assert parts == pytest.approx(c["actual_change"])


def test_forecast_explanation_has_no_yield_level_change():
    state, rates = synthetic_state(ORIGIN), synthetic_rates()
    curve = published_curve()
    from components.predictive_farm_intelligence.pfoi.herd_engine import MilkCurveArrays
    arrays = MilkCurveArrays.from_yield(curve.yield_array(), curve.preg_multiplier(330))
    proj = project(state, rates, 120, milk_curve=arrays, record_milk_mix=True)
    dates = list(pd.to_datetime(proj.daily["date"]).dt.date)
    out = explain_forecast_milk(proj.milk_mix, dates, 1.0, curve, None, ORIGIN)
    assert len(out) and (out[out["factor"] == "yield_level"]["contribution"].abs() < 1e-9).all()
    # model value of each month equals k x curve litres from the engine
    jan = proj.milk_mix[:31].sum(axis=0)
    from components.predictive_farm_intelligence.pfoi.attribution import _parts, milk_per_day
    v = milk_per_day(*_parts(jan, 31, jan), 1.0, yield_table(curve))
    assert v == pytest.approx(proj.daily["curve_litres"].iloc[:31].mean(), rel=0.02)  # 10-day bins


def test_flows_explain_every_stock_change():
    state, rates = synthetic_state(ORIGIN), synthetic_rates()
    d = project(state, rates, 90).daily
    prev = state.state_totals()
    for i in range(len(d)):
        row = d.iloc[i]
        for st, col in STATE_TO_STOCK.items():
            net = sum(row[c] for c in d.columns if c.startswith(f"flow|{st}|"))
            assert row[col] - prev[st] == pytest.approx(net, abs=1e-9), (i, st)
            prev[st] = row[col]
    monthly = herd_flows(d, ORIGIN)
    assert set(monthly["target_period"]) == {date(2021, 1, 1), date(2021, 2, 1), date(2021, 3, 1)}


def test_calving_split_is_exact_and_rate_driven_starts_late():
    state, rates = synthetic_state(ORIGIN), synthetic_rates()
    split = calving_split(state, rates, 365, ORIGIN)
    total = project(state, rates, 365).daily
    total["month"] = [x.replace(day=1) for x in pd.to_datetime(total["date"]).dt.date]
    tm = total.groupby("month")["calvings"].sum()
    for m, g in split.groupby("target_period"):
        assert g["contribution"].sum() == pytest.approx(tm[m])
    rd = split[split["factor"] == "rate_driven"].set_index("target_period")["contribution"]
    assert rd[date(2021, 1, 1)] == pytest.approx(0.0, abs=1e-9)  # new conceptions need ~9 months
    assert (split["contribution"] >= -1e-9).all()


def test_mastitis_rates_are_labelled_and_leak_free():
    src = FakeHerdSource()
    health = src.health_months(date(2015, 8, 1), ORIGIN)
    md = pd.Series(1000.0, index=sorted(set(health["month"])))
    rates = mastitis_rates(health, md, ORIGIN)
    labels = [r[0] for r in rates]
    assert labels[0].startswith("last 12 months (2020-01 to 2020-12)")
    assert any(l.startswith("reference 2016-2018") for l in labels)
    assert mastitis_rates(health, md, date(2018, 6, 1))[-1][0].startswith("last 12")  # no reference yet
    d = pd.DataFrame({"date": pd.date_range("2021-01-01", "2021-01-31").date, "milking": 10.0})
    e = expected_mastitis(d, [("x", 0.01)], ORIGIN)
    assert e["contribution"].iloc[0] == pytest.approx(310 * 0.01)


def test_generation_composition_by_group():
    proj = project(synthetic_state(ORIGIN), synthetic_rates(), 62, record_cells=True)
    comp = generation_composition(proj.cells)
    assert {"calves", "heifers", "cows"} <= set(comp["group"])
    jan = comp[comp["month"] == date(2021, 1, 1)]
    assert jan["mean_animals"].sum() == pytest.approx(
        proj.daily.iloc[:31][["calves", "heifers_open", "heifers_pregnant", "milking", "dry_open",
                              "dry_pregnant"]].sum(axis=1).mean())


def test_mix_from_cowdays_round_trip():
    cd = FakeHerdSource().milking_cowdays(date(2020, 1, 1), date(2020, 3, 1))
    mixes = mix_from_cowdays(cd)
    for m, mix in mixes.items():
        assert mix.sum() == pytest.approx(cd[cd["month"] == m]["cow_days"].sum())


def test_first_forecast_month_has_no_step_when_nothing_changes():
    from components.predictive_farm_intelligence.pfoi.attribution import starting_mix
    from components.predictive_farm_intelligence.pfoi.herd_engine import MilkCurveArrays, OriginState
    from .test_herd_engine import _no_flows

    s = OriginState(origin=ORIGIN)
    s.milk_open[0, 0, 500] = 20.0  # late-lactation cows, no flows: the herd does not change
    curve = published_curve()
    arrays = MilkCurveArrays.from_yield(curve.yield_array(), curve.preg_multiplier(330))
    proj = project(s, _no_flows(), 31, milk_curve=arrays, record_milk_mix=True)
    dates = list(pd.to_datetime(proj.daily["date"]).dt.date)
    out = explain_forecast_milk(proj.milk_mix, dates, 1.0, curve, starting_mix(s, ORIGIN), ORIGIN)
    jan = out[out["target_period"] == date(2021, 1, 1)].set_index("factor")["contribution"]
    assert jan["herd_size"] == pytest.approx(0.0, abs=1e-9)  # no false step at the junction
