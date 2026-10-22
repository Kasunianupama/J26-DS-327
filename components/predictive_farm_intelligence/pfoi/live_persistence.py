"""T1 persistence-only live adapter. Pure herd-aggregate computations, no I/O."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest_milk import _target_frame, benchmark_series
from .blend import KEYS, persistence_blend, weights_at

MODEL = "milk_baseline_adaptive_blend"


@dataclass
class LivePersistence:
    weights: dict
    reference: float | None
    reference_week: str | None
    reference_age_days: int | None
    withheld: str | None = None

    def detail(self, grain, horizon):
        candidates = sorted(h for g, h in self.weights if g == grain)
        scored = next((h for h in candidates if h >= horizon), candidates[-1] if candidates else None)
        w, n = self.weights.get((grain, scored), (1., 0))
        p = None if self.reference is None else self.reference * (7 if grain == "weekly" else 1)
        if p is None or grain not in ("daily", "weekly"):
            w = 1.
        return dict(horizon=horizon, scored_horizon=scored, weight=float(w), n_finished=int(n),
                    persistence=p)

    def adjust(self, grain, horizon, value):
        if grain not in ("daily", "weekly"):
            return value
        row = self.detail(grain, horizon)
        return value if row["persistence"] is None else (
            row["weight"] * value + (1 - row["weight"]) * row["persistence"])

    def audit(self):
        return {"enabled": True, "model": MODEL, "partners": ["persistence"],
                "rule": "inverse MAE on matched finished forecasts; minimum 8 pairs",
                "reference_rule": "last complete calendar week with at least 5/7 scoreable days",
                "persistence_week": self.reference_week, "reference_age_days": self.reference_age_days,
                "fallback": self.withheld or ("no_persistence_reference" if self.reference is None else None),
                "horizon_rule": "next longer scored horizon, else longest",
                "interval_rule": "own finished blend errors; unavailable below interval minimum",
                "grains": {g: [self.detail(g, h) for h in range(1, end + 1)]
                           for g, end in (("daily", 14), ("weekly", 13))}}


def attach_live_persistence(run, errors):
    """Attach to an existing adaptive OutputLayer; return errors with blend rows.

    Only this explicit call enables the option. Missing history keeps weight one.
    Reconciled paths are rejected rather than silently bypassing the blend.
    """
    if run.reconciled or run.layer is None:
        raise ValueError("live persistence requires an unreconciled adaptive OutputLayer")
    target = run.hist.target_before(run.origin)
    week = benchmark_series(_target_frame(target), run.origin, "weekly").dropna()
    week = week[np.isfinite(week)]
    ref = float(week.iloc[-1]) if len(week) else None
    withheld = getattr(run, "milk_withheld", None)
    if withheld:
        ref = None
    start = pd.Timestamp(week.index[-1]) if len(week) else None
    weights = {}
    combined = errors
    if errors is not None and len(errors):
        e = errors[(errors["series"] == "herd_milk") & errors.model.isin(
            ["milk_baseline_adaptive", "persistence"])].copy()
        if e.duplicated(KEYS + ["model"]).any():
            raise ValueError("duplicate milk errors: pass one backtest configuration")
        # Reject malformed future-issued history even if its period_end is earlier.
        e = e[pd.to_datetime(e.origin) < pd.Timestamp(run.origin)]
        for grain in ("daily", "weekly"):
            for row in weights_at(e, run.origin, grain).itertuples():
                weights[(grain, row.horizon)] = (row.w, row.n_finished)
        blend = persistence_blend(e)
        combined = pd.concat([errors[errors.model != MODEL], blend], ignore_index=True)
    run.layer.persistence = LivePersistence(
        weights, ref, start.date().isoformat() if start is not None else None,
        (run.origin - start.date()).days - 7 if start is not None else None, withheld)
    # Frozen version identifiers must never identify opt-in output.
    run.version = "pfoi-1.2.0-dev-persistence"
    return combined
