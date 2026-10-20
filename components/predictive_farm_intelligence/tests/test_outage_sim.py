"""M2 (docs/pp1_plan.md): simulated milk-recording outages, on SYNTHETIC data only."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.backtest_milk import BASELINE, run_milk_backtest
from components.predictive_farm_intelligence.pfoi.milk_baseline import (
    WITHHELD_NO_TRUSTED_DAYS, MilkConfig,
)
from components.predictive_farm_intelligence.pfoi.outage_sim import (
    PERSISTENCE, mask_target, outage_cost, record_freshness, run_outage_sim, scenarios,
    staleness_table, status_table, summarise,
)

from .synthetic import FakeHerdSource

FIRST = MilkConfig(k_mode="anchor_first")
ORIGINS = [date(2021, 10, 4), date(2021, 11, 1)]


class SpikedSource(FakeHerdSource):
    """Recorded milk multiplied by 10 inside [start, end): only visible if it leaks."""

    def __init__(self, start: date, end: date, **kw):
        super().__init__(**kw)
        self.window = (start, end)

    def target_daily(self, start, end):
        t = super().target_daily(start, end).copy()
        inside = (t["date"] >= self.window[0]) & (t["date"] < self.window[1])
        t.loc[inside, "target_litres"] = t.loc[inside, "target_litres"] * 10
        return t


def test_scenarios_start_with_the_normal_case():
    s = scenarios((28, 90), (0, 7))
    assert s[0] == (0, 0) and len(s) == 5 and (90, 7) in s


def test_mask_hides_exactly_the_outage_window():
    t = FakeHerdSource().target_daily(date(2021, 1, 1), date(2022, 1, 1))
    origin = date(2021, 10, 4)
    m = mask_target(t, origin, gap=28, resumed=7)
    d = pd.to_datetime(m["date"]).dt.date
    hidden = ~m["is_scoreable"].astype(bool)
    lo, hi = origin - timedelta(days=35), origin - timedelta(days=7)
    assert set(d[hidden]) == {lo + timedelta(days=i) for i in range((hi - lo).days)}
    assert m.loc[hidden, "target_litres"].isna().all()
    assert t["is_scoreable"].astype(bool).loc[hidden].all()  # input left unchanged
    assert mask_target(t, origin, 0, 0).equals(t)


def test_record_freshness():
    t = FakeHerdSource().target_daily(date(2021, 1, 1), date(2022, 1, 1))
    origin = date(2021, 10, 4)
    assert record_freshness(t, origin) == (1.0, 28)
    assert record_freshness(mask_target(t, origin, 90, 0), origin) == (91.0, 0)
    assert record_freshness(mask_target(t, origin, 90, 3), origin) == (1.0, 3)


def test_normal_scenario_matches_the_milk_backtest():
    src = FakeHerdSource()
    sim = run_outage_sim(src, "weekly", milk_cfg=FIRST, origins=ORIGINS, scen=[(0, 0)])
    bt = run_milk_backtest(src, "weekly", milk_cfg=FIRST, origins=ORIGINS).errors
    keys = ["origin", "grain", "horizon", "model"]
    a = sim.errors[sim.errors["model"].isin([BASELINE, PERSISTENCE])].set_index(keys)["forecast"]
    b = bt[bt["model"].isin([BASELINE, PERSISTENCE])].set_index(keys)["forecast"]
    assert len(a) and a.sort_index().to_numpy() == pytest.approx(b.loc[a.index].sort_index().to_numpy())


def test_hidden_days_never_reach_the_forecast():
    origin = date(2021, 10, 4)
    window = (origin - timedelta(days=97), origin - timedelta(days=7))
    scen = [(90, 7)]
    clean = run_outage_sim(FakeHerdSource(), "weekly", milk_cfg=FIRST, origins=[origin], scen=scen)
    spiked = run_outage_sim(SpikedSource(*window), "weekly", milk_cfg=FIRST, origins=[origin], scen=scen)
    for res in (clean, spiked):
        assert set(res.status["outcome"]) == {"forecast"}
    a = clean.errors.set_index(["grain", "horizon", "model"])["forecast"].sort_index()
    b = spiked.errors.set_index(["grain", "horizon", "model"])["forecast"].sort_index()
    assert a.to_numpy() == pytest.approx(b.to_numpy())


def test_actuals_are_the_recorded_ones_in_every_scenario():
    res = run_outage_sim(FakeHerdSource(), "weekly", milk_cfg=FIRST, origins=ORIGINS[:1],
                         scen=[(0, 0), (90, 0), (180, 14)])
    per = res.errors.groupby(["grain", "horizon", "period_start"])["actual"].nunique()
    assert (per == 1).all()


def test_long_ongoing_outage_is_withheld_and_counted():
    origin = date(2021, 10, 4)
    res = run_outage_sim(FakeHerdSource(), "weekly", milk_cfg=FIRST, origins=[origin],
                         scen=[(0, 0), (500, 0), (500, 14)])
    out = dict(zip(zip(res.status["gap_days"], res.status["resumed_days"]), res.status["outcome"]))
    assert out[(500, 0)] == f"withheld ({WITHHELD_NO_TRUSTED_DAYS})"
    assert out[(500, 14)] == "forecast" and out[(0, 0)] == "forecast"
    assert BASELINE not in set(res.errors[res.errors["gap_days"] == 500]
                               .query("resumed_days == 0")["model"])
    st = status_table(res.status)
    assert st["origins"].sum() == 3


def test_summaries_are_aggregates_only():
    res = run_outage_sim(FakeHerdSource(), "weekly", milk_cfg=FIRST, origins=ORIGINS,
                         scen=[(0, 0), (28, 0), (90, 7)])
    s = summarise(res.errors)
    assert {"n", "mae", "bias", "wape_pct"} <= set(s.columns)
    c = outage_cost(res.errors)
    normal = c[c["gap_days"] == 0]
    assert np.allclose(normal["ratio_to_no_outage"], 1.0)
    assert {"ratio_to_persistence", "n"} <= set(c.columns)
    st = staleness_table(res.errors)
    assert {"stale_band", "n", "sd", "q05", "q95"} <= set(st.columns)


def test_refuses_the_test_block():
    with pytest.raises(ValueError):
        run_outage_sim(FakeHerdSource(), "weekly", origins=[date(2024, 2, 5)])


def test_command_prints_aggregates_and_writes_tables(monkeypatch, tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import data, outage_sim

    monkeypatch.setattr(data.SqlHerdSource, "from_env",
                        classmethod(lambda cls, **kw: FakeHerdSource()))
    rc = outage_sim.main(["--preset", "pfoi-1.0", "--every", "120", "--gaps", "90",
                          "--resumed", "0", "7", "--out", str(tmp_path)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "outage cost" in printed and "Only milk records are hidden" in printed
    files = sorted(p.name for p in (tmp_path / "outage_sim").iterdir())
    assert len(files) == 4 and all(f.startswith("outage_") for f in files)
