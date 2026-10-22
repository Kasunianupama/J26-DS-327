"""Layer 2 loader and CLI on SYNTHETIC cows with a fake source (no database)."""
import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi import cli
from components.predictive_farm_intelligence.pfoi.cow_data import (
    COWDAY_COLUMNS, cowday_sql, load_cowdays, tidy_cowdays,
)

from .synthetic_cows import synthetic_cowdays


def _raw(n_cows=60):
    f = synthetic_cowdays(n_cows=n_cows)
    ids = {a: i + 1 for i, a in enumerate(sorted(f["animal"].unique()))}
    raw = f.assign(cow_id=f["animal"].map(ids), after_dry_off=False).drop(columns=["animal", "true_litres"])
    return raw[["cow_id", "date", "parity_group", "dim", "days_pregnant", "litres", "after_dry_off"]]


class FakeSource:
    core = "core"

    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def _q(self, sql, **params):
        self.calls.append((sql, params))
        return self.raw.copy()


def test_sql_keeps_animal_keys_in_the_database():
    sql = cowday_sql("core")
    final = sql[sql.rindex("SELECT DENSE_RANK"):]
    assert "DENSE_RANK() OVER (ORDER BY animal_key) AS cow_id" in final
    selected = final[:final.index("FROM rows_")].replace("ORDER BY animal_key", "")
    assert "animal_key" not in selected
    assert "is_placeholder" in sql and "is_yield_valid" in sql
    with pytest.raises(ValueError):
        cowday_sql("core; drop table x")


def test_tidy_refuses_animal_keys_and_types_columns():
    raw = _raw(10)
    with pytest.raises(ValueError):
        tidy_cowdays(raw.assign(animal_key="A1"))
    f = tidy_cowdays(raw.assign(after_dry_off=None))
    assert tuple(f.columns) == COWDAY_COLUMNS
    assert f["animal"].dtype == "int64" and f["after_dry_off"].dtype == bool
    assert f["dim"].dtype == "float64"


def test_load_cowdays_passes_dates():
    src = FakeSource(_raw(10))
    f = load_cowdays(src, pd.Timestamp("2016-01-01").date(), pd.Timestamp("2026-08-20").date())
    assert len(src.calls) == 1 and set(src.calls[0][1]) == {"start", "end"}
    assert len(f) == len(src.raw)


def test_cli_writes_aggregate_files_only(tmp_path, monkeypatch):
    pytest.importorskip("interpret")
    src = FakeSource(_raw())
    monkeypatch.setattr(cli.SqlHerdSource, "from_env", classmethod(lambda cls, **kw: src))
    rc = cli.main(["layer2-cow", "--out", str(tmp_path), "--ebm-bags", "2", "--ebm-interactions", "0"])
    assert rc == 0
    out = tmp_path / "layer2"
    names = {p.name for p in out.iterdir()}
    for need in ("input_summary.csv", "cow_scores.csv", "herd_scores.csv", "wood_parameters.csv",
                 "ebm_importances.csv", "ebm_shape_dim.csv", "herd_daily_wood.csv"):
        assert need in names
    for p in out.iterdir():
        cols = set(pd.read_csv(p, nrows=1).columns)
        assert not cols & {"animal", "cow_id", "animal_key"}, p.name
    daily = pd.read_csv(out / "herd_daily_wood.csv")
    assert not daily["period"].isin(["recalibrate", "test"]).any()  # test truth stays hidden
    scores = pd.read_csv(out / "cow_scores.csv")
    assert set(scores["period"]) == {"train", "validate"}
