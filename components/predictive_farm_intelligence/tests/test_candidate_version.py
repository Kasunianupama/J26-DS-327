"""pfoi-1.1.0 (frozen 2026-10-20): recency-weighted rates, correction layer and version
separation from pfoi-1.0.0 (SYNTHETIC data)."""
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import MODEL_VERSION, cli
from components.predictive_farm_intelligence.pfoi.config import EngineConfig
from components.predictive_farm_intelligence.pfoi.data import load_origin_inputs
from components.predictive_farm_intelligence.pfoi.freeze import (
    CANDIDATE_ENGINE, CANDIDATE_VERSION, FROZEN_ENGINE, FROZEN_MILK, config_hash, version_label,
)
from components.predictive_farm_intelligence.pfoi.rates import (
    _month_weights, estimate_rates, recency_weighted,
)

from .synthetic import FakeHerdSource

ORIGIN = date(2020, 1, 1)


def _inputs(window: int = 12):
    return load_origin_inputs(FakeHerdSource(), ORIGIN, EngineConfig(window_months=window)).rate_inputs


def test_frozen_hash_unchanged_by_new_option():
    assert config_hash() == "3cbd28787fcb"  # docs/freeze.md
    assert FROZEN_ENGINE.rate_half_life_months is None


def test_version_labels_keep_frozen_and_candidate_apart():
    assert version_label(FROZEN_ENGINE, FROZEN_MILK) == MODEL_VERSION
    assert version_label(CANDIDATE_ENGINE, FROZEN_MILK) == CANDIDATE_VERSION
    other = replace(CANDIDATE_ENGINE, rate_half_life_months=3.0)
    assert version_label(other).startswith("experiment-")
    assert CANDIDATE_VERSION != MODEL_VERSION


def test_month_weights_halve_every_half_life():
    months = pd.Series([date(2019, 12, 1), date(2019, 6, 1), date(2018, 12, 1)])
    w = _month_weights(months, ORIGIN, half_life=6.0)
    assert w == pytest.approx([1.0, 0.5, 0.25])


def test_no_half_life_gives_the_frozen_rates():
    ri = _inputs()
    a = estimate_rates(ri, EngineConfig())
    b = estimate_rates(ri, EngineConfig(rate_half_life_months=None))
    assert a.abortion == b.abortion and a.exit == b.exit


def test_steady_rates_are_unchanged_by_weighting():
    ri = _inputs()
    flat = estimate_rates(ri, EngineConfig())
    weighted = estimate_rates(ri, EngineConfig(rate_half_life_months=3.0))
    assert weighted.conc_heifer == pytest.approx(flat.conc_heifer, rel=1e-6)
    assert weighted.calf_to_heifer == pytest.approx(flat.calf_to_heifer, rel=1e-6)
    assert any(n.startswith("recency-weighted") for n in weighted.notes)


def test_recent_abortion_surge_is_picked_up_faster():
    ri = _inputs()
    months = sorted(ri.panel["month"].unique())
    ri.panel["real_abortions"] = 1.0
    ri.panel.loc[ri.panel["month"].isin(months[-2:]), "real_abortions"] = 30.0  # surge
    flat = estimate_rates(ri, EngineConfig()).abortion
    weighted = estimate_rates(ri, EngineConfig(rate_half_life_months=3.0)).abortion
    assert weighted > 1.5 * flat


def test_weighting_does_not_mutate_inputs_and_keeps_ratio_scale():
    ri = _inputs()
    before = ri.panel.copy()
    w, mean_w = recency_weighted(ri, 6.0)
    pd.testing.assert_frame_equal(ri.panel, before)
    assert 0 < mean_w < 1
    assert w.preg_milking_days == pytest.approx(ri.preg_milking_days * mean_w)
    with pytest.raises(ValueError):
        recency_weighted(ri, 0.0)


def _args(argv):
    parser_args = {}

    def capture(a):
        parser_args["a"] = a
        return 0
    orig = cli._cmd_herd_rates
    cli._cmd_herd_rates = capture
    try:
        cli.main(["herd-rates", "--origin", "2020-01-01", *argv])
    finally:
        cli._cmd_herd_rates = orig
    return parser_args["a"]


def test_cli_preset_builds_the_candidate_config():
    args = _args(["--preset", "candidate"])
    assert cli._engine_cfg(args) == CANDIDATE_ENGINE
    assert cli._wtag(args).endswith("_hl6")


def test_cli_defaults_still_build_the_frozen_config():
    args = _args([])
    assert cli._engine_cfg(args) == FROZEN_ENGINE
    assert cli._wtag(args) == "w12"


def test_posthoc_block_refuses_the_frozen_model(tmp_path):
    args = _args([])
    args.block, args.out, args.every = "posthoc", str(tmp_path), 1
    with pytest.raises(SystemExit):
        cli._block_setup(args, "monthly", "herd", FROZEN_ENGINE)


