"""Leakage audit (docs/leakage_audit.md) on SYNTHETIC aggregates: conception cut, freeze hash."""
from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs
from components.predictive_farm_intelligence.pfoi.freeze import FROZEN_ENGINE, config_hash
from components.predictive_farm_intelligence.pfoi.rates import (
    conception_cut_month, conception_per_ai, estimate_rates,
)

from .synthetic import FakeHerdSource

ORIGIN = date(2020, 6, 1)
KNOWN = EngineConfig(window_months=12, conception_cut="known")


def test_frozen_hash_is_unchanged_by_the_new_option():
    assert config_hash() == "3cbd28787fcb"
    assert FROZEN_ENGINE.conception_cut == "origin"
    assert config_hash(KNOWN) != config_hash()


def test_cut_month_is_month_of_origin_minus_lag():
    inp = load_origin_inputs(FakeHerdSource(), ORIGIN, KNOWN).rate_inputs
    assert conception_cut_month(inp, KNOWN) == date(2020, 4, 1)  # 2020-06-01 - 35 d = 04-27
    assert conception_cut_month(inp, FROZEN_ENGINE) is None
    with pytest.raises(ValueError):
        conception_cut_month(inp, EngineConfig(conception_cut="later"))


def _inflate_recent_conceptions(inp, from_month: date, factor: float = 10.0):
    """Multiply heifer and dry-cow conceptions and pregnancy losses in months >= from_month."""
    tr = inp.transitions.copy()
    months = pd.to_datetime(tr["month"]).dt.date
    preg = tr["to_state"].isin(["heifer_pregnant", "dry_pregnant"]) | (
        tr["from_state"].isin(["heifer_pregnant", "dry_pregnant"])
        & tr["to_state"].isin(["heifer_open", "dry_open"]))
    tr.loc[preg & (months >= from_month), "n_moved"] *= factor
    return replace(inp, transitions=tr)


def test_unconfirmable_months_do_not_change_rates_with_known_cut():
    inp = load_origin_inputs(FakeHerdSource(), ORIGIN, KNOWN).rate_inputs
    changed = _inflate_recent_conceptions(inp, date(2020, 4, 1))
    a, b = estimate_rates(inp, KNOWN), estimate_rates(changed, KNOWN)
    assert a.conc_heifer == b.conc_heifer and a.conc_dry == b.conc_dry
    assert a.heifer_loss == b.heifer_loss and a.dry_loss == b.dry_loss
    assert conception_per_ai(inp, cfg=KNOWN) == conception_per_ai(changed, cfg=KNOWN)
    # pfoi-1.0.0 behaviour: the same months do move the heifer conception rate
    a0, b0 = estimate_rates(inp, FROZEN_ENGINE), estimate_rates(changed, FROZEN_ENGINE)
    assert b0.conc_heifer > a0.conc_heifer


def test_known_cut_still_uses_older_months():
    inp = load_origin_inputs(FakeHerdSource(), ORIGIN, KNOWN).rate_inputs
    changed = _inflate_recent_conceptions(inp, date(2019, 9, 1))
    assert estimate_rates(changed, KNOWN).conc_heifer > estimate_rates(inp, KNOWN).conc_heifer


# --- L3: starting herd from day_cell_known (pregnancies only once confirmed) --------------

def _sql_source(table="day_cell"):
    from types import SimpleNamespace

    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    src = SqlHerdSource(None, SimpleNamespace(core_schema="core", model_input_schema="model_input"),
                        cell_table=table)
    seen = []
    src._q = lambda sql, **kw: seen.append(sql) or pd.DataFrame()
    return src, seen


def test_cell_table_option_keeps_the_frozen_hash():
    assert FROZEN_ENGINE.cell_table == "day_cell"
    assert config_hash() == "3cbd28787fcb"
    assert config_hash(EngineConfig(window_months=12, cell_table="day_cell_known")) != config_hash()


def test_every_cell_query_reads_the_chosen_table():
    src, seen = _sql_source("day_cell_known")
    src.cells_on(date(2020, 1, 1))
    src.exposure(date(2019, 1, 1), date(2020, 1, 1))
    src.snapshots_batch([date(2020, 1, 1)], [date(2019, 11, 27)], 35)
    cell_sql = [q for q in seen if "model_input.day_cell" in q]
    assert len(cell_sql) == 3
    assert all("model_input.day_cell_known" in q for q in cell_sql)
    src, seen = _sql_source("day_cell")
    src.cells_on(date(2020, 1, 1))
    assert "model_input.day_cell " in seen[0] and "day_cell_known" not in seen[0]


def test_unknown_cell_table_is_refused():
    with pytest.raises(ValueError):
        _sql_source("day_cell; drop")


def test_source_and_configuration_must_agree_on_the_cell_table():
    with pytest.raises(ValueError, match="day_cell_known"):
        load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig(cell_table="day_cell_known"))


