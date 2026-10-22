"""Stability gate (G1) on SYNTHETIC daily aggregates and error tables (no database)."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.gate import (
    GateConfig, GateFeatures, KEYS, forward_gate, label_rows, run_gate_audit, switch_check,
)

START, END = date(2015, 8, 1), date(2024, 1, 1)
# synthetic unstable spells (fictional, not Farm X): daily yield per cow is volatile and the base
# model errs about +-15 % instead of +-3 % for forecasts issued inside them (detectable at the
# forecast date by construction)
SPELLS = ((date(2017, 5, 1), date(2017, 10, 1)), (date(2018, 9, 1), date(2018, 12, 1)),
          (date(2019, 4, 1), date(2019, 7, 1)), (date(2020, 9, 1), date(2021, 1, 15)),
          (date(2021, 8, 1), date(2021, 11, 1)), (date(2022, 3, 1), date(2022, 8, 1)),
          (date(2023, 5, 1), date(2023, 9, 1)))
WEEKLY_H = {"daily": (1, 7, 14), "weekly": (1, 4, 8, 13)}
MONTHLY_H = (1, 3, 6, 12)
FAST = GateConfig(markov=False)


def _unstable(day) -> bool:
    return any(s <= day < e for s, e in SPELLS)


def _daily(seed=0, gap=None):
    rng = np.random.default_rng(seed)
    days = pd.date_range(START, END - timedelta(days=1))
    sd = np.where([_unstable(x) for x in days.date], 0.10, 0.02)
    ypc = 10 * np.exp(rng.normal(0, 1, len(days)) * sd)
    d = pd.DataFrame(dict(date=days.date, milking=500.0, target_litres=500.0 * ypc, is_scoreable=True,
                          data_gap=0, identified_share=0.8, n_herd=900.0,
                          target_source=np.where(days < "2020-08-01", "shipment", "delpro")))
    if gap is not None:
        m = (d["date"] >= gap[0]) & (d["date"] < gap[1])
        d.loc[m, ["target_litres"]] = np.nan
        d.loc[m, "is_scoreable"] = False
        d.loc[m, "data_gap"] = 1
    return d


def _periods():
    out = []
    for o in pd.date_range("2017-01-02", "2023-12-25", freq="W-MON"):
        for h in WEEKLY_H["daily"]:
            s = o + pd.Timedelta(days=int(h) - 1)
            out.append(("daily", h, o, s, s + pd.Timedelta(days=1)))
        for h in WEEKLY_H["weekly"]:
            s = o + pd.Timedelta(days=7 * (int(h) - 1))
            out.append(("weekly", h, o, s, s + pd.Timedelta(days=7)))
    for o in pd.date_range("2017-01-01", "2023-12-01", freq="MS"):
        for h in MONTHLY_H:
            s = o + pd.DateOffset(months=h - 1)
            out.append(("monthly", h, o, s, s + pd.DateOffset(months=1)))
    return out


def _errors(daily, noise_only=False, seed=1):
    """Base model errs ~3 % normally, ~15 % for forecasts issued in an unstable spell; with
    ``noise_only`` its error size is unrelated to anything known at the origin. Alternative
    'alt_steady' errs ~6 % everywhere (worse when stable, better when unstable)."""
    rng = np.random.default_rng(seed)
    s = pd.Series(daily["target_litres"].to_numpy(), index=pd.to_datetime(daily["date"]))
    cum = s.cumsum()
    rows = []
    for grain, h, o, ps, pe in _periods():
        if pe > pd.Timestamp(END):
            continue
        actual = float(cum.loc[pe - pd.Timedelta(days=1)] - (cum.loc[ps - pd.Timedelta(days=1)]
                                                            if ps > s.index[0] else 0.0))
        sd = 0.08 if noise_only else (0.15 if _unstable(o.date()) else 0.03)
        base = actual * float(np.exp(rng.normal(0, sd)))
        alt = actual * float(np.exp(rng.normal(0, 0.06)))
        for model, f in (("milk_baseline_adaptive", base), ("alt_steady", alt),
                         ("persistence", actual)):
            rows.append(dict(origin=o.date(), grain=grain, horizon=h, period_start=ps.date(),
                             period_end=pe.date(), series="herd_milk", model=model,
                             forecast=f, actual=actual))
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def signal_case():
    d = _daily()
    return d, _errors(d)


def test_untrusted_periods_are_never_labels(signal_case):
    _, e = signal_case
    e = e.assign(band=np.where(e["horizon"] % 2 == 0, "unverified", "normal"))
    lab = label_rows(e, "milk_baseline_adaptive")
    assert set(lab["band"]) == {"normal"}
    assert set(lab["horizon"] % 2) == {1}
    assert {"miss", "log_err", "horizon_days"} <= set(lab.columns)


def test_features_use_only_days_and_errors_before_the_origin(signal_case):
    d, e = signal_case
    origin = date(2021, 10, 4)
    lab = label_rows(e, "milk_baseline_adaptive")
    a = GateFeatures(d, lab, GateConfig(markov=True)).row(origin)
    d2 = d.copy()
    late = pd.to_datetime(d2["date"]).dt.date >= origin
    d2.loc[late, "target_litres"] *= 3
    d2.loc[late, "milking"] *= 0.5
    d2.loc[late, "target_source"] = "delpro_new"
    lab2 = lab.copy()
    later = lab2["period_end"] > origin
    lab2.loc[later, "log_err"] += 1.0
    b = GateFeatures(d2, lab2, GateConfig(markov=True)).row(origin)
    for k in a:
        assert (np.isnan(a[k]) and np.isnan(b[k])) or a[k] == pytest.approx(b[k], abs=1e-12), k
    assert np.isfinite(a["ms_unstable_prob"])  # the Markov feature was actually computed


def test_missing_records_stay_missing_not_zero():
    d = _daily(gap=(date(2020, 1, 1), date(2020, 5, 1)))
    lab = label_rows(_errors(_daily()), "milk_baseline_adaptive")
    r = GateFeatures(d, lab, FAST).row(date(2020, 4, 20))
    assert np.isnan(r["ypc_change_28d"]) and np.isnan(r["ypc_vol_28d"])
    assert r["trusted_share_28d"] == 0.0
    assert r["days_since_trusted"] > 100


def test_gate_detects_planted_instability_and_passes_go_rule(signal_case):
    d, e = signal_case
    audit = run_gate_audit(e, d, "milk_baseline_adaptive", alternatives=("alt_steady",), cfg=FAST)
    overall = audit.scores_by_year[audit.scores_by_year["fold_year"] == "all"].set_index("gate")
    for g in ("logistic", "lgbm"):
        assert overall.loc[g, "auc"] > 0.75
        assert overall.loc[g, "brier_skill"] > 0.1
    assert audit.go
    # the target table: long-horizon cells flagged, interval brackets the estimate
    t = audit.auc_target
    assert set(map(tuple, t.loc[t["long"], ["grain", "horizon"]].to_numpy())) == {
        ("weekly", 13), ("monthly", 6), ("monthly", 12)}
    ok = t.dropna(subset=["auc_lo"])
    assert ((ok["auc_lo"] <= ok["auc"] + 1e-12) & (ok["auc"] <= ok["auc_hi"] + 1e-12)).all()
    # week 13 (about 250 forecasts) can show the 0.80 target with its interval; monthly cells
    # (about 50 forecasts, under 10 misses) cannot: even this detectable-by-construction case
    # gives month-12 intervals about 0.35 wide, so a monthly AUC claim needs more periods
    w13 = t[(t["grain"] == "weekly") & (t["horizon"] == 13)]
    assert w13["lower_end_reaches"].all()
    m12 = t[(t["grain"] == "monthly") & (t["horizon"] == 12)]
    assert ((m12["auc_hi"] - m12["auc_lo"]) > 0.25).all()
    # switching to the in-fold chosen alternative raises the hit rate overall
    sw = audit.switch
    assert (sw["hit_switch"] * sw["n"]).sum() > (sw["hit_base"] * sw["n"]).sum()
    assert (sw["hit_ceiling_hindsight"] >= sw["hit_switch"] - 1e-12).all()
    # aggregate outputs carry no forecast dates
    for frame in (audit.scores_by_year, audit.scores_by_cell, audit.features, audit.switch, audit.verdict,
                  audit.auc_target):
        assert "origin" not in frame.columns


def test_pure_noise_gives_no_skill_and_fails_go_rule():
    d = _daily(seed=3)
    e = _errors(d, noise_only=True, seed=4)
    audit = run_gate_audit(e, d, "milk_baseline_adaptive", cfg=FAST)
    overall = audit.scores_by_year[audit.scores_by_year["fold_year"] == "all"].set_index("gate")
    for g in ("logistic", "lgbm"):
        assert 0.4 < overall.loc[g, "auc"] < 0.6
    assert not audit.go


def test_fold_uses_only_labels_ended_before_the_year_and_later_outcomes_change_nothing(signal_case):
    d, e = signal_case
    lab = label_rows(e, "milk_baseline_adaptive")
    X = GateFeatures(d, lab, FAST).matrix(lab)
    pred, folds = forward_gate(lab, X, FAST, fold_years=(2021,))
    assert folds.loc[0, "last_train_period_end"] <= date(2021, 1, 1)
    first = min(pred["origin"])
    # change every outcome whose period ends after the first 2021 forecast date
    e2 = e.copy()
    late = pd.to_datetime(e2["period_end"]).dt.date > first
    e2.loc[late, "actual"] *= 1.5
    lab2 = label_rows(e2, "milk_baseline_adaptive")
    X2 = GateFeatures(d, lab2, FAST).matrix(lab2)
    pred2, _ = forward_gate(lab2, X2, FAST, fold_years=(2021,))
    a = pred[pred["origin"] == first].set_index(KEYS).sort_index()
    b = pred2[pred2["origin"] == first].set_index(KEYS).sort_index()
    for c in ("p_base_rate", "p_logistic", "p_lgbm"):
        np.testing.assert_allclose(a[c].to_numpy(), b[c].to_numpy(), rtol=0, atol=1e-12)


def test_persistence_is_never_a_specialist(signal_case):
    d, e = signal_case
    lab = label_rows(e, "milk_baseline_adaptive")
    pred = pd.DataFrame({**{k: lab[k] for k in KEYS}, "fold_year": 2021, "miss": lab["miss"],
                         "forecast": lab["forecast"], "actual": lab["actual"], "p_lgbm": 1.0})
    with pytest.raises(ValueError):
        switch_check(pred, lab, {"persistence": e[e["model"] == "persistence"]})


def test_gate_audit_command_end_to_end_with_mocked_source(tmp_path, monkeypatch, capsys):
    from components.predictive_farm_intelligence.pfoi import cli

    d = _daily()
    e = _errors(d)
    raw = e[e["model"] == "alt_steady"].assign(model="milk_baseline")
    adapt_tag, raw_tag = "synthetic_ad", "synthetic"
    for tag, frame in ((adapt_tag, e), (raw_tag, raw)):
        monthly = frame["grain"] == "monthly"
        frame[monthly].to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}.csv", index=False)
        frame[~monthly].to_csv(tmp_path / f"milk_backtest_errors_weekly_{tag}.csv", index=False)

    class FakeSource:
        def target_daily(self, start, end):
            return d[["date", "target_source", "target_litres", "is_scoreable", "identified_share", "data_gap"]]

        def panel_daily(self, start, end):
            return d[["date", "milking", "n_herd"]]

        def driver_daily(self, start, end):
            return d[["date", "milking", "identified_share", "target_litres", "is_scoreable"]]

    monkeypatch.setattr(cli.SqlHerdSource, "from_env", classmethod(lambda cls: FakeSource()))
    rc = cli.main(["gate-audit", "--tag", adapt_tag, "--alt-tag", raw_tag, "--no-markov",
                   "--out", str(tmp_path)])
    text = capsys.readouterr().out
    assert rc == 0
    assert "Verdict: GO" in text
    assert "persistence" not in pd.read_csv(tmp_path / f"gate_switch_{adapt_tag}_milk_baseline_adaptive.csv").to_string()
    for f in ("folds", "scores", "features", "switch", "auc_target"):
        frame = pd.read_csv(tmp_path / f"gate_{f}_{adapt_tag}_milk_baseline_adaptive.csv")
        assert "origin" not in frame.columns


def test_classification_report_counts_and_chart(tmp_path, signal_case):
    from components.predictive_farm_intelligence.pfoi.gate import classification_report, plot_confusion

    pred = pd.DataFrame(dict(grain="weekly", horizon=[1, 1, 1, 1, 4, 4], miss=[1, 0, 1, 0, 1, 0],
                             p_logistic=[0.9, 0.2, 0.3, 0.7, 0.8, 0.1]))
    r = classification_report(pred, ("logistic",)).iloc[0]
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2, 1, 1, 2)
    assert r["accuracy"] == pytest.approx(4 / 6) and r["recall"] == pytest.approx(2 / 3)
    assert r["mae"] == pytest.approx(np.mean([0.1, 0.2, 0.7, 0.7, 0.2, 0.1]))
    plot_confusion(classification_report(pred, ("logistic",)), tmp_path / "cm.png")
    assert (tmp_path / "cm.png").exists()
