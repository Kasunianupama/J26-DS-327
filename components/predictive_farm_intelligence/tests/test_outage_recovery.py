"""M1 (docs/pp1_plan.md): anchor first, 12-month k only as fallback, explicit withholding.

SYNTHETIC data only. A long recording gap leaves no usable months for the 12-month k;
``k_mode="anchor_first"`` must still set the level from trusted recent days, and withhold
the milk forecast (with a reason) when there are none.
"""
from datetime import date, timedelta

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.backtest_milk import BASELINE, run_milk_backtest
from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs
from components.predictive_farm_intelligence.pfoi.freeze import (
    FROZEN_MILK, V11_ENGINE, config_hash, v11_config_hash, version_label,
)
from components.predictive_farm_intelligence.pfoi.milk_baseline import (
    WITHHELD_NO_TRUSTED_DAYS, MilkConfig, MilkHistory, MilkWithheld, anchor_k, prepare_milk,
)

from .synthetic import FakeHerdSource

FIRST = MilkConfig(k_mode="anchor_first")
GAP_START = date(2020, 9, 1)


class GapSource(FakeHerdSource):
    """Synthetic source whose milk target is missing in [gap_start, gap_end)."""

    def __init__(self, gap_start: date, gap_end: date, **kw):
        super().__init__(**kw)
        self.gap = (gap_start, gap_end)

    def target_daily(self, start, end):
        t = super().target_daily(start, end).copy()
        inside = (t["date"] >= self.gap[0]) & (t["date"] < self.gap[1])
        t.loc[inside, "is_scoreable"] = False
        t.loc[inside, "target_litres"] = None
        t.loc[inside, "data_gap"] = True
        return t


def _hist(src, end=date(2024, 1, 1)):
    return MilkHistory(cowdays=src.milking_cowdays(date(2015, 8, 1), end),
                       target=src.target_daily(date(2015, 8, 1), end))


def _setup(src, origin, cfg):
    hist = _hist(src)
    setup = prepare_milk(src, origin, cfg, hist)
    state = load_origin_inputs(src, origin, EngineConfig()).state
    return anchor_k(setup, hist.target_before(origin), state, cfg), hist, state


def test_anchor_first_recovers_after_a_long_gap():
    origin = date(2021, 12, 1)
    src = GapSource(GAP_START, date(2021, 11, 10))  # 14+ months missing, 21 days back
    with pytest.raises(ValueError, match="no usable months"):  # pfoi-1.0.0 / 1.1.0 behaviour
        _setup(src, origin, MilkConfig())
    setup, hist, state = _setup(src, origin, FIRST)
    th = hist.target_before(origin)
    ok = th[th["is_scoreable"].astype(bool)]
    recent = ok[pd.to_datetime(ok["date"]).dt.date >= origin - timedelta(days=28)].tail(14)
    assert setup.k == pytest.approx(recent["target_litres"].mean() / setup.arrays.litres(state))
    assert setup.k_source == "anchored:delpro"
    assert "no_window_k" in setup.flags and "k_window" not in setup.flags


def test_withheld_with_a_reason_when_no_trusted_recent_days():
    origin = date(2021, 12, 1)
    src = GapSource(GAP_START, origin)  # still in the outage at the origin
    with pytest.raises(MilkWithheld) as err:
        _setup(src, origin, FIRST)
    assert err.value.reason == WITHHELD_NO_TRUSTED_DAYS


def test_window_k_stays_the_fallback_when_it_exists():
    """Recent days missing but the 12-month k usable: same result as pfoi-1.0.0."""
    origin = date(2021, 10, 4)
    src = GapSource(origin - timedelta(days=28), origin)
    old, *_ = _setup(src, origin, MilkConfig())
    new, *_ = _setup(src, origin, FIRST)
    assert new.k == pytest.approx(old.k) and "k_window" in new.flags


def test_same_level_as_anchored_when_both_exist():
    src = FakeHerdSource()
    for origin in (date(2019, 6, 3), date(2021, 10, 4)):
        old, *_ = _setup(src, origin, MilkConfig())
        new, *_ = _setup(src, origin, FIRST)
        assert new.k == pytest.approx(old.k) and new.k_source == old.k_source


def test_later_days_never_change_the_anchor():
    origin = date(2021, 12, 1)
    a, *_ = _setup(GapSource(GAP_START, date(2021, 11, 10)), origin, FIRST)
    b, *_ = _setup(GapSource(GAP_START, date(2021, 11, 10), cutoff=origin, future_scale=3.0),
                   origin, FIRST)
    assert a.k == pytest.approx(b.k)


