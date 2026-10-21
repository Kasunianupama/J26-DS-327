"""Live M10 adapter: fictional synthetic inputs only, no database."""
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.live_persistence import MODEL, attach_live_persistence
from components.predictive_farm_intelligence.pfoi.outlook import OutputLayer

ORIGIN = date(2021, 10, 1)


def errors():
    rows = []
    for grain in ("daily", "weekly"):
        for h in (1, 7) if grain == "daily" else (1, 4):
            for o in pd.date_range("2020-01-01", periods=15, freq="7D"):
                for model, f in (("milk_baseline_adaptive", 120.), ("persistence", 110.)):
                    rows.append(dict(origin=o, period_start=o, period_end=o.to_pydatetime() + timedelta(days=7),
                                     grain=grain, horizon=h, series="herd_milk", model=model,
                                     forecast=f, actual=100.))
    return pd.DataFrame(rows)


def target():
    return pd.DataFrame(dict(date=pd.date_range("2021-08-01", "2021-10-10"),
                             target_litres=100., is_scoreable=True, target_source="delpro"))


def run(t=None):
    t = target() if t is None else t
    return SimpleNamespace(origin=ORIGIN, layer=OutputLayer({}, {}, ("milking",)),
                           hist=SimpleNamespace(target_before=lambda origin: t), reconciled=False,
                           version="pfoi-1.1.0")


def test_same_m10_weights_reference_units_and_unchanged_monthly_herd():
    r = run()
    e = attach_live_persistence(r, errors())
    assert MODEL in set(e.model)
    assert r.layer.adjust("daily", "herd_milk", 1, 120.) == pytest.approx(320 / 3)
    assert r.layer.persistence.detail("weekly", 2)["scored_horizon"] == 4
    assert r.layer.persistence.detail("weekly", 2)["persistence"] == 700.
    assert r.layer.adjust("monthly", "herd_milk", 1, 3000.) == 3000.
    assert r.layer.adjust("weekly", "milking", 1, 100.) == 100.
    assert r.layer.model_for("herd_milk", "milk_baseline", "weekly") == MODEL
    assert r.layer.model_for("herd_milk", "milk_baseline", "monthly") == "milk_baseline_adaptive"
    assert r.version == "pfoi-1.2.0-dev-persistence"


def test_future_actuals_and_future_reference_days_cannot_change_output():
    a, b = run(), run(target().assign(target_litres=lambda x:
        np.where(x.date >= pd.Timestamp(ORIGIN), 1e12, x.target_litres)))
    e = errors()
    future = e.assign(origin=pd.Timestamp("2021-09-01"),
                      period_start=pd.Timestamp("2021-09-01"),
                      period_end=pd.Timestamp("2021-12-01"), actual=1e12)
    # One future-ended pair per grain/horizon/model, no duplicate forecast keys.
    future = future.drop_duplicates(["grain", "horizon", "model"])
    attach_live_persistence(a, e)
    attach_live_persistence(b, pd.concat([e, future], ignore_index=True))
    assert a.layer.persistence.audit() == b.layer.persistence.audit()


def test_missing_reference_and_short_history_keep_adaptive():
    r = run(target().assign(is_scoreable=False))
    attach_live_persistence(r, errors())
    assert r.layer.adjust("daily", "herd_milk", 1, 120.) == 120.
    assert r.layer.persistence.audit()["fallback"] == "no_persistence_reference"
    r = run()
    attach_live_persistence(r, errors().iloc[:2])
    assert r.layer.adjust("daily", "herd_milk", 1, 120.) == 120.


def test_duplicates_and_reconciliation_refused():
    with pytest.raises(ValueError, match="duplicate"):
        attach_live_persistence(run(), pd.concat([errors(), errors()]))
    r = run()
    r.reconciled = True
    with pytest.raises(ValueError, match="unreconciled"):
        attach_live_persistence(r, errors())


def test_cli_rejects_unsupported_mode_before_any_source_access(monkeypatch):
    from components.predictive_farm_intelligence.pfoi import cli
    monkeypatch.setattr(cli, "_source", lambda args: pytest.fail("must not open source"))
    assert cli.main(["build-outlook", "--persistence-blend", "on", "--preset", "pfoi-1.1.1"]) == 2


def test_cli_default_is_off_and_frozen_layer_is_unchanged(monkeypatch):
    from components.predictive_farm_intelligence.pfoi import cli
    captured = []
    monkeypatch.setattr(cli, "_cmd_build_outlook", lambda args: captured.append(args) or 0)
    assert cli.main(["build-outlook", "--preset", "pfoi-1.1"]) == 0
    assert captured[0].persistence_blend == "off"
    assert not cli._pp1_dev(captured[0])
    layer = OutputLayer({}, {("daily", 1): .1}, ())
    assert layer.persistence is None
    assert layer.adjust("daily", "herd_milk", 1, 100.) == pytest.approx(110.)


def test_withheld_milk_is_not_given_a_persistence_reference():
    r = run()
    r.milk_withheld = "milk_withheld:no_trusted_recent_days"
    attach_live_persistence(r, errors())
    assert r.layer.persistence.reference is None
    assert r.layer.persistence.audit()["fallback"] == r.milk_withheld


def test_table_page_forecasts_and_audit_agree():
    from components.predictive_farm_intelligence.pfoi.config import EngineConfig
    from components.predictive_farm_intelligence.pfoi.milk_baseline import MilkConfig
    from components.predictive_farm_intelligence.pfoi.outlook import build_outlook, run_model
    from components.predictive_farm_intelligence.pfoi.page_run import build_page_run
    from .synthetic import FakeHerdSource
    src = FakeHerdSource()
    r = run_model(src, ORIGIN, EngineConfig(), MilkConfig(k_mode="anchor_first"))
    r.layer = OutputLayer({}, {}, ())
    original_month = r.period_value("monthly", 1, "herd_milk", False)
    e = attach_live_persistence(r, errors())
    table, attr, _ = build_outlook(src, ORIGIN, e, "synthetic", run=r)
    doc = build_page_run(src, r, attr, {}, "synthetic", interval_errors=e)
    for row in doc["outlook"]:
        if row["series"] != "milk_litres":
            continue
        grain = {"day": "daily", "week": "weekly", "month": "monthly"}[row["grain"]]
        matching = table[(table.series == "herd_milk") & (table.grain == grain)
                         & (table.horizon == row["horizon"])].iloc[0]
        assert row["forecast"] == pytest.approx(matching.forecast, abs=.001)
        if np.isfinite(matching.lower):
            assert row["lower"] == pytest.approx(matching.lower, abs=.001)
            assert row["upper"] == pytest.approx(matching.upper, abs=.001)
    assert r.period_value("monthly", 1, "herd_milk", False) == original_month
    assert doc["blend"]["partners"] == ["persistence"]
    assert doc["blend"]["grains"]["daily"][0]["weight"] == pytest.approx(1 / 3)
    assert doc["model_version"] == "pfoi-1.2.0-dev-persistence"
    for correction in doc["corrections"]:
        row = next(x for x in doc["outlook"] if x["series"] == correction["series"]
                   and x["grain"] == correction["grain"] and x["horizon"] == correction["horizon"])
        assert correction["structural"] + correction["correction"] == pytest.approx(row["forecast"], abs=.002)
