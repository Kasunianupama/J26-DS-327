"""Frozen configuration and the run-once final test block (no database)."""
from datetime import date

import pytest

from components.predictive_farm_intelligence.pfoi import MODEL_VERSION
from components.predictive_farm_intelligence.pfoi.backtest_herd import check_block, run_backtest
from components.predictive_farm_intelligence.pfoi.freeze import (
    DATA_END, FROZEN_MILK, FinalTestAlreadyRun, config_hash, final_test_origins,
    guard_final_test, record_final_test,
)

from .synthetic import FakeHerdSource


def test_frozen_configuration():
    assert MODEL_VERSION == "pfoi-1.0.0"
    assert FROZEN_MILK.curve_mode == "herd_fitted" and FROZEN_MILK.k_mode == "anchored"
    assert len(config_hash()) == 12


def test_final_test_origins_cover_2024_to_2026_08():
    m = final_test_origins("monthly")
    assert m[0] == date(2024, 1, 1) and m[-1] == date(2026, 8, 1) and len(m) == 32
    w = final_test_origins("weekly")
    assert w[0] == date(2024, 1, 1) and all(d.weekday() == 0 for d in w) and w[-1] < DATA_END


def test_blocks_do_not_mix():
    with pytest.raises(ValueError):
        check_block([date(2024, 1, 1)], date(2024, 1, 1), "development")
    with pytest.raises(ValueError):
        check_block([date(2023, 12, 1)], DATA_END, "test")
    check_block([date(2024, 1, 1)], DATA_END, "test")


def test_final_test_runs_once(tmp_path):
    marker, rerun = guard_final_test(tmp_path, "milk_monthly", force=False)
    assert not rerun
    record_final_test(marker, rerun, ["x.csv"], 32)
    with pytest.raises(FinalTestAlreadyRun):
        guard_final_test(tmp_path, "milk_monthly", force=False)
    marker2, rerun2 = guard_final_test(tmp_path, "milk_monthly", force=True)
    assert rerun2
    record_final_test(marker2, rerun2, ["x.csv"], 32)
    assert '"rerun": true' in marker2.read_text()


def test_test_block_backtest_runs_on_synthetic_data():
    res = run_backtest(FakeHerdSource(), "monthly", origins=[date(2024, 1, 1)],
                       score_until=date(2024, 3, 1), block="test")
    assert len(res.errors) and (res.errors["origin"] == date(2024, 1, 1)).all()