def test_posthoc_block_runs_candidate_on_2024_origins_without_marker(tmp_path):
    args = _args(["--preset", "candidate"])
    args.block, args.out, args.every = "posthoc", str(tmp_path), 1
    origins, _, marker, rerun, _ = cli._block_setup(args, "monthly", "herd", CANDIDATE_ENGINE)
    assert origins[0] == date(2024, 1, 1) and marker is None and not rerun
    assert cli._bt(args) == "_posthoc"


def test_test_block_still_refuses_the_candidate(tmp_path):
    args = _args(["--preset", "candidate"])
    args.block, args.out, args.every, args.force = "test", str(tmp_path), 1, False
    with pytest.raises(SystemExit):
        cli._block_setup(args, "monthly", "herd", CANDIDATE_ENGINE)
    assert not (tmp_path / "final_test").exists()


def test_model_selection_never_reads_posthoc_or_test_files(tmp_path, capsys):
    row = pd.DataFrame({"origin": ["2024-01-01"], "grain": ["monthly"], "horizon": [1],
                        "period_start": ["2024-01-01"], "period_end": ["2024-01-31"],
                        "series": ["milking"], "model": ["herd_engine"], "forecast": [1.0],
                        "actual": [1.0], "error": [0.0]})
    for tag in ("w24_hl6_posthoc", "w12_test", "w24_posthoc"):
        row.to_csv(tmp_path / f"herd_backtest_errors_monthly_{tag}.csv", index=False)
    assert cli.main(["nested-cv", "--family", "herd", "--out", str(tmp_path)]) == 0
    assert "fewer than two candidates" in capsys.readouterr().out
    assert cli.main(["adapt", "--family", "herd", "--out", str(tmp_path)]) in (0, 1)
    assert not any("_ad" in p.name for p in tmp_path.iterdir())


