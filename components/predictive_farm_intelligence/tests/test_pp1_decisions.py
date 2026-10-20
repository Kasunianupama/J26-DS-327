"""Decision guards and orchestration on fictional aggregate metric tables only."""
from pathlib import Path

import pandas as pd
import pytest

from components.predictive_farm_intelligence.pfoi.break_eval import KEY_ROWS, verdict
from components.predictive_farm_intelligence.pfoi.pp1_decisions import (
    BASE_TAG, HORIZONS, evaluation_commands, exit_safeguards, main,
)


def summaries():
    rows = [dict(grain=g, series=s, horizon=h, model="herd_engine", mae=10., n=40)
            for g, hs in HORIZONS.items() for h in hs
            for s in ("calvings", "milking", "n_herd")]
    base = pd.DataFrame(rows)
    new = base.copy()
    new.loc[new.series != "calvings", "mae"] = 9.
    return base, new


def reset_table():
    return pd.DataFrame([dict(series=s, grain=g, horizon=h, model="candidate" + suffix,
                              n=30, n_after=8, accuracy=.91, after_break=after)
                         for s, g, h in KEY_ROWS for suffix, after in (("", .85), ("_br", .88))])


def test_exit_rule_checks_long_and_weekly_calving_safeguards():
    base, new = summaries()
    keep, table = exit_safeguards(base, new)
    assert keep and len(table) == 12
    new.loc[(new.grain == "weekly") & (new.series == "calvings") & (new.horizon == 13), "mae"] = 10.21
    assert not exit_safeguards(base, new)[0]
    new.loc[new.series == "calvings", "mae"] = 10.
    new.loc[(new.grain == "monthly") & (new.series == "n_herd") & (new.horizon == 6), "mae"] = 10.
    assert not exit_safeguards(base, new)[0]  # unchanged is not improvement


@pytest.mark.parametrize("issue", ["missing", "duplicate", "n", "nan"])
def test_exit_audit_stops_on_incomplete_evidence(issue):
    base, new = summaries()
    if issue == "missing":
        new = new.iloc[1:]
    elif issue == "duplicate":
        new = pd.concat([new, new.iloc[:1]])
    elif issue == "n":
        new.loc[0, "n"] = 39
    else:
        new.loc[0, "mae"] = float("nan")
    with pytest.raises(ValueError):
        exit_safeguards(base, new)


def test_reset_requires_every_pair_and_same_sample_but_preserves_small_n_rule():
    t = reset_table()
    assert verdict(t)[0]  # n_after < 12 is qualified, not a changed keep threshold
    assert not verdict(t.iloc[2:])[0]
    assert not verdict(pd.concat([t, t.iloc[:1]]))[0]
    t.loc[1, "n_after"] = 7
    assert not verdict(t)[0]


def test_evaluation_sequence_uses_selected_tags_and_development_before_posthoc():
    for keep in (True, False):
        commands = evaluation_commands(keep, Path("fictional-output"), 2)
        milk_runs = [c for c in commands if c[3] == "backtest-milk"]
        assert "--block" not in milk_runs[0] and milk_runs[1][-1] == "2"
        assert milk_runs[1][milk_runs[1].index("--block") + 1] == "posthoc"
        assert all(("--exit-model" in c) == keep for c in commands if c[3] != "break-reset")
        assert all(not ({"--write", "--force", "--fast-half-life", "test"} & set(c)) for c in commands)
        for c in commands:
            if c[3] == "break-reset":
                assert c[c.index("--herd-tag") + 1] == BASE_TAG + ("_xl" if keep else "")


def test_preflight_missing_summaries_runs_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("must not run"))
    assert main(["--out", str(tmp_path), "--run"]) == 2


def test_runner_executes_only_mocked_commands_and_reads_selected_reset(monkeypatch, tmp_path, capsys):
    base, new = summaries()
    for tag, f in ((BASE_TAG, base), (BASE_TAG + "_xl", new)):
        for grain, part in f.groupby("grain"):
            part.to_csv(tmp_path / f"herd_backtest_summary_{grain}_{tag}.csv", index=False)
    calls = []
    def run(cmd, check):
        assert check
        calls.append(cmd)
        if cmd[3] == "backtest-milk" and "--block" not in cmd:
            for grain in HORIZONS:
                tag = "herd_fitted_p1_g0_kf_" + BASE_TAG + "_xl"
                pd.DataFrame({"model": ["milk_baseline"]}).to_csv(
                    tmp_path / f"milk_backtest_errors_{grain}_{tag}.csv", index=False)
        if cmd[3] == "break-reset" and "--block" not in cmd:
            tag = cmd[cmd.index("--milk-tag") + 1]
            reset_table().to_csv(tmp_path / f"break_reset_comparison_{tag}.csv", index=False)
    monkeypatch.setattr("subprocess.run", run)
    assert main(["--out", str(tmp_path), "--run"]) == 0
    assert len(calls) == 10
    assert "SELECTED-CONFIG RESET: KEEP" in capsys.readouterr().out


