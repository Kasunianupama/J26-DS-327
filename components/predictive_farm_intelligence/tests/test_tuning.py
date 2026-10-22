"""Nested hyperparameter tuning of the gate and the Track A switch, on SYNTHETIC data (no database)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.gate import GateFeatures, KEYS, label_rows
from components.predictive_farm_intelligence.pfoi.specialists import TRACK_A_CELLS
from components.predictive_farm_intelligence.pfoi.tuning import (
    GAPS, gate_grid, inner_split, tuned_gate, tuned_gate_scores, tuned_track_a,
)
from components.predictive_farm_intelligence.tests.test_gate import FAST, _daily, _errors


@pytest.fixture(scope="module")
def case():
    d = _daily()
    e = _errors(d)
    lab = label_rows(e, "milk_baseline_adaptive")
    X = GateFeatures(d, lab, FAST).matrix(lab)
    return d, e, lab, X


def test_inner_split_is_chronological_with_horizon_embargo(case):
    _, _, lab, _ = case
    inner, tr, va, vstart = inner_split(lab, 2021)
    ends = pd.to_datetime(lab["period_end"])
    assert (ends[inner] <= pd.Timestamp(2021, 1, 1)).all()
    assert (pd.to_datetime(lab.loc[va, "origin"]) >= vstart).all()
    gap = lab.loc[tr, "grain"].map(GAPS)
    assert (ends[tr] + pd.to_timedelta(gap, unit="D") <= vstart).all()
    assert not (tr & va).any()
    span = pd.Timestamp(2021, 1, 1) - pd.to_datetime(lab.loc[inner, "origin"]).min()
    assert (pd.Timestamp(2021, 1, 1) - vstart) / span == pytest.approx(0.2)


def test_grid_starts_with_the_g1_defaults():
    g = gate_grid()
    assert g[0][0] == "logistic" and g[1][0] == "lgbm"
    assert len(g) == len(set(g)) >= 20


def test_tuned_gate_learns_planted_signal_and_reports_choices(case):
    _, _, lab, X = case
    tg = tuned_gate(lab, X)
    sc = tuned_gate_scores(tg.predictions).set_index(["fold_year", "gate"])
    assert sc.loc[("all", "tuned"), "auc"] > 0.75
    assert sc.loc[("all", "tuned"), "brier_skill"] > 0.1
    assert set(tg.folds["fold_year"]) == {2019, 2020, 2021, 2022, 2023}
    assert tg.folds["chosen"].notna().all() and len(tg.grid_scores)
    assert "origin" not in tg.folds.columns and "origin" not in tg.grid_scores.columns


def test_tuning_never_sees_the_outer_year(case):
    d, e, lab, X = case
    a = tuned_gate(lab, X, fold_years=(2021,))
    first = min(a.predictions["origin"])
    e2 = e.copy()
    later = pd.to_datetime(e2["period_end"]).dt.date > first
    e2.loc[later, "actual"] *= 1.5
    lab2 = label_rows(e2, "milk_baseline_adaptive")
    X2 = GateFeatures(d, lab2, FAST).matrix(lab2)
    b = tuned_gate(lab2, X2, fold_years=(2021,))
    assert a.folds["chosen"].iloc[0] == b.folds["chosen"].iloc[0]
    pa = a.predictions[a.predictions["origin"] == first].set_index(KEYS)["p_tuned"].sort_index()
    pb = b.predictions[b.predictions["origin"] == first].set_index(KEYS)["p_tuned"].sort_index()
    np.testing.assert_allclose(pa.to_numpy(), pb.to_numpy(), atol=1e-12)


def test_tuned_track_a_switches_only_track_a_cells_and_picks_from_the_grid(case):
    _, e, lab, X = case
    raw = e[e["model"] == "alt_steady"].assign(model="milk_baseline")
    tg = tuned_gate(lab, X)
    rows, choice, grid = tuned_track_a(raw, tg)
    assert set(choice["window"]) <= {7, 14, 28} and set(choice["threshold"]) <= {0.3, 0.4, 0.5, 0.6, 0.7}
    sw = rows[rows["switched"]]
    assert len(sw) and set(zip(sw["grain"], sw["horizon"])) <= set(TRACK_A_CELLS)
    # in this world the alternative is better when unstable, so the tuned switch must help
    hit = lambda f: ((f["forecast"] - f["actual"]).abs() / f["actual"] <= 0.1 + 1e-9).mean()  # noqa: E731
    assert hit(rows) > hit(tg.predictions)


def _b_inputs():
    from components.predictive_farm_intelligence.tests import test_specialists as ts

    d = ts._daily()
    base = ts._rows(d, model="milk_baseline_adaptive")
    herd = base.assign(series="milking", model="herd_engine", forecast=400.0, actual=400.0)
    preds = {"median": lambda ctx, steps: np.array([np.full(steps, c[np.isfinite(c)][-1]) for c in ctx]),
             "mean": lambda ctx, steps: np.array([np.full(steps, np.nanmean(c)) for c in ctx])}
    return d, base, herd, preds


def test_context_mode_all_reaches_back_across_the_source_switch():
    from components.predictive_farm_intelligence.pfoi.specialists import contexts, weekly_series
    from components.predictive_farm_intelligence.tests import test_specialists as ts

    wk = weekly_series(ts._daily())
    cur, _ = contexts(wk, date(2021, 9, 1), "ypc", mode="current")
    allv, _ = contexts(wk, date(2021, 9, 1), "ypc", mode="all")
    assert len(allv) > len(cur)


def test_tuned_track_b_choices_are_nested_and_outcome_blind():
    from components.predictive_farm_intelligence.pfoi.specialists import weekly_series
    from components.predictive_farm_intelligence.pfoi.tuning import B_SETTINGS, b_label, tuned_track_b

    d, base, herd, preds = _b_inputs()
    wk = weekly_series(d)
    rows, choice, hind = tuned_track_b(base, herd, wk, preds)
    assert set(choice["chosen"]) <= {b_label(s) for s in B_SETTINGS}
    assert len(hind) == len(B_SETTINGS)
    yrs = pd.to_datetime(rows["origin"]).dt.year
    assert yrs.min() >= 2019 and set(rows["model"]) == {"chronos2_tuned"}
    # after the synthetic jump the latest-value point beats the context mean, and tuning finds it
    assert choice.set_index("fold_year").loc[2022, "chosen"].endswith("/median")
    # outcomes of periods ending after 1 Jan 2022 cannot change the 2022 choice
    base2 = base.copy()
    late = pd.to_datetime(base2["period_end"]) > pd.Timestamp(2022, 1, 1)
    base2.loc[late, "actual"] *= 3
    _, choice2, _ = tuned_track_b(base2, herd, wk, preds, fold_years=(2022,))
    assert choice2["chosen"].iloc[0] == choice.set_index("fold_year").loc[2022, "chosen"]


def test_tune_commands_end_to_end_with_mocked_source(tmp_path, monkeypatch, capsys):
    from components.predictive_farm_intelligence.pfoi import cli, specialists

    d = _daily()
    e = _errors(d)
    raw = e[e["model"] == "alt_steady"].assign(model="milk_baseline")
    for tag, frame in (("s_ad", e), ("s", raw)):
        m = frame["grain"] == "monthly"
        frame[m].to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}.csv", index=False)
        frame[~m].to_csv(tmp_path / f"milk_backtest_errors_weekly_{tag}.csv", index=False)
    herd = e[e["model"] == "milk_baseline_adaptive"].assign(series="milking", model="herd_engine",
                                                             forecast=500.0, actual=500.0)
    for g in ("monthly", "weekly"):
        part = herd[(herd["grain"] == "monthly") == (g == "monthly")]
        part.to_csv(tmp_path / f"herd_backtest_errors_{g}_h.csv", index=False)

    class FakeSource:
        def target_daily(self, start, end):
            return d[["date", "target_source", "target_litres", "is_scoreable", "identified_share", "data_gap"]]

        def panel_daily(self, start, end):
            return d[["date", "milking", "n_herd"]]

        def driver_daily(self, start, end):
            return d[["date", "milking", "identified_share", "target_litres", "is_scoreable"]]

    monkeypatch.setattr(cli.SqlHerdSource, "from_env", classmethod(lambda cls: FakeSource()))
    assert cli.main(["tune-gate", "--tag", "s_ad", "--raw-tag", "s", "--no-markov", "--out", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "chosen setting per fold year" in text and "Verdict:" in text
    for f in ("tune_gate_folds", "tune_gate_grid", "tune_gate_scores", "tune_track_a_choice"):
        assert "origin" not in pd.read_csv(tmp_path / f"{f}_s_ad_milk_baseline_adaptive.csv").columns

    monkeypatch.setattr(specialists, "chronos2_pipeline", lambda *a, **k: None)
    monkeypatch.setattr(specialists, "predictor_from", lambda pipe, point="median": (
        lambda ctx, steps: np.array([np.full(steps, c[np.isfinite(c)][-1]) for c in ctx])))
    assert cli.main(["specialist-b", "--tune", "--tag", "s_ad", "--herd-tag", "h", "--out", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert "chosen setting per fold year" in text and "Verdict:" in text
