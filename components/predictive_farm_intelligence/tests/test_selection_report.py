"""Selection reports use synthetic saved forecasts only; no database."""
from datetime import date

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import selection_report as report
from components.predictive_farm_intelligence.pfoi.scorecard import prepare


def candidate(model="milk_baseline", error=5.0):
    origins = pd.date_range("2017-01-01", "2023-12-01", freq="MS")
    return pd.DataFrame({
        "origin": origins.date, "period_start": origins.date,
        "period_end": (origins + pd.offsets.MonthBegin(1)).date,
        "grain": "monthly", "series": "herd_milk", "horizon": 1,
        "model": model, "actual": 100.0, "forecast": 100.0 + error,
        "error": error,
    })


def test_loader_ignores_test_files_and_deduplicates_benchmarks(tmp_path):
    bench = candidate("persistence", 10)
    for tag in ("w12", "w36"):
        f = pd.concat([candidate(), bench], ignore_index=True)
        f.to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}.csv", index=False)
    # Would fail to parse if the loader attempted to inspect the final-test file.
    (tmp_path / "milk_backtest_errors_monthly_w12_test.csv").write_text("excluded")
    cands, benchmarks = report.load_saved(tmp_path, "milk")
    assert len(cands) == 2
    assert len(benchmarks) == 84
    assert set(benchmarks["model"]) == {"persistence"}


def test_loader_refuses_non_development_dates(tmp_path):
    f = candidate()
    f.loc[0, "period_end"] = date(2024, 1, 2)
    f.to_csv(tmp_path / "milk_backtest_errors_monthly_w12.csv", index=False)
    with pytest.raises(ValueError, match="Non-development"):
        report.load_saved(tmp_path, "milk")


@pytest.mark.parametrize("method", ["empirical", "aci"])
def test_nested_scorecard_keeps_candidate_history_and_real_benchmarks(monkeypatch, method):
    monkeypatch.setattr(report, "default_objectives", lambda series: [("herd_milk", "monthly", 1)])
    a, b = candidate(), candidate(error=20)
    benchmarks = candidate("persistence", 10)
    nested, ranking, card, recovery = report.evaluate({"A": a, "B": b}, benchmarks, "milk", method)
    row = card.iloc[0]
    assert nested.folds.loc[nested.folds["selected"], "candidate"].eq("A").all()
    assert ranking.loc[ranking["selected"], "candidate"].tolist() == ["A"]
    assert ranking.iloc[0]["inner_score"] == pytest.approx(.05)
    assert row["n"] == 60
    assert row["accuracy"] == pytest.approx(.95)
    assert row["skill"] == pytest.approx(.5)
    assert row["bias_pct"] == pytest.approx(.05)
    # Pre-2019 candidate errors must remain available for the first outer intervals.
    expected = prepare(a, method=method)
    expected = expected[expected["origin"] >= date(2019, 1, 1)]
    assert row["n_coverage"] == expected["covered90"].notna().sum()
    assert row["coverage90"] == pytest.approx(expected["covered90"].mean())
    assert not recovery.empty


def test_report_refuses_missing_objective_coverage():
    with pytest.raises(ValueError, match="zero coverage"):
        report.evaluate({"A": candidate(), "B": candidate(error=10)},
                        candidate("persistence"), "milk", "empirical")


def test_conflicting_benchmark_copies_are_refused(tmp_path):
    for tag, error in (("w12", 10), ("w36", 20)):
        f = pd.concat([candidate(), candidate("persistence", error)], ignore_index=True)
        f.to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}.csv", index=False)
    with pytest.raises(ValueError, match="Conflicting benchmark"):
        report.load_saved(tmp_path, "milk")


def test_quality_filtering_keeps_ranking_but_excludes_unverified_periods(monkeypatch):
    monkeypatch.setattr(report, "default_objectives", lambda series: [("herd_milk", "monthly", 1)])
    days = pd.date_range("2015-08-01", "2023-12-31", freq="D")
    quality = pd.DataFrame({
        "date": days.date, "target_source": "delpro", "identified_share": .9,
        "gap": False, "target_litres": 100.0, "milking": 10.0,
        "litres_per_cow": 10.0,
    })
    quality.loc[days.year == 2020, "identified_share"] = .1
    cands = {"A": candidate(), "B": candidate(error=20)}
    benchmarks = candidate("persistence", 10)
    _, original, unfiltered, _ = report.evaluate(cands, benchmarks, "milk", "aci")
    _, ranking, filtered, _ = report.evaluate(cands, benchmarks, "milk", "aci", quality)
    pd.testing.assert_frame_equal(original, ranking)
    assert unfiltered.iloc[0]["n"] == 60
    assert filtered.iloc[0]["n"] == 48
    winner, fixed = report.fixed_scorecard(cands, benchmarks, ranking, "milk", "aci", quality)
    assert winner == "A"
    assert fixed.iloc[0]["n"] == 48


def test_quality_loader_uses_mocked_source_and_development_bounds(monkeypatch):
    from components.predictive_farm_intelligence.pfoi.data import DATA_START, SqlHerdSource

    calls = []
    class FakeQualitySource:
        def target_daily(self, start, end):
            calls.append(("target", start, end))
            return pd.DataFrame({"date": [date(2020, 1, 1)], "target_source": ["delpro"],
                                 "target_litres": [100.0], "identified_share": [.9], "data_gap": [0]})

        def panel_daily(self, start, end):
            calls.append(("panel", start, end))
            return pd.DataFrame({"date": [date(2020, 1, 1)], "milking": [10.0]})

    monkeypatch.setattr(SqlHerdSource, "from_env", staticmethod(lambda: FakeQualitySource()))
    quality = report.load_quality()
    assert calls == [("target", DATA_START, report.CUTOFF), ("panel", DATA_START, report.CUTOFF)]
    assert quality["litres_per_cow"].mean() == 10.0