def test_backtest_scores_recovery_origins_and_counts_withheld_ones():
    src = GapSource(GAP_START, date(2021, 11, 10))
    origins = [date(2021, 11, 1), date(2021, 12, 6)]  # inside the outage, then 26 days after it
    old = run_milk_backtest(src, "weekly", origins=origins)
    assert BASELINE not in set(old.errors.get("model", pd.Series(dtype=str)))
    new = run_milk_backtest(src, "weekly", milk_cfg=FIRST, origins=origins)
    base = new.errors[new.errors["model"] == BASELINE]
    assert set(pd.to_datetime(base["origin"]).dt.date) == {date(2021, 12, 6)}
    notes = dict(zip(new.notes["note"], new.notes["n_origins"]))
    assert notes[f"withheld ({WITHHELD_NO_TRUSTED_DAYS})"] == 1


def test_new_mode_leaves_frozen_hashes_unchanged():
    assert config_hash() == "3cbd28787fcb"
    assert v11_config_hash() == "2a865a0c2687"
    assert FIRST.tag() != FROZEN_MILK.tag() and FIRST.tag().endswith("_kf")
    assert version_label(V11_ENGINE, FIRST).startswith("experiment-")


# ------------------------------------------------------------------ M3: anchor trust gate

class M3Source(FakeHerdSource):
    """Synthetic herd at a realistic level (half the fixture's litres, about 13 L per milking
    cow; the fixture's 26 L would fail the agreed 20 L rule). Recorded milk in [start, end)
    can be multiplied by ``scale``, given an identified ``share``, or be ``missing``."""

    def __init__(self, start=None, end=None, scale=1.0, share=None, missing=False, **kw):
        super().__init__(**kw)
        self.window, self.scale, self.share, self.missing = (start, end), scale, share, missing

    def target_daily(self, start, end):
        t = super().target_daily(start, end).copy()
        t["target_litres"] = t["target_litres"] * 0.5
        t["identified_share"] = t["identified_share"].astype(float)
        t.loc[t["target_source"] == "delpro", "identified_share"] = 0.8
        if self.window[0] is None:
            return t
        inside = (t["date"] >= self.window[0]) & (t["date"] < self.window[1])
        t.loc[inside, "target_litres"] = t.loc[inside, "target_litres"] * self.scale
        if self.share is not None:
            t.loc[inside, "identified_share"] = self.share
        if self.missing:
            t.loc[inside, "is_scoreable"] = False
            t.loc[inside, "target_litres"] = None
        return t


GATED = MilkConfig(k_mode="anchor_first", anchor_gate=True)
ORIGIN_M3 = date(2021, 10, 4)
BAD = (ORIGIN_M3 - timedelta(days=5), ORIGIN_M3)


def test_gate_leaves_out_implausible_days():
    clean, *_ = _setup(M3Source(*BAD, missing=True), ORIGIN_M3, FIRST)  # the 5 days missing
    inflated = M3Source(*BAD, scale=500.0)
    open_, *_ = _setup(inflated, ORIGIN_M3, FIRST)
    gated, *_ = _setup(inflated, ORIGIN_M3, GATED)
    assert open_.k > 10 * clean.k  # without the gate the bad days set the level
    assert gated.k == pytest.approx(clean.k)
    assert any("anchor gate: 5" in n for n in gated.notes)


def test_gate_leaves_out_unidentified_days():
    clean, *_ = _setup(M3Source(*BAD, missing=True), ORIGIN_M3, FIRST)
    gated, *_ = _setup(M3Source(*BAD, scale=1.5, share=0.05), ORIGIN_M3, GATED)
    assert gated.k == pytest.approx(clean.k)


def test_gate_changes_nothing_on_verified_days():
    a, *_ = _setup(M3Source(), ORIGIN_M3, FIRST)
    b, *_ = _setup(M3Source(), ORIGIN_M3, GATED)
    assert a.k == pytest.approx(b.k)


def test_gate_option_is_outside_the_frozen_hashes():
    from components.predictive_farm_intelligence.pfoi.freeze import v111_config_hash

    assert config_hash() == "3cbd28787fcb" and v11_config_hash() == "2a865a0c2687"
    assert v111_config_hash()  # computed from the same milk dict (no anchor_gate key)
    assert GATED.tag().endswith("_kfg") and version_label(V11_ENGINE, GATED).startswith("experiment-")
