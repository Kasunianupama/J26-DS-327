"""Evidence ladder (F7) and the PP1 page-document sections, on SYNTHETIC data only."""
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.evidence import (
    Rung, add_bands, ladder, matched, parse_rung, status_of_tag,
)

from .synthetic import FakeHerdSource


def _rows(model, scale, n=20, start=date(2019, 1, 7), skip=()):
    rows = []
    for i in range(n):
        o = start + timedelta(days=7 * i)
        if i in skip:
            continue
        rows.append(dict(origin=o, grain="weekly", horizon=4, period_start=o + timedelta(days=21),
                         period_end=o + timedelta(days=28), model=model, actual=1000.0,
                         forecast=1000.0 + scale * (1 if i % 2 else -1)))
    return pd.DataFrame(rows)


RUNGS = [Rung("persistence", "persistence"), Rung("current", "milk_baseline_adaptive"),
         Rung("+heat", "milk_baseline_adaptive_drivers"), Rung("oracle", "x", "oracle")]


def test_every_rung_is_scored_on_the_same_periods():
    frames = {"persistence": _rows("persistence", 100), "current": _rows("m", 50),
              "+heat": _rows("m", 40, skip=(3, 4))}
    m = matched(frames)
    assert m.groupby("rung").size().nunique() == 1 and len(m) == 3 * 18


def test_ratios_status_and_small_n():
    frames = {"persistence": _rows("persistence", 100), "current": _rows("m", 50),
              "+heat": _rows("m", 40), "oracle": _rows("m", 10)}
    t = ladder(frames, RUNGS)
    a = t[t["band"] == "all"].set_index("rung")
    assert a.loc["persistence", "ratio_to_reference"] == pytest.approx(1.0)
    assert a.loc["current", "ratio_to_reference"] == pytest.approx(0.5)
    assert a.loc["+heat", "status"] == "development" and a.loc["oracle", "status"] == "oracle"
    small = ladder({k: v.head(8) for k, v in frames.items()}, RUNGS)
    assert set(small.loc[small["rung"] != "oracle", "status"]) == {"not interpretable"}


def test_bands_use_past_weather_and_labelled_breaks():
    days = pd.date_range("2016-01-01", "2023-12-31")
    thi = pd.DataFrame({"date": days.date, "thi_mean": 70.0})
    hot = (days >= "2019-06-01") & (days < "2019-07-01")
    thi.loc[hot, "thi_mean"] = 80.0
    rows = pd.DataFrame([
        dict(origin=date(2019, 5, 27), period_start=date(2019, 6, 10), period_end=date(2019, 6, 17)),
        dict(origin=date(2019, 1, 7), period_start=date(2019, 1, 28), period_end=date(2019, 2, 4)),
        dict(origin=date(2022, 12, 5), period_start=date(2022, 12, 26), period_end=date(2023, 1, 2)),
    ])
    b = add_bands(rows, thi)
    assert list(b["heat"]) == [True, False, False]
    assert list(b["recovery"]) == [False, False, True]  # E5a: milk back from 2022-12-01


def test_tag_status_and_rung_parsing():
    assert status_of_tag("x_dr_w6p75_oracle") == "oracle"
    assert status_of_tag("x_posthoc") == "post-test development"
    assert parse_rung("current=a_b_c:milk_baseline_adaptive") == ("current", "a_b_c", "milk_baseline_adaptive")


def test_page_sections_only_in_development_builds():
    from components.predictive_farm_intelligence.pfoi.outlook import build_outlook, run_frozen
    from components.predictive_farm_intelligence.pfoi.page_run import build_page_run

    src = FakeHerdSource()
    origin = date(2021, 10, 1)
    run = run_frozen(src, origin)
    _, attribution, _ = build_outlook(src, origin, None, None, run=run)
    frozen = build_page_run(src, run, attribution, {}, None)
    assert "heat" not in frozen and "evidence_ladder" not in frozen
    ev = {"ladder": ladder({"persistence": _rows("persistence", 100), "current": _rows("m", 50)},
                           RUNGS[:2])}
    dev = build_page_run(src, run, attribution, {}, None, evidence=ev)
    for key in ("record_status", "repro_timing", "generation_outcomes", "heat",
                "outage_simulation", "evidence_ladder", "feature_registry"):
        assert key in dev, key
    assert dev["heat"]["last_weather_day"] == (origin - timedelta(days=6)).isoformat()
    assert all(r["date"] <= dev["heat"]["last_weather_day"] for r in dev["heat"]["recent"])
    assert dev["heat"]["climatology"][0]["date"] == origin.isoformat()
    assert len(dev["evidence_ladder"]) and dev["outage_simulation"] == []
    json.dumps(dev)  # the document must be plain JSON
    text = json.dumps(dev)
    assert "animal_key" not in text


def test_ladder_chart_is_written(tmp_path):
    from components.predictive_farm_intelligence.pfoi.evidence import plot_ladder

    frames = {"persistence": _rows("persistence", 100), "current": _rows("m", 50),
              "oracle": _rows("m", 10)}
    t = ladder(frames, [RUNGS[0], RUNGS[1], RUNGS[3]])
    plot_ladder(t, tmp_path / "ladder.png")
    assert (tmp_path / "ladder.png").stat().st_size > 10_000


def test_named_ladders_are_not_page_evidence(tmp_path):
    from components.predictive_farm_intelligence.pfoi.cli import _load_evidence

    ev = tmp_path / "evidence"
    ev.mkdir()
    t = ladder({"persistence": _rows("persistence", 100), "current": _rows("m", 50)}, RUNGS[:2])
    t.to_csv(ev / "evidence_ladder_weekly.csv", index=False)
    t.assign(rung="other").to_csv(ev / "evidence_ladder_weekly_posthoc.csv", index=False)
    out = _load_evidence(tmp_path)
    assert set(out["ladder"]["rung"]) == {"persistence", "current"}
