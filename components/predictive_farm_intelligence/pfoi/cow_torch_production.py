"""Origin-safe producer for the aggregate cow-model correction artifact.

The herd engine remains responsible for future cow counts and lactation structure.
Notebook 6 is fitted strictly before the forecast origin and supplies one recent,
out-of-sample relative yield-level estimate.  That aggregate factor is applied to the
structural daily milk path and later tapered by :mod:`cow_torch_outlook`.

No per-cow prediction is returned or persisted by this module.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from .cow_accuracy import AccuracyModels
from .cow_torch_outlook import (
    CalibrationCell,
    build_correction_artifact,
)


def structural_daily_from_document(document: dict, origin: date) -> pd.DataFrame:
    """Extract the reconciled daily milk path from a built structural page document."""
    document_origin = date.fromisoformat(str(document.get("origin_date", ""))[:10])
    if document_origin != origin:
        raise ValueError(f"structural document origin {document_origin} does not match {origin}")
    rows = [
        r for r in document.get("outlook", [])
        if r.get("grain") == "day" and r.get("series") == "milk_litres"
    ]
    if not rows:
        raise ValueError("structural document has no daily milk forecast")
    path = pd.DataFrame({
        "date": pd.to_datetime([r["target_period"] for r in rows]).date,
        "structural_litres": pd.to_numeric([r["forecast"] for r in rows], errors="coerce"),
    }).sort_values("date").reset_index(drop=True)
    if path["date"].duplicated().any() or path["date"].iloc[0] != origin:
        raise ValueError("structural daily milk path must be unique and start at the origin")
    expected = [origin + timedelta(days=i) for i in range(len(path))]
    if path["date"].tolist() != expected:
        raise ValueError("structural daily milk path must be continuous")
    values = path["structural_litres"].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("structural daily milk forecasts must be finite and positive")
    return path


def structural_daily_from_outlook(outlook: pd.DataFrame, origin: date) -> pd.DataFrame:
    """Extract the complete daily milk path from build-outlook's aggregate CSV.

    The frontend page document intentionally keeps only selected day horizons (1, 7,
    and 14).  The sibling aggregate outlook table retains every reconciled forecast day
    and is therefore the authoritative input for the correction artifact.
    """
    required = {"target_period", "grain", "series", "forecast"}
    missing = required - set(outlook.columns)
    if missing:
        raise ValueError(f"structural outlook table is missing {sorted(missing)}")
    grain = outlook["grain"].astype(str).str.strip().str.lower()
    series = outlook["series"].astype(str).str.strip().str.lower()
    daily = grain.isin(["day", "daily"]) | grain.str.startswith("day_") | grain.str.startswith("daily_")
    rows = outlook[daily & series.str.contains("milk", regex=False)]
    if rows.empty:
        counts = (outlook.assign(_grain=grain, _series=series)
                  .groupby(["_grain", "_series"]).size().sort_values(ascending=False))
        summary = ", ".join(f"{g}/{s}={int(n)}" for (g, s), n in counts.head(12).items())
        raise ValueError("structural outlook table has no daily milk forecast; aggregate "
                         f"grain/series counts: {summary or 'none'}")
    path = pd.DataFrame({
        "date": pd.to_datetime(rows["target_period"]).dt.date,
        "structural_litres": pd.to_numeric(rows["forecast"], errors="coerce"),
    }).sort_values("date").reset_index(drop=True)
    if path["date"].duplicated().any() or path["date"].iloc[0] != origin:
        raise ValueError("structural daily milk path must be unique and start at the origin")
    expected = [origin + timedelta(days=i) for i in range(len(path))]
    if path["date"].tolist() != expected:
        raise ValueError("structural daily milk path must be continuous")
    values = path["structural_litres"].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("structural daily milk forecasts must be finite and positive")
    return path


def reference_model(selected_model: str) -> str:
    """The like-for-like Wood reference for a neural candidate."""
    if selected_model.endswith("_grp"):
        return "wood_mixed_grp"
    if selected_model.endswith("_recal"):
        return "wood_mixed_recal"
    return "wood_mixed"


def estimate_origin_factor(
    models: AccuracyModels,
    origin: date,
    selected_model: str,
    *,
    recent_days: int = 28,
    min_cows: int = 20,
) -> dict:
    """Estimate one aggregate neural/Wood ratio from recent pre-origin forecasts.

    Only each cow's latest eligible validation prediction is used, preventing cows with
    more frequent recordings from dominating the origin estimate.  The returned audit
    contains aggregates only.
    """
    frame, predictions = models.for_grain("daily")
    reference = reference_model(selected_model)
    missing = {selected_model, reference} - set(predictions)
    if missing:
        raise ValueError(f"cow model predictions are missing {sorted(missing)}")
    id_column = "animal" if "animal" in frame.columns else "cow_id"
    required = {"date", id_column, "period", "score_eligible"}
    if required - set(frame.columns):
        raise ValueError(f"cow model frame is missing {sorted(required - set(frame.columns))}")
    dates = pd.to_datetime(frame["date"])
    start = pd.Timestamp(origin - timedelta(days=recent_days))
    eligible = (
        (frame["period"] == "validation")
        & frame["score_eligible"].astype(bool)
        & (dates >= start)
        & (dates < pd.Timestamp(origin))
    )
    idx = frame.index[eligible]
    if len(idx) == 0:
        raise ValueError("no eligible pre-origin validation predictions for the cow correction")
    recent = frame.loc[idx, [id_column, "date"]].copy()
    recent["_position"] = np.flatnonzero(eligible.to_numpy())
    latest = recent.sort_values("date").groupby(id_column, sort=False).tail(1)
    positions = latest["_position"].to_numpy(dtype=int)
    neural = np.asarray(predictions[selected_model], dtype=float)[positions]
    baseline = np.asarray(predictions[reference], dtype=float)[positions]
    valid = np.isfinite(neural) & np.isfinite(baseline) & (neural >= 0) & (baseline > 0)
    neural, baseline = neural[valid], baseline[valid]
    n_cows = int(valid.sum())
    if n_cows < min_cows:
        raise ValueError(f"cow correction has only {n_cows} eligible cows; minimum is {min_cows}")
    factor = float(neural.sum() / baseline.sum())
    if not np.isfinite(factor) or factor <= 0:
        raise ValueError("cow correction factor is not finite and positive")
    return {
        "factor": factor,
        "n_cows": n_cows,
        "selected_model": selected_model,
        "reference_model": reference,
        "recent_days": int(recent_days),
        "estimate_start": (origin - timedelta(days=recent_days)).isoformat(),
        "estimate_end": (origin - timedelta(days=1)).isoformat(),
    }


def produce_correction_artifact(
    document: dict,
    raw: pd.DataFrame,
    events: dict | None,
    origin: date,
    calibration: list[CalibrationCell] | None = None,
    *,
    selected_model: str = "torch_mlp_small_grp",
    calibration_days: int = 84,
    recent_days: int = 28,
    min_cows: int = 20,
    taper_days: float = 120.0,
    device: str = "auto",
    params: dict | None = None,
    options: dict | None = None,
    verbose: bool = False,
    fit_fn: Callable = None,
    structural_daily: pd.DataFrame | None = None,
) -> dict:
    """Fit the pre-origin neural correction and return one aggregate artifact."""
    if calibration_days <= recent_days or recent_days <= 0:
        raise ValueError("calibration_days must be greater than recent_days, both positive")
    history = raw.loc[pd.to_datetime(raw["date"]).dt.date < origin].copy()
    if history.empty:
        raise ValueError("no cow history exists before the forecast origin")
    train_end = origin - timedelta(days=calibration_days + 1)
    validation_end = origin - timedelta(days=1)
    if fit_fn is None:
        from .cow_torch import fit_torch_models
        fit_fn = fit_torch_models
    base_model = selected_model.removesuffix("_grp").removesuffix("_recal")
    if base_model not in {"torch_mlp_small", "torch_mlp_large"}:
        raise ValueError("production correction currently supports torch_mlp_small/large variants")
    fit_options = {
        "ensemble": 1,
        "use_gru": False,
        "use_quantile": False,
        **(options or {}),
    }
    models = fit_fn(
        history,
        train_end=train_end,
        validation_end=validation_end,
        events=events,
        device=device,
        params=params,
        options=fit_options,
        grains=("daily",),
        model_names=(base_model,),
        verbose=verbose,
    )
    estimate = estimate_origin_factor(
        models, origin, selected_model, recent_days=recent_days, min_cows=min_cows,
    )
    structural = (structural_daily_from_document(document, origin)
                  if structural_daily is None else structural_daily.copy())
    aggregate = structural.assign(
        cow_reference_litres=structural["structural_litres"],
        cow_model_litres=structural["structural_litres"] * estimate["factor"],
        n_cows=estimate["n_cows"],
    )
    artifact = build_correction_artifact(
        origin,
        aggregate,
        calibration or [],
        selected_model=selected_model,
        trained_through=validation_end,
        taper_days=taper_days,
    )
    artifact["origin_estimate"] = {
        **estimate,
        "weights_trained_through": train_end.isoformat(),
        "outcomes_used_through": validation_end.isoformat(),
        "role": "relative yield-level correction; herd engine owns future cow structure",
    }
    return artifact
