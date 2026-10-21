"""G2 specialists (Track A re-level + gate, Track B zero-shot yield) on SYNTHETIC data, no database
and no model download (a stand-in predictor replaces Chronos-2)."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.specialists import (
    TRACK_A_CELLS, contexts, fast_relevel, gated_switch, matched_hits, run_track_b, track_a_rule,
    track_b_rows, track_b_rule, weekly_path_forecasts, weekly_series,
)

START, END = date(2015, 8, 1), date(2024, 1, 1)
SHIFT = date(2021, 3, 1)  # synthetic yield jump (+20 %), fictional


def _daily(gap=None):
    days = pd.date_range(START, END - timedelta(days=1))
    ypc = np.where(days.date >= SHIFT, 12.0, 10.0)
    d = pd.DataFrame(dict(date=days.date, milking=400.0, target_litres=400.0 * ypc, is_scoreable=True,
                          data_gap=0, identified_share=0.8,
                          target_source=np.where(days < "2020-08-01", "shipment", "delpro")))
    if gap is not None:
        m = (d["date"] >= gap[0]) & (d["date"] < gap[1])
        d.loc[m, "target_litres"] = np.nan
        d.loc[m, "is_scoreable"] = False
        d.loc[m, "data_gap"] = 1
    return d


def _rows(daily, model="milk_baseline", level=4000.0):
    """Raw structural model that never learns the jump: forecast = 4000 L/day x days."""
    s = pd.Series(daily["target_litres"].to_numpy(), index=pd.to_datetime(daily["date"]))
    rows = []
    for o in pd.date_range("2017-01-02", "2023-10-02", freq="W-MON"):
        for grain, h, step in (("daily", 1, 1), ("daily", 7, 1), ("daily", 14, 1), ("weekly", 1, 7),
                               ("weekly", 4, 7), ("weekly", 13, 7)):
            ps = o + pd.Timedelta(days=(h - 1) * step)
            pe = ps + pd.Timedelta(days=step)
            act = float(s.loc[ps:pe - pd.Timedelta(days=1)].sum())
            rows.append(dict(origin=o.date(), grain=grain, horizon=h, period_start=ps.date(),
                             period_end=pe.date(), series="herd_milk", model=model,
                             forecast=level * step, actual=act))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- Track A

def test_relevel_follows_a_level_shift_within_two_weeks():
    raw = _rows(_daily())
    s1 = fast_relevel(raw)
    after = s1[pd.to_datetime(s1["origin"]) >= pd.Timestamp(SHIFT) + pd.Timedelta(days=21)]
    ape = (after["forecast"] - after["actual"]).abs() / after["actual"]
    assert ape.max() < 0.01  # raw is 17 % off after the jump
    raw_after = raw[pd.to_datetime(raw["origin"]) >= pd.Timestamp(SHIFT) + pd.Timedelta(days=21)]
    assert ((raw_after["forecast"] - raw_after["actual"]).abs() / raw_after["actual"]).min() > 0.15


def test_relevel_uses_only_finished_trusted_errors_before_the_origin():
    raw = _rows(_daily())
    origin = date(2021, 3, 8)
    a = fast_relevel(raw)
    raw2 = raw.copy()
    later = pd.to_datetime(raw2["period_end"]).dt.date > origin
    raw2.loc[later, "actual"] *= 2.0
    b = fast_relevel(raw2)
    fa = a[a["origin"] == origin].set_index(["grain", "horizon"])["forecast"]
    fb = b[b["origin"] == origin].set_index(["grain", "horizon"])["forecast"]
    pd.testing.assert_series_equal(fa, fb)
    # untrusted errors never set the level: with every period unverified there is no S1 forecast
    assert not len(fast_relevel(raw.assign(band="unverified")))


def test_gate_switches_only_track_a_cells_when_unstable_and_refuses_persistence():
    raw = _rows(_daily())
    base = raw.assign(model="milk_baseline_adaptive")
    s1 = fast_relevel(raw)
    probs = base[["origin", "grain", "horizon", "period_start"]].copy()
    probs["p_logistic"] = np.where(pd.to_datetime(probs["origin"]).dt.year == 2021, 0.9, 0.1)
    g = gated_switch(base, s1, probs)
    sw = g[g["switched"]]
    assert len(sw) and set(pd.to_datetime(sw["origin"]).dt.year) == {2021}
    assert set(zip(sw["grain"], sw["horizon"])) <= set(TRACK_A_CELLS)
    assert not g[(g["grain"] == "weekly") & (g["horizon"] == 13)]["switched"].any()
    with pytest.raises(ValueError):
        gated_switch(base, s1.assign(model="persistence"), probs)


def test_track_a_rule_as_written():
    hits = pd.DataFrame([dict(grain=g, horizon=h, model=m, n=50, within_10=v)
                         for g, h in TRACK_A_CELLS for m, v in (("old", 0.70), ("new", 0.73))])
    hits_y = pd.DataFrame([dict(grain=g, horizon=h, year=2019, model=m, n=10, within_10=v)
                           for g, h in TRACK_A_CELLS for m, v in (("old", 0.95), ("new", 0.945))])
    checks, keep = track_a_rule(hits, hits_y, "old", "new")
    assert keep
    hits.loc[(hits["model"] == "new") & (hits["horizon"] == 1) & (hits["grain"] == "daily"), "within_10"] = 0.68
    assert not track_a_rule(hits, hits_y, "old", "new")[1]


# --------------------------------------------------------------------------- Track B

def test_context_ends_before_the_origin_uses_current_source_and_keeps_gaps_missing():
    d = _daily(gap=(date(2021, 6, 1), date(2021, 7, 15)))
    wk = weekly_series(d)
    origin = date(2021, 9, 1)  # a Wednesday
    vals, last_week = contexts(wk, origin, "ypc")
    assert last_week + pd.Timedelta(days=6) < pd.Timestamp(origin)
    assert last_week + pd.Timedelta(days=13) >= pd.Timestamp(origin)  # the latest complete week
    assert np.isnan(vals).sum() >= 5          # the gap weeks are missing, not zero
    n_delpro_weeks = ((wk.index >= pd.Timestamp("2020-08-03")) & (wk.index + pd.Timedelta(days=6) < pd.Timestamp(origin))).sum()
    assert np.isfinite(vals).sum() <= n_delpro_weeks  # no value from the shipment source
    assert np.isnan(vals[0])                   # the week mixing both sources is missing
    d2 = d.copy()
    late = pd.to_datetime(d2["date"]).dt.date >= origin
    d2.loc[late, "target_litres"] *= 5
    vals2, _ = contexts(weekly_series(d2), origin, "ypc")
    np.testing.assert_array_equal(np.nan_to_num(vals, nan=-1), np.nan_to_num(vals2, nan=-1))


def test_forecast_is_engine_cows_times_forecast_yield_summed_over_days():
    d = _daily()
    wk = weekly_series(d)
    seen = {}

    def const(ctx, steps):
        seen["steps"] = steps
        return np.full((len(ctx), steps), 11.0)

    origin = date(2022, 3, 7)
    paths = weekly_path_forecasts(wk, [origin], "ypc", const)
    lit = weekly_path_forecasts(wk, [origin], "litres", const)
    base = pd.DataFrame([dict(origin=origin, grain="monthly", horizon=12, period_start=date(2023, 2, 1),
                              period_end=date(2023, 3, 1), series="herd_milk", model="milk_baseline_adaptive",
                              forecast=1.0, actual=28 * 4800.0)])
    herd = pd.DataFrame([dict(origin=origin, grain="monthly", horizon=12, period_start=date(2023, 2, 1),
                              period_end=date(2023, 3, 1), series="milking", model="herd_engine",
                              forecast=380.0, actual=400.0)])
    rows = track_b_rows(base, herd, paths, lit).set_index("model")["forecast"]
    assert rows["chronos2_ypc_x_engine"] == pytest.approx(380.0 * 11.0 * 28)
    assert rows["chronos2_milk"] == pytest.approx(11.0 * 28)
    assert seen["steps"] * 7 >= 400


def test_run_track_b_end_to_end_with_stand_in_model_and_rule():
    d = _daily()
    raw = _rows(d, model="milk_baseline_adaptive")
    herd = raw.assign(series="milking", model="herd_engine", forecast=400.0, actual=400.0)

    def last_value(ctx, steps):  # a naive stand-in: repeat the latest known week
        out = []
        for c in ctx:
            known = c[np.isfinite(c)]
            out.append(np.full(steps, known[-1]))
        return np.array(out)

    res = run_track_b(raw, herd, d, last_value)
    assert len(res.rows) and set(res.rows["model"]) == {"chronos2_ypc_x_engine", "chronos2_milk"}
    w13 = res.hits[(res.hits["grain"] == "weekly") & (res.hits["horizon"] == 13)].set_index("model")["within_10"]
    # the base never learns the jump; the yield path re-levels from the latest weeks
    assert w13["chronos2_ypc_x_engine"] > w13["milk_baseline_adaptive"]
    assert "persistence" not in set(res.rows["model"])
    assert {"check", "value", "passed"} <= set(res.checks.columns)
    assert set(res.coverage.columns) >= {"trusted_base", "issued"}


def test_track_b_rule_as_written():
    cells = (("weekly", 13), ("monthly", 6), ("monthly", 12))
    hits = pd.DataFrame([dict(grain=g, horizon=h, model=m, n=40, within_10=v)
                         for g, h in cells for m, v in (("old", 0.40), ("new", 0.45))])
    hits_y = pd.DataFrame([dict(grain=g, horizon=h, year=y, model=m, n=8, within_10=v)
                           for g, h in cells for y in (2020, 2021)
                           for m, v in (("old", 0.40), ("new", 0.42 if y == 2020 else 0.36))])
    assert track_b_rule(hits, hits_y, "old", "new")[1]
    hits_y.loc[(hits_y["model"] == "new") & (hits_y["year"] == 2021), "within_10"] = 0.30
    assert not track_b_rule(hits, hits_y, "old", "new")[1]


def test_matched_hits_scores_only_common_periods():
    a = _rows(_daily(), model="a")
    b = a[a["horizon"] != 13].assign(model="b")
    h = matched_hits({"a": a, "b": b})
    assert not ((h["grain"] == "weekly") & (h["horizon"] == 13)).any()


class _FakeSource:
    def __init__(self, d):
        self.d = d

    def target_daily(self, start, end):
        return self.d[["date", "target_source", "target_litres", "is_scoreable", "identified_share", "data_gap"]]

    def panel_daily(self, start, end):
        return self.d[["date", "milking"]]


def _write(frame, out, tag, prefix="milk"):
    monthly = frame["grain"] == "monthly"
    frame[monthly].to_csv(out / f"{prefix}_backtest_errors_monthly_{tag}.csv", index=False)
    frame[~monthly].to_csv(out / f"{prefix}_backtest_errors_weekly_{tag}.csv", index=False)


def test_specialist_commands_end_to_end_with_mocked_source(tmp_path, monkeypatch, capsys):
    from components.predictive_farm_intelligence.pfoi import cli, specialists

    d = _daily()
    raw = _rows(d)
    base = raw.assign(model="milk_baseline_adaptive")
    _write(base, tmp_path, "t_ad")
    _write(raw, tmp_path, "t")
    _write(raw.assign(series="milking", model="herd_engine", forecast=400.0, actual=400.0), tmp_path, "h", "herd")
    probs = base[["origin", "grain", "horizon", "period_start"]].copy()
    probs = probs[pd.to_datetime(probs["origin"]).dt.year >= 2019]
    probs["p_logistic"] = np.where(pd.to_datetime(probs["origin"]).dt.year == 2021, 0.9, 0.1)
    probs.to_csv(tmp_path / "gate_probs_t_ad_milk_baseline_adaptive.csv", index=False)
    monkeypatch.setattr(cli.SqlHerdSource, "from_env", classmethod(lambda cls: _FakeSource(d)))

    assert cli.main(["specialist-a", "--tag", "t_ad", "--raw-tag", "t", "--out", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "pre-registered Track A rule" in text and "Verdict:" in text
    assert (tmp_path / "milk_backtest_errors_weekly_t_ad_gs1.csv").exists()

    def stand_in(model_id="x", device="cpu"):
        return lambda ctx, steps: np.array([np.full(steps, c[np.isfinite(c)][-1]) for c in ctx])

    monkeypatch.setattr(specialists, "chronos2_predictor", stand_in)
    assert cli.main(["specialist-b", "--tag", "t_ad", "--herd-tag", "h", "--out", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "pre-registered Track B rule" in text and "Verdict:" in text
    written = pd.read_csv(tmp_path / "milk_backtest_errors_weekly_t_ad_chronos2.csv")
    assert {"chronos2_ypc_x_engine", "chronos2_milk"} <= set(written["model"])
    assert "persistence" not in set(written["model"])
