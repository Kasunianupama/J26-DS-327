"""Comparison charts on SYNTHETIC error tables only (no database, no Farm X data)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.ml_charts import CURRENT, ML, PERSIST, draw, load
from components.predictive_farm_intelligence.pfoi.periods import HORIZONS, period_bounds


def _errors(models, series, grains, seed):
    rng = np.random.default_rng(seed)
    rows = []
    for og, grains_ in (("monthly", ("monthly",)), ("weekly", ("weekly", "daily"))):
        if og == "monthly":
            origins = [date(2018 + i // 12, i % 12 + 1, 1) for i in range(30)]
        else:
            origins = [date(2018, 1, 1) + timedelta(days=7 * i) for i in range(60)]
        for o in origins:
            for g in grains_:
                if g not in grains:
                    continue
                for h in HORIZONS[g]:
                    s, e = period_bounds(o, g, h)
                    for ser in series:
                        actual = (900.0 if ser == "herd_milk" else 50.0) * (e - s).days
                        for m in models:
                            rows.append(dict(origin=o, grain=g, horizon=h, period_start=s, period_end=e,
                                             series=ser, model=m, actual=actual,
                                             forecast=actual * (1 + rng.normal(0, .05 * h ** .5)),
                                             year=o.year))
    return pd.DataFrame(rows)


def test_charts_are_drawn_on_matched_periods(tmp_path):
    ml = _errors(["ml_lgbm", "persistence"], ["herd_milk", "milking", "calvings"], GRAINS_ALL, 1)
    milk = _errors(["milk_baseline_adaptive"], ["herd_milk"], GRAINS_ALL, 2)
    herd = _errors(["herd_engine"], ["milking", "calvings"], ("monthly", "weekly"), 3)
    herd = herd.iloc[: len(herd) - 40]  # a few periods the current model did not forecast
    paths = []
    for name, frame in (("ml_m.csv", ml), ("milk.csv", milk), ("herd.csv", herd)):
        frame.to_csv(tmp_path / name, index=False)
        paths.append(tmp_path / name)
    e = load([paths[0]], [paths[1]], [paths[2]])
    assert set(e["label"]) == {ML, CURRENT, PERSIST}
    assert (e.groupby(["series", "grain", "horizon", "origin", "period_start"])["label"].nunique() == 3).all()
    imp = pd.DataFrame({"series": ["herd_milk", "calvings"], "grain": "monthly", "baseline": .1,
                        "recent milk": [.02, .01], "pregnancy pipeline": [.05, .2], "season": [.01, .1]})
    written = draw(e, tmp_path / "out", imp)
    assert len(written) == 6
    assert all(p.exists() and p.stat().st_size > 10_000 for p in written)


GRAINS_ALL = ("monthly", "weekly", "daily")
