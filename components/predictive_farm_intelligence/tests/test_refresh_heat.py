"""Synthetic fixtures and mocked SQL only; never connects to a database."""
from copy import deepcopy
from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from components.predictive_farm_intelligence.pfoi.refresh_heat import refreshed_heat, refresh_documents


class SyntheticWeather:
    def __init__(self):
        days = pd.date_range("2020-01-01", "2024-02-01")
        self.days = pd.DataFrame({"date": days, "thi_mean": 70.0,
                                  "thi_max": 75 + np.sin(np.arange(len(days)) / 60),
                                  "weather_is_complete": True})

    def driver_daily(self, start, end):
        return self.days.loc[(self.days.date >= pd.Timestamp(start)) & (self.days.date < pd.Timestamp(end))].copy()


def _document():
    return {"origin_date": "2024-01-01", "model_version": "synthetic",
            "outlook": [{"synthetic": True}],
            "heat": {"weather_lag_days": 6, "climatology": [], "recent": [], "knot_p75": 76.0}}


def test_refresh_adds_both_series_without_changing_original_forecasts():
    original = _document()
    before = deepcopy(original)
    source = SyntheticWeather()
    heat = refreshed_heat(original, source, date(2024, 1, 20))
    assert original == before
    assert heat["climatology"] == original["heat"]["climatology"]
    assert heat["knot_p75"] == 76.0
    assert len(heat["forecast"]["predictions"]) == 90
    assert len(heat["realised"]) == 19
    source.days.loc[source.days.date >= "2024-01-01", "thi_max"] = 100.0
    later = refreshed_heat(original, source, date(2024, 1, 20))
    assert later["forecast"] == heat["forecast"]
    assert later["realised"] != heat["realised"]
    assert refreshed_heat({}, source, date(2024, 1, 20)) is None


def test_dry_run_only_counts_and_write_only_changes_heat_key():
    conn = MagicMock()
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    rows = [{"origin_date": date(2024, 1, 1), "model_version": "synthetic", "document": _document()}]
    selected = MagicMock()
    selected.mappings.return_value.all.return_value = rows
    updated = MagicMock(rowcount=1)
    conn.execute.side_effect = [selected]
    counts = refresh_documents(engine, SyntheticWeather(), date(2024, 1, 20))
    assert counts["predictions"] == 90 and counts["observations"] == 19
    assert counts["updated"] == 0
    assert conn.execute.call_count == 1
    conn.execute.reset_mock(side_effect=True)
    conn.execute.side_effect = [selected, updated]
    counts = refresh_documents(engine, SyntheticWeather(), date(2024, 1, 20), write=True)
    assert counts["updated"] == 1 and counts["conflicts"] == 0
    sql, params = conn.execute.call_args.args
    assert "jsonb_set(document, '{heat}'" in str(sql)
    assert "document = CAST(:original AS jsonb)" in str(sql)
    assert set(params) == {"heat", "origin", "version", "original"}


def test_refresh_v2_adds_band_hot_chances_and_usual_shares_only():
    original = _document()
    original["heat"]["knot_p90"] = 75.8
    original["heat"]["climatology"] = [{"date": "2024-01-05", "p10": 74.0, "p50": 75.0, "p90": 76.0}]
    heat = refreshed_heat(original, SyntheticWeather(), date(2024, 1, 20), thi_method="v2")
    assert heat["forecast"]["method"].endswith("_v2")
    assert heat["forecast"]["thresholds"] == {"p75": 76.0, "p90": 75.8}
    first = heat["forecast"]["predictions"][0]
    assert first["lower"] <= first["thi_max"] <= first["upper"] and set(first["p_above"]) == {"p75", "p90"}
    clim = heat["climatology"][0]
    assert {k: clim[k] for k in ("p10", "p50", "p90")} == {"p10": 74.0, "p50": 75.0, "p90": 76.0}
    assert 0.0 <= clim["share_above_p75"] <= 1.0 and 0.0 <= clim["share_above_p90"] <= 1.0
