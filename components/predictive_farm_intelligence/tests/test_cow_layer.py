"""Layer 2 cow model on SYNTHETIC cows: split, guards, Wood recovery, EBM, herd sums."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.cow_layer import (
    DEFAULT_SPLIT, fit_wood_mixed, herd_daily, label_period, level_label, prepare_cowdays,
    run_layer2, shrunken_cow_effects, trailing_level,
)

from .synthetic_cows import PREG_SLOPE, TRUE_WOOD, synthetic_cowdays

pytest.importorskip("statsmodels")
EBM_FAST = {"outer_bags": 2, "interactions": 0}


@pytest.fixture(scope="module")
def cows():
    return synthetic_cowdays()


@pytest.fixture(scope="module")
def prepared(cows):
    return prepare_cowdays(cows)


@pytest.fixture(scope="module")
def wood(prepared):
    return fit_wood_mixed(prepared)


def test_period_boundaries():
    days = [date(2015, 12, 31), date(2016, 1, 1), date(2020, 12, 31), date(2021, 1, 1),
            date(2022, 4, 30), date(2022, 5, 1), date(2026, 3, 31), date(2026, 4, 1),
            date(2026, 5, 31), date(2026, 6, 1)]
    assert list(label_period(days)) == ["excluded", "train", "train", "validate", "validate",
                                        "gap", "gap", "recalibrate", "recalibrate", "test"]


def test_gap_and_bad_records_never_usable(cows):
    f = cows.copy()
    f.loc[f.index[:5], "litres"] = 25.0  # implausible
    p = prepare_cowdays(f)
    assert not p.loc[p["period"].isin(["gap", "excluded"]), "usable"].any()
    assert not p.loc[p["litres"] > 18, "usable"].any()
    assert not p.loc[~p["dim"].between(5, 400), "usable"].any()
    # the synthetic gap fragments exist but are dropped
    assert p.loc[p["period"] == "gap", "litres"].notna().sum() > 0


def test_after_dry_off_and_duplicate_cow_days_never_usable(cows):
    f = cows[cows["litres"].notna() & cows["dim"].between(5, 400)].head(10).copy()
    f["after_dry_off"] = [True] + [False] * 9
    f = pd.concat([f, f.iloc[[1]]], ignore_index=True)  # one cow-day twice
    p = prepare_cowdays(f)
    assert not p.loc[0, "usable"]
    assert p.attrs["duplicate_cow_day_rows"] == 2
    assert not p.loc[p.duplicated(["animal", "date"], keep=False), "usable"].any()
    assert p["usable"].sum() <= 8


def test_placeholder_dropped_and_unknown_dim_imputed_in_herd_sum(cows, wood):
    day = cows[cows["date"] == pd.Timestamp("2019-06-01")].copy()
    day["is_placeholder"] = False
    extra = day.iloc[[0]].assign(animal="PLACEHOLDER", litres=400.0, is_placeholder=True)
    day = pd.concat([day, extra], ignore_index=True)
    day["after_dry_off"] = False
    day.loc[day.index[1], ["after_dry_off", "dim"]] = [True, 900]
    p = prepare_cowdays(day)
    assert "PLACEHOLDER" not in set(p["animal"])
    d = herd_daily(p, wood.predict(p)).iloc[0]
    assert d["dim_unknown"] == 1 and d["milking"] == len(day) - 1
    known = p["dim_known"].to_numpy()
    pk = wood.predict(p)[known]
    assert d["pred_herd"] == pytest.approx(pk.sum() + pk.mean())


def test_fit_uses_train_rows_only(prepared, wood):
    corrupt = prepared.copy()
    later = corrupt["period"] != "train"
    corrupt.loc[later, "litres"] = corrupt.loc[later, "litres"] * 0.3
    again = fit_wood_mixed(corrupt)
    np.testing.assert_allclose(again.params.to_numpy(), wood.params.to_numpy(), rtol=1e-6)


def test_wood_recovers_true_curve(wood):
    s = wood.summary().set_index("parity_group")
    for p, (a, b, c) in TRUE_WOOD.items():
        assert s.loc[p, "b"] == pytest.approx(b, abs=0.02)
        assert s.loc[p, "c_per_day"] == pytest.approx(c, abs=0.0004)
        assert s.loc[p, "peak_day"] == pytest.approx(b / c, rel=0.15)
    assert s.attrs["preg_late_per_day"] == pytest.approx(-PREG_SLOPE, abs=0.0005)
    assert s.attrs["sigma2_cow"] > 0


def test_unknown_cow_gets_marginal_prediction(prepared, wood):
    row = prepared[prepared["usable"]].head(1).copy()
    known = wood.predict(row)[0]
    row["animal"] = "SYN_NEW"
    new = wood.predict(row)[0]
    assert new == pytest.approx(wood.predict(row, use_cow_effect=False)[0])
    assert known > 0 and new > 0


def test_shrinkage_pulls_small_cows_toward_zero():
    rng = np.random.default_rng(0)
    animals = np.repeat(["x", "y"], [200, 2])
    resid = np.concatenate([rng.normal(0.3, 0.1, 200), [0.3, 0.3]])
    resid = np.concatenate([resid, rng.normal(-0.3, 0.1, 200)])
    animals = np.concatenate([animals, np.repeat("z", 200)])
    u, s2u, s2e = shrunken_cow_effects(resid, animals)
    assert abs(u["y"]) < abs(u["x"]) and s2u > 0 and s2e > 0


def test_herd_sum_corrects_selection_bias(prepared, wood):
    d = herd_daily(prepared, wood.predict(prepared))
    true = prepared.groupby("date")["true_litres"].sum()
    # ordinary sample days (whole-herd test days are unbiased by construction)
    sample = (d["period"] == "train") & (d["recorded"] >= 3) & (d["recorded"] < 0.5 * d["milking"])
    t = d[sample].join(true.rename("true_herd"))
    naive_err = (t["naive_herd"] / t["true_herd"] - 1).abs().mean()
    model_err = (t["pred_herd"] / t["true_herd"] - 1).abs().mean()
    assert t["selection_bias_pct"].mean() < -2  # late-lactation cows recorded more often
    assert model_err < naive_err


def test_run_layer2_hides_test_unless_asked(cows):
    r = run_layer2(cows, models=("wood",))
    assert set(r.cow_scores["period"]) == {"train", "validate"}
    assert "test" not in set(r.herd_scores["period"])
    assert "animal" not in r.cow_scores.columns  # aggregates only


def test_run_layer2_with_ebm_and_test(cows):
    pytest.importorskip("interpret")
    r = run_layer2(cows, score_test=True, ebm_kwargs=EBM_FAST)
    sc = r.cow_scores.set_index(["model", "variant", "period"])
    for m in ("wood", "ebm"):
        assert sc.loc[(m, "raw", "validate"), "mape_pct"] < 15
        assert ("recalibrated", "test") in [(v, p) for (mm, v, p) in sc.index if mm == m]
        assert 0.8 < r.level_factors[m] < 1.2
    imp = r.models["ebm"].importances()
    assert imp.iloc[0]["term"] == "dim"
    shape = r.models["ebm"].shape("dim")
    peak = float(shape.loc[shape["log_effect"].idxmax(), "value"])
    assert 30 <= peak <= 120
    assert r.known_cow_share.set_index("period").loc["train", "known_cow_share"] == 1.0


def _drifted(cows):
    """2016 cows give 30% more; from 2021 on, 20% less (a level drift, same curve)."""
    f = cows.copy()
    f.loc[f["date"].dt.year == 2016, "litres"] *= 1.3
    f.loc[f["date"] >= pd.Timestamp("2021-01-01"), "litres"] *= 0.8
    return f


def test_level_labels_clip_to_training_half_years():
    lv = level_label([date(2015, 12, 1), date(2016, 7, 1), date(2020, 12, 31), date(2026, 6, 1)])
    assert list(lv) == ["2016H1", "2016H2", "2020H2", "2020H2"]


def test_calendar_level_absorbs_drift_and_keeps_curve(cows):
    p = prepare_cowdays(_drifted(cows))
    with_level = fit_wood_mixed(p)
    lt = with_level.level_table().set_index("level")["factor_vs_reference"]
    assert lt["2016H1"] == pytest.approx(1.3, rel=0.06)
    assert lt["2018H1"] == pytest.approx(1.0, abs=0.06)
    s = with_level.summary().set_index("parity_group")
    for par, (a, b, c) in TRUE_WOOD.items():
        assert s.loc[par, "b"] == pytest.approx(b, abs=0.03)
        assert s.loc[par, "c_per_day"] == pytest.approx(c, abs=0.0006)


def test_trailing_level_uses_only_earlier_days(prepared, wood):
    d = herd_daily(prepared, wood.predict(prepared))
    base = trailing_level(d)
    day = d[(d["period"] == "validate") & (d["recorded"] > 0)].index[10]
    bumped = d.copy()
    bumped.loc[day, "actual_recorded"] *= 5
    after = trailing_level(bumped)
    assert after[day] == pytest.approx(base[day])
    later = after.index[after.index > day][0]
    assert after[later] != pytest.approx(base[later])


def test_trailing_variant_removes_validation_drift(cows):
    r = run_layer2(_drifted(cows), models=("wood",))
    h = r.herd_scores.set_index(["variant", "period"])
    c = r.cow_scores.set_index(["variant", "period"])
    assert h.loc[("raw", "validate"), "bias_pct"] > 15  # fitted at the 2020 level
    assert c.loc[("trailing", "validate"), "mape_pct"] < c.loc[("raw", "validate"), "mape_pct"]
    assert abs(c.loc[("trailing", "validate"), "bias"]) < 0.3 * abs(c.loc[("raw", "validate"), "bias"])
    assert "trailing_factor" in r.herd_daily["wood"].columns