def test_worker_factory_is_picklable_and_reads_the_same_table():
    import pickle
    from types import SimpleNamespace

    from components.predictive_farm_intelligence.pfoi.cli import _source_factory
    f = pickle.loads(pickle.dumps(_source_factory(SimpleNamespace(cell_table="day_cell_known"))))
    assert f.keywords == {"cell_table": "day_cell_known", "conception_known": "lag"}


# --- conception known from the recorded pregnancy check -----------------------------------

def _sql_source_mode(mode):
    from types import SimpleNamespace

    from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource
    src = SqlHerdSource(None, SimpleNamespace(core_schema="core", model_input_schema="model_input"),
                        conception_known=mode)
    seen = []
    src._q = lambda sql, **kw: seen.append((sql, kw)) or pd.DataFrame()
    return src, seen


def _pregnancy_queries(src):
    asof, ku = date(2020, 5, 31), date(2020, 4, 27)
    src.milking_clock(asof, ku)
    src.dry_clock(asof, ku)
    src.cow_open(date(2019, 6, 1), ku, origin=date(2020, 6, 1))
    src.preg_milking_days(date(2019, 6, 1), ku, date(2020, 6, 1))
    src.dryoff_gest(date(2019, 6, 1), ku, date(2020, 6, 1))


def test_recorded_mode_uses_the_pregnancy_check_date_everywhere():
    src, seen = _sql_source_mode("recorded")
    _pregnancy_queries(src)
    assert all("conception_known_date" in sql for sql, _ in seen)
    clocks = seen[:2]
    assert all(kw["origin"] == date(2020, 6, 1) for _, kw in clocks)  # known before the origin
    assert seen[2][1]["origin"] == date(2020, 6, 1)
    src.snapshots_batch([date(2020, 5, 31)], [date(2020, 4, 27)], 35)
    snap = [sql for sql, _ in seen[5:] if "conc_raw" in sql]
    assert len(snap) == 2 and all("conc_known <= o.asof" in sql for sql in snap)


def test_lag_mode_sql_is_unchanged():
    src, seen = _sql_source_mode("lag")
    _pregnancy_queries(src)
    src.snapshots_batch([date(2020, 5, 31)], [date(2020, 4, 27)], 35)
    assert not any("conception_known_date" in sql or "conc_known" in sql for sql, _ in seen)
    assert all("origin" not in kw for _, kw in seen[:2])


def test_cow_conceptions_are_counted_only_inside_the_rate_window():
    src, seen = _sql_source_mode("recorded")
    src.cow_open(date(2019, 6, 1), date(2020, 3, 1), origin=date(2020, 6, 1))
    assert "iv.conc < CAST(:known_until AS date)" in seen[0][0]


@pytest.mark.parametrize("mode", ["lag", "recorded"])
def test_cow_open_metadata_excludes_conceptions_outside_the_rate_window(mode):
    # Recorded mode can know a recent conception before the origin even though it
    # is too recent for this rate window. The metadata must respect that window.
    src, seen = _sql_source_mode(mode)
    src.cow_open(date(2019, 6, 1), date(2020, 3, 1), origin=date(2020, 6, 1))
    sql, params = seen[0]
    metadata = " ".join(sql[sql.index("MAX(GREATEST"):].split())
    assert "CASE WHEN iv.conc < CAST(:known_until AS date) THEN iv.conc END" in metadata
    assert params["known_until"] == date(2020, 3, 1)


@pytest.mark.parametrize("offset", [0, 1, 89])
def test_cow_open_guard_still_rejects_dates_at_or_after_rate_cutoff(offset):
    from datetime import timedelta
    from components.predictive_farm_intelligence.pfoi.data import LeakageError, check_before

    cutoff = date(2020, 3, 1)
    frame = pd.DataFrame({"conceptions": [1.0], "max_date": [cutoff + timedelta(days=offset)]})
    with pytest.raises(LeakageError, match="cow_open"):
        check_before(frame, cutoff, "cow_open")
    result = check_before(frame.assign(max_date=cutoff - timedelta(days=1)), cutoff, "cow_open")
    assert result["conceptions"].sum() == 1.0
    assert "max_date" not in result


def test_conception_known_option_is_checked_and_hash_safe():
    from components.predictive_farm_intelligence.pfoi.cli import _source_factory
    from types import SimpleNamespace
    with pytest.raises(ValueError):
        _sql_source_mode("sometimes")
    with pytest.raises(ValueError, match="recorded"):
        load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig(conception_known="recorded"))
    assert config_hash() == "3cbd28787fcb"
    assert config_hash(EngineConfig(window_months=12, conception_known="recorded")) != config_hash()
    f = _source_factory(SimpleNamespace(cell_table="day_cell_known", conception_known="recorded"))
    assert f.keywords == {"cell_table": "day_cell_known", "conception_known": "recorded"}
