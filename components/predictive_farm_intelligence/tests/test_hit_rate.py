"""Hit rate (pfoi/hit_rate.py) on SYNTHETIC error tables."""
from datetime import date

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.hit_rate import hit_rates, table


def _errors(pcts, model="m", band="normal", grain="weekly", horizon=1):
    return pd.DataFrame(dict(block="development", grain=grain, horizon=horizon, model=model, band=band,
                             actual=100.0, forecast=[100.0 * (1 + p) for p in pcts]))


def test_shares_within_thresholds_and_target_flag():
    e = _errors([0.0, 0.04, -0.05, 0.07, -0.09, 0.10, 0.2, -0.3, 0.01, 0.02])
    r = hit_rates(e).iloc[0]
    assert r["n"] == 10
    assert r["within_5"] == pytest.approx(0.5)   # 0, 4, -5, 1, 2 %
    assert r["within_10"] == pytest.approx(0.8)  # plus 7, -9, 10 %
    assert r["wape"] == pytest.approx(sum(abs(p) for p in
                                          [0, .04, .05, .07, .09, .10, .2, .3, .01, .02]) / 10)
    assert not r["meets_target"]
    assert hit_rates(_errors([0.01] * 9 + [0.5])).iloc[0]["meets_target"]  # 90 % within


def test_unverified_periods_are_reported_separately():
    e = pd.concat([_errors([0.0] * 4), _errors([0.5] * 6, band="unverified"),
                   _errors([0.5], band="gap")])
    r = hit_rates(e).set_index("trust")
    assert r.loc["trusted", "within_10"] == 1.0 and r.loc["trusted", "n"] == 4
    assert r.loc["unverified_or_gap", "n"] == 7


def test_no_band_column_scores_everything_and_zero_actuals_are_skipped():
    e = _errors([0.0, 0.2]).drop(columns="band")
    e.loc[len(e)] = dict(block="development", grain="weekly", horizon=1, model="m", actual=0.0, forecast=5.0)
    r = hit_rates(e).iloc[0]
    assert r["trust"] == "all" and r["n"] == 2


def test_table_orders_grains_and_puts_models_in_columns():
    e = pd.concat([_errors([0.0], model="a", grain="monthly", horizon=3),
                   _errors([0.2], model="b", grain="daily", horizon=7),
                   _errors([0.0], model="a", grain="daily", horizon=1)])
    t = table(hit_rates(e))
    assert list(t.index) == [("daily", 1), ("daily", 7), ("monthly", 3)]
    assert {"a", "b", "n"} <= set(t.columns)


def test_cli_with_explicit_files(tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    f = tmp_path / "errs.csv"
    _errors([0.0, 0.03, 0.2]).assign(series="herd_milk").to_csv(f, index=False)
    assert cli.main(["hit-rate", "--files", str(f), "--quality", "off", "--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "share within +-10 %" in printed and "Target: 85%" in printed
