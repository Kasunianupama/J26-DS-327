"""Blended outlook documents and the multi-version comparison, on SYNTHETIC documents only."""
import copy
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.blend import persistence_blend
from components.predictive_farm_intelligence.pfoi.blend_outlook import blend_document, last_complete_week
from components.predictive_farm_intelligence.pfoi.compare_runs import plot_versions, score_versions

ORIGIN = date(2020, 3, 1)
LAST_WEEK_LITRES = 90_000.0


def _doc(withheld=False, complete_week=True):
    weeks = [date(2020, 1, 6) + timedelta(days=7 * i) for i in range(8)]       # 6 Jan .. 24 Feb
    actuals = []
    for w in weeks:
        incomplete = w + timedelta(days=7) > ORIGIN                             # 24 Feb ends after the origin
        v = np.nan if incomplete or not complete_week else (LAST_WEEK_LITRES if w == date(2020, 2, 17) else 100_000.0)
        actuals.append(dict(period=w.isoformat(), grain="week", series="milk_litres", value=v,
                            source="delpro", scoreable=bool(np.isfinite(v))))
    outlook = []
    for h in range(1, 14):
        outlook.append(dict(origin_date=ORIGIN.isoformat(), target_period=(date(2020, 3, 2) + timedelta(days=7 * (h - 1))).isoformat(),
                            grain="week", horizon=h, series="milk_litres", forecast=120_000.0, lower=110_000.0,
                            upper=130_000.0, quality_flag="high", model_version="pfoi-test", core_version="x"))
    for h in range(1, 15):
        outlook.append(dict(origin_date=ORIGIN.isoformat(), target_period=(ORIGIN + timedelta(days=h - 1)).isoformat(),
                            grain="day", horizon=h, series="milk_litres", forecast=17_000.0, lower=16_000.0,
                            upper=18_000.0, quality_flag="high", model_version="pfoi-test", core_version="x"))
    outlook.append(dict(origin_date=ORIGIN.isoformat(), target_period="2020-03-01", grain="month", horizon=1,
                        series="milk_litres", forecast=500_000.0, lower=400_000.0, upper=600_000.0,
                        quality_flag="high", model_version="pfoi-test", core_version="x"))
    outlook.append(dict(origin_date=ORIGIN.isoformat(), target_period="2020-03-02", grain="week", horizon=1,
                        series="milking", forecast=400.0, lower=380.0, upper=420.0, quality_flag="high",
                        model_version="pfoi-test", core_version="x"))
    corrections = [dict(target_period="2020-03-02", grain="week", horizon=1, series="milk_litres",
                        structural=119_000.0, correction=1_000.0),
                   dict(target_period="2020-03-01", grain="day", horizon=1, series="milk_litres",
                        structural=16_900.0, correction=100.0)]
    return dict(origin_date=ORIGIN.isoformat(), model_version="pfoi-test", outlook=outlook, corrections=corrections,
                actuals=actuals, realised=[], interval_method={"milk": "aci"}, withheld=withheld)


def _frame(shift_future=0.0):
    """Backtest errors: the structural forecast misses by 20k, persistence by 5k, at every scored horizon."""
    rows = []
    for grain, hs in (("weekly", (1, 4, 8, 13)), ("daily", (1, 7, 14))):
        for h in hs:
            for i in range(60):
                o = pd.Timestamp("2019-01-07") + pd.Timedelta(days=7 * i)
                end = o + pd.Timedelta(days=14)
                finished = end <= pd.Timestamp(ORIGIN)
                a = 100.0 if finished else 100.0 + shift_future
                common = dict(origin=o, grain=grain, horizon=h, period_start=o + pd.Timedelta(days=7), period_end=end,
                              series="herd_milk", actual=a, source="delpro")
                rows.append(dict(common, model="milk_baseline_adaptive", forecast=120.0))
                rows.append(dict(common, model="persistence", forecast=105.0))
    f = pd.DataFrame(rows)
    f["error"] = f["forecast"] - f["actual"]
    return f


def _blend(doc, frame=None):
    frame = _frame() if frame is None else frame
    return blend_document(doc, frame, persistence_blend(frame, base_model="milk_baseline_adaptive"))


def test_last_complete_week_skips_the_unfinished_one():
    assert last_complete_week(_doc(), ORIGIN) == (date(2020, 2, 17), LAST_WEEK_LITRES)
    assert last_complete_week(_doc(complete_week=False), ORIGIN) is None


def test_weekly_and_daily_milk_are_blended_with_the_persistence_value():
    out = _blend(_doc())
    wk = [r for r in out["outlook"] if r["series"] == "milk_litres" and r["grain"] == "week"]
    dy = [r for r in out["outlook"] if r["series"] == "milk_litres" and r["grain"] == "day"]
    # structural MAE 20, persistence MAE 5 -> w = 0.2; persistence = last complete week (and its daily mean)
    assert wk[0]["forecast"] == pytest.approx(0.2 * 120_000 + 0.8 * LAST_WEEK_LITRES)
    assert dy[0]["forecast"] == pytest.approx(0.2 * 17_000 + 0.8 * LAST_WEEK_LITRES / 7)
    assert out["model_version"] == "pfoi-test+blend" and all(r["model_version"] == "pfoi-test+blend" for r in out["outlook"])
    a = out["blend"]["grains"]["week"]
    assert a["persistence_week"] == "2020-02-17" and all(abs(r["weight"] - 0.2) < 1e-9 for r in a["rows"])


