"""Bundle export, merge and publish of notebook 09 (no database: a fake engine records SQL)."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import herd_publish as P


def _doc(source="model"):
    return {"source": source, "model_version": "pfoi-herd-milk-combined-test", "core_version": None,
            "origin_date": "2026-09-01", "data_through": "2026-08-31",
            "outlook": [{"series": "milk_litres", "grain": "month", "forecast": 75000.0},
                        {"series": "milking", "grain": "month", "forecast": 300.0}],
            "attribution": [{"series": "milk_litres", "factor": "herd_size", "contribution": 2.0}],
            "actuals": [{"period": "2026-08-01", "grain": "month", "series": "milk_litres", "value": 77000.0,
                         "source": "delpro", "scoreable": True},
                        {"period": "2026-08-01", "grain": "month", "series": "milking", "value": 301.0,
                         "source": None, "scoreable": True}],
            "backtest": [], "replay": [], "record_status": {"status": "current"},
            "reproducibility": {"config_hash": "abc"}}


def _c1():
    o = pd.DataFrame([{"origin_date": "2026-09-01", "target_period": "2026-09-01", "grain": "monthly",
                       "horizon": 1, "series": "herd_milk", "forecast": 75000.0, "lower": 70000.0,
                       "upper": 80000.0, "quality_flag": "high", "model_version": "pfoi-herd-milk-combined-test",
                       "core_version": None}])
    a = pd.DataFrame([{"origin_date": "2026-09-01", "target_period": "2026-09-01", "grain": "monthly",
                       "series": "herd_milk", "factor": "herd_size", "contribution": 2.0, "kind": "forecast",
                       "model_version": "pfoi-herd-milk-combined-test", "core_version": None}])
    return o, a


class FakeConn:
    def __init__(self, log, row=None):
        self.log, self.row = log, row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((str(sql), params))
        row = self.row

        class R:
            def first(self_inner):
                return row
        return R()


class FakeEngine:
    def __init__(self, row=None):
        self.log, self.row = [], row

    def begin(self):
        return FakeConn(self.log)

    def connect(self):
        return FakeConn(self.log, self.row)


def test_export_and_load_bundle(tmp_path):
    o, a = _c1()
    m = P.export_bundle(tmp_path, _doc(), o, a)
    assert m["rows"] == {"c1_outlook.csv": 1, "c1_attribution.csv": 1, "c1_history.csv": 2}
    b = P.load_bundle(tmp_path)
    assert b["outlook"]["quality_flag"].iloc[0] == "ok"
    assert b["attribution"]["series"].iloc[0] == "herd_milk_litres_per_day"
    assert set(b["history"]["series"]) == {"herd_milk", "milking"}
    (tmp_path / "c1_outlook.csv").write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        P.load_bundle(tmp_path)


def test_merge_keeps_other_panels_and_replaces_ours():
    base = {"model_version": "pfoi-1.2.0-dev", "origin_date": "2026-09-01",
            "generations": [{"g": 1}], "fertility": [{"f": 1}],
            "outlook": [{"series": "milk_litres", "forecast": 1.0}, {"series": "abortions", "forecast": 2.0}],
            "attribution": [{"series": "milk_litres", "factor": "thi"}, {"series": "calvings", "factor": "determined"}]}
    d = P.merge_document(base, _doc())
    assert d["generations"] == [{"g": 1}] and d["fertility"] == [{"f": 1}]
    assert {r["series"] for r in d["outlook"]} == {"abortions", "milk_litres", "milking"}
    assert [r for r in d["outlook"] if r["series"] == "milk_litres"][0]["forecast"] == 75000.0
    assert {r["factor"] for r in d["attribution"]} == {"determined", "herd_size"}
    assert d["model_version"] == "pfoi-herd-milk-combined-test" and d["merged_from"] == "pfoi-1.2.0-dev"
    assert d["record_status"] == {"status": "current"}
    empty = P.merge_document(None, _doc())
    assert empty["generations"] == [] and empty["revisions"] == []


def test_publish_is_a_dry_run_unless_asked(tmp_path):
    o, a = _c1()
    P.export_bundle(tmp_path, _doc(), o, a)
    eng = FakeEngine(row=(json.dumps({"model_version": "pfoi-1.2.0-dev", "generations": [1]}),))
    r = P.publish_bundle(tmp_path, publish=False, engine=eng)
    assert not r["published"] and r["merged_into"] is None          # default: no other model's document
    r = P.publish_bundle(tmp_path, publish=False, engine=eng, merge=True)
    assert r["merged_into"] == "pfoi-1.2.0-dev"
    assert not any("INSERT" in s for s, _ in eng.log)
    r = P.publish_bundle(tmp_path, publish=True, engine=eng)
    assert r["published"] and r["written"] == {"outlook": 1, "attribution": 1, "history": 2}
    inserts = [s for s, _ in eng.log if "INSERT" in s]
    assert any("c1_output.outlook" in s for s in inserts) and any("run_document" in s for s in inserts)
    assert all("DELETE" not in s or "model_version = :v" in s for s, _ in eng.log)


def test_demo_bundle_is_never_published(tmp_path):
    o, a = _c1()
    P.export_bundle(tmp_path, _doc(source="demo"), o, a)
    with pytest.raises(ValueError, match="demo"):
        P.publish_bundle(tmp_path, publish=True, engine=FakeEngine())


def test_merge_drops_dated_rows_of_another_forecast_date():
    base = {"model_version": "pfoi-1.2.1-dev", "origin_date": "2026-09-01", "generations": [{"g": 1}],
            "outlook": [{"series": "abortions", "forecast": 2.0}], "realised": [{"x": 1}]}
    ours = dict(_doc(), origin_date="2026-03-01", realised=[{"period": "2026-03-01"}], run_kind="test")
    d = P.merge_document(base, ours)
    assert d["generations"] == [{"g": 1}]                         # undated panel kept
    assert {r["series"] for r in d["outlook"]} == {"milk_litres", "milking"}   # other date's rows dropped
    assert d["realised"] == [{"period": "2026-03-01"}] and d["run_kind"] == "test"


def test_missing_core_version_is_filled_from_the_publish_log(tmp_path):
    o, a = _c1()
    P.export_bundle(tmp_path, _doc(), o, a)

    class CoreEngine(FakeEngine):
        def connect(self):
            log = self.log

            class C(FakeConn):
                def execute(self_inner, sql, params=None):
                    log.append((str(sql), params))
                    row = ("p20261019T162835Z",) if "publish_log" in str(sql) else None

                    class R:
                        def first(self):
                            return row
                    return R()
            return C(log)

    eng = CoreEngine()
    r = P.publish_bundle(tmp_path, publish=True, engine=eng)
    assert r["core_version"] == "p20261019T162835Z"
    inserted = [p for s, p in eng.log if "INSERT INTO c1_output.outlook" in s][0]
    assert inserted[0]["core_version"] == "p20261019T162835Z"


def test_publish_all_takes_every_dated_bundle(tmp_path):
    o, a = _c1()
    for day in ("2026-03-01", "2026-04-01"):
        P.export_bundle(tmp_path / day, dict(_doc(), origin_date=day), o.assign(origin_date=day), a.assign(origin_date=day))
    t = P.publish_all(tmp_path, publish=False, merge=False)
    assert list(t["origin_date"]) == ["2026-03-01", "2026-04-01"] and not t["published"].any()


def test_complete_document_builds_missing_panels_without_other_models():
    from datetime import date

    from components.predictive_farm_intelligence.tests.synthetic import FakeHerdSource

    ours = {"source": "model", "model_version": "pfoi-herd-milk-combined-test", "core_version": "c1",
            "origin_date": "2021-10-01", "data_through": "2021-09-30",
            "outlook": [{"origin_date": "2021-10-01", "target_period": "2021-10-01", "grain": "month",
                         "horizon": 1, "series": "milk_litres", "forecast": 1.0, "lower": 0.9, "upper": 1.1,
                         "quality_flag": "high"},
                        {"origin_date": "2021-10-01", "target_period": "2021-10-01", "grain": "month",
                         "horizon": 1, "series": "milking", "forecast": 30.0, "lower": 28.0, "upper": 32.0,
                         "quality_flag": "high"}],
            "actuals": [{"period": "2021-09-01", "grain": "month", "series": "milk_litres", "value": 2.0,
                         "source": "delpro", "scoreable": True}],
            "attribution": [{"series": "milk_litres", "factor": "herd_size", "contribution": 0.1}],
            "realised": [], "record_status": {"status": "current"}}
    d = P.complete_document(FakeHerdSource(), ours, realised_until=date(2022, 1, 1))
    milk = [r for r in d["outlook"] if r["series"] == "milk_litres"]
    assert milk == ours["outlook"][:1]                                   # only our milk rows
    assert [r for r in d["actuals"] if r["series"] == "milk_litres"] == ours["actuals"]
    assert [r for r in d["outlook"] if r["series"] == "milking"] == ours["outlook"][1:]
    assert {"abortions", "other", "mastitis_episodes"} & {r["series"] for r in d["outlook"]}
    assert d["generations"] and d["coverage"] and d["merged_from"] is None
    assert d["model_version"] == "pfoi-herd-milk-combined-test" and d["panels_from"]["computed_at"] == "2021-10-01"
    assert not any(k in d for k in ("corrections", "blend", "qualityBands"))
    assert {r["factor"] for r in d["attribution"] if r["series"] == "milk_litres"} == {"herd_size"}


def test_prune_deletes_only_this_models_other_dates():
    eng = FakeEngine()
    P.prune_dates(eng, "pfoi-herd-milk-combined-test", ["2026-03-01", "2026-09-01"])
    sql = [(s, p) for s, p in eng.log if "DELETE" in s]
    assert len(sql) == 4 and all("model_version = :v" in s for s, _ in sql)
    assert all(p["v"] == "pfoi-herd-milk-combined-test" and p["keep"] == ["2026-03-01", "2026-09-01"] for _, p in sql)


def test_dates_inside_the_training_period_are_never_published(tmp_path):
    o, a = _c1()
    repro = {"selection_train_end": "2020-09-27", "config_hash": "abc"}
    for day, kind in (("2017-04-01", "walk-forward 1"), ("2020-09-01", "validation"),
                      ("2020-10-01", "validation"), ("2021-02-01", "test")):
        doc = dict(_doc(), origin_date=day, run_kind=kind, reproducibility=repro)
        P.export_bundle(tmp_path / day, doc, o.assign(origin_date=day), a.assign(origin_date=day))
    eng = FakeEngine()
    t = P.publish_all(tmp_path, publish=True, engine=eng, prune=True).set_index("folder")
    assert not t.loc["2017-04-01", "published"] and t.loc["2017-04-01", "note"].startswith("refused")
    assert not t.loc["2020-09-01", "published"]                    # on/before training end
    assert t.loc["2020-10-01", "published"] and t.loc["2021-02-01", "published"]
    inserted = {p[0]["origin_date"] for s, p in eng.log if "INSERT INTO c1_output.outlook" in s}
    assert inserted == {"2020-10-01", "2021-02-01"}
    keep = [p["keep"] for s, p in eng.log if s.startswith("DELETE") and "NOT (CAST" in s][0]
    assert keep == ["2020-10-01", "2021-02-01"]                     # earlier walk-forward rows pruned
    with pytest.raises(P.InsideTrainingPeriod):
        P.publish_bundle(tmp_path / "2017-04-01", publish=True, engine=eng)


def _windowed_doc():
    """A document whose heat, breeding, make-up and mastitis rows straddle the validation start."""
    return {"origin_date": "2024-06-01", "reproducibility": {"selection_train_end": "2024-02-14"},
            "repro_timing": [{"period": "2015-2019", "step": "first_ai"},
                             {"period": "2024-02 to 2024-05", "step": "first_ai"}],
            "generation_outcomes": [{"period": "2023-2026", "outcome": "productive_share"}],
            "fertility": [{"period_label": "2020-2022", "generation": "0"},
                          {"period_label": "2024-02 to 2024-05", "generation": "0"}],
            "generations": [{"period": "2024-02-01", "projected": False}, {"period": "2024-03-01", "projected": False},
                            {"period": "2024-07-01", "projected": True}],
            "heat": {"recent": [{"date": "2024-02-14"}, {"date": "2024-02-15"}, {"date": "2024-05-31"}],
                     "hot_run_days": 2, "heat_load_7d": 1.5,
                     "climatology": [{"date": "2024-06-01"}]},
            "actuals": [{"period": "2024-02-01", "series": "mastitis_episodes"},
                        {"period": "2024-03-01", "series": "mastitis_episodes"},
                        {"period": "2018-01-01", "series": "milk_litres"}],
            "outlook": [{"series": "mastitis_episodes", "target_period": "2024-06-01"},
                        {"series": "milk_litres", "target_period": "2024-06-01"}],
            "mastitis_rate_period": "reference 2016-2018 (2016-01 to 2018-12)"}


def test_restrict_panels_drops_everything_before_the_validation_start():
    d = P.restrict_panels(_windowed_doc())
    assert P.validation_start(_windowed_doc()).isoformat() == "2024-02-15"
    assert [r["period"] for r in d["repro_timing"]] == ["2024-02 to 2024-05"]
    assert d["generation_outcomes"] == []                                   # calendar periods go
    assert [r["period_label"] for r in d["fertility"]] == ["2024-02 to 2024-05"]
    assert [r["period"] for r in d["generations"]] == ["2024-03-01", "2024-07-01"]  # whole months; projection kept
    assert [r["date"] for r in d["heat"]["recent"]] == ["2024-02-15", "2024-05-31"]
    assert d["heat"]["climatology"] == [{"date": "2024-06-01"}]             # coming weeks untouched
    assert d["heat"]["hot_run_days"] == 2                                   # last week is inside the window
    early = P.restrict_panels(dict(_windowed_doc(), origin_date="2024-02-20"))
    assert early["heat"]["hot_run_days"] is None and early["heat"]["heat_load_7d"] is None
    assert [(r["series"], r["period"]) for r in d["actuals"]] == [("mastitis_episodes", "2024-03-01"),
                                                                    ("milk_litres", "2018-01-01")]
    assert [r["series"] for r in d["outlook"]] == ["milk_litres"]           # rate from 2016-18: not shown
    assert d["mastitis_rate_period"] == ""
    assert d["panels_window"]["from"] == "2024-02-15" and d["panels_window"]["to"] == "2024-05-31"


def test_restrict_panels_keeps_a_mastitis_rate_from_the_window():
    doc = dict(_windowed_doc(), mastitis_rate_period="records since the validation start (2024-03 to 2024-05)")
    d = P.restrict_panels(doc)
    assert [r["series"] for r in d["outlook"]] == ["mastitis_episodes", "milk_litres"]
    assert d["mastitis_rate_period"] == doc["mastitis_rate_period"]


def test_restrict_panels_leaves_documents_without_a_validation_start():
    doc = {k: v for k, v in _windowed_doc().items() if k != "reproducibility"}
    assert P.restrict_panels(doc) == doc


def test_complete_document_builds_panels_from_the_validation_start_only():
    from datetime import date

    from components.predictive_farm_intelligence.tests.synthetic import FakeHerdSource

    ours = {"source": "model", "model_version": "pfoi-herd-milk-combined-test", "core_version": "c1",
            "origin_date": "2021-10-01", "data_through": "2021-09-30",
            "reproducibility": {"selection_train_end": "2021-03-14"},
            "outlook": [], "actuals": [], "attribution": [], "realised": [], "record_status": {"status": "current"}}
    src = FakeHerdSource()
    d = P.complete_document(src, ours, realised_until=date(2022, 1, 1))
    label = "2021-03 to 2021-09"
    assert d["repro_timing"] and {r["period"] for r in d["repro_timing"]} == {label}
    assert d["generation_outcomes"] and {r["period"] for r in d["generation_outcomes"]} == {label}
    assert d["fertility"] and {r["period_label"] for r in d["fertility"]} == {label}
    assert ("generation_fertility", date(2021, 10, 1), date(2021, 3, 15)) in src.calls  # as known at the date
    assert all(r["projected"] or r["period"] >= "2021-04-01" for r in d["generations"])
    assert d["heat"]["recent"] and min(r["date"] for r in d["heat"]["recent"]) >= "2021-03-15"
    mast = [r for r in d["actuals"] if r["series"] == "mastitis_episodes"]
    assert mast and min(r["period"] for r in mast) >= "2021-04-01"
    assert d["mastitis_rate_period"] == "records since the validation start (2021-04 to 2021-09)"
    assert any(r["series"] == "mastitis_episodes" for r in d["outlook"])   # forecast from the window rate
    assert d["panels_window"]["label"] == label


def test_breeding_queries_filter_from_the_validation_start_and_bind_every_parameter():
    import re
    from datetime import date
    from types import SimpleNamespace

    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    src = SqlHerdSource(None, SimpleNamespace(core_schema="core", model_input_schema="model_input"))
    src._placeholder_free = False
    seen = []
    src._q = lambda sql, **kw: seen.append((sql, kw)) or pd.DataFrame()
    asof, since = date(2024, 6, 1), date(2024, 2, 15)
    src.repro_steps(asof, since=since)
    src.generation_yield(asof, since=since)
    src.generation_days(asof, since=since)
    src.generation_alarms(asof, since=since)
    src.generation_fertility(asof=asof, since=since)
    for sql, kw in seen:
        assert ":since" in sql and kw["since"] == since and kw["plabel"] == "2024-02 to 2024-05"
        assert "2015-2019" not in sql                                    # no calendar periods
        assert set(re.findall(r"(?<!:):(\w+)", sql)) <= set(kw)           # every :param is bound
    repro, fert = seen[0][0], seen[-1][0]
    assert "FROM lac WHERE in_window" in repro and "l.cycle_end_date < CAST(:asof AS date)" in repro
    assert "conception_known_date < CAST(:asof AS date)" in fert and "calving_date < CAST(:asof AS date)" in fert
    seen.clear()
    src.repro_steps(asof)                                                 # unchanged without a window
    assert "2015-2019" in seen[0][0] and "since" not in seen[0][1]