def test_nested_cv_leaves_out_hindsight_configurations(tmp_path, capsys):
    row = pd.DataFrame({"origin": ["2019-01-01"], "grain": ["monthly"], "horizon": [1],
                        "period_start": ["2019-01-01"], "period_end": ["2019-01-31"],
                        "series": ["milking"], "model": ["herd_engine"], "forecast": [1.0],
                        "actual": [1.0], "error": [0.0]})
    for tag in ("w12_ck", "w36_ck", "w24_ck_kn_rk_lag90"):
        row.to_csv(tmp_path / f"herd_backtest_errors_monthly_{tag}.csv", index=False)
    assert cli.main(["nested-cv", "--family", "herd", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2 tags left out" in out and "fewer than two candidates" in out


def test_outlook_of_a_new_version_is_labelled_with_it():
    from components.predictive_farm_intelligence.pfoi.outlook import build_outlook, run_model

    cfg = replace(FROZEN_ENGINE, rate_half_life_months=6.0)
    run = run_model(FakeHerdSource(), date(2021, 10, 1), cfg, FROZEN_MILK)
    outlook, _, _ = build_outlook(FakeHerdSource(), run.origin, None, "core-test", run=run)
    assert run.version == version_label(cfg, FROZEN_MILK) != MODEL_VERSION
    assert (outlook["model_version"] == run.version).all()


def test_v11_is_frozen_with_its_own_hash():
    from components.predictive_farm_intelligence.pfoi.freeze import (
        V11_ADAPTIVE, V11_ENGINE, V11_VERSION, v11_config_hash,
    )
    assert V11_VERSION == "pfoi-1.1.0" and v11_config_hash() == "2a865a0c2687"
    assert V11_ENGINE.rate_half_life_months == 6.0 and V11_ENGINE.window_months == 24
    assert not V11_ADAPTIVE.pooled and V11_ADAPTIVE.q30 == 0.1


def _errs(model, series, grain, horizon, origins, forecast, actual):
    rows = []
    for o in origins:
        o = pd.Timestamp(o)
        rows.append({"origin": o.date(), "period_end": (o + pd.Timedelta(days=30 * horizon)).date(),
                     "grain": grain, "horizon": horizon, "series": series, "model": model,
                     "forecast": forecast, "actual": actual})
    return pd.DataFrame(rows)


def test_output_layer_uses_only_errors_known_at_the_origin():
    from components.predictive_farm_intelligence.pfoi.freeze import V11_ADAPTIVE
    from components.predictive_farm_intelligence.pfoi.outlook import build_output_layer

    origin = date(2023, 1, 1)
    past = pd.date_range("2021-03-01", periods=18, freq="MS")  # ended before the origin
    future = pd.date_range("2023-01-01", periods=6, freq="MS")  # end after it: unknown
    e = pd.concat([
        _errs("herd_engine", "milking", "monthly", 1, past, 110.0, 100.0),
        _errs("herd_engine", "milking", "monthly", 1, future, 500.0, 100.0),
        _errs("herd_engine", "real_abortions", "monthly", 1, past, 30.0, 10.0),
        _errs("milk_baseline", "herd_milk", "monthly", 1, past, 100.0, 120.0),
    ], ignore_index=True)
    layer = build_output_layer(e, origin, V11_ADAPTIVE, ("milking",))
    assert layer.herd_bias == {("monthly", "milking", 1): pytest.approx(10.0)}
    assert layer.adjust("monthly", "milking", 1, 200.0) == pytest.approx(190.0)
    assert layer.adjust("monthly", "milking", 6, 200.0) == pytest.approx(190.0)  # longest known
    assert layer.adjust("monthly", "milking", 1, 5.0) == 0.0  # never negative
    assert layer.adjust("monthly", "real_abortions", 1, 7.0) == 7.0  # not a corrected series
    x = layer.milk_level[("monthly", 1)]
    assert 0.0 < x <= 0.2  # actual 20 % above forecast; faded towards 0 by tau
    assert layer.adjust("monthly", "herd_milk", 3, 100.0) == pytest.approx(100.0 * (1 + x))
    assert layer.model_for("milking", "herd_engine") == "herd_engine_corrected"
    assert layer.model_for("calves", "herd_engine") == "herd_engine"
    empty = build_output_layer(None, origin, V11_ADAPTIVE, ("milking",))
    assert empty.adjust("monthly", "milking", 1, 50.0) == 50.0


def test_v11_outlook_and_page_apply_the_layer():
    from components.predictive_farm_intelligence.pfoi.freeze import V11_ADAPTIVE
    from components.predictive_farm_intelligence.pfoi.outlook import (
        OutputLayer, build_outlook, run_model,
    )
    from components.predictive_farm_intelligence.pfoi.page_run import build_page_run

    cfg = replace(FROZEN_ENGINE, rate_half_life_months=6.0)
    run = run_model(FakeHerdSource(), date(2021, 10, 1), cfg, FROZEN_MILK)
    raw, _, _ = build_outlook(FakeHerdSource(), run.origin, None, "core-test", run=run)
    run.layer = OutputLayer({("monthly", "milking", 1): 5.0}, {("monthly", 1): 0.1}, ("milking",))
    corr, attribution, _ = build_outlook(FakeHerdSource(), run.origin, None, "core-test", run=run)
    key = ["grain", "horizon", "series"]
    m = raw.merge(corr, on=key, suffixes=("_raw", "_corr")).set_index(key)
    assert m.loc[("monthly", 3, "milking"), "forecast_corr"] == pytest.approx(
        m.loc[("monthly", 3, "milking"), "forecast_raw"] - 5.0)
    assert m.loc[("monthly", 3, "herd_milk"), "forecast_corr"] == pytest.approx(
        m.loc[("monthly", 3, "herd_milk"), "forecast_raw"] * 1.1)
    assert m.loc[("monthly", 3, "calvings"), "forecast_corr"] == m.loc[("monthly", 3, "calvings"), "forecast_raw"]
    doc = build_page_run(FakeHerdSource(), run, attribution, {}, "core-test")
    c = pd.DataFrame(doc["corrections"])
    assert set(c["series"]) == {"milk_litres", "milking"}
    assert (c.loc[c["series"] == "milking", "correction"] == -5.0).all()
    assert doc["model_version"] == run.version
    assert V11_ADAPTIVE.tau_days == 365.0


def _doc(forecast: float, lower: float, upper: float) -> dict:
    months = ["2024-02-01", "2024-03-01"]
    return {
        "outlook": [{"grain": "month", "series": "milking", "target_period": m, "horizon": i + 1,
                     "forecast": forecast, "lower": lower, "upper": upper}
                    for i, m in enumerate(months)],
        "realised": [{"grain": "month", "series": "milking", "period": m, "value": 100.0,
                      "scoreable": True} for m in months]
                    + [{"grain": "month", "series": "milking", "period": "2024-04-01",
                        "value": None, "scoreable": False}],
        "actuals": [{"grain": "month", "series": "milking", "period": "2023-12-01",
                     "value": 105.0, "scoreable": True}],
    }


def test_compare_scores_both_models_on_the_same_recorded_months(tmp_path):
    from components.predictive_farm_intelligence.pfoi.compare_runs import plot, score

    frozen, cand = _doc(120.0, 110.0, 130.0), _doc(95.0, 90.0, 105.0)
    t = score(frozen, cand, series=("milking",)).iloc[0]
    assert t["n_months"] == 2
    assert t["mae_frozen"] == pytest.approx(20.0) and t["mae_candidate"] == pytest.approx(5.0)
    assert t["bias_frozen"] == pytest.approx(20.0) and t["bias_candidate"] == pytest.approx(-5.0)
    assert t["cover90_frozen"] == 0.0 and t["cover90_candidate"] == 1.0
    assert t["change_pct"] == pytest.approx(-75.0)
    assert t["layer_candidate"] == 0.0  # no corrections list: structural only
    norange = _doc(120.0, 120.0, 120.0)  # no past errors: lower = upper = forecast
    cand["corrections"] = [{"grain": "month", "series": "milking", "target_period": "2024-02-01",
                            "correction": -4.0}]
    t2 = score(norange, cand, series=("milking",)).iloc[0]
    assert np.isnan(t2["cover90_frozen"]) and t2["cover90_candidate"] == 1.0
    assert t2["layer_candidate"] == pytest.approx(-4.0)
    plot(frozen, cand, date(2024, 1, 1), tmp_path / "c.png", series=("milking",))
    assert (tmp_path / "c.png").stat().st_size > 0
