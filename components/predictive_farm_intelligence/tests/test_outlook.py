"""Outlook from the frozen model on SYNTHETIC data; writer tested on in-memory SQLite."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, event, text

from components.predictive_farm_intelligence.pfoi import MODEL_VERSION
from components.predictive_farm_intelligence.pfoi.outlook import (
    ATTRIBUTION_COLUMNS, HISTORY_COLUMNS, OUTLOOK_COLUMNS, build_outlook, interval_table,
    write_outlook,
)

from .synthetic import FakeHerdSource

ORIGIN = date(2021, 10, 1)
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")  # sqlite date adapter


@pytest.fixture(scope="module")
def built():
    return build_outlook(FakeHerdSource(), ORIGIN, None, "core-test")


def test_outlook_shape_and_contract(built):
    outlook, attribution, history = built
    assert list(outlook.columns) == OUTLOOK_COLUMNS
    assert list(attribution.columns) == ATTRIBUTION_COLUMNS
    assert list(history.columns) == HISTORY_COLUMNS
    counts = outlook.groupby(["grain", "series"]).size()
    assert counts.loc[("monthly", "herd_milk")] == 12 and counts.loc[("daily", "herd_milk")] == 14
    assert (outlook["model_version"] == MODEL_VERSION).all()
    assert (outlook["core_version"] == "core-test").all()
    assert outlook["lower"].isna().all()  # no backtest errors given -> no intervals
    assert {"herd_size", "residual", "dry_off", "determined"} <= set(attribution["factor"])
    assert history["period"].min() >= date(2019, 10, 1)


def test_intervals_from_past_errors_only():
    rows = []
    for i in range(20):
        o = date(2019, 1, 1) + pd.Timedelta(days=30 * i)
        rows.append(("milk_baseline", "monthly", "herd_milk", 1, o, o + pd.Timedelta(days=30),
                     100.0, 100.0 * (1.1 if i % 2 else 0.9)))
    rows.append(("milk_baseline", "monthly", "herd_milk", 1, date(2022, 1, 1), date(2022, 2, 1), 100.0, 500.0))
    e = pd.DataFrame(rows, columns=["model", "grain", "series", "horizon", "origin", "period_end",
                                    "forecast", "actual"])
    q = interval_table(e, ORIGIN)
    r = q.iloc[0]
    assert r["n"] == 20  # the 2022 error ended after the origin and is ignored
    assert r["q_lo"] == pytest.approx(-0.1) and r["q_hi"] == pytest.approx(0.1)
    outlook, _, _ = build_outlook(FakeHerdSource(), ORIGIN, e, None)
    m = outlook[(outlook["grain"] == "monthly") & (outlook["series"] == "herd_milk")]
    assert (m["lower"] < m["forecast"]).all() and (m["upper"] > m["forecast"]).all()


def test_writer_replaces_rows_of_one_origin(built):
    outlook, attribution, history = built
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _attach(dbapi_conn, _):
        dbapi_conn.execute("ATTACH DATABASE ':memory:' AS c1_output")

    with engine.begin() as c:
        for name, frame in (("outlook", outlook), ("attribution", attribution), ("history", history)):
            cols = ", ".join(f"{col} TEXT" for col in frame.columns)
            c.execute(text(f"CREATE TABLE c1_output.{name} ({cols})"))
    first = write_outlook(engine, outlook, attribution, history)
    again = write_outlook(engine, outlook, attribution, history)
    assert first == again
    with engine.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM c1_output.outlook")).scalar()
    assert n == len(outlook)  # re-running replaced, not duplicated


def test_page_document_matches_frontend_contract():
    from components.predictive_farm_intelligence.pfoi.backtest_milk import run_milk_backtest
    from components.predictive_farm_intelligence.pfoi.outlook import run_frozen
    from components.predictive_farm_intelligence.pfoi.page_run import build_page_run

    src = FakeHerdSource()
    dev = run_milk_backtest(src, "monthly", origins=[date(2020, m, 1) for m in range(1, 13)]).errors
    run = run_frozen(src, ORIGIN)
    _, attribution, _ = build_outlook(src, ORIGIN, dev, "core-test", run=run)
    doc = build_page_run(src, run, attribution, {("milk", "development"): dev}, "core-test")
    keys = {"source", "model_version", "core_version", "origin_date", "data_through", "generated_at",
            "outlook", "attribution", "actuals", "replay", "revisions", "backtest", "qualityBands",
            "generations", "fertility", "coverage", "mastitis_rate_period", "moves"}
    assert keys <= set(doc) and doc["source"] == "model"
    o = pd.DataFrame(doc["outlook"])
    assert set(o["grain"]) == {"day", "week", "month"}
    assert set(o[o["grain"] == "day"]["series"]) == {"milk_litres"}
    assert {"total_herd", "culls_sales", "mastitis_episodes"} <= set(o[o["grain"] == "month"]["series"])
    assert set(o["quality_flag"]) <= {"high", "moderate", "limited"}
    # the five herd stocks (bulls and unknown-state animals in "other") add up to the total
    parts = ["milking", "dry", "heifers", "calves", "other"]
    for rows in (o.rename(columns={"target_period": "period", "forecast": "value"}),
                 pd.DataFrame(doc["actuals"])):
        stocks = rows[rows["series"].isin(parts + ["total_herd"])]
        wide = stocks.pivot_table(index=[c for c in ("period", "grain", "horizon") if c in stocks],
                                  columns="series", values="value")
        assert len(wide) and set(parts) <= set(wide.columns)
        assert (wide[parts].sum(axis=1) - wide["total_herd"]).abs().max() < 0.01
    # empirical bands may exclude the line when past errors are one-sided (bias): only order them
    assert (o["lower"] <= o["upper"] + 1e-9).all() and (o["lower"] >= 0).all()
    a = pd.DataFrame(doc["attribution"])
    assert {"determined", "rate_driven", "herd_size"} <= set(a["factor"])
    assert {"milk_litres", "calvings"} == set(a["series"])
    b = pd.DataFrame(doc["backtest"])
    assert set(b["model"]) <= {"pfoi", "persistence", "seasonal_naive", "sarima"}
    assert {"day", "week", "month"} >= set(pd.DataFrame(doc["actuals"])["grain"])
    # herd moves between groups: recorded by month, forecast by week and month
    mv = pd.DataFrame(doc["moves"])
    groups = {"born", "arrived", "calves", "heifers", "milking", "dry", "other", "died", "culled_sold",
              "herd", "lost_pregnancy"}
    assert set(mv["from"]) <= groups and set(mv["to"]) <= groups and (mv["from"] != mv["to"]).all()
    assert (mv["value"] > 0).all()
    assert set(mv[~mv["forecast"]]["grain"]) == {"day", "week", "month"}
    assert set(mv[mv["forecast"]]["grain"]) == {"week", "month"}
    rec = mv[~mv["forecast"]]
    assert ((rec["from"] == "heifers") & (rec["to"] == "milking")).any()
    # recorded days: exits leave a named group; arrivals are herd totals
    rd = rec[rec["grain"] == "day"]
    assert rd[rd["to"].isin(["died", "culled_sold"])]["from"].isin(["calves", "heifers", "milking", "dry", "other"]).all()
    assert (rd[rd["from"] == "arrived"]["to"] == "herd").all()
    # forecast pregnancies lost by group
    assert {"heifers", "dry", "milking"} >= set(mv[mv["forecast"] & (mv["to"] == "lost_pregnancy")]["from"])
    assert (rec["period"] < doc["origin_date"]).all()
    # forecast moves agree with the outlook totals for the same period
    fm = mv[mv["forecast"] & (mv["grain"] == "month")]
    om = o[o["grain"] == "month"].set_index(["target_period", "series"])["forecast"]
    for period, g in fm.groupby("period"):
        dry_offs = g[(g["from"] == "milking") & (g["to"] == "dry")]["value"].sum()
        assert abs(dry_offs - om[(period, "dry_offs")]) < 0.01
        calvings = g[g["from"].isin(["heifers", "dry"]) & (g["to"] == "milking")]["value"].sum()
        assert calvings <= om[(period, "calvings")] + 0.01  # cows calving while still milking stay in milking
    import json
    json.dumps(doc)  # serialisable


def _page_doc(src, until):
    from components.predictive_farm_intelligence.pfoi.outlook import run_frozen
    from components.predictive_farm_intelligence.pfoi.page_run import build_page_run

    run = run_frozen(src, ORIGIN)
    _, attribution, _ = build_outlook(src, ORIGIN, None, "core-test", run=run)
    return build_page_run(src, run, attribution, {}, "core-test", realised_until=until)


def test_realised_outcomes_are_never_model_inputs():
    """Recorded outcomes after the origin are shown next to the forecasts but change nothing
    the model produced: tripling every synthetic day on/after the origin moves only them."""
    until = date(2022, 3, 15)
    base = _page_doc(FakeHerdSource(), until)
    future = _page_doc(FakeHerdSource(cutoff=ORIGIN, future_scale=3.0), until)
    without = _page_doc(FakeHerdSource(), None)
    for key in set(base) - {"generated_at", "realised", "realised_through"}:
        assert base[key] == future[key], key
        assert base[key] == without[key], key
    assert without["realised"] == [] and without["realised_through"] is None
    assert base["realised_through"] == "2022-03-14"
    # not vacuous: the realised values themselves do see the tripled future
    b = pd.DataFrame(base["realised"]).set_index(["grain", "series", "period"])["value"]
    f = pd.DataFrame(future["realised"]).set_index(["grain", "series", "period"])["value"]
    m = ("month", "milk_litres", "2021-11-01")
    assert f.loc[m] == pytest.approx(3 * b.loc[m])
    calv = ("month", "calvings", "2021-11-01")
    assert f.loc[calv] == pytest.approx(3 * b.loc[calv], abs=0.005)  # herd values are rounded to 3 dp


def test_realised_covers_only_complete_forecast_periods():
    src = FakeHerdSource()
    until = date(2022, 3, 15)
    doc = _page_doc(src, until)
    r = pd.DataFrame(doc["realised"])
    o = pd.DataFrame(doc["outlook"])
    targets = set(zip(o["grain"], o["series"], o["target_period"]))
    assert set(zip(r["grain"], r["series"], r["period"])) <= targets
    assert (r["period"] >= doc["origin_date"]).all()
    assert list(r.columns) == list(pd.DataFrame(doc["actuals"]).columns)  # same shape as actuals
    months = sorted(r[(r["grain"] == "month") & (r["series"] == "milk_litres")]["period"])
    assert months == ["2021-10-01", "2021-11-01", "2021-12-01", "2022-01-01", "2022-02-01"]
    weeks = [date.fromisoformat(p) for p in r[r["grain"] == "week"]["period"]]
    assert weeks and all(w + timedelta(days=7) <= until for w in weeks)
    assert len(r[r["grain"] == "day"]) == 14 and set(r[r["grain"] == "day"]["series"]) == {"milk_litres"}
    assert {"total_herd", "calvings", "mastitis_episodes"} <= set(r[r["grain"] == "month"]["series"])
    # a realised month is the recorded herd milk of that month
    t = src.target_daily(date(2021, 11, 1), date(2021, 12, 1))
    nov = r[(r["grain"] == "month") & (r["series"] == "milk_litres") & (r["period"] == "2021-11-01")]
    assert nov["value"].iloc[0] == pytest.approx(t["target_litres"].sum()) and nov["scoreable"].iloc[0]
    # stocks still add up to the total herd
    parts = ["milking", "dry", "heifers", "calves", "other"]
    wide = r[r["series"].isin(parts + ["total_herd"])].pivot_table(
        index=["period", "grain"], columns="series", values="value")
    assert (wide[parts].sum(axis=1) - wide["total_herd"]).abs().max() < 0.01
    # nothing realised when the data ends before the first forecast period is complete
    assert _page_doc(src, ORIGIN)["realised"] == []