def test_other_series_and_months_are_untouched_and_the_input_is_not_modified():
    doc = _doc()
    before = copy.deepcopy(doc)
    out = _blend(doc)
    assert doc == before
    month = [r for r in out["outlook"] if r["grain"] == "month"][0]
    other = [r for r in out["outlook"] if r["series"] == "milking"][0]
    assert month["forecast"] == 500_000.0 and other["forecast"] == 400.0 and other["lower"] == 380.0


def test_corrections_still_add_up_to_the_shown_forecast():
    out = _blend(_doc())
    wk = [r for r in out["outlook"] if r["series"] == "milk_litres" and r["grain"] == "week" and r["horizon"] == 1][0]
    c = [c for c in out["corrections"] if c["grain"] == "week" and c["series"] == "milk_litres"][0]
    assert c["structural"] + c["correction"] == pytest.approx(wk["forecast"])


def test_range_is_never_tighter_than_the_documents_own_range_and_contains_the_forecast():
    out = _blend(_doc())
    for r in out["outlook"]:
        if r["series"] == "milk_litres" and r["grain"] in ("week", "day"):
            assert r["lower"] < r["forecast"] < r["upper"]
    orig = _doc()
    for r0, r1 in zip(orig["outlook"], out["outlook"]):
        if r0["series"] == "milk_litres" and r0["grain"] == "week":
            assert (r1["upper"] - r1["lower"]) >= (r0["upper"] - r0["lower"]) - 1e-6


def test_outcomes_after_the_forecast_date_never_change_the_result():
    clean = _blend(_doc())
    leaked = _blend(_doc(), _frame(shift_future=500.0))      # only forecasts that end after the origin differ
    for a, b in zip(clean["outlook"], leaked["outlook"]):
        assert a["forecast"] == pytest.approx(b["forecast"])


def test_no_complete_week_or_withheld_milk_leaves_the_forecasts_unchanged():
    for doc in (_doc(complete_week=False), _doc(withheld=True)):
        out = _blend(doc)
        assert "skipped" in out["blend"]
        assert [r["forecast"] for r in out["outlook"]] == [r["forecast"] for r in doc["outlook"]]


# ------------------------------------------------------------------ comparison of several versions

def _cmp_doc(version, level, realised):
    outlook = [dict(origin_date="2020-03-01", target_period=(date(2020, 3, 2) + timedelta(days=7 * i)).isoformat(),
                    grain="week", horizon=i + 1, series="milk_litres", forecast=level, lower=level - 5,
                    upper=level + 5, quality_flag="high", model_version=version, core_version="x") for i in range(3)]
    real = [dict(period=(date(2020, 3, 2) + timedelta(days=7 * i)).isoformat(), grain="week", series="milk_litres",
                 value=realised, source="delpro", scoreable=True) for i in range(3)]
    hist = [dict(period=(date(2020, 1, 6) + timedelta(days=7 * i)).isoformat(), grain="week", series="milk_litres",
                 value=100.0, source="delpro", scoreable=True) for i in range(4)]
    hist.append(dict(period="2020-02-24", grain="week", series="milk_litres", value=100.0, source="delpro", scoreable=True))
    return dict(outlook=outlook, actuals=hist, realised=real, model_version=version)


def test_score_versions_uses_the_periods_every_version_forecast():
    docs = [("a", _cmp_doc("a", 110.0, 100.0)), ("b", _cmp_doc("b", 103.0, 100.0))]
    docs[1][1]["outlook"] = docs[1][1]["outlook"][:2]               # b forecasts only two of the three weeks
    t = score_versions(docs, series=("milk_litres",), grain="week").set_index("version")
    assert t.loc["a", "n_periods"] == 2 and t.loc["b", "n_periods"] == 2
    assert t.loc["a", "mae"] == pytest.approx(10.0) and t.loc["b", "mae"] == pytest.approx(3.0)
    assert t.loc["a", "cover90"] == 0.0 and t.loc["b", "cover90"] == 1.0


def test_plot_versions_draws_three_versions_and_breaks_the_history_at_a_gap(tmp_path):
    docs = [(v, _cmp_doc(v, lv, 100.0)) for v, lv in (("a", 110.0), ("b", 105.0), ("c", 101.0))]
    path = tmp_path / "x.png"
    plot_versions(docs, date(2020, 3, 1), path, grain="week")
    assert path.exists() and path.stat().st_size > 5_000


def test_daily_milk_also_uses_ets_when_it_can_be_fitted():
    from components.predictive_farm_intelligence.pfoi.blend import skill_blend

    doc = _doc()
    days = [ORIGIN - timedelta(days=120 - i) for i in range(120)]            # a clean, slowly rising daily record
    doc["actuals"] += [dict(period=d.isoformat(), grain="day", series="milk_litres", value=16_000.0 + 10 * i,
                            source="delpro", scoreable=True) for i, d in enumerate(days)]
    frame = _frame()
    e = frame[(frame["model"] == "persistence") & (frame["grain"] == "daily")].copy()
    e["model"], e["forecast"] = "ets", 101.0                                   # ETS misses by 1: far better
    frame = pd.concat([frame, e], ignore_index=True)
    blend_rows = pd.concat([skill_blend(frame, base_model="milk_baseline_adaptive", partners=("persistence",), grains=("weekly",)),
                            skill_blend(frame, base_model="milk_baseline_adaptive", partners=("persistence", "ets"), grains=("daily",))],
                           ignore_index=True)
    out = blend_document(doc, frame, blend_rows)
    day = out["blend"]["grains"]["day"]
    assert day["partners"] == ["persistence", "ets"]
    first = day["rows"][0]
    assert first["ets"] is not None and first["weights"]["ets"] > first["weights"]["persistence"]
    assert sum(first["weights"].values()) == pytest.approx(1.0)
    assert out["blend"]["grains"]["week"]["partners"] == ["persistence"]    # weekly stays two-way
