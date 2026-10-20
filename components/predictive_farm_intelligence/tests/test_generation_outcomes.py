"""M8 (docs/pp1_plan.md): separate outcomes by generation, SYNTHETIC data only."""
from datetime import date

import pytest

from components.predictive_farm_intelligence.pfoi.generation_outcomes import (
    generation_outcomes, time_and_coverage, yield_vs_expected,
)

from .synthetic import FakeHerdSource

ASOF = date(2026, 8, 21)


def _all(src=None):
    src = src or FakeHerdSource()
    return generation_outcomes(src.generation_yield(ASOF), src.generation_days(ASOF),
                               src.repro_steps(ASOF), src.generation_alarms(ASOF))


def test_yield_is_compared_within_strata_not_raw():
    y = FakeHerdSource().generation_yield(ASOF)
    t = yield_vs_expected(y).set_index(["period", "generation_group"])["value"]
    # Gen 1 yields 10 % more in every stratum but has more early-lactation days. The
    # standardised ratios put gen 1 above and gen 0 below expectation, close to the true 10 %
    # (indirect standardisation is not exactly the stratum ratio when compositions differ),
    # while the raw means overstate the gap through composition.
    raw = y.groupby("generation_group")[["litres", "cow_days"]].sum()
    raw = raw["litres"] / raw["cow_days"]
    assert raw["1"] / raw["0"] > 1.2
    for period in ("2020-2022", "2023-2026"):
        assert t[(period, "1")] > 1.0 > t[(period, "0")]
        assert abs(t[(period, "1")] / t[(period, "0")] - 1.1) < 0.01


def test_productive_share_and_coverage():
    src = FakeHerdSource()
    t = time_and_coverage(src.generation_days(ASOF), src.generation_yield(ASOF))
    ps = t[t["outcome"] == "productive_share"]
    assert ps["value"].to_numpy() == pytest.approx(0.75)  # heifers (parity 0) left out
    cov = t[t["outcome"] == "yield_record_coverage"]
    assert (cov["value"] > 0).all()


def test_long_table_has_separate_outcomes_and_counts():
    t = _all()
    assert {"yield_vs_expected", "productive_share", "yield_record_coverage",
            "days_to_first_service_median", "days_to_conception_median", "conceived_by_150d",
            "pregnancy_calved_share", "pregnancy_pending_share", "alarm_share", "persistent_alarm_share"} <= set(t["outcome"])
    assert list(t.columns) == ["period", "generation_group", "outcome", "value", "n"]
    assert (t["n"] > 0).all() and "efficiency" not in " ".join(t["outcome"])


def test_command_prints_note_and_writes(monkeypatch, tmp_path, capsys):
    from components.predictive_farm_intelligence.pfoi import cli, data

    monkeypatch.setattr(data.SqlHerdSource, "from_env", classmethod(lambda cls, **kw: FakeHerdSource()))
    assert cli.main(["generation-outcomes", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Not genetic or causal effects" in out
    assert (tmp_path / "generation" / "generation_outcomes.csv").exists()


def test_calved_share_is_over_known_outcomes():
    t = _all()
    c = t[(t["outcome"] == "pregnancy_calved_share")]
    # synthetic: per parity group 50 calved, 5 lost, 5 pending; three parity groups per
    # generation -> 150 / 165, n = 165 pregnancies with a known outcome
    assert c["value"].to_numpy() == pytest.approx(50 / 55)
    assert (c["n"] == 165).all()
