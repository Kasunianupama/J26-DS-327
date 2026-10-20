"""Scorecard on SYNTHETIC error tables: metrics, best benchmark, verdicts, targets doc."""
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.scorecard import (
    COUNT_SERIES, MIN_PERIODS, TARGETS, confirm, poisson_deviance, scorecard, with_intervals,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "targets.md"


def _months(n: int, start: date = date(2017, 1, 1)) -> list[date]:
    out, y, m = [], start.year, start.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _rows(series, model, actual, forecast, horizon=1, grain="monthly", origins=None, block=None):
    origins = origins or _months(len(actual))
    rows = []
    for o, a, f in zip(origins, actual, forecast):
        end = _months(2, o)[1]
        rows.append(dict(origin=o, grain=grain, horizon=horizon, period_start=o, period_end=end,
                         series=series, model=model, forecast=float(f), actual=float(a)))
    df = pd.DataFrame(rows)
    df["error"] = df["forecast"] - df["actual"]
    if block:
        df["block"] = block
    return df


def _one(card, **kw):
    sel = card
    for k, v in kw.items():
        sel = sel[sel[k] == v]
    assert len(sel) == 1
    return sel.iloc[0]


def test_accuracy_is_one_minus_wape_and_bias_is_relative():
    actual = np.full(24, 100.0)
    forecast = np.r_[np.full(12, 110.0), np.full(12, 96.0)]
    card = scorecard(_rows("herd_milk", "milk_baseline", actual, forecast))
    r = _one(card, model="milk_baseline")
    assert r["accuracy"] == pytest.approx(1 - (12 * 10 + 12 * 4) / 2400)
    assert r["bias_pct"] == pytest.approx((12 * 10 - 12 * 4) / 2400)
    assert r["n"] == 24


def test_skill_uses_best_benchmark_on_common_periods_and_ignores_sparse_ones():
    rng = np.random.default_rng(0)
    actual = 100 + rng.normal(0, 5, 30)
    cand = _rows("herd_milk", "milk_baseline", actual, actual + 2)
    pers = _rows("herd_milk", "persistence", actual, actual + 8)
    sn = _rows("herd_milk", "seasonal_naive", actual, actual + 4)
    # SARIMA is perfect but forecasts only 10 periods: too few to count as a benchmark
    sar = _rows("herd_milk", "sarima", actual[:10], actual[:10], origins=_months(10))
    card = scorecard(pd.concat([cand, pers, sn, sar], ignore_index=True))
    r = _one(card, model="milk_baseline")
    assert r["best_benchmark"] == "seasonal_naive"
    assert r["skill"] == pytest.approx(1 - 2 / 4)
    assert r["n_common"] == 30


def test_too_few_periods_is_not_interpretable():
    n = MIN_PERIODS - 1
    card = scorecard(_rows("herd_milk", "milk_baseline", np.full(n, 100.0), np.full(n, 100.0)))
    assert _one(card, model="milk_baseline")["target"] == "not interpretable"


def test_target_met_and_missed_with_reasons():
    actual = np.full(30, 1000.0)
    good = _rows("milking", "herd_engine", actual, actual * 1.01)  # 99 % accuracy
    pers = _rows("milking", "persistence", actual, actual * 1.05)
    card = scorecard(pd.concat([good, pers], ignore_index=True))
    r = _one(card, model="herd_engine")
    assert r["target"] == "met"  # horizon 1 has no skill condition for milking
    bad = _rows("milking", "herd_engine", actual, actual * 1.10)  # 90 % < 97 %
    card = scorecard(pd.concat([bad, pers], ignore_index=True))
    r = _one(card, model="herd_engine")
    assert r["target"] == "missed" and "accuracy" in r["reasons"]


def test_skill_condition_fails_when_benchmark_is_better():
    actual = np.full(30, 1000.0)
    eng = _rows("n_herd", "herd_engine", actual, actual * 1.02, horizon=6)  # 98 % >= 94 %
    pers = _rows("n_herd", "persistence", actual, actual * 1.01, horizon=6)
    card = scorecard(pd.concat([eng, pers], ignore_index=True))
    r = _one(card, model="herd_engine")
    assert r["target"] == "missed" and "skill" in r["reasons"]


def test_non_primary_models_and_untargeted_series_have_no_target():
    actual = np.full(20, 50.0)
    corr = _rows("milking", "herd_engine_corrected", actual, actual)
    other = _rows("ais", "herd_engine", actual, actual)
    card = scorecard(pd.concat([corr, other], ignore_index=True))
    assert set(card["target"]) == {"no target"}
    assert not card["met"].any()


def test_count_series_use_deviance_and_coverage():
    rng = np.random.default_rng(1)
    lam = 4.0
    actual = rng.poisson(lam, 60).astype(float)
    eng = _rows("deaths", "herd_engine", actual, np.full(60, lam), origins=_months(60))
    pers = _rows("deaths", "persistence", actual, np.r_[actual[0], actual[:-1]], origins=_months(60))
    card = scorecard(pd.concat([eng, pers], ignore_index=True))
    r = _one(card, model="herd_engine")
    assert r["deviance_ratio"] < 1
    assert np.isnan(r["target_accuracy"])
    assert r["target"] in ("met", "missed")
    if r["target"] == "missed":
        assert "coverage" in r["reasons"]


def test_poisson_deviance_zero_for_perfect_forecast():
    y = np.array([0.0, 3.0, 5.0])
    assert poisson_deviance(y, np.array([0.1, 3.0, 5.0])) == pytest.approx(2 * 0.1 / 3)
    assert poisson_deviance(np.array([2.0, 4.0]), np.array([2.0, 4.0])) == pytest.approx(0.0)


def test_coverage_uses_only_past_errors_and_test_block_learns_from_development():
    rng = np.random.default_rng(2)
    actual = 100 + rng.normal(0, 3, 60)
    origins = _months(60)
    dev = _rows("herd_milk", "milk_baseline", actual[:48], np.full(48, 100.0),
                origins=origins[:48], block="development")
    test = _rows("herd_milk", "milk_baseline", actual[48:], np.full(12, 100.0),
                 origins=origins[48:], block="test")
    card = scorecard(pd.concat([dev, test], ignore_index=True))
    t = _one(card, block="test", model="milk_baseline")
    assert t["n_coverage"] == 12  # every test row has an interval thanks to development errors
    d = _one(card, block="development", model="milk_baseline")
    assert d["n_coverage"] < 48  # the first development origins have too few past errors
    alone = scorecard(test)
    assert _one(alone, model="milk_baseline")["n_coverage"] < 12


def test_future_outcomes_do_not_change_past_intervals():
    rng = np.random.default_rng(3)
    actual = 100 + rng.normal(0, 3, 40)
    base = _rows("herd_milk", "milk_baseline", actual, np.full(40, 100.0))
    shocked = base.copy()
    shocked.loc[35:, "actual"] *= 3  # change only the last five outcomes
    a, b = with_intervals(base), with_intervals(shocked)
    # an origin may use outcome 35 only once its month has ended (origin 36 onward)
    for col in ("lower80", "upper80", "lower90", "upper90"):
        assert a[col].iloc[:36].equals(b[col].iloc[:36])
    assert not a["lower90"].iloc[36:].equals(b["lower90"].iloc[36:])


def test_confirm_compares_development_and_test():
    actual = np.full(30, 100.0)
    dev = _rows("herd_milk", "milk_baseline", actual, actual * 1.05, block="development")
    test = _rows("herd_milk", "milk_baseline", actual, actual * 1.08,
                 origins=_months(30, date(2024, 1, 1)), block="test")
    c = confirm(scorecard(pd.concat([dev, test], ignore_index=True)))
    assert c.iloc[0]["confirmed"] == "yes"  # 92 % vs 95 %: within 5 points
    test2 = _rows("herd_milk", "milk_baseline", actual, actual * 1.20,
                  origins=_months(30, date(2024, 1, 1)), block="test")
    c = confirm(scorecard(pd.concat([dev, test2], ignore_index=True)))
    assert c.iloc[0]["confirmed"] == "no"


def test_targets_match_the_document():
    text = DOC.read_text()
    names = {"herd_milk": "Herd milk", "milking": "Milking cows", "n_herd": "Total herd",
             "calvings": "Calvings", "dry_offs": "Dry-offs"}
    for (series, grain), by_h in TARGETS.items():
        line = next(l for l in text.splitlines()
                    if l.startswith(f"| {names[series]} | {grain} |"))
        doc_pct = [int(x) for x in re.findall(r"(\d+)(?= / | %)", line.split("|")[3])]
        assert doc_pct == [round(t.accuracy * 100) for t in by_h.values()], series
    for s in COUNT_SERIES:
        assert s.replace("real_", "").replace("_", " ") in text.lower()


def test_rows_without_target_stay_no_target_even_when_few_periods():
    actual = np.full(5, 100.0)
    rows = pd.concat([_rows("ais", "herd_engine", actual, actual),
                      _rows("milking", "herd_engine_corrected", actual, actual),
                      _rows("milking", "herd_engine", actual, actual)], ignore_index=True)
    card = scorecard(rows).set_index(["series", "model"])
    assert card.loc[("ais", "herd_engine"), "target"] == "no target"
    assert card.loc[("milking", "herd_engine_corrected"), "target"] == "no target"
    assert card.loc[("milking", "herd_engine"), "target"] == "not interpretable"
