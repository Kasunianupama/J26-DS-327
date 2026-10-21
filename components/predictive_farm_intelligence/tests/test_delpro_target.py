"""DelPro-only milk target on SYNTHETIC data (no database)."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.backtest_milk import BASELINE, run_milk_backtest
from components.predictive_farm_intelligence.pfoi.delpro_target import (
    DelProFactory, DelProTargetSource, delpro_target, target_rule,
)
from components.predictive_farm_intelligence.tests.synthetic import FakeHerdSource


def _frame(n=120, start=date(2021, 1, 1)):
    days = [start + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(dict(date=days, milk_delpro_total=8000.0, milking=1000.0,
                             identified_share=0.8, data_gap=0))


def test_daily_rules_missing_low_share_implausible_gap_and_suspect_low():
    f = _frame()
    f.loc[10, "milk_delpro_total"] = 0.0          # no DelPro litres: no target
    f.loc[20, "identified_share"] = 0.1           # unverified
    f.loc[30, "milk_delpro_total"] = 25000.0      # 25 L per cow: implausible
    f.loc[40, "data_gap"] = 1                     # gap
    f.loc[50, "milk_delpro_total"] = 3000.0       # below half the recent mean: suspect low
    t = delpro_target(f).set_index("date")
    d = lambda i: date(2021, 1, 1) + timedelta(days=i)  # noqa: E731
    assert np.isnan(t.loc[d(10), "target_litres"]) and t.loc[d(10), "target_source"] is None
    for i in (10, 20, 30, 40, 50):
        assert not t.loc[d(i), "is_scoreable"], i
    assert t.loc[d(60), "is_scoreable"] and t.loc[d(60), "target_source"] == "delpro"
    assert t.loc[d(60), "target_litres"] == 8000.0
    # the first days have too little history for the suspect-low rule and stay scoreable
    assert t.loc[d(0), "is_scoreable"]


def test_scoreable_flags_use_only_earlier_days():
    a = delpro_target(_frame())
    f = _frame()
    f.loc[f.index >= 70, "milk_delpro_total"] = 30.0  # later collapse
    b = delpro_target(f)
    pd.testing.assert_series_equal(a.loc[:69, "is_scoreable"], b.loc[:69, "is_scoreable"])


class _DelProFake(FakeHerdSource):
    """Synthetic herd with DelPro litres from 2020-08 at 80 % of the recorded target."""

    def delpro_daily(self, start, end):
        t = FakeHerdSource.target_daily(self, start, end).copy()
        t["date"] = pd.to_datetime(t["date"]).dt.date
        on = np.array([x >= date(2020, 8, 1) for x in t["date"]])
        t["milk_delpro_total"] = np.where(on, 0.8 * t["target_litres"].fillna(0.0), 0.0)
        t["milking"] = 400.0
        t["identified_share"] = 0.9
        t["data_gap"] = 0
        return t[["date", "milk_delpro_total", "milking", "identified_share", "data_gap"]]


def test_wrapped_source_serves_delpro_target_and_delegates_the_rest():
    src = DelProTargetSource(_DelProFake())
    t = src.target_daily(date(2020, 7, 1), date(2020, 9, 1))
    assert set(t["target_source"].dropna()) == {"delpro"}
    assert t[pd.to_datetime(t["date"]) < "2020-08-01"]["target_litres"].isna().all()
    assert hasattr(src, "cells_on")  # everything else is the wrapped source
    assert isinstance(DelProFactory(_DelProFake)(), DelProTargetSource)


def test_backtest_on_delpro_target_scores_only_delpro_periods():
    src = DelProTargetSource(_DelProFake())
    res = run_milk_backtest(src, "monthly", origins=[date(2018, 3, 1), date(2021, 7, 1)])
    e = res.errors
    assert len(e) and set(e["source"]) == {"delpro"}
    assert (pd.to_datetime(e["period_start"]).dt.date >= date(2020, 8, 1)).all()
    assert set(e["origin"].astype(str)) == {"2021-07-01"}   # 2018 has no DelPro level: not forecast
    raw = FakeHerdSource().target_daily(date(2021, 7, 1), date(2021, 9, 1))
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    july = raw[(raw["date"] >= date(2021, 7, 1)) & (raw["date"] < date(2021, 8, 1))]["target_litres"].sum()
    first = e[(e["model"] == BASELINE) & (e["horizon"] == 1)]
    assert first["actual"].iloc[0] == pytest.approx(0.8 * july)


def test_target_rule_as_written():
    cells = (("weekly", 13), ("monthly", 6), ("monthly", 12))
    hits = pd.DataFrame([dict(grain=g, horizon=h, model=m, n=30, within_10=v)
                         for g, h in cells for m, v in (("record_target", 0.4), ("delpro_target", 0.5))])
    hits_y = pd.DataFrame([dict(grain=g, horizon=h, year=y, model=m, n=8, within_10=v)
                           for g, h in cells for y in (2021, 2022)
                           for m, v in (("record_target", 0.3), ("delpro_target", 0.35))])
    assert target_rule(hits, hits_y, "record_target", "delpro_target")[1]
    hits_y.loc[(hits_y["year"] == 2021) & (hits_y["model"] == "delpro_target"), "within_10"] = 0.29
    assert not target_rule(hits, hits_y, "record_target", "delpro_target")[1]


def test_backtest_and_compare_commands_end_to_end(tmp_path, monkeypatch, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    monkeypatch.setattr(cli, "_source", lambda args: _DelProFake())
    monkeypatch.setattr(cli, "_source_factory", lambda args: _DelProFake)
    rc = cli.main(["backtest-milk", "--grain", "monthly", "--every", "30", "--k", "anchor_first",
                   "--target", "delpro", "--out", str(tmp_path)])
    assert rc == 0
    files = list(tmp_path.glob("milk_backtest_errors_monthly_*_tdp.csv"))
    assert len(files) == 1
    e = pd.read_csv(files[0])
    assert set(e["target_definition"]) == {"delpro_only"} and set(e["source"]) == {"delpro"}
    assert cli.main(["backtest-milk", "--grain", "monthly", "--target", "delpro", "--block", "posthoc",
                     "--out", str(tmp_path)]) == 1  # development only

    # compare-target on two small synthetic file sets
    tag_dp = files[0].name.replace("milk_backtest_errors_monthly_", "").replace(".csv", "")
    base = e[e["model"] == BASELINE].assign(model="milk_baseline_adaptive")
    base.to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag_dp}.csv", index=False)
    base.assign(actual=base["actual"] / 0.8).to_csv(tmp_path / "milk_backtest_errors_monthly_rec.csv", index=False)
    fake = _DelProFake()

    class Src:
        def panel_daily(self, s, t):
            p = fake.target_daily(s, t)[["date"]].copy()
            p["milking"] = 400.0
            return p

        def target_daily(self, s, t):
            return FakeHerdSource.target_daily(fake, s, t).assign(identified_share=0.9)

        def delpro_daily(self, s, t):
            return fake.delpro_daily(s, t)

    monkeypatch.setattr(cli.SqlHerdSource, "from_env", classmethod(lambda cls: Src()))
    capsys.readouterr()
    rc = cli.main(["compare-target", "--tag-record", "rec", "--tag-delpro", tag_dp, "--out", str(tmp_path)])
    text = capsys.readouterr().out
    assert rc == 0 and "pre-registered rule" in text and "Verdict:" in text
