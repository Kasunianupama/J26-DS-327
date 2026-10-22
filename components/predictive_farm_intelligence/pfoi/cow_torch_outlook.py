"""Aggregate cow-model correction joined to a built herd-engine page document.

The cow model never replaces the herd engine.  It estimates a relative yield level for
the cows known at the forecast origin; that ratio corrects the structural herd path::

    final milk = structural herd milk * cow-model / cow structural reference

Only the resulting herd-day aggregates are persisted.  No animal key or per-animal
prediction is part of this artifact or page document.
"""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .outlook import period_starts
from .periods import period_bounds

ARTIFACT_SCHEMA = "pfoi.cow-correction.v1"
COW_MODEL_VERSION = "pfoi-cow-torch-1.6.0"
HYBRID_VERSION = "pfoi-1.7.0-dev"
METHOD = "structural_plus_cow_torch_v1"
SERIES = "milk_litres"
GRAIN_MODEL = {"day": "daily", "week": "weekly", "month": "monthly"}
ALLOWED_DAILY_KEYS = {
    "date", "structural_litres", "cow_factor", "correction_litres", "forecast_litres",
    "n_cows", "taper_weight",
}


@dataclass(frozen=True)
class CalibrationCell:
    grain: str
    horizon: int
    q_lo: float
    q_hi: float
    n: int


def build_correction_artifact(
    origin: date,
    aggregate_path: pd.DataFrame,
    calibration: Iterable[CalibrationCell] = (),
    *,
    selected_model: str = "torch_mlp_small_grp",
    trained_through: date | None = None,
    taper_days: float = 120.0,
    factor_bounds: tuple[float, float] = (0.75, 1.25),
    anchor_correction_litres_per_day: float = 0.0,
) -> dict:
    """Create a privacy-safe artifact from an already aggregated cow forecast path.

    ``aggregate_path`` has one row per future day with ``structural_litres`` from the
    herd engine and the cow model/reference totals over the same known-cow cohort.  It
    must not contain animal identifiers.  The correction is tapered with forecast lead
    because the origin cohort represents progressively less of the future herd.
    """
    required = {"date", "structural_litres", "cow_model_litres", "cow_reference_litres"}
    missing = required - set(aggregate_path.columns)
    if missing:
        raise ValueError(f"aggregate cow path is missing {sorted(missing)}")
    forbidden = [c for c in aggregate_path.columns if "animal" in c.lower() or c.lower() in {"cow_id", "key"}]
    if forbidden:
        raise ValueError(f"aggregate artifact cannot contain animal-level columns: {forbidden}")
    p = aggregate_path.copy()
    p["date"] = pd.to_datetime(p["date"]).dt.date
    p = p.sort_values("date")
    if p["date"].duplicated().any() or len(p) == 0:
        raise ValueError("aggregate cow path must contain one row per future date")
    if p["date"].iloc[0] != origin:
        raise ValueError("aggregate cow path must start on the forecast origin")
    expected = [origin + timedelta(days=i) for i in range(len(p))]
    if p["date"].tolist() != expected:
        raise ValueError("aggregate cow path dates must be continuous")
    numeric = p[["structural_litres", "cow_model_litres", "cow_reference_litres"]].to_numpy(float)
    if not np.isfinite(numeric).all() or (numeric < 0).any() or (p["cow_reference_litres"] <= 0).any():
        raise ValueError("aggregate cow path values must be finite and non-negative; references must be positive")

    raw_factor = p["cow_model_litres"].to_numpy(float) / p["cow_reference_litres"].to_numpy(float)
    raw_factor = np.clip(raw_factor, factor_bounds[0], factor_bounds[1])
    lead = np.arange(len(p), dtype=float)
    weight = np.exp(-lead / taper_days) if taper_days > 0 else np.ones(len(p))
    factor = 1.0 + weight * (raw_factor - 1.0)
    structural = p["structural_litres"].to_numpy(float)
    forecast = structural * factor
    daily = []
    for i, d in enumerate(p["date"]):
        row = {
            "date": d.isoformat(),
            "structural_litres": round(float(structural[i]), 6),
            "cow_factor": round(float(factor[i]), 8),
            "correction_litres": round(float(forecast[i] - structural[i]), 6),
            "forecast_litres": round(float(forecast[i]), 6),
            "taper_weight": round(float(weight[i]), 8),
        }
        if "n_cows" in p and pd.notna(p["n_cows"].iloc[i]):
            row["n_cows"] = int(p["n_cows"].iloc[i])
        daily.append(row)
    cells = [c.__dict__ for c in calibration]
    return {
        "schema": ARTIFACT_SCHEMA,
        "origin_date": origin.isoformat(),
        "trained_through": (trained_through or origin - timedelta(days=1)).isoformat(),
        "cow_model_version": COW_MODEL_VERSION,
        "hybrid_model_version": HYBRID_VERSION,
        "selected_model": selected_model,
        "method": METHOD,
        "formula": "final_neural_forecast = structural_forecast + cow_model_correction",
        "correction_formula": "cow_model_correction = structural_forecast * (cow_factor - 1)",
        "cohort_ratio_formula": "cow_factor = cow_model_known_cohort / structural_known_cohort",
        "taper_days": taper_days,
        "factor_bounds": list(factor_bounds),
        "anchor_correction_litres_per_day": float(anchor_correction_litres_per_day),
        "daily": daily,
        "calibration": cells,
    }


