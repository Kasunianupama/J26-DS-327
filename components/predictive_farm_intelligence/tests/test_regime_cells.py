"""T0 source and boundary checks; all inputs fictional and synthetic."""
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.regime_cells import (
    CROSS_BREAK, DELPRO_EARLY, SHIPMENT, SHIPMENT_EARLY, assign_regime, boundary_audit,
)
from components.predictive_farm_intelligence.pfoi.regimes import matched_table, regime_table


def test_source_pairs_and_shipment_split_follow_issuance():
    origins = pd.Series(pd.to_datetime(["2020-07-31", "2020-08-01", "2022-07-31", "2022-08-02"]))
    targets = pd.Series(pd.to_datetime(["2021-01-01", "2021-01-01", "2022-09-01", "2022-09-01"]))
    source = pd.Series(["shipment", "shipment", "delpro", "delpro"])
    assert assign_regime(targets, source, origins).tolist() == [
        SHIPMENT_EARLY, SHIPMENT, CROSS_BREAK, DELPRO_EARLY]


def table():
    rows = []
    for origin, forecast in [("2022-07-01", 160.), ("2022-12-01", 80.)]:
        for model, f in [("milk_baseline", forecast), ("persistence", 110.)]:
            rows.append(dict(origin=origin, period_start="2023-01-01", grain="monthly",
                             horizon=6, source="delpro", k_source="shipment",
                             actual=100., forecast=f, model=model))
    return pd.DataFrame(rows)


def test_cross_break_opposite_bias_never_pooled_and_borrowed_k_not_origin_source():
    result = regime_table(table()).set_index("regime")
    assert result.loc[CROSS_BREAK, "bias_pct"] == 60
    assert result.loc[DELPRO_EARLY, "bias_pct"] == -20
    assert result.n.tolist() == [1, 1]


def test_explicit_unknown_source_not_inferred_from_target():
    frame = table().assign(origin_source="unknown")
    assert regime_table(frame).regime.tolist() == ["other"]


def test_right_only_comparison_retains_regime():
    b = table()
    a = b[b.origin == "2022-07-01"]
    result = matched_table(a, b).set_index("regime")
    assert result.loc[DELPRO_EARLY, "only_b"] == 1
    assert result.loc[CROSS_BREAK, "n_both"] == 1


def test_mismatched_actual_refused():
    with pytest.raises(ValueError, match="disagree"):
        matched_table(table(), table().assign(actual=99.))


def test_boundary_audit_cannot_see_future_or_same_day():
    dates = pd.date_range("2020-01-01", periods=220)
    daily = pd.DataFrame(dict(date=dates, n_herd=100., is_scoreable=True, target_litres=100.))
    daily.loc[150:179, "is_scoreable"] = False
    origin = dates[180]
    before = boundary_audit(daily, [origin])
    assert before.n_breaks.iloc[0] == 0  # recovery day is not yet known
    assert boundary_audit(daily, [dates[181]]).n_breaks.iloc[0] == 1
    changed = daily.copy()
    changed.loc[180:, "n_herd"] = 10000.
    pd.testing.assert_frame_equal(before, boundary_audit(changed, [origin]))


def test_user_boundary_report_uses_only_synthetic_source():
    from components.predictive_farm_intelligence.pfoi.regime_boundary_check import audit_source
    class SyntheticSource:
        def panel_daily(self, start, end):
            return pd.DataFrame({"date": pd.date_range(start, end, inclusive="left"), "n_herd": 100.})

        def target_daily(self, start, end):
            return self.panel_daily(start, end).assign(is_scoreable=True, target_litres=100.)
    result = audit_source(SyntheticSource())
    assert len(result) == 7
    assert (result.n_breaks == 0).all()
    assert (result.use == "posthoc_descriptive").sum() == 3


def test_cli_calibration_sensitivity_and_development_cut(tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi.regimes import main
    frame = table()
    future = frame.assign(origin="2023-12-01", period_start="2024-01-01")
    path = tmp_path / "synthetic_errors.csv"
    pd.concat([frame, future]).to_csv(path, index=False)
    assert main([str(path), "--source-basis", "calibration"]) == 0
    output = capsys.readouterr().out
    assert "APPENDIX F SENSITIVITY" in output
    assert DELPRO_EARLY not in output
    assert CROSS_BREAK in output


def test_chart_reports_cross_break_as_separate_panel(tmp_path, monkeypatch):
    from components.predictive_farm_intelligence.docs import make_blend_figures as charts
    monkeypatch.setattr(charts, "OUT_FIG", tmp_path)
    frame = pd.DataFrame({"regime": [SHIPMENT_EARLY, SHIPMENT, CROSS_BREAK, DELPRO_EARLY],
                          "grain": "weekly", "block": "development", "horizon": 1,
                          "err_a": 20., "err_b": 10., "err_p": 30.,
                          "covered_a": True, "covered_b": True})
    result = charts.fig_regime(frame)
    cross = result[(result.regime == CROSS_BREAK) & (result.horizon == 1)]
    assert cross.n.iloc[0] == 1
    assert (tmp_path / "m10_blend_mae_by_regime.png").is_file()
