"""pfoi-1.2.1-dev page documents and compare chart markers, on SYNTHETIC data (no database)."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.gate import GateFeatures, label_rows
from components.predictive_farm_intelligence.pfoi.gate_outlook import calibration_flags, gate_document, run
from components.predictive_farm_intelligence.pfoi.outlook import period_starts
from components.predictive_farm_intelligence.pfoi.periods import period_bounds
from components.predictive_farm_intelligence.tests.test_gate import FAST, _daily, _errors

ORIGIN = date(2022, 3, 1)


def _doc(origin=ORIGIN):
    rows = []
    for g, gm, hs in (("week", "weekly", (1, 4, 8, 13)), ("month", "monthly", (1, 3, 6, 12))):
        for h in hs:
            s, _ = period_bounds(period_starts(origin)[gm], gm, h)
            for sid, f in (("milk_litres", 100000.0 if g == "month" else 25000.0), ("milking", 500.0)):
                rows.append(dict(origin_date=origin.isoformat(), target_period=s.isoformat(), grain=g, horizon=h,
                                 series=sid, forecast=f, lower=0.9 * f, upper=1.1 * f, model_version="pfoi-1.2.0-dev"))
    return {"origin_date": origin.isoformat(), "model_version": "pfoi-1.2.0-dev", "outlook": rows,
            "actuals": [], "realised": [], "interval_method": {"milk": "own past errors"}}


@pytest.fixture(scope="module")
def parts():
    d = _daily()
    e = _errors(d)
    lab = label_rows(e, "milk_baseline_adaptive")
    feats = GateFeatures(d, lab, FAST)
    X = feats.matrix(lab)
    return d, e, lab, feats, X, calibration_flags(lab, X, 2023, FAST)


def test_forecasts_unchanged_flags_added_milk_ranges_replaced_herd_ranges_kept(parts):
    _, _, lab, feats, X, cal = parts
    doc = _doc()
    new = gate_document(doc, lab, X, feats, cal)
    assert new["model_version"] == "pfoi-1.2.1-dev" and "gate" in new
    for a, b in zip(doc["outlook"], new["outlook"]):
        assert a["forecast"] == b["forecast"]
        assert b["confidence"] in ("low", "normal") and 0 <= b["p_gate"] <= 1
        if a["series"] == "milking":
            assert (a["lower"], a["upper"]) == (b["lower"], b["upper"])
    milk = [(a, b) for a, b in zip(doc["outlook"], new["outlook"]) if a["series"] == "milk_litres"]
    assert any((a["lower"], a["upper"]) != (b["lower"], b["upper"]) for a, b in milk)
    assert all(b["lower"] <= b["forecast"] <= b["upper"] for _, b in milk)


def test_document_uses_nothing_after_its_forecast_date(parts):
    d, e, _, _, _, _ = parts
    def build(errors):
        lab = label_rows(errors, "milk_baseline_adaptive")
        feats = GateFeatures(d, lab, FAST)
        X = feats.matrix(lab)
        return gate_document(_doc(), lab, X, feats, calibration_flags(lab, X, 2022, FAST))
    a = build(e)
    e2 = e.copy()
    later = pd.to_datetime(e2["period_end"]).dt.date > ORIGIN
    e2.loc[later, "actual"] *= 1.7
    b = build(e2)
    for x, y in zip(a["outlook"], b["outlook"]):
        assert (x["p_gate"], x["lower"], x["upper"]) == (y["p_gate"], y["lower"], y["upper"])


def test_run_writes_documents_and_compare_chart_marks_low_confidence(tmp_path, parts):
    from components.predictive_farm_intelligence.pfoi.compare_runs import forecasts, plot_versions

    d, e, *_ = parts
    src = tmp_path / "outlook" / "pfoi-1.2.0-dev"
    src.mkdir(parents=True)
    for o in (date(2021, 9, 1), ORIGIN):
        (src / f"run_{o:%Y%m}.json").write_text(json.dumps(_doc(o)))
    assert run(tmp_path, "pfoi-1.2.0-dev", e, d, markov=False) == 0
    new = json.loads((tmp_path / "outlook" / "pfoi-1.2.1-dev" / f"run_{ORIGIN:%Y%m}.json").read_text())
    f = forecasts(new, "month")
    assert "confidence" in f.columns
    old = json.loads((src / f"run_{ORIGIN:%Y%m}.json").read_text())
    path = tmp_path / "chart.png"
    plot_versions([("pfoi-1.2.0-dev", old), ("pfoi-1.2.1-dev", new)], ORIGIN, path)
    assert path.exists() and path.stat().st_size > 0


def test_gate_outlook_and_gate_intervals_commands(tmp_path, monkeypatch, capsys, parts):
    from components.predictive_farm_intelligence.pfoi import cli

    d, e, lab, *_ = parts
    tag = "t_ad"
    m = e["grain"] == "monthly"
    e[m].to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}.csv", index=False)
    e[~m].to_csv(tmp_path / f"milk_backtest_errors_weekly_{tag}.csv", index=False)
    probs = lab[["grain", "horizon", "origin", "period_start"]].copy()
    probs = probs[pd.to_datetime(probs["origin"]).dt.year >= 2019]
    probs["p_logistic"] = 0.3
    probs.to_csv(tmp_path / f"gate_probs_{tag}_milk_baseline_adaptive.csv", index=False)
    src = tmp_path / "outlook" / "pfoi-1.2.0-dev"
    src.mkdir(parents=True)
    (src / f"run_{ORIGIN:%Y%m}.json").write_text(json.dumps(_doc()))

    class FakeSource:
        def target_daily(self, s, t):
            return d[["date", "target_source", "target_litres", "is_scoreable", "identified_share", "data_gap"]]

        def panel_daily(self, s, t):
            return d[["date", "milking", "n_herd"]]

        def driver_daily(self, s, t):
            return d[["date", "milking", "identified_share", "target_litres", "is_scoreable"]]

    monkeypatch.setattr(cli.SqlHerdSource, "from_env", classmethod(lambda cls: FakeSource()))
    assert cli.main(["gate-outlook", "--tag", tag, "--no-markov", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "outlook" / "pfoi-1.2.1-dev" / f"run_{ORIGIN:%Y%m}.json").exists()
    capsys.readouterr()
    assert cli.main(["gate-intervals", "--tag", tag, "--herd-tag", "none", "--out", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "pre-registered 1.2.1-dev rule" in text and "Verdict:" in text
