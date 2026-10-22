"""LSTM-attention specialist behind the 1.2.1-dev confidence flag, on SYNTHETIC data only (fictional
herd, no database)."""
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from components.predictive_farm_intelligence.pfoi.lstm_specialist import (  # noqa: E402
    GATED, H, LOOKBACK, MODEL, SEQ, STATIC, Daily, LSTMConfig, build_samples, confidence_switch, day_range,
    lstm_rows, lstm_rule, make_net, run_folds, run_lstm_specialist,
)

START, END = date(2015, 8, 1), date(2024, 1, 1)
FAST = LSTMConfig(seeds=(0,), max_epochs=4, patience=2, fold_years=(2019, 2020))


def _daily(step_from=None, factor=5.0):
    days = pd.date_range(START, END - timedelta(days=1))
    t = np.arange(len(days))
    ypc = 10.0 + 1.5 * np.sin(2 * np.pi * t / 365.25)  # fictional seasonal yield per cow
    litres = 400.0 * ypc
    if step_from is not None:
        litres = np.where(days.date >= step_from, litres * factor, litres)
    return pd.DataFrame(dict(date=days.date, milking=400.0, target_litres=litres, is_scoreable=True, data_gap=0,
                             identified_share=0.8,
                             target_source=np.where(days < "2022-08-01", "shipment", "delpro")))


def _base(daily, years=(2019, 2020)):
    s = pd.Series(daily["target_litres"].to_numpy(), index=pd.to_datetime(daily["date"]))
    rows = []
    for o in pd.date_range(f"{years[0]}-01-07", f"{years[-1]}-12-28", freq="W-MON"):
        for grain, h, step in (("daily", 1, 1), ("daily", 7, 1), ("daily", 14, 1), ("weekly", 1, 7),
                               ("weekly", 4, 7), ("weekly", 8, 7), ("weekly", 13, 7)):
            ps = o + pd.Timedelta(days=int((h - 1) * step))
            pe = ps + pd.Timedelta(days=int(step))
            act = float(s.loc[ps:pe - pd.Timedelta(days=1)].sum())
            rows.append(dict(origin=o.date(), grain=grain, horizon=h, period_start=ps.date(), period_end=pe.date(),
                             series="herd_milk", model="milk_baseline_adaptive", forecast=act * 1.15, actual=act))
    return pd.DataFrame(rows)


def test_windows_use_only_days_before_the_origin_and_mask_targets():
    dl = Daily.from_frame(_daily())
    o, end = date(2019, 3, 4), date(2019, 3, 20)
    a = build_samples(dl, [o], end)
    b = build_samples(Daily.from_frame(_daily(step_from=o, factor=1.5)), [o], end)  # every day from o x1.5
    assert a.seq.shape == (1, LOOKBACK, len(SEQ)) and a.stat.shape == (1, len(STATIC))
    np.testing.assert_allclose(a.seq, b.seq)
    np.testing.assert_allclose(a.stat, b.stat)
    assert a.m[0, :(end - o).days].all() and not a.m[0, (end - o).days:].any()
    assert np.allclose(b.y[0, :(end - o).days] - a.y[0, :(end - o).days], np.log(1.5))


def test_major_change_gets_more_loss_weight():
    dl = Daily.from_frame(_daily(step_from=date(2019, 3, 1), factor=0.7))
    calm = build_samples(dl, [date(2019, 1, 7)], None)
    shock = build_samples(dl, [date(2019, 3, 6)], None)
    assert calm.w[0] < 1.5 and shock.w[0] > 3.0
    assert shock.stat[0, STATIC.index("abs_change_7_28")] > 0.2


def test_net_attention_sums_to_one_and_output_is_bounded():
    net = make_net()
    seq = torch.randn(5, LOOKBACK, len(SEQ))
    out, a = net(seq, torch.randn(5, len(STATIC)))
    assert out.shape == (5, H) and a.shape == (5, LOOKBACK)
    assert torch.allclose(a.sum(dim=1), torch.ones(5), atol=1e-5)
    assert float(out.detach().abs().max()) <= 1.0


