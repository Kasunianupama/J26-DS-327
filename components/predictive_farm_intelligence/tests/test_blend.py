"""Persistence blend (pfoi/blend.py) on SYNTHETIC error tables."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.blend import MIN_OBS, persistence_blend

BASE = "milk_baseline_adaptive"


def _table(n=40, struct=110.0, pers=105.0, actual=100.0, grain="weekly", horizon=1):
    """One weekly origin per week; horizon 1 target = the following week (ends 14 days on)."""
    rows = []
    for i in range(n):
        o = pd.Timestamp(date(2019, 1, 7) + timedelta(days=7 * i))
        common = dict(origin=o, grain=grain, horizon=horizon, period_start=o + pd.Timedelta(days=7),
                      period_end=o + pd.Timedelta(days=14), series="herd_milk", actual=actual,
                      source="delpro", lower=1.0, upper=2.0, covered=1.0)
        rows.append(dict(common, model=BASE, forecast=struct))
        rows.append(dict(common, model="persistence", forecast=pers))
    e = pd.DataFrame(rows)
    e["error"] = e["forecast"] - e["actual"]
    return e


def test_weight_follows_past_mae_ratio():
    out = persistence_blend(_table()).sort_values("origin").reset_index(drop=True)
    # structural MAE 10, persistence MAE 5 -> w = (1/10) / (1/10 + 1/5) = 1/3
    assert out["blend_w"].iloc[-1] == pytest.approx(1 / 3)
    assert out["forecast"].iloc[-1] == pytest.approx(110 / 3 + 105 * 2 / 3)
    assert (out["model"] == f"{BASE}_blend").all()
    assert out["error"].iloc[-1] == pytest.approx(out["forecast"].iloc[-1] - 100)


def test_short_history_keeps_the_structural_forecast():
    out = persistence_blend(_table()).sort_values("origin").reset_index(drop=True)
    # finished forecasts at row i are those of rows 0..i-2, so w is 1 until MIN_OBS are finished
    assert (out["blend_w"].iloc[:MIN_OBS + 1] == 1.0).all()
    assert (out["forecast"].iloc[:MIN_OBS + 1] == 110.0).all()
    assert out["blend_w"].iloc[MIN_OBS + 2] < 1.0


def test_unfinished_outcomes_never_change_the_weight():
    e = _table()
    clean = persistence_blend(e).sort_values("origin").reset_index(drop=True)
    k = 30
    # rows k and k-1 have not finished by origin k (they end 14 and 7 days after their origins)
    late = e["origin"].isin([clean["origin"].iloc[k], clean["origin"].iloc[k - 1]])
    assert late.sum() == 4  # two origins x (structural, persistence): the mask really selects them
    changed = e.copy()
    changed.loc[late, "actual"] = 9999.0
    out = persistence_blend(changed).sort_values("origin").reset_index(drop=True)
    assert out["blend_w"].iloc[k] == pytest.approx(clean["blend_w"].iloc[k])
    # control: a finished outcome (row k-2 ends exactly at origin k) does move it
    done = e["origin"] == clean["origin"].iloc[k - 2]
    moved = e.copy()
    moved.loc[done, "actual"] = 9999.0
    out2 = persistence_blend(moved).sort_values("origin").reset_index(drop=True)
    assert out2["blend_w"].iloc[k] != pytest.approx(clean["blend_w"].iloc[k])


def test_better_persistence_moves_weight_to_persistence_and_perfect_model_keeps_it():
    worse = persistence_blend(_table(struct=130.0, pers=101.0)).sort_values("origin")
    assert worse["blend_w"].iloc[-1] < 0.1
    perfect = persistence_blend(_table(struct=100.0, pers=105.0)).sort_values("origin")
    assert perfect["blend_w"].iloc[-1] > 0.999
    assert perfect["forecast"].iloc[-1] == pytest.approx(100.0, abs=0.01)


def test_monthly_rows_are_left_to_the_structural_model():
    out = persistence_blend(_table(grain="monthly"))
    assert len(out) == 0


def test_periods_without_a_persistence_forecast_are_dropped_and_intervals_reset():
    e = _table()
    e = e[~((e["model"] == "persistence") & (e["origin"] == e["origin"].min()))]
    out = persistence_blend(e)
    assert len(out) == _table()["origin"].nunique() - 1
    assert out["lower"].isna().all() and out["upper"].isna().all() and out["covered"].isna().all()


def test_each_horizon_gets_its_own_weight():
    a = _table(struct=110.0, pers=105.0, horizon=1)
    b = _table(struct=101.0, pers=110.0, horizon=4)
    out = persistence_blend(pd.concat([a, b], ignore_index=True)).sort_values("origin")
    last = out.groupby("horizon")["blend_w"].last()
    assert last[1] < 0.5 < last[4]


def _cmd(tmp_path, tag="t_adhq0.1t365z3", **kw):
    import argparse

    from components.predictive_farm_intelligence.pfoi.cli import _cmd_blend

    args = argparse.Namespace(tag=tag, base=BASE, min_obs=8, out=str(tmp_path), **kw)
    return _cmd_blend(args)


def test_blend_command_writes_both_files_with_plain_dates_and_own_intervals(tmp_path, capsys):
    weekly, monthly = _table(), _table(grain="monthly")
    for df in (weekly, monthly):
        for col in ("origin", "period_start", "period_end"):
            df[col] = df[col].dt.strftime("%Y-%m-%d")      # the backtest files hold plain dates
    tag = "t_adhq0.1t365z3"
    weekly.to_csv(tmp_path / f"milk_backtest_errors_weekly_{tag}.csv", index=False)
    monthly.to_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}.csv", index=False)
    assert _cmd(tmp_path, tag) == 0
    w = pd.read_csv(tmp_path / f"milk_backtest_errors_weekly_{tag}_bl.csv")
    m = pd.read_csv(tmp_path / f"milk_backtest_errors_monthly_{tag}_bl.csv")
    assert f"{BASE}_blend" in set(w["model"]) and f"{BASE}_blend" not in set(m["model"])
    assert {BASE, "persistence"} <= set(w["model"]) | set(m["model"])        # original rows kept
    for col in ("origin", "period_start", "period_end"):
        assert w[col].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()            # no timestamps mixed in
    b = w[w["model"] == f"{BASE}_blend"]
    assert b["lower"].notna().any() and (b["lower"] != 1.0).all()           # own intervals, not copied
    assert "Weight on the structural forecast" in capsys.readouterr().out


def test_blend_command_refuses_non_development_and_blended_tags(tmp_path):
    assert _cmd(tmp_path, "t_posthoc") == 2
    assert _cmd(tmp_path, "t_bl") == 2
    assert _cmd(tmp_path, "t_missing") == 1


def test_regime_report_compares_two_models_from_the_same_files():
    from components.predictive_farm_intelligence.pfoi.regimes import matched_table

    e = _table()
    e["source"] = "shipment"
    blend = persistence_blend(e)
    t = matched_table(pd.concat([e, blend], ignore_index=True), pd.concat([e, blend], ignore_index=True),
                      BASE, f"{BASE}_blend")
    r = t[(t["grain"] == "weekly") & (t["horizon"] == 1)].iloc[0]
    assert r["n_both"] == len(blend) and r["mae_b"] < r["mae_a"]            # persistence is closer here


def test_skill_blend_with_one_partner_equals_the_persistence_blend():
    from components.predictive_farm_intelligence.pfoi.blend import skill_blend

    e = _table(struct=110.0, pers=103.0)
    a = persistence_blend(e).sort_values("origin").reset_index(drop=True)
    b = skill_blend(e, partners=("persistence",)).sort_values("origin").reset_index(drop=True)
    assert np.allclose(a["forecast"], b["forecast"]) and np.allclose(a["blend_w"], b["blend_w"])


def _with_ets(ets=102.0, drop_last_origin=False):
    e = _table(struct=110.0, pers=105.0)
    ets_rows = e[e["model"] == "persistence"].copy()
    ets_rows["model"], ets_rows["forecast"] = "ets", ets
    if drop_last_origin:
        ets_rows = ets_rows[ets_rows["origin"] != ets_rows["origin"].max()]
    return pd.concat([e, ets_rows], ignore_index=True)


def test_three_models_get_weights_proportional_to_inverse_past_mae():
    from components.predictive_farm_intelligence.pfoi.blend import skill_blend

    out = skill_blend(_with_ets(), partners=("persistence", "ets")).sort_values("origin")
    last = out.iloc[-1]
    inv = np.array([1 / 10, 1 / 5, 1 / 2])                     # MAE 10 (structural), 5 (persistence), 2 (ETS)
    w = inv / inv.sum()
    assert (last["blend_w"], last["w_persistence"], last["w_ets"]) == pytest.approx(tuple(w))
    assert last["forecast"] == pytest.approx(float(w @ np.array([110.0, 105.0, 102.0])))


def test_a_partner_without_a_forecast_is_left_out_and_the_rest_renormalised():
    from components.predictive_farm_intelligence.pfoi.blend import skill_blend

    out = skill_blend(_with_ets(drop_last_origin=True), partners=("persistence", "ets")).sort_values("origin")
    last = out.iloc[-1]
    assert last["w_ets"] == 0.0
    assert last["blend_w"] == pytest.approx((1 / 10) / (1 / 10 + 1 / 5))      # as the two-model blend


def test_skill_weights_at_matches_the_row_weights_and_honours_availability():
    from components.predictive_farm_intelligence.pfoi.blend import skill_weights_at

    e = _with_ets()
    origin = e["origin"].max() + pd.Timedelta(days=14)
    full = skill_weights_at(e, origin, "weekly", "herd_milk", base_model=BASE, partners=("persistence", "ets"))
    row = full.iloc[0]
    inv = np.array([1 / 10, 1 / 5, 1 / 2]); w = inv / inv.sum()
    assert (row[f"w_{BASE}"], row["w_persistence"], row["w_ets"]) == pytest.approx(tuple(w))
    no_ets = skill_weights_at(e, origin, "weekly", "herd_milk", base_model=BASE,
                              partners=("persistence", "ets"), available=("persistence",)).iloc[0]
    assert no_ets["w_ets"] == 0.0 and no_ets[f"w_{BASE}"] == pytest.approx((1 / 10) / (1 / 10 + 1 / 5))
