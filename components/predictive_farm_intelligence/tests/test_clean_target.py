"""Placeholder-free milk target on model_input2 (docs/model_input2.md section 5). SYNTHETIC data,
no database: SqlHerdSource._q is replaced by a stub."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.config import DatabaseSettings
from components.predictive_farm_intelligence.pfoi.data import SqlHerdSource, clean_target_frame

START = date(2026, 1, 1)


def _raw(n=80):
    days = [START + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(dict(date=days, milk_per_recorded_cow=10.0, observed_milking_cows=50,
                             milking=400.0, milk_record_type="cow_sample",
                             # placeholder / shipped columns must never reach the target
                             milk_observed_placeholder_litres=90000.0, herd_milk_measured=95000.0,
                             milk_shipped=70000.0, target_litres=95000.0))


def _d(i):
    return START + timedelta(days=i)


def test_target_is_identified_cows_times_milking_herd_without_placeholder_or_shipped():
    t = clean_target_frame(_raw()).set_index("date")
    assert t.loc[_d(40), "target_litres"] == pytest.approx(4000.0)  # 10 L x 400 cows
    assert t.loc[_d(40), "target_source"] == "delpro"
    assert t.loc[_d(40), "identified_share"] == 1.0
    assert t["target_litres"].max() == pytest.approx(4000.0)        # no 90k / 95k / 70k anywhere


def test_placeholder_only_sparse_and_none_days_are_missing_not_zero():
    r = _raw()
    r.loc[10, ["milk_per_recorded_cow", "observed_milking_cows"]] = [np.nan, 2]  # placeholder only
    r.loc[10, "milk_record_type"] = "herd_total"
    r.loc[20, "observed_milking_cows"] = 9                                      # too few cows
    r.loc[30, "milk_record_type"] = "none"
    r.loc[35, "milking"] = 0
    r.loc[40, "milk_per_recorded_cow"] = 18.01                           # above hard limit
    r.loc[41, "milk_per_recorded_cow"] = 0.0                             # zero is not milk
    t = clean_target_frame(r).set_index("date")
    for i in (10, 20, 30, 35, 40, 41):
        assert np.isnan(t.loc[_d(i), "target_litres"]), i
        assert t.loc[_d(i), "data_gap"] and not t.loc[_d(i), "is_scoreable"], i
        assert t.loc[_d(i), "target_source"] is None, i


def test_eighteen_litres_is_inclusive_but_anything_above_is_removed():
    r = _raw()
    r.loc[40, "milk_per_recorded_cow"] = 18.0
    r.loc[41, "milk_per_recorded_cow"] = 18.0001
    t = clean_target_frame(r).set_index("date")
    assert t.loc[_d(40), "target_litres"] == pytest.approx(18.0 * 400)
    assert np.isnan(t.loc[_d(41), "target_litres"])
    assert t.loc[_d(41), "data_gap"] and not t.loc[_d(41), "is_scoreable"]


def test_herd_total_day_with_enough_identified_cows_keeps_a_clean_estimate():
    r = _raw()
    r.loc[15, "milk_record_type"] = "herd_total"
    t = clean_target_frame(r).set_index("date")
    assert t.loc[_d(15), "target_litres"] == pytest.approx(4000.0)


def test_suspect_flags_are_past_only_and_catch_drops_and_spikes():
    r = _raw()
    r.loc[50, "milk_per_recorded_cow"] = 4.0     # litres below half the past mean
    r.loc[60, "milk_per_recorded_cow"] = 16.0    # per cow above 1.5x the past mean
    t = clean_target_frame(r).set_index("date")
    assert not t.loc[_d(50), "is_scoreable"] and not t.loc[_d(60), "is_scoreable"]
    assert t.loc[_d(0), "is_scoreable"] and t.loc[_d(49), "is_scoreable"]
    later = r.copy()
    later.loc[later.index >= 70, "milk_per_recorded_cow"] = 1.0
    a, b = clean_target_frame(r), clean_target_frame(later)
    pd.testing.assert_series_equal(a.loc[:69, "is_scoreable"], b.loc[:69, "is_scoreable"])


class _Stub(SqlHerdSource):
    """SqlHerdSource with the database replaced by canned herd-level frames."""

    def __init__(self, raw, has_columns=True):
        url = "postgresql+psycopg://u@localhost/x"
        super().__init__(engine=None, settings=DatabaseSettings(url=url, model_input_schema="model_input2"))
        self.raw, self.has_columns, self.sql = raw, has_columns, []

    def _q(self, sql, **params):
        self.sql.append(sql)
        if "information_schema" in sql:
            return pd.DataFrame({"n": [1 if self.has_columns else 0]})
        if "weather_is_complete" in sql:
            f = self.raw[["date"]].copy()
            for c in ("milking", "thi_mean", "identified_share", "target_litres", "is_scoreable"):
                f[c] = 999.0
            return f
        return self.raw.copy()


def test_sql_source_on_model_input2_serves_the_clean_target_and_trims_the_warm_up():
    s = _Stub(_raw())
    t = s.target_daily(_d(30), _d(80))
    assert s.placeholder_free()
    assert t["date"].min() == _d(30) and len(t) == 50
    assert t["target_litres"].max() == pytest.approx(4000.0)
    raw_sql = [q for q in s.sql if "day_panel" in q and "information_schema" not in q][0]
    assert "milk_per_recorded_cow" in raw_sql and "target_litres" not in raw_sql
    assert "placeholder" not in raw_sql and "shipped" not in raw_sql


def test_driver_frame_uses_the_clean_target_and_delpro_only_target_is_refused():
    s = _Stub(_raw())
    d = s.driver_daily(_d(30), _d(80)).set_index("date")
    assert d.loc[_d(40), "target_litres"] == pytest.approx(4000.0)
    assert d.loc[_d(40), "identified_share"] == 1.0
    with pytest.raises(ValueError, match="placeholder"):
        s.delpro_daily(_d(30), _d(80))


def test_old_model_input_is_read_as_stored():
    stored = pd.DataFrame(dict(date=[_d(0)], target_source=["shipment"], target_litres=[123.0],
                               is_scoreable=[True], identified_share=[0.5], data_gap=[False]))
    s = _Stub(stored, has_columns=False)
    t = s.target_daily(_d(0), _d(1))
    assert not s.placeholder_free() and t["target_litres"].iloc[0] == 123.0


def test_curve_cow_days_on_model_input2_drop_records_above_18_litres_and_the_placeholder_animal():
    s = _Stub(_raw())
    s.cow_curve_stats(_d(0), _d(80))
    sql = [q for q in s.sql if "cow_day" in q][0]
    assert "d.yield_litres <= 18" in sql and "d.animal_key <> 'A_PLACEHOLDER'" in sql
    old = _Stub(_raw(), has_columns=False)
    old.cow_curve_stats(_d(0), _d(80))
    sql = [q for q in old.sql if "cow_day" in q][0]
    assert "<= 18" not in sql and "A_PLACEHOLDER" not in sql  # frozen versions unchanged


@pytest.mark.parametrize("schema, start", [("model_input2", date(2015, 11, 1)),
                                           ("model_input", date(2015, 8, 1)), ("", date(2015, 8, 1))])
def test_model_input2_data_starts_in_november_2015(monkeypatch, schema, start):
    from components.predictive_farm_intelligence.pfoi import data

    monkeypatch.setenv("PFOI_MODEL_INPUT_SCHEMA", schema)
    assert data._data_start() == start