def calibration_from_errors(errors: pd.DataFrame, origin: date, level: float = 0.90,
                            min_samples: int = 8) -> list[CalibrationCell]:
    """Past-only conformal log-error cells for the hybrid forecast.

    The input is period-level aggregate backtest output.  A row is eligible only when
    its outcome period ended on or before this forecast origin.
    """
    required = {"grain", "horizon", "forecast", "actual", "period_end"}
    missing = required - set(errors.columns)
    if missing:
        raise ValueError(f"calibration errors are missing {sorted(missing)}")
    e = errors.copy()
    e["period_end"] = pd.to_datetime(e["period_end"]).dt.date
    e = e[(e["period_end"] <= origin) & (e["forecast"] > 0) & (e["actual"] > 0)]
    e["log_error"] = np.log(e["actual"].astype(float) / e["forecast"].astype(float))
    names = {"daily": "day", "weekly": "week", "monthly": "month"}
    cells = []
    for (grain, horizon), group in e.groupby(["grain", "horizon"]):
        values = group["log_error"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy(float)
        if len(values) < min_samples:
            continue
        finite_level = min(1.0, level * (len(values) + 1) / len(values))
        tail = (1.0 - finite_level) / 2.0
        cells.append(CalibrationCell(names.get(str(grain), str(grain)), int(horizon),
                                     float(np.quantile(values, tail)),
                                     float(np.quantile(values, 1.0 - tail)), len(values)))
    return cells


def write_correction_artifact(path, artifact: dict) -> Path:
    """Validate and persist one aggregate artifact as JSON."""
    validate_artifact(artifact)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=1))
    return target


def validate_artifact(artifact: dict, origin: date | None = None) -> None:
    if artifact.get("schema") != ARTIFACT_SCHEMA or artifact.get("method") != METHOD:
        raise ValueError("unsupported cow correction artifact")
    actual_origin = date.fromisoformat(str(artifact["origin_date"])[:10])
    if origin is not None and actual_origin != origin:
        raise ValueError(f"artifact origin {actual_origin} does not match document origin {origin}")
    trained = date.fromisoformat(str(artifact["trained_through"])[:10])
    if trained >= actual_origin:
        raise ValueError("cow artifact leaks the forecast period: trained_through must precede origin")
    rows = artifact.get("daily") or []
    if not rows:
        raise ValueError("cow artifact has no daily forecast path")
    for row in rows:
        unknown = set(row) - ALLOWED_DAILY_KEYS
        if unknown:
            raise ValueError(f"cow artifact daily row has unsupported keys: {sorted(unknown)}")
        vals = [row.get(k) for k in ("structural_litres", "cow_factor", "correction_litres", "forecast_litres")]
        if not all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in vals):
            raise ValueError("cow artifact daily values must be finite numbers")


def _calibration(artifact: dict, grain: str, horizon: int) -> dict | None:
    rows = [r for r in artifact.get("calibration", []) if r.get("grain") == grain]
    if not rows:
        return None
    exact = [r for r in rows if int(r["horizon"]) == horizon]
    if exact:
        return exact[0]
    above = sorted((r for r in rows if int(r["horizon"]) >= horizon), key=lambda r: int(r["horizon"]))
    return above[0] if above else max(rows, key=lambda r: int(r["horizon"]))


def _daily_frame(artifact: dict) -> pd.DataFrame:
    p = pd.DataFrame(artifact["daily"])
    p["date"] = pd.to_datetime(p["date"]).dt.date
    return p.set_index("date").sort_index()


