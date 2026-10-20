"""Record-quality bands and recovery buckets on SYNTHETIC daily aggregates."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.episodes import (
    DEGRADED, GAP, NO_BREAK, NORMAL, UNVERIFIED, Break, add_bands, add_recovery,
    daily_quality, months_since_break, period_band,
)
from components.predictive_farm_intelligence.pfoi.scorecard import group_scores, scorecard


def _quality(start: date, days: int, share=0.8, litres=4000.0, cows=800.0, gap=0,
             source="delpro") -> pd.DataFrame:
    dates = [start + timedelta(days=i) for i in range(days)]
    target = pd.DataFrame({"date": dates, "target_source": source, "target_litres": litres,
                           "identified_share": share, "data_gap": gap})
    panel = pd.DataFrame({"date": dates, "milking": cows})
    return daily_quality(target, panel)


def test_bands_from_share_gap_source_and_litres_per_cow():
    s, e = date(2024, 1, 1), date(2024, 2, 1)
    assert period_band(_quality(s, 31, share=0.8), s, e) == NORMAL
    assert period_band(_quality(s, 31, share=0.4), s, e) == DEGRADED
    assert period_band(_quality(s, 31, share=0.05), s, e) == UNVERIFIED
    assert period_band(_quality(s, 31, gap=1), s, e) == GAP
    assert period_band(_quality(s, 31, share=np.nan, source="shipment"), s, e) == NORMAL
    # well identified, but 24 L per recorded cow-day is not realistic (user, 2026-10-19)
    assert period_band(_quality(s, 31, share=0.9, litres=24 * 400, cows=400), s, e) == UNVERIFIED
    assert period_band(_quality(s, 31), date(2030, 1, 1), date(2030, 2, 1)) == GAP


def test_one_gap_day_makes_the_period_a_gap():
    q = _quality(date(2024, 1, 1), 31)
    q.loc[10, "gap"] = True
    assert period_band(q, date(2024, 1, 1), date(2024, 2, 1)) == GAP
    assert period_band(q, date(2024, 1, 1), date(2024, 1, 8)) == NORMAL


def test_months_since_break_uses_latest_break_on_or_before_origin():
    breaks = (Break("X", "test", date(2022, 9, 1)), Break("Y", "test", date(2024, 3, 1)))
    assert months_since_break(date(2022, 1, 1), breaks)[0] is None
    code, m = months_since_break(date(2024, 5, 1), breaks)
    assert code == "Y" and 1.9 < m < 2.1
    assert months_since_break(date(2024, 3, 1), breaks)[1] == 0


def _errors():
    rows = []
    for i, o in enumerate(pd.date_range("2023-01-01", periods=24, freq="MS").date):
        end = (pd.Timestamp(o) + pd.offsets.MonthBegin(1)).date()
        for model, f in (("herd_engine", 103.0), ("persistence", 110.0)):
            rows.append(dict(origin=o, grain="monthly", horizon=1, period_start=o, period_end=end,
                             series="milking", model=model, forecast=f, actual=100.0))
    e = pd.DataFrame(rows)
    e["error"] = e["forecast"] - e["actual"]
    return e


def test_recovery_buckets_and_group_scores():
    breaks = (Break("X", "test", date(2024, 1, 1)),)
    e = add_recovery(_errors(), breaks)
    assert set(e.loc[pd.to_datetime(e["origin"]) < "2024-01-01", "since_break"]) == {NO_BREAK}
    g = group_scores(e, "since_break")
    assert set(g["model"]) == {"herd_engine"}
    assert g.set_index("since_break").loc["0-2 months", "n"] == 3
    assert np.allclose(g["accuracy"], 0.97)


def test_targets_are_judged_on_verified_bands_only():
    e = _errors()
    q = pd.concat([_quality(date(2023, 1, 1), 365, share=0.8),
                   _quality(date(2024, 1, 1), 366, share=0.05)], ignore_index=True)
    banded = add_bands(e, q)
    assert set(banded["band"]) == {NORMAL, UNVERIFIED}
    card = scorecard(banded)
    assert card.set_index("model").loc["herd_engine", "n"] == 12
    by_band = group_scores(banded, "band").set_index("band")
    assert by_band.loc[UNVERIFIED, "n"] == 12


def test_recovery_target_verdict():
    from components.predictive_farm_intelligence.pfoi.scorecard import (
        RECOVERY_TARGETS, recovery_verdicts,
    )
    assert RECOVERY_TARGETS == {("herd_milk", "weekly", 4, "0-2 months"): 0.90}
    rows = []
    origins = pd.date_range("2024-01-01", periods=13, freq="W-MON").date
    for o in origins:
        rows.append(dict(origin=o, grain="weekly", horizon=4, period_start=o,
                         period_end=o + timedelta(days=7), series="herd_milk",
                         model="milk_baseline", forecast=95.0, actual=100.0))
    e = add_recovery(pd.DataFrame(rows), (Break("X", "test", date(2024, 1, 1)),))
    r = recovery_verdicts(e).iloc[0]
    assert r["n"] == 13 and abs(r["accuracy"] - 0.95) < 1e-9 and r["target"] == "met"
    r = recovery_verdicts(e.iloc[:5]).iloc[0]
    assert r["target"] == "not interpretable"
