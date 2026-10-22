"""Synthetic-only tests for the chronological individual-cow accuracy notebook."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from components.predictive_farm_intelligence.pfoi.cow_accuracy import (
    AccuracyModels,
    SELECTION_TRAIN_END,
    VALID_END,
    aggregate_grain,
    cow_accuracy_sql,
    daily_prediction,
    feature_catalogue,
    plot_model_performance,
    prepare_accuracy_frame,
    safe_column_profile,
    safe_split_summary,
    safe_test_coverage_by_year,
    score_models,
    score_performance_windows,
    select_validation_winners,
    split_accuracy_frames,
    to_frontend_backtest_rows,
    write_accuracy_outputs,
)


def raw_cowdays() -> pd.DataFrame:
    dates = pd.to_datetime([
        "2019-06-28", "2019-06-29", "2019-06-30", "2019-07-01", "2019-12-31",
        "2020-01-01", "2020-01-02",
    ])
    rows = []
    for cow in range(1, 13):
        for i, day in enumerate(dates):
            rows.append({
                "cow_id": cow,
                "date": day,
                "litres": 8.0 + cow / 10 + i / 20,
                "dim": 40 + i,
                "parity_group": "1" if cow % 2 else "2",
                "age_days": 900 + cow,
                "milkings": 2.0,
                "conductivity": np.nan,
                "milking_duration_sec": np.nan,
                "avg_blood": np.nan,
                "avg_cell_count": np.nan,
                "avg_bcs": 3.0,
                "avg_weight": 350.0,
                "avg_rectal_temp": 38.5,
                "thi_mean": 68.0,
                "mastitis_30d": 0.0,
                "health_30d": 0.0,
                "treatments_30d": 0.0,
            })
    return pd.DataFrame(rows)


def test_sql_filters_target_and_does_not_return_pseudonym_key():
    sql = cow_accuracy_sql("core")
    final_select = sql.split("SELECT DENSE_RANK()", 1)[1]
    output_clause = final_select.split("FROM target", 1)[0]
    assert "AS animal_key" not in output_clause
    assert "AS cow_id" in output_clause
    assert "d.yield_litres > 0 AND d.yield_litres <= 18" in sql
    assert "NOT COALESCE(a.is_placeholder, false)" in sql
    assert "d.animal_key <> 'A_PLACEHOLDER'" in sql
    assert "NOT COALESCE(d.is_unlinked_animal, false)" in sql
    assert "target_raw WHERE n_records = 1" in sql
    # Health and treatment history come from origin-safe event features, not same-day joins.
    assert "health_episode" not in sql and "treatment_history" not in sql
    for forbidden in ("milk_shipped", "milk_internal", "milk_hand_milked_est", "milk_delpro"):
        assert forbidden not in sql
    with pytest.raises(ValueError):
        cow_accuracy_sql("core; drop schema core")


def test_python_boundary_also_removes_yield_above_eighteen():
    raw = raw_cowdays()
    raw.loc[0, "litres"] = 18.0
    raw.loc[1, "litres"] = 18.0001
    prepared = prepare_accuracy_frame(raw)
    assert prepared["litres"].max() <= 18.0
    assert len(prepared) == len(raw) - 1


def test_lags_are_past_only_and_source_keys_are_rejected():
    raw = raw_cowdays()
    prepared = prepare_accuracy_frame(raw)
    cow = prepared[prepared["animal"] == 1].reset_index(drop=True)
    assert np.isnan(cow.loc[0, "yield_lag1"])
    assert cow.loc[1, "yield_lag1"] == cow.loc[0, "litres"]
    assert cow.loc[2, "yield_lag1"] == cow.loc[1, "litres"]

    changed = raw.copy()
    changed.loc[(changed["cow_id"] == 1) & (changed["date"] == pd.Timestamp("2019-07-01")),
                "litres"] = 17.5
    changed_cow = prepare_accuracy_frame(changed)
    changed_cow = changed_cow[changed_cow["animal"] == 1].reset_index(drop=True)
    baseline_validation = cow[cow["date"] == pd.Timestamp("2019-07-01")].iloc[0]
    changed_validation = changed_cow[
        changed_cow["date"] == pd.Timestamp("2019-07-01")
    ].iloc[0]
    assert changed_validation["yield_lag1"] == baseline_validation["yield_lag1"]

    baseline = prepare_accuracy_frame(raw)
    changed_test = raw.copy()
    changed_test.loc[(changed_test["cow_id"] == 1)
                     & (changed_test["date"] == pd.Timestamp("2020-01-01")),
                     "litres"] = 17.5
    mutated = prepare_accuracy_frame(changed_test)
    features = ["yield_lag1", "yield_mean7", "yield_mean28", "yield_sd28",
                "days_since_record", "dim", "age_days", "parity_group"]
    before = baseline[(baseline["animal"] == 1)
                      & (baseline["date"] == pd.Timestamp("2020-01-02"))]
    after = mutated[(mutated["animal"] == 1)
                    & (mutated["date"] == pd.Timestamp("2020-01-02"))]
    pd.testing.assert_frame_equal(before[features].reset_index(drop=True),
                                  after[features].reset_index(drop=True))

    raw["animal_key"] = "A_RESTRICTED"
    with pytest.raises(ValueError, match="source keys"):
        prepare_accuracy_frame(raw)


def test_daily_weekly_monthly_scores_and_frontend_rows_are_aggregate(tmp_path):
    frame = prepare_accuracy_frame(raw_cowdays())
    predictions = {
        "model_a": frame["litres"].to_numpy() * 0.98,
        "model_b": frame["litres"].to_numpy() * 1.03,
    }
    models = AccuracyModels(frame=frame, predictions=predictions, fitted={})
    metrics, performance = score_models(models, blocks=("test",))
    assert set(metrics["grain"]) == {"daily", "weekly", "monthly"}
    assert {"mae", "rmse", "bias", "wape_pct", "accuracy_pct", "within_5pct",
            "within_10pct", "within_20pct", "mape_pct", "r2", "pearson_r",
            "skill_vs_persistence_pct"} <= set(metrics.columns)
    assert len(metrics) == 6
    daily_a = metrics[(metrics["model"] == "model_a") & (metrics["grain"] == "daily")].iloc[0]
    # Every cow-day is 2% low: accuracy 98%, all within 5%, MAPE 2%.
    assert daily_a["accuracy_pct"] == pytest.approx(98.0)
    assert daily_a["within_5pct"] == pytest.approx(100.0)
    assert daily_a["mape_pct"] == pytest.approx(2.0)
    assert daily_a["wape_pct"] == pytest.approx(2.0)

    windows = score_performance_windows(
        performance, {"untouched_2020": (pd.Timestamp("2020-01-01").date(),
                                         pd.Timestamp("2020-12-31").date())},
    )
    assert set(windows["block"]) == {"untouched_2020"}
    assert set(windows["grain"]) == {"daily", "weekly", "monthly"}

    frontend = to_frontend_backtest_rows(metrics)
    assert list(frontend.columns) == [
        "block", "model", "grain", "horizon", "series", "mae", "rmse",
        "bias", "coverage", "n_origins",
    ]
    assert set(frontend["grain"]) == {"day", "week", "month"}
    assert set(frontend["series"]) == {"milk_litres_per_cow_experiment"}
    assert not any("animal" in c or "cow_id" in c for c in frontend.columns)

    written = write_accuracy_outputs(metrics, performance, tmp_path)
    assert tmp_path / "frontend_backtest_rows.csv" not in written
    for path in written:
        columns = pd.read_csv(path, nrows=0).columns
        assert "animal" not in columns
        assert "animal_key" not in columns
        assert "cow_id" not in columns


def test_chronological_selection_then_final_refit_split():
    raw = raw_cowdays()
    selection = prepare_accuracy_frame(
        raw, train_end=SELECTION_TRAIN_END, validation_end=VALID_END,
    )
    assert set(selection.loc[selection["date"] <= pd.Timestamp("2019-06-30"), "period"]) == {"train"}
    assert set(selection.loc[selection["date"].between("2019-07-01", "2019-12-31"),
                             "period"]) == {"validation"}
    assert set(selection.loc[selection["date"].dt.year == 2020, "period"]) == {"test"}

    final = prepare_accuracy_frame(raw)
    assert set(final.loc[final["date"].dt.year == 2019, "period"]) == {"train"}
    assert set(final.loc[final["date"].dt.year == 2020, "period"]) == {"test"}
    assert "validation" not in set(final["period"])

    parts = split_accuracy_frames(selection)
    assert set(parts) == {"train", "validation", "test"}
    assert all((part["period"] == name).all() for name, part in parts.items())
    summary = safe_split_summary(parts)
    assert set(summary["dataframe"]) == {"train_df", "validation_df", "test_df"}
    assert not ({"animal", "cow_id", "animal_key"} & set(summary.columns))

    coverage = safe_test_coverage_by_year(final)
    assert list(coverage["year"]) == list(range(2020, 2027))
    assert coverage.loc[coverage["year"] == 2026,
                        "scoreable_cow_days"].iloc[0] == 0
    assert not ({"animal", "cow_id", "animal_key"} & set(coverage.columns))


def test_safe_eda_profiles_columns_without_identifiers_or_rows():
    raw = raw_cowdays()
    profile = safe_column_profile(raw)
    assert "cow_id" not in set(profile["column"])
    assert set(profile.columns) == {"column", "dtype", "non_null", "missing_pct", "unique_count"}
    assert not ({"litres", "date"} - set(profile["column"]))

    catalogue = feature_catalogue(["mastitis_episodes_30d", "health_available",
                                   "health_unavailable"])
    assert {"yield_lag1", "yield_mean7", "mastitis_episodes_30d", "parity_*"} <= set(
        catalogue["feature"])
    mastitis = catalogue[catalogue["feature"] == "mastitis_episodes_30d"].iloc[0]
    assert mastitis["source"] == "core.health_episode"
    assert mastitis["used_by"] == "all residual models"
    same_day = catalogue[catalogue["feature"] == "milkings"].iloc[0]
    assert "excluded" in same_day["forecast_availability"]
    assert "unavailable at forecast origin" in same_day["forecast_availability"]
    assert same_day["used_by"] == "none"


def test_winners_are_selected_only_from_validation_rows():
    metrics = pd.DataFrame([
        {"block": block, "grain": grain, "model": model, "wape_pct": score}
        for grain in ("daily", "weekly", "monthly")
        for block, model, score in (
            ("validation", "chosen_before_test", 5.0),
            ("validation", "looks_good_only_on_test", 6.0),
            ("test", "chosen_before_test", 20.0),
            ("test", "looks_good_only_on_test", 1.0),
        )
    ])
    winners = select_validation_winners(metrics)
    assert set(winners["model"]) == {"chosen_before_test"}


def test_monday_start_week_and_coverage_gate():
    daily = daily_prediction(
        prepare_accuracy_frame(raw_cowdays()),
        prepare_accuracy_frame(raw_cowdays())["litres"].to_numpy(),
        "identity",
    )
    weekly = aggregate_grain(daily, "weekly", min_coverage=0.0)
    assert (pd.to_datetime(weekly["period_start"]).dt.dayofweek == 0).all()


def test_monthly_public_value_is_mean_cow_day_not_a_herd_total():
    frame = prepare_accuracy_frame(raw_cowdays())
    models = AccuracyModels(
        frame=frame,
        predictions={"identity": frame["litres"].to_numpy()},
        fitted={},
    )
    _, performance = score_models(
        models, min_coverage=0.0, blocks=("test",),
    )
    monthly = performance["identity"]["monthly"]
    test = monthly[monthly["period"] == "test"]
    assert len(test) == 1
    eligible = frame.loc[frame["score_eligible"]].copy()
    expected = eligible["litres"].mean()
    assert test.iloc[0]["actual"] == pytest.approx(expected)
    assert test.iloc[0]["prediction"] == pytest.approx(test.iloc[0]["actual"])
    assert test.iloc[0]["actual"] <= 18.0


def test_plot_does_not_join_across_missing_months():
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    monthly = pd.DataFrame({
        "period_start": pd.to_datetime(["2021-12-01", "2026-01-01"]),
        "period": ["test", "test"],
        "actual": [9.0, 10.0],
        "prediction": [9.5, 10.5],
    })
    fig = plot_model_performance(
        "gap_check", {"monthly": monthly}, show_test_grains={"monthly"},
    )
    actual_line = next(
        line for line in fig.axes[2].lines
        if line.get_label().startswith("Final-test actual")
    )
    assert np.isnan(np.asarray(actual_line.get_ydata(), dtype=float)).any()
    right_edge = matplotlib.dates.num2date(fig.axes[2].get_xlim()[1]).date()
    assert right_edge == pd.Timestamp("2026-08-31").date()
    assert any("No leakage-free" in text.get_text() for text in fig.axes[2].texts)
    plt.close(fig)


def test_notebook_builder_uses_supported_source_factory_signature():
    builder = Path(__file__).parents[1] / "notebooks" / "build_05_individual_cow_accuracy.py"
    source = builder.read_text(encoding="utf-8")
    assert "SqlHerdSource.from_env()" in source
    assert "from_env(mi=" not in source
    assert 'os.environ["PFOI_MODEL_INPUT_SCHEMA"] = INPUT_SCHEMA' in source
    assert 'target_sql = cow_accuracy_sql("core")' in source
    assert '"milk_shipped", "milk_internal", "milk_hand_milked_est", "milk_delpro"' in source
    assert 'raw.duplicated(["cow_id", "date"]' in source
    assert 'assert cleaning_checks["passed"].all()' in source
    assert 'assert period_cleaning_checks["passed"].all()' in source



def test_weekly_and_monthly_origins_freeze_history_at_period_start():
    dates = pd.date_range("2019-12-02", "2020-02-28", freq="D")
    raw = pd.DataFrame([{"cow_id": cow, "date": d, "litres": 8.0 + (i % 5) / 10 + cow / 10,
                         "dim": 40 + i, "parity_group": "1", "age_days": 900 + i}
                        for cow in range(1, 4) for i, d in enumerate(dates)])
    for grain in ("weekly", "monthly"):
        base = prepare_accuracy_frame(raw, evaluation_mode="walk_forward", origin_grain=grain)
        # Change a yield in the middle of a test period: no feature of a later day in the
        # same period may move, because they were all issued at the period start.
        target = pd.Timestamp("2020-02-12")  # Wednesday, mid-month
        changed = raw.copy()
        changed.loc[(changed["cow_id"] == 1) & (changed["date"] == target), "litres"] = 17.5
        after = prepare_accuracy_frame(changed, evaluation_mode="walk_forward",
                                       origin_grain=grain)
        later = pd.Timestamp("2020-02-14")
        cols = ["yield_lag1", "yield_mean7", "yield_mean28", "yield_sd28",
                "days_since_record", "origin_history_n"]
        a = base[(base["animal"] == 1) & (base["date"] == later)][cols]
        b = after[(after["animal"] == 1) & (after["date"] == later)][cols]
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
        row = base[(base["animal"] == 1) & (base["date"] == later)].iloc[0]
        start = pd.Timestamp("2020-02-10") if grain == "weekly" else pd.Timestamp("2020-02-01")
        assert row["origin_date"] == start
        assert row["days_since_record"] == (later - start).days + 1
    daily = prepare_accuracy_frame(raw, evaluation_mode="walk_forward")
    assert (daily["origin_date"] == daily["date"]).all()


def _dense_raw(start="2018-01-01", end="2021-06-30", cows=12):
    dates = pd.date_range(start, end, freq="D")
    rng = np.random.default_rng(3)
    rows = []
    for cow in range(1, cows + 1):
        for i, d in enumerate(dates):
            level = 0.6 if d.year >= 2021 else 1.0  # herd-wide drop the curve cannot see
            rows.append({"cow_id": cow, "date": d, "dim": 30 + (i % 300),
                         "parity_group": "1" if cow % 2 else "2", "age_days": 900 + i,
                         "litres": float(np.clip(level * (9 + cow / 4) + rng.normal(0, 0.3),
                                                 0.5, 18))})
    return pd.DataFrame(rows)


def test_level_features_use_only_days_before_the_origin():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import _add_level_features
    raw = _dense_raw(end="2020-03-31", cows=4)
    f = prepare_accuracy_frame(raw, evaluation_mode="walk_forward")
    wood = np.full(len(f), 10.0)
    base = _add_level_features(f, wood)
    changed = f.copy()
    day = pd.Timestamp("2020-02-10")
    changed.loc[changed["date"] == day, "litres"] = 17.0
    after = _add_level_features(changed, wood)
    cols = ["herd_resid_28d", "herd_yield_28d", "cow_resid_mean7"]
    same = base["date"] <= day
    pd.testing.assert_frame_equal(base.loc[same, cols], after.loc[same, cols])
    assert not np.allclose(base.loc[base["date"] == day + pd.Timedelta(days=1), cols],
                           after.loc[after["date"] == day + pd.Timedelta(days=1), cols])
    assert base[cols].notna().all().all()


def test_expanding_backtest_refits_each_year_and_assigns_rows_by_origin():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import expanding_backtest
    raw = _dense_raw()
    models, folds = expanding_backtest(
        raw, {"persistence_last_yield": {"daily", "weekly", "monthly"}},
        test_years=(2020, 2021, 2022))
    assert list(folds["status"]) == ["fitted", "fitted", "insufficient data"]
    assert folds.loc[1, "train_end"] == pd.Timestamp("2020-12-31").date()
    for grain in ("daily", "weekly", "monthly"):
        frame, _ = models.for_grain(grain)
        test = frame[frame["period"] == "test"]
        assert not test.duplicated(["animal", "date"]).any()
        assert test["date"].min() >= pd.Timestamp("2020-01-01")
        assert test["origin_date"].dt.year.isin([2020, 2021]).all()
    metrics, _ = score_models(models, blocks=("test",))
    assert set(metrics["status"]) == {"scored"}


def test_chronological_split_hits_target_shares_in_time_order():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import chronological_split
    raw = _dense_raw(start="2018-01-01", end="2021-12-31", cows=5)
    split = chronological_split(raw["date"], (0.75, 0.05, 0.20))
    s = split.summary.set_index("block")
    assert list(s.index) == ["train", "validation", "test"]
    for block, target in (("train", 75), ("validation", 5), ("test", 20)):
        assert abs(s.loc[block, "share_pct"] - target) < 0.5
    assert s.loc["train", "end"] < s.loc["validation", "start"]
    assert s.loc["validation", "end"] < s.loc["test", "start"]
    assert split.test_start == (pd.Timestamp(split.validation_end) + pd.Timedelta(days=1)).date()
    with pytest.raises(ValueError):
        chronological_split(raw["date"], (0.8, 0.3, 0.2))


def test_recording_gap_is_removed_and_reported():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import (
        exclude_recording_gap, recording_gap_check,
    )
    raw = _dense_raw(start="2022-04-25", end="2022-05-05", cows=2)
    raw["milkings"] = 2.0
    kept = exclude_recording_gap(raw, (pd.Timestamp("2022-05-01").date(),
                                       pd.Timestamp("2025-12-31").date()))
    assert pd.to_datetime(kept["date"]).max() == pd.Timestamp("2022-04-30")
    assert len(exclude_recording_gap(raw, None)) == len(raw)
    check = recording_gap_check(raw)
    assert list(check.columns) == ["year", "cow_days", "cows", "mean_litres", "mean_milkings",
                                   "milkings_recorded", "in_recording_gap"]
    assert check["in_recording_gap"].all()


def test_backtest_with_mid_year_test_start_never_trains_past_it():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import expanding_backtest
    raw = _dense_raw(start="2019-01-01", end="2021-03-31", cows=10)
    start = pd.Timestamp("2020-09-01").date()
    models, folds = expanding_backtest(
        raw, {"persistence_last_yield": {"daily"}}, test_start=start)
    assert folds.loc[0, "train_end"] == pd.Timestamp("2020-08-31").date()
    assert folds.loc[1, "train_end"] == pd.Timestamp("2020-12-31").date()
    test = models.frame[models.frame["period"] == "test"]
    assert test["date"].min() >= pd.Timestamp(start)
    assert not test.duplicated(["animal", "date"]).any()


def test_parallel_folds_match_sequential_folds():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import expanding_backtest
    raw = _dense_raw(start="2019-01-01", end="2021-06-30", cows=8)
    selected = {"persistence_last_yield": {"daily", "weekly"}}
    seq, seq_folds = expanding_backtest(raw, selected, test_years=(2020, 2021),
                                        parallel_folds=1)
    par, par_folds = expanding_backtest(raw, selected, test_years=(2020, 2021),
                                        parallel_folds=2, verbose=True)
    assert list(seq_folds["test_cow_days"]) == list(par_folds["test_cow_days"])
    for grain in ("daily", "weekly"):
        a_frame, a_pred = seq.for_grain(grain)
        b_frame, b_pred = par.for_grain(grain)
        pd.testing.assert_frame_equal(a_frame.reset_index(drop=True),
                                      b_frame.reset_index(drop=True))
        np.testing.assert_allclose(a_pred["persistence_last_yield"],
                                   b_pred["persistence_last_yield"])


def test_lags_reset_at_a_new_lactation_and_previous_lactation_mean_is_kept():
    dates = pd.date_range("2020-01-01", periods=12, freq="10D")
    dim = [200, 210, 220, 230, 240, 250, 5, 15, 25, 35, 45, 55]  # calving between 6 and 7
    raw = pd.DataFrame({"cow_id": 1, "date": dates, "litres": [8.0] * 6 + [14.0] * 6,
                        "dim": dim, "parity_group": ["1"] * 6 + ["2"] * 6,
                        "age_days": 900, "milkings": [0.0] * 6 + [2.0] * 6})
    f = prepare_accuracy_frame(raw, evaluation_mode="walk_forward")
    first_new = f.iloc[6]
    assert np.isnan(first_new["yield_lag1"])  # no lag from the previous lactation
    assert first_new["prev_lactation_mean"] == pytest.approx(8.0)
    assert first_new["days_since_any_record"] == 10
    assert f.iloc[7]["yield_lag1"] == 14.0
    assert f.iloc[7]["prev_lactation_mean"] == pytest.approx(8.0)
    assert f["milkings"].iloc[:6].isna().all()  # 0 milkings means "not recorded"
    assert f.iloc[3]["cow_records_28d"] == 2


def test_recalibration_uses_only_outcomes_before_the_origin():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import recalibrate
    raw = _dense_raw(start="2020-01-01", end="2020-06-30", cows=60)
    f = prepare_accuracy_frame(raw, evaluation_mode="walk_forward")
    biased = f["litres"].to_numpy() * 0.8  # every prediction 20% too low
    fixed = recalibrate(f, biased)
    late = (f["date"] > pd.Timestamp("2020-03-01")).to_numpy()
    # 60 cows x 28 days = 1,680 cow-days vs a 200 cow-day prior: almost fully corrected.
    assert np.mean(fixed[late] / f["litres"].to_numpy()[late]) == pytest.approx(1.0, abs=0.04)
    first_day = (f["date"] == f["date"].min()).to_numpy()
    np.testing.assert_allclose(fixed[first_day], biased[first_day])  # nothing known yet
    changed = f.copy()
    day = pd.Timestamp("2020-04-10")
    changed.loc[changed["date"] == day, "litres"] = 18.0
    again = recalibrate(changed, biased)
    upto = (f["date"] <= day).to_numpy()
    np.testing.assert_allclose(fixed[upto], again[upto])


def test_blend_is_cross_fitted_on_validation_and_reused_on_test():
    from components.predictive_farm_intelligence.pfoi.cow_accuracy import (
        add_blend_candidate, apply_blend_spec,
    )
    raw = _dense_raw(start="2019-01-01", end="2020-12-31", cows=12)
    f = prepare_accuracy_frame(raw, train_end=pd.Timestamp("2019-12-31").date(),
                               validation_end=pd.Timestamp("2020-06-30").date(),
                               evaluation_mode="walk_forward")
    y = f["litres"].to_numpy()
    models = AccuracyModels(frame=f, fitted={}, predictions={
        "model": y * 1.1, "persistence_last_yield": f["yield_lag1"].fillna(10).to_numpy()})
    spec = add_blend_candidate(models, {"daily": "model"})
    weights = spec["daily"][1]
    assert set(weights.values()) <= set(np.round(np.linspace(0, 1, 21), 2))
    blend_once = models.predictions["blend"].copy()
    apply_blend_spec(models, spec)
    test = (f["period"] == "test").to_numpy()
    np.testing.assert_allclose(blend_once[test], models.predictions["blend"][test])


def test_time_series_tuning_never_uses_rows_after_train_end():
    from components.predictive_farm_intelligence.pfoi.cow_tuning import (
        build_folds, tune_residual_model,
    )
    raw = _dense_raw(start="2019-01-01", end="2021-06-30", cows=6)
    end = pd.Timestamp("2020-12-31").date()
    folds = build_folds(raw, end)
    assert folds[-1]["score_end"] == end
    assert all(f["fit_end"] < f["score_end"] for f in folds)
    best, table = tune_residual_model(folds, "lgbm", n_trials=3, n_jobs=2)
    assert table["setting"].tolist().count("default") == 1
    assert {"num_leaves", "learning_rate", "objective"} <= set(best)
    best_rf, _ = tune_residual_model(folds, "rf", n_trials=2, n_jobs=2)
    assert "min_samples_leaf" in best_rf


def test_diagnostics_are_aggregate_only():
    from components.predictive_farm_intelligence.pfoi.cow_diagnostics import (
        error_breakdown, noise_floor,
    )
    raw = _dense_raw(start="2019-01-01", end="2020-12-31", cows=12)
    f = prepare_accuracy_frame(raw, evaluation_mode="walk_forward",
                               train_end=pd.Timestamp("2019-12-31").date(),
                               validation_end=pd.Timestamp("2019-12-31").date())
    out = error_breakdown(f, f["litres"].to_numpy() * 1.05, block="test")
    assert not ({"animal", "cow_id", "animal_key"} & set(out.columns))
    ok = out[out["status"] == "ok"]
    assert (ok["cow_days"] >= 20).all()
    assert np.allclose(ok["bias_pct"], 5.0)
    floor = noise_floor(f)
    assert "short_gap_persistence_accuracy_pct" in floor
    assert not ({"animal", "cow_id"} & set(floor.columns))


def test_two_year_windows_follow_the_clean_blocks_and_never_overlap():
    from components.predictive_farm_intelligence.pfoi.cow_runner import (
        rolling_window_study, two_year_windows,
    )
    d = pd.Series(pd.to_datetime(["2015-10-07", "2016-06-01", "2017-01-01", "2018-01-01",
                                  "2019-01-01", "2020-01-01", "2021-01-01", "2022-04-30",
                                  "2025-11-03", "2026-08-20"]))
    windows = two_year_windows(d)
    assert [w["window"] for w in windows] == [
        "train 2015-2016 / test 2017-2018", "train 2017-2018 / test 2019-2020",
        "train 2019-2020 / test 2021-2022", "train 2021-2022 / test 2025-2026"]
    assert all(w["train_end"] < w["test_start"] for w in windows)
    raw = _dense_raw(start="2017-01-01", end="2020-12-31", cows=6)
    metrics, cond = rolling_window_study(raw, None, n_jobs=2, parallel_grains=False,
                                         exclude_gap=False, blocks="two_years")
    assert set(metrics["window"]) == {"train 2017-2018 / test 2019-2020"}
    assert {"persistence_last_yield", "lgbm_residual_history"} <= set(metrics["model"])
    assert cond.loc[0, "test_cow_days"] > 0


def test_equal_record_windows_hold_equal_cow_days():
    from components.predictive_farm_intelligence.pfoi.cow_runner import equal_record_windows
    raw = _dense_raw(start="2015-11-01", end="2020-12-31", cows=4)
    windows = equal_record_windows(raw["date"], n_blocks=5)
    assert len(windows) == 4
    sizes = [windows[0]["train_cow_days"]] + [w["test_cow_days"] for w in windows]
    assert max(sizes) - min(sizes) <= 2 * 4  # equal up to whole days
    assert sum(sizes) == len(raw)
    assert all(w["train_end"] < w["test_start"] for w in windows)


def test_cleaning_period_and_consistency_checks_are_aggregate():
    from components.predictive_farm_intelligence.pfoi.cow_diagnostics import (
        cleaning_contract_checks, period_cleaning_checks, record_consistency,
    )
    raw = _dense_raw(start="2019-01-01", end="2019-12-31", cows=5)
    raw["milkings"] = 2.0
    checks = cleaning_contract_checks(raw, cow_accuracy_sql("core"),
                                      pd.Timestamp("2015-08-01").date(),
                                      pd.Timestamp("2026-08-31").date())
    assert checks["passed"].all()
    bad = pd.concat([raw, raw.iloc[[0]]])
    assert not cleaning_contract_checks(bad, cow_accuracy_sql("core"),
                                        pd.Timestamp("2015-08-01").date(),
                                        pd.Timestamp("2026-08-31").date())["passed"].all()
    frame = pd.DataFrame({"period_start": pd.to_datetime(["2019-01-07"]), "coverage": [0.5],
                          "actual": [9.0]})
    assert not period_cleaning_checks({"m": {"weekly": frame}})["passed"].all()
    f = prepare_accuracy_frame(raw, evaluation_mode="walk_forward")
    out = record_consistency(f)
    assert set(out) == {"ratio_bands", "by_milkings", "by_weekday"}
    for t in out.values():
        assert not ({"animal", "cow_id", "animal_key"} & set(t.columns))


def test_kalman_follows_fresh_records_and_reverts_to_base_after_long_gaps():
    from components.predictive_farm_intelligence.pfoi.cow_kalman import (
        fit_kalman, kalman_at_origin,
    )
    raw = _dense_raw(start="2019-01-01", end="2019-12-31", cows=6)
    raw.loc[raw["cow_id"] == 1, "litres"] *= 1.3  # cow 1 is persistently high
    f = prepare_accuracy_frame(raw, evaluation_mode="walk_forward")
    base = f.groupby("date")["litres"].transform("median").to_numpy()
    params, table = fit_kalman(f, base, np.ones(len(f), dtype=bool))
    assert len(table) == 125 and 0 < params["phi"] < 1
    mean, sd = kalman_at_origin(f, base, params)
    cow1 = (f["animal"] == 1).to_numpy() & (f["dim"] > 60).to_numpy()
    assert np.median(mean[cow1]) > 0.1  # learned the cow's high level
    # Changing a later yield never changes an earlier forecast (past-only filter).
    changed = f.copy()
    day = pd.Timestamp("2019-06-01")
    changed.loc[changed["date"] == day, "litres"] = 17.0
    mean2, _ = kalman_at_origin(changed, base, params)
    upto = (f["date"] <= day).to_numpy()
    np.testing.assert_allclose(mean[upto], mean2[upto])
    # A forecast far after the last record reverts towards the base curve.
    far = f.copy()
    far["origin_date"] = far["date"] - pd.Timedelta(days=200)
    mean_far, sd_far = kalman_at_origin(far, base, params)
    assert np.abs(mean_far[cow1]).mean() < np.abs(mean[cow1]).mean()
