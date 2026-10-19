"""Aggregate report checks using fictional forecasts only."""
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.error_diagnostics import (
    benchmark_pairs, grouped, load_tag, main, metrics, paired_counts,
)


def sample():
    dates = pd.date_range("2022-01-01", periods=12, freq="MS")
    return pd.DataFrame(dict(origin=dates, period_start=dates,
                             period_end=dates + pd.offsets.MonthBegin(1),
                             grain="monthly", horizon=1, series="herd_milk",
                             model="milk_baseline_adaptive", actual=100., forecast=120.))


def test_errors_against_actuals():
    m = metrics(sample())
    assert m["mae"] == 20
    assert m["wape_pct"] == 20
    assert m["bias_pct"] == 20
    assert m["n"] == 12
    f = sample()
    f.loc[0, "actual"] = 0
    assert metrics(f)["positive_actual_n"] == 11


def test_pairwise_missing_coverage_and_matching():
    f = sample()
    b = f.iloc[:4].assign(model="ets", forecast=105.)
    report = benchmark_pairs(f, b)
    ets = report[report.comparison == "ets"]
    assert ets.n.tolist() == [4, 4]
    assert ets.missing_pair.tolist() == [8, 8]
    assert ets.mae.tolist() == [20., 5.]
    assert report[report.comparison == "sarima"].n.eq(0).all()
    b.loc[b.index[0], "actual"] = 999
    with pytest.raises(ValueError, match="actuals disagree"):
        benchmark_pairs(f, b)


def test_cow_association_uses_raw_engine_and_matched_dates():
    f = sample()
    h = f.assign(series="milking", model="herd_engine", actual=10., forecast=12.)
    corrected = h.assign(model="herd_engine_corrected", forecast=100.)
    result = paired_counts(f, pd.concat([h, corrected]))
    assert result.iloc[0].matched_n == 12
    assert result.iloc[0].cow_mae == 2
    assert result.iloc[0].mean_cow_error_pct == pytest.approx(20)


def test_user_command_synthetic_only(tmp_path, capsys):
    for family in ("milk", "herd"):
        for grain in ("monthly", "weekly"):
            f = sample().assign(grain=grain)
            if family == "herd":
                f = f.assign(series="milking", model="herd_engine", actual=10., forecast=12.)
            f.to_csv(tmp_path / f"{family}_backtest_errors_{grain}_synthetic.csv", index=False)
    assert main(["--tag", "synthetic", "--herd-tag", "synthetic", "--out", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "errors by target year" in text
    assert "before any break" in text
    assert "2022-01-01" not in text  # aggregate tables only, no individual periods
    assert len(list(tmp_path.iterdir())) == 4  # no generated files


def test_reject_test_and_future(tmp_path):
    with pytest.raises(ValueError, match="development tag"):
        load_tag(tmp_path, "milk", "synthetic_test")
    for grain in ("monthly", "weekly"):
        f = sample().assign(grain=grain)
        f.loc[0, "period_end"] = pd.Timestamp("2024-02-01")
        f.to_csv(tmp_path / f"milk_backtest_errors_{grain}_synthetic.csv", index=False)
    with pytest.raises(ValueError, match="Development"):
        load_tag(tmp_path, "milk", "synthetic")
