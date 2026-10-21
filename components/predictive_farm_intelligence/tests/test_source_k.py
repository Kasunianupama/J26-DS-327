"""Source-break k (borrow_other_source_k) and the by-regime error report. SYNTHETIC data only.

The synthetic target switches from shipment to DelPro on 2020-08-01. An origin in 2020-10 has
no DelPro month in its 12-month window, so the default borrows the shipment k (flag
``source_switch``); ``borrow_other_source_k=False`` must not.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.freeze import (
    V11_ENGINE, config_hash, v11_config_hash, version_label,
)
from components.predictive_farm_intelligence.pfoi.milk_baseline import (
    WITHHELD_NO_TRUSTED_DAYS, MilkConfig, MilkWithheld, prepare_milk,
)
from components.predictive_farm_intelligence.pfoi.regimes import (
    DELPRO_EARLY, DELPRO_LATE, GAP, SHIPMENT, assign_regime, flag_table, regime_table,
)

from .synthetic import FakeHerdSource
from .test_outage_recovery import GapSource, _hist, _setup

BORROW = MilkConfig(k_mode="anchor_first")
SAME = MilkConfig(k_mode="anchor_first", borrow_other_source_k=False)
SWITCH_ORIGIN = date(2020, 10, 5)  # DelPro is current, but the window holds only shipment months


def test_default_borrows_the_other_sources_k_and_flags_it():
    src = FakeHerdSource()
    setup = prepare_milk(src, SWITCH_ORIGIN, BORROW, _hist(src))
    assert np.isfinite(setup.k) and "source_switch" in setup.flags
    assert setup.target_source == "delpro" and setup.k_source == "shipment"


def test_refusing_to_borrow_leaves_no_window_k_and_says_so():
    src = FakeHerdSource()
    setup = prepare_milk(src, SWITCH_ORIGIN, SAME, _hist(src))
    assert not np.isfinite(setup.k) and setup.k_source == "none"
    assert "no_same_source_k" in setup.flags and "source_switch" not in setup.flags


def test_level_then_comes_from_recent_same_source_days():
    src = FakeHerdSource()
    borrowed, *_ = _setup(src, SWITCH_ORIGIN, BORROW)
    same, *_ = _setup(src, SWITCH_ORIGIN, SAME)
    assert same.k_source == "anchored:delpro" and np.isfinite(same.k)
    assert same.k == pytest.approx(borrowed.k)  # both anchored on the same delpro days


def test_no_recent_same_source_days_withholds_instead_of_borrowing():
    src = GapSource(SWITCH_ORIGIN - timedelta(days=28), SWITCH_ORIGIN)
    old, *_ = _setup(src, SWITCH_ORIGIN, BORROW)
    assert "k_window" in old.flags and old.k_source == "shipment"  # silent borrow today
    with pytest.raises(MilkWithheld) as err:
        _setup(src, SWITCH_ORIGIN, SAME)
    assert err.value.reason == WITHHELD_NO_TRUSTED_DAYS


def test_anchored_mode_skips_the_origin_instead_of_borrowing():
    cfg = MilkConfig(k_mode="anchored", borrow_other_source_k=False)
    src = FakeHerdSource()
    with pytest.raises(ValueError, match="no same-source k"):
        prepare_milk(src, SWITCH_ORIGIN, cfg, _hist(src))


def test_nothing_changes_once_the_new_source_has_enough_months():
    src = FakeHerdSource()
    origin = date(2021, 10, 4)
    a, *_ = _setup(src, origin, BORROW)
    b, *_ = _setup(src, origin, SAME)
    assert a.k == pytest.approx(b.k) and a.flags == b.flags


def test_option_is_outside_the_frozen_hashes_and_in_the_tag():
    assert config_hash() == "3cbd28787fcb" and v11_config_hash() == "2a865a0c2687"
    assert SAME.tag().endswith("_kfs") and BORROW.tag().endswith("_kf")
    assert version_label(V11_ENGINE, SAME).startswith("experiment-")


# ------------------------------------------------------------------ regime report

def _errors():
    rows = []
    for i, (start, source) in enumerate([
            ("2021-03-01", "shipment"), ("2021-04-01", "shipment"), ("2023-05-01", "delpro"),
            ("2024-03-01", "delpro"), ("2024-06-01", "delpro")]):
        for model, f in (("milk_baseline", 120.0), ("persistence", 150.0)):
            rows.append(dict(origin=start, period_start=start, grain="monthly", horizon=1,
                             model=model, forecast=f, actual=100.0, source=source,
                             flags="source_switch" if i == 2 else ""))
    return pd.DataFrame(rows)


def test_regime_labels_follow_period_and_source():
    e = _errors()
    got = assign_regime(pd.to_datetime(e.loc[e.model == "milk_baseline", "period_start"]),
                        e.loc[e.model == "milk_baseline", "source"])
    assert got.tolist() == [SHIPMENT, SHIPMENT, DELPRO_EARLY, GAP, DELPRO_LATE]


def test_regime_table_has_own_n_bias_and_matched_ratio():
    t = regime_table(_errors()).set_index("regime")
    assert t.loc[SHIPMENT, "n"] == 2 and t.loc[SHIPMENT, "bias"] == 20 and t.loc[SHIPMENT, "bias_pct"] == 20
    assert t.loc[SHIPMENT, "mae_ratio"] == pytest.approx(20 / 50)
    assert t.loc[DELPRO_EARLY, "n"] == 1 and bool(t.loc[DELPRO_EARLY, "small_n"])
    assert list(t.index) == [SHIPMENT, DELPRO_EARLY, GAP, DELPRO_LATE]  # fixed order


def test_ratio_uses_only_periods_both_models_forecast():
    e = _errors()
    e = e[~((e.model == "persistence") & (e.period_start == "2021-04-01"))]
    t = regime_table(e).set_index("regime")
    assert t.loc[SHIPMENT, "n"] == 2 and t.loc[SHIPMENT, "n_common"] == 1


def test_flag_table_counts_fallbacks_per_regime():
    f = flag_table(_errors()).set_index("regime")
    assert f.loc[DELPRO_EARLY, "source_switch"] == 100.0 and f.loc[SHIPMENT, "source_switch"] == 0.0


def test_missing_columns_are_refused():
    with pytest.raises(ValueError, match="lacks columns"):
        regime_table(_errors().drop(columns="source"))


def test_mixed_configurations_are_refused():
    e = _errors()
    with pytest.raises(ValueError, match="more than once"):
        regime_table(pd.concat([e, e], ignore_index=True))


def test_matched_comparison_uses_only_periods_both_runs_forecast():
    from components.predictive_farm_intelligence.pfoi.regimes import matched_table

    a = _errors()
    a = a[a.model == "milk_baseline"].copy()
    b = a.copy()
    b["forecast"] = 110.0                                     # B is closer to the actual of 100
    b = b[b.period_start != "2023-05-01"]                     # B declines one period
    t = matched_table(a, b).set_index("regime")
    assert t.loc[SHIPMENT, "n_both"] == 2 and t.loc[SHIPMENT, "mae_a"] == 20 and t.loc[SHIPMENT, "mae_b"] == 10
    assert t.loc[DELPRO_EARLY, "n_both"] == 0 and t.loc[DELPRO_EARLY, "only_a"] == 1
    assert t.loc[DELPRO_EARLY, "mae_a_on_only_a"] == 20       # what B declined to forecast