def test_runner_stops_if_development_did_not_produce_milk_errors(monkeypatch, tmp_path):
    base, new = summaries()
    for tag, f in ((BASE_TAG, base), (BASE_TAG + "_xl", new)):
        for grain, part in f.groupby("grain"):
            part.to_csv(tmp_path / f"herd_backtest_summary_{grain}_{tag}.csv", index=False)
    calls = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: calls.append(cmd))
    with pytest.raises(RuntimeError, match="posthoc stopped"):
        main(["--out", str(tmp_path), "--run"])
    assert len(calls) == 1 and "--block" not in calls[0]


def test_quality_off_audit_preserves_quality_on_output(monkeypatch, tmp_path):
    from components.predictive_farm_intelligence.pfoi import cli, data
    from .test_scorecard import _rows

    monkeypatch.setattr(data.SqlHerdSource, "from_env", lambda **kw: pytest.fail("no database"))
    actual = [100.] * 30
    errors = pd.concat([_rows("milking", "herd_engine", actual, [105.] * 30),
                        _rows("milking", "persistence", actual, [110.] * 30)])
    errors.to_csv(tmp_path / f"herd_backtest_errors_monthly_{BASE_TAG}.csv", index=False)
    name = f"scorecard_development_herd_fitted_p1_g0_kf_{BASE_TAG}_aci"
    prior = tmp_path / f"{name}.csv"
    prior.write_text("fictional prior quality-on result")
    assert cli.main(["scorecard", "--out", str(tmp_path), "--block", "development",
                     "--preset", "pfoi-1.1", "--k", "anchor_first", "--intervals", "aci",
                     "--quality", "off"]) == 0
    assert prior.read_text() == "fictional prior quality-on result"
    assert len(pd.read_csv(tmp_path / f"{name}_quality_off.csv")) > 0


def test_interval_quality_control_keeps_the_same_scored_periods(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from components.predictive_farm_intelligence.pfoi import cli, data
    from .test_scorecard import _rows

    actual = [100.] * 30
    errors = pd.concat([_rows("milking", "herd_engine", actual, [105.] * 30),
                        _rows("milking", "persistence", actual, [110.] * 30)])
    errors.to_csv(tmp_path / f"herd_backtest_errors_monthly_{BASE_TAG}.csv", index=False)
    dates = pd.date_range("2016-01-01", "2019-07-01").date
    target = pd.DataFrame(dict(date=dates, target_source="delpro", target_litres=100.,
                               identified_share=.8, data_gap=False))
    # Fictional milk recording gap removes the same forecast periods from both audits.
    target.loc[pd.to_datetime(target.date).dt.year == 2018, "data_gap"] = True
    panel = pd.DataFrame(dict(date=dates, milking=10.))
    fake = SimpleNamespace(target_daily=lambda *a: target, panel_daily=lambda *a: panel)
    monkeypatch.setattr(data.SqlHerdSource, "from_env", lambda **kw: fake)
    args = ["scorecard", "--out", str(tmp_path), "--block", "development", "--preset", "pfoi-1.1",
            "--k", "anchor_first", "--intervals", "aci"]
    assert cli.main(args) == 0
    assert cli.main([*args, "--interval-quality", "off"]) == 0
    name = f"scorecard_development_herd_fitted_p1_g0_kf_{BASE_TAG}_aci"
    a = pd.read_csv(tmp_path / f"{name}.csv")
    b = pd.read_csv(tmp_path / f"{name}_interval_quality_off.csv")
    cols = ["block", "grain", "series", "horizon", "model", "n", "accuracy", "bias_pct", "skill"]
    pd.testing.assert_frame_equal(a[cols], b[cols])
    assert (a.n < 30).all() and (a.n >= 12).all()
    assert "n_coverage" in b
