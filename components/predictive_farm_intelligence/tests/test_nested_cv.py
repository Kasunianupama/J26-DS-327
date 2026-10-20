"""Nested, purged validation on SYNTHETIC error tables."""
from datetime import date

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.nested_cv import (
    default_objectives, nested_select,
)

OBJ = [("herd_milk", "monthly", 1)]


def _months(start: date, n: int) -> list[date]:
    return list(pd.date_range(start, periods=n, freq="MS").date)


def _cand(error_by_year: dict[int, float], start=date(2017, 1, 1), n=84, drop=()):
    rows = []
    for o in _months(start, n):
        if o in drop:
            continue
        end = (pd.Timestamp(o) + pd.offsets.MonthBegin(1)).date()
        f = 100.0 * (1 + error_by_year.get(o.year, 0.0))
        rows.append(dict(origin=o, grain="monthly", horizon=1, period_start=o, period_end=end,
                         series="herd_milk", forecast=f, actual=100.0))
    return pd.DataFrame(rows)


def test_selection_uses_only_periods_ended_before_the_fold():
    # A is better up to 2018 and worse from 2019; B the opposite.
    a = _cand({2017: .01, 2018: .01, 2019: .20, 2020: .20, 2021: .20, 2022: .20, 2023: .20})
    b = _cand({2017: .10, 2018: .10, 2019: .02, 2020: .02, 2021: .02, 2022: .02, 2023: .02})
    r = nested_select({"A": a, "B": b}, OBJ)
    chosen = r.folds[r.folds["selected"]].set_index("fold_year")["candidate"]
    assert chosen[2019] == "A"            # only 2017-2018 known: A looked better
    assert chosen[2021] == "B"            # by 2021, 2019-2020 errors favour B
    s = r.summary.iloc[0]
    assert s["acc_best_in_hindsight"] == s["acc_B"]
    assert s["optimism"] > 0              # picking in hindsight would flatter the score


def test_outcomes_in_the_fold_year_do_not_change_that_folds_choice():
    a = _cand({2017: .01, 2018: .01})
    b = _cand({2017: .05, 2018: .05})
    base = nested_select({"A": a, "B": b}, OBJ)
    b2 = b.copy()
    b2.loc[pd.to_datetime(b2["origin"]).dt.year == 2019, "forecast"] = 100.0  # B perfect in 2019
    shocked = nested_select({"A": a, "B": b2}, OBJ)
    pick = lambda r: r.folds[r.folds["selected"]].set_index("fold_year")["candidate"]
    assert pick(base)[2019] == pick(shocked)[2019] == "A"


def test_candidates_are_compared_on_common_periods_only():
    a = _cand({y: .05 for y in range(2017, 2024)})
    # B is perfect, but only on the months it forecast; it misses the rest
    missing = set(_months(date(2017, 1, 1), 84)[::2])
    b = _cand({}, drop=missing)
    b_bad = _cand({y: .30 for y in range(2017, 2024)})
    b_bad = b_bad[b_bad["origin"].isin(missing)]
    b = pd.concat([b, b_bad], ignore_index=True)
    a_common = a[~a["origin"].isin(missing)]
    r = nested_select({"A": a_common, "B": b}, OBJ)
    # only months both forecast count, where B is perfect
    assert r.folds[r.folds["selected"]]["candidate"].eq("B").all()


def test_objectives_with_too_few_inner_periods_are_skipped():
    a = _cand({}, start=date(2018, 6, 1), n=24)
    b = _cand({}, start=date(2018, 6, 1), n=24)
    r = nested_select({"A": a, "B": b}, OBJ, fold_years=(2019,))
    assert r.folds["n_objectives"].eq(0).all()  # 7 inner months < 12
    assert not r.folds["selected"].any()


def test_default_objectives_follow_the_targets():
    objs = default_objectives(("herd_milk",))
    assert ("herd_milk", "monthly", 3) in objs and ("herd_milk", "daily", 1) in objs
    assert all(s == "herd_milk" for s, _, _ in objs)
    assert np.isclose(len(default_objectives(("milking", "n_herd"))), 8)
