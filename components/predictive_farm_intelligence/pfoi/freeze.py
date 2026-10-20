"""The frozen model (Step 6) and the run-once final test block.

All design choices were made on the development block (origins 2017-01 – 2023-12); see
docs/herd_engine.md and docs/milk_model.md. They are fixed here. The final test block
(origins 2024-01 – 2026-08, targets up to the last data day) is scored once with this
configuration: a marker file records each run, and a second run is refused unless
forced, in which case the marker and the report say so.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import MODEL_VERSION
from .adaptive import AdaptiveConfig
from .config import EngineConfig
from .milk_baseline import MilkConfig

TEST_START = date(2024, 1, 1)
DATA_END = date(2026, 8, 21)  # first day without data (last data day 2026-08-20)
LAST_TEST_ORIGIN = date(2026, 8, 1)

FROZEN_ENGINE = EngineConfig(window_months=12)
FROZEN_MILK = MilkConfig(curve_mode="herd_fitted", pregnancy_factor=True,
                         generation_factor=False, k_mode="anchored")


# Options added after pfoi-1.0.0, with the value that reproduces 1.0.0. They are left out
# of the hash while they keep that value, so the frozen hash (and its run-once markers)
# does not change; any other value changes the hash.
LEGACY_ENGINE_VALUES = {"conception_cut": "origin", "cell_table": "day_cell",
                        "conception_known": "lag", "rate_half_life_months": None}

# pfoi-1.1.0, frozen 2026-10-20 (docs/pfoi_1_1_candidate.md, decision by the user). Chosen on
# the development block (nested CV); its 2024-26 scores are post-hoc, and months published
# after 2026-08-20 are its prospective holdout. pfoi-1.0.0 above keeps its run-once test.
# One engine for herd and milk; the outputs then pass through the correction layer
# (outlook.OutputLayer): herd series bias-corrected, herd milk adaptive per horizon.
V11_VERSION = "pfoi-1.1.0"
V11_FROZEN_ON = date(2026, 10, 20)
V11_ENGINE = EngineConfig(window_months=24, rate_half_life_months=6.0,
                          conception_cut="known", cell_table="day_cell_known",
                          conception_known="recorded", pregnancy_check_lag_days=90)
V11_MILK = FROZEN_MILK
V11_ADAPTIVE = AdaptiveConfig(q30=0.1, tau_days=365.0, z_reset=3.0, pooled=False)
V11_CORRECTED_HERD = ("milking", "n_herd", "calvings", "dry_offs")  # the series selection scored
# Names kept for the commands already run while it was a candidate.
CANDIDATE_VERSION, CANDIDATE_ENGINE, CANDIDATE_MILK = V11_VERSION, V11_ENGINE, V11_MILK

# pfoi-1.1.1 (2026-10-20, decision by the user; docs/pfoi_1_1_1.md): pfoi-1.1.0 unchanged
# (engine, milk model, correction layer, monthly outputs), published for the next 12 months
# at every grain. Days are reconciled top-down ("option b"): each day is the structural day
# times its month's correction factor, so days, weeks and months always add up; weeks are
# sums of those days. Daily and weekly intervals come from the reconciled forecast's own
# errors at monthly forecast dates (path_backtest).
V111_VERSION = "pfoi-1.1.1"
V111_FROZEN_ON = date(2026, 10, 20)
V111_RECONCILIATION = "top_down_monthly"


def v11_config_hash() -> str:
    blob = json.dumps({"engine": asdict(V11_ENGINE), "milk": asdict(V11_MILK),
                       "adaptive": asdict(V11_ADAPTIVE), "corrected_herd": V11_CORRECTED_HERD,
                       "version": V11_VERSION}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def v111_config_hash() -> str:
    blob = json.dumps({"engine": asdict(V11_ENGINE), "milk": asdict(V11_MILK),
                       "adaptive": asdict(V11_ADAPTIVE), "corrected_herd": V11_CORRECTED_HERD,
                       "reconciliation": V111_RECONCILIATION, "version": V111_VERSION},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def config_hash(engine: EngineConfig = FROZEN_ENGINE, milk: MilkConfig = FROZEN_MILK) -> str:
    eng = {k: v for k, v in asdict(engine).items()
           if not (k in LEGACY_ENGINE_VALUES and v == LEGACY_ENGINE_VALUES[k])}
    blob = json.dumps({"engine": eng, "milk": asdict(milk), "version": MODEL_VERSION},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def version_label(engine: EngineConfig, milk: MilkConfig | None = None) -> str:
    """Version written next to every backtest row: the frozen model, the candidate, or
    an unnamed experiment identified by its configuration hash."""
    m_frozen = milk is None or milk == FROZEN_MILK
    if engine == FROZEN_ENGINE and m_frozen:
        return MODEL_VERSION
    if engine == CANDIDATE_ENGINE and (milk is None or milk == CANDIDATE_MILK):
        return CANDIDATE_VERSION
    h = config_hash(engine, milk or FROZEN_MILK)
    return f"experiment-{h}"


def final_test_origins(grain: str, every: int = 1) -> list[date]:
    """Origins of the final test block: months 2024-01 – 2026-08, or Mondays in that range."""
    out = []
    if grain == "monthly":
        d = TEST_START
        while d <= LAST_TEST_ORIGIN:
            out.append(d)
            d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    else:
        d = TEST_START + timedelta(days=(7 - TEST_START.weekday()) % 7)
        while d < DATA_END:
            out.append(d)
            d += timedelta(days=7)
    return out[::every]


class FinalTestAlreadyRun(RuntimeError):
    pass


def final_test_marker(out_dir: Path, name: str) -> Path:
    return Path(out_dir) / "final_test" / f"{name}_{MODEL_VERSION}_{config_hash()}.json"


def guard_final_test(out_dir: Path, name: str, force: bool) -> tuple[Path, bool]:
    """Refuse a second final-test run unless ``force``. Returns (marker path, is_rerun)."""
    marker = final_test_marker(out_dir, name)
    if marker.exists() and not force:
        info = json.loads(marker.read_text())
        raise FinalTestAlreadyRun(
            f"final test '{name}' already run on {info.get('run_at')} for {MODEL_VERSION} "
            f"(config {config_hash()}); use --force only if you must, it will be reported")
    return marker, marker.exists()


def record_final_test(marker: Path, rerun: bool, files: list[str], n_origins: int) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(marker.read_text()) if marker.exists() else None
    marker.write_text(json.dumps({
        "model_version": MODEL_VERSION,
        "config_hash": config_hash(),
        "engine": asdict(FROZEN_ENGINE),
        "milk": asdict(FROZEN_MILK),
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rerun": rerun,
        "previous_run_at": previous.get("run_at") if previous else None,
        "n_origins": n_origins,
        "files": files,
    }, indent=2, default=str))