def test_fold_forecasts_ignore_data_after_the_fold_year_starts():
    """Same fold-2020 model either way: forecasts at origins before a x1.5 jump in mid-2020 stay identical."""
    jump = date(2020, 6, 1)
    origins = [date(2020, 1, 6), date(2020, 3, 2), date(2020, 5, 4)]
    cfg = replace(FAST, fold_years=(2020,))
    a = run_folds(Daily.from_frame(_daily()), origins, cfg)
    b = run_folds(Daily.from_frame(_daily(step_from=jump, factor=1.5)), origins, cfg)
    assert set(a.paths) == set(origins)
    for o in origins:
        assert a.paths[o][0] == pytest.approx(b.paths[o][0])
        np.testing.assert_allclose(a.paths[o][1], b.paths[o][1], atol=1e-6)
    assert a.attention["mean_attention"].groupby(a.attention["fold_year"]).sum().round(5).eq(1).all()


def test_learns_seasonal_shape_better_than_a_flat_level():
    cfg = LSTMConfig(seeds=(0,), max_epochs=40, patience=10, fold_years=(2019,))
    dl = Daily.from_frame(_daily())
    origins = day_range(date(2019, 1, 1), date(2019, 12, 1))[::7]
    res = run_folds(dl, origins, cfg)
    test = build_samples(dl, origins, date(2024, 1, 1))
    pred = np.stack([res.paths[o][1] for o in test.origin])
    mae_net = (np.abs(pred - test.y) * test.m).sum() / test.m.sum()
    mae_flat = (np.abs(test.y) * test.m).sum() / test.m.sum()
    assert mae_net < 0.8 * mae_flat


def test_rows_sum_the_daily_path_over_each_period():
    base = _base(_daily(), years=(2019,))
    o = base["origin"].iloc[0]
    paths = {o: (1000.0, np.zeros(H))}
    rows = lstm_rows(base, paths)
    assert set(rows["model"]) == {MODEL} and (rows["origin"] == o).all()
    w13 = rows[(rows["grain"] == "weekly") & (rows["horizon"] == 13)]
    assert w13["forecast"].iloc[0] == pytest.approx(7000.0)


def test_switch_only_where_confidence_is_low():
    base = _base(_daily(), years=(2019,))
    lstm = base.assign(model=MODEL, forecast=base["actual"])
    p = base[["grain", "horizon", "origin", "period_start"]].copy()
    p["p_logistic"] = np.where(pd.to_datetime(p["origin"]).dt.month >= 7, 0.8, 0.2)
    g = confidence_switch(base, lstm, p)
    low = pd.to_datetime(g["origin"]).dt.month >= 7
    assert g.loc[low, "switched"].all() and not g.loc[~low, "switched"].any()
    assert (g.loc[low, "forecast"] == g.loc[low, "actual"]).all()


def test_rule_includes_week_13():
    rows = []
    for g, h in (("daily", 1), ("daily", 7), ("daily", 14), ("weekly", 1), ("weekly", 4), ("weekly", 8),
                 ("monthly", 1), ("monthly", 3), ("weekly", 13)):
        rows += [dict(grain=g, horizon=h, model="b", within_10=0.5, n=50),
                 dict(grain=g, horizon=h, model=GATED, within_10=0.6 if h != 13 else 0.45, n=50)]
    hits = pd.DataFrame(rows)
    hits_y = hits.assign(year=2019)
    checks, keep = lstm_rule(hits, hits_y, "b")
    assert not keep and not checks.iloc[-1]["passed"]


def test_end_to_end_on_synthetic_data():
    d = _daily(step_from=date(2020, 4, 1), factor=0.6)
    base = _base(d)
    p = base[["grain", "horizon", "origin", "period_start"]].copy()
    p["p_logistic"] = np.where(pd.to_datetime(p["origin"]) >= pd.Timestamp("2020-04-01"), 0.9, 0.1)
    res = run_lstm_specialist(base, d, p, cfg=FAST)
    assert len(res.lstm) and res.gated["switched"].any()
    assert set(res.checks["check"]).issuperset({"week 13 falls <= 0.01"})
    assert res.fits["fold_year"].nunique() == 2