def _period(path: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    p = path.loc[(path.index >= start) & (path.index < end)]
    if len(p) != (end - start).days:
        raise ValueError(f"cow artifact does not completely cover {start} to {end}")
    return p


def hybrid_document(document: dict, artifact: dict) -> dict:
    """Return a page document whose milk path is structural + cow-model correction."""
    origin = date.fromisoformat(str(document["origin_date"])[:10])
    validate_artifact(artifact, origin)
    out = copy.deepcopy(document)
    path = _daily_frame(artifact)
    starts = period_starts(origin)
    correction_rows = []
    month_level = {}
    month_cursor = origin.replace(day=1)
    last_day = max(path.index)
    while month_cursor <= last_day:
        next_month = (month_cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        days = _period(path, month_cursor, min(next_month, last_day + timedelta(days=1)))
        if len(days) == (next_month - month_cursor).days:
            month_level[month_cursor] = float(days["correction_litres"].sum()) / len(days)
        month_cursor = next_month
    for row in out.get("outlook", []):
        row["model_version"] = HYBRID_VERSION
        if row.get("series") != SERIES:
            continue
        gm = GRAIN_MODEL[row["grain"]]
        start, end = period_bounds(starts[gm], gm, int(row["horizon"]))
        part = _period(path, start, end)
        structural = float(part["structural_litres"].sum())
        correction = float(part["correction_litres"].sum())
        forecast = float(part["forecast_litres"].sum())
        if not np.isclose(structural + correction, forecast, atol=0.02):
            raise ValueError("cow artifact does not reconcile structural + correction to forecast")
        row["forecast"] = round(forecast, 3)
        cell = _calibration(artifact, row["grain"], int(row["horizon"]))
        if cell is not None and int(cell.get("n", 0)) > 0:
            lo = forecast * math.exp(float(cell["q_lo"]))
            hi = forecast * math.exp(float(cell["q_hi"]))
            row["lower"], row["upper"] = round(max(0.0, lo), 3), round(max(forecast, hi), 3)
        else:
            old = float(row["forecast"]) - correction
            ratio = forecast / old if old > 0 else 1.0
            row["lower"] = round(max(0.0, float(row.get("lower", old)) * ratio), 3)
            row["upper"] = round(max(forecast, float(row.get("upper", old)) * ratio), 3)
        correction_rows.append({
            "target_period": start.isoformat(), "grain": row["grain"], "horizon": int(row["horizon"]),
            "series": SERIES, "structural": round(structural, 3), "correction": round(correction, 3),
            "forecast": round(forecast, 3), "factor": round(forecast / structural, 6) if structural else 1.0,
            "method": METHOD,
        })
    # Replace any earlier milk correction audit rows; all non-milk audit rows are retained.
    out["corrections"] = [r for r in out.get("corrections", []) if r.get("series") != SERIES] + correction_rows
    for row in out.get("attribution", []):
        row["model_version"] = HYBRID_VERSION
    # Exact extra term: change in the cow correction's L/day level from the prior month.
    attr = out.setdefault("attribution", [])
    existing = {(r.get("target_period"), r.get("factor")) for r in attr if r.get("series") == SERIES}
    anchor = float(artifact.get("anchor_correction_litres_per_day", 0.0))
    forecast_months = {
        date.fromisoformat(str(r["target_period"])[:10])
        for r in out.get("outlook", []) if r.get("series") == SERIES and r.get("grain") == "month"
    }
    for target in sorted(forecast_months):
        previous_month = (target.replace(day=1) - timedelta(days=1)).replace(day=1)
        previous = month_level.get(previous_month, anchor)
        key = (target.isoformat(), "cow_model_correction")
        if key not in existing:
            attr.append({
                "origin_date": origin.isoformat(), "target_period": target.isoformat(), "grain": "month",
                "series": SERIES, "factor": "cow_model_correction",
                "contribution": round(month_level[target] - previous, 3),
                "model_version": HYBRID_VERSION, "core_version": out.get("core_version", "unknown"),
            })
    out["model_version"] = HYBRID_VERSION
    out["cow_model"] = {
        "model_version": artifact["cow_model_version"], "selected_model": artifact["selected_model"],
        "method": METHOD, "trained_through": artifact["trained_through"],
        "formula": artifact["formula"],
        "explanation": "The herd engine sets cow numbers and lactation structure. The cow model adjusts only the yield level; the displayed correction is the exact difference in litres.",
        "intervals": "Forward calibration from this hybrid model's past errors; no future outcome is used.",
    }
    method = dict(out.get("interval_method") or {})
    method["cow_model"] = "5-95% forward conformal log-error quantiles by grain and horizon"
    out["interval_method"] = method
    return out


def run(out_dir, source_version: str, artifact_dir, origins: list[str] | None = None) -> list[Path]:
    """Build hybrid documents for all matching origins (files only)."""
    root = Path(out_dir)
    files = sorted((root / "outlook" / source_version).glob("run_*.json"))
    if origins:
        wanted = {date.fromisoformat(o).strftime("%Y%m") for o in origins}
        files = [p for p in files if p.stem.split("_")[1] in wanted]
    if not files:
        raise FileNotFoundError(f"no source documents for {source_version}")
    artifacts = Path(artifact_dir)
    dest = root / "outlook" / HYBRID_VERSION
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for source in files:
        stamp = source.stem.split("_")[1]
        artifact_path = artifacts / f"cow_correction_{stamp}.json"
        if not artifact_path.exists():
            raise FileNotFoundError(f"missing aggregate cow artifact {artifact_path}")
        doc = hybrid_document(json.loads(source.read_text()), json.loads(artifact_path.read_text()))
        target = dest / source.name
        target.write_text(json.dumps(doc, indent=1))
        written.append(target)
    return written
