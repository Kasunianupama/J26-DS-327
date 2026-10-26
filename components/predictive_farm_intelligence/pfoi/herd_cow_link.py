"""Notebook 06 per-cow yield predictions as an input to the herd milk model (notebook 08).

Herd milk = milking cows x litres per cow. Notebook 07 estimates litres per cow from the
herd's own recent average; notebook 06 predicts every recorded cow's yield from her own
lactation stage, parity, history and health. This module turns notebook 06's models into
a herd-level input without leaking:

* the cow models are refitted **walk-forward** at each cut (``fit_torch_models``,
  ``train_end = validation_end = cut``), and each fit predicts only the next block
  ``(cut_k, cut_k+1]``. Every prediction therefore comes from a model that never saw
  that period; the first block has none;
* the per-cow predictions are aggregated by notebook 06's own scorer to one value per
  day / Monday week / month: mean predicted litres per recorded cow-day. Daily values
  use records up to the day before; weekly and monthly values are frozen at the start
  of the week / month (notebook 06's walk-forward rule), so each is known at the herd
  model's origin for that grain;
* only these herd-level aggregates leave this module (no cow key).

Caveat: the mean is over the cows that were recorded in the period, the same cohort as
the clean herd target (``milk_per_recorded_cow``); which cows get recorded is only known
afterwards, so a live forecast would have to assume the recent cohort.
"""
from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd

HERD_COW_MODEL_NAME = "pfoi-herd-milk-cow06-1.10.0-dev"
# Notebook 06 winners on Farm X (docs/neural_milk_1_8.md, user-supplied aggregates 2026-10-22).
NB06_FARM_X_WINNERS = {"daily": "kalman_state_grp", "weekly": "kalman_state_grp",
                       "monthly": "kalman_state"}
# Light refits: the Kalman winners need no network; one small MLP keeps fit_torch_models'
# usual path. Pass the notebook 06 settings instead for its full comparison.
LIGHT_COW_FIT = {"options": {"ensemble": 1, "use_gru": False, "use_quantile": False},
                 "model_names": ("torch_mlp_small",)}


def prediction_blocks(cuts: list, end) -> list[tuple[date, date]]:
    """(train_end, block_end) pairs: fit at each cut, predict up to the next one."""
    points = sorted({pd.Timestamp(c).normalize() for c in cuts} | {pd.Timestamp(end)})
    return [(a.date(), b.date()) for a, b in zip(points[:-1], points[1:])]


def cow_herd_predictions(raw: pd.DataFrame, events: dict | None, cuts: list, end,
                         model_by_grain: dict[str, str], fit_kwargs: dict | None = None,
                         min_cows: int = 10, min_coverage: float = 1.0,
                         verbose: bool = False) -> pd.DataFrame:
    """Out-of-sample herd-level means of notebook 06 predictions, one row per period.

    Columns: grain, period_start, block, train_end, model, pred_litres_per_cow,
    actual_litres_per_cow, cow_days (aggregates only)."""
    from .cow_accuracy import score_models
    from .cow_torch import fit_torch_models

    dates = pd.to_datetime(raw["date"])
    rows = []
    for k, (t_end, b_end) in enumerate(prediction_blocks(cuts, end), start=1):
        t0 = time.perf_counter()
        sub = raw[dates <= pd.Timestamp(b_end)]
        if not (pd.to_datetime(sub["date"]) > pd.Timestamp(t_end)).any():
            continue
        models = fit_torch_models(sub, t_end, t_end, events=events, **(fit_kwargs or {}))
        _, frames = score_models(models, min_cows, min_coverage, blocks=("test",))
        for grain, model in model_by_grain.items():
            f = frames.get(model, {}).get(grain)
            if f is None:
                raise KeyError(f"notebook 06 model {model!r} ({grain}) was not fitted; "
                               "add it to the fit settings")
            ps = pd.to_datetime(f["period_start"])
            q = f[(f["period"] == "test") & (ps > pd.Timestamp(t_end)) & (ps <= pd.Timestamp(b_end))]
            rows.append(pd.DataFrame({
                "grain": grain, "period_start": pd.to_datetime(q["period_start"]).to_numpy(),
                "block": f"block_{k + 1}", "train_end": t_end, "model": model,
                "pred_litres_per_cow": q["prediction"].to_numpy(float),
                "actual_litres_per_cow": q["actual"].to_numpy(float),
                "cow_days": q["cow_days"].to_numpy(float)}))
        if verbose:
            print(f"  cow models fitted to {t_end}, predicting to {b_end} "
                  f"({time.perf_counter() - t0:,.0f}s)")
    if not rows:
        return pd.DataFrame(columns=["grain", "period_start", "block", "train_end", "model",
                                     "pred_litres_per_cow", "actual_litres_per_cow", "cow_days"])
    out = pd.concat(rows, ignore_index=True)
    return out.drop_duplicates(["grain", "period_start"]).sort_values(
        ["grain", "period_start"]).reset_index(drop=True)


def cow_pred_series(table: pd.DataFrame) -> dict[str, pd.Series]:
    """grain -> predicted litres per cow indexed by period start (herd model input)."""
    return {g: f.set_index(pd.to_datetime(f["period_start"]))["pred_litres_per_cow"]
            for g, f in table.groupby("grain")}


def cow_prediction_summary(table: pd.DataFrame, daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per grain and block: periods, mean predicted and recorded litres per cow, and the
    accuracy of the predicted herd mean (100 - WAPE). With ``daily``, also the herd
    target's own litres per milking cow on the same periods (consistency check)."""
    rows = []
    for (grain, block), g in table.groupby(["grain", "block"], sort=False):
        a, p = g["actual_litres_per_cow"].to_numpy(), g["pred_litres_per_cow"].to_numpy()
        ok = np.isfinite(a) & np.isfinite(p) & (a > 0)
        row = {"grain": grain, "block": block, "train_end": g["train_end"].iloc[0],
               "periods": int(ok.sum()), "mean_pred_per_cow": p[ok].mean() if ok.any() else np.nan,
               "mean_recorded_per_cow": a[ok].mean() if ok.any() else np.nan,
               "herd_mean_accuracy_pct": 100 - 100 * np.abs(p[ok] - a[ok]).sum() / a[ok].sum()
               if ok.any() else np.nan}
        if daily is not None and grain == "daily":
            pc = daily["per_cow"].reindex(pd.to_datetime(g["period_start"])).to_numpy()
            row["herd_target_per_cow_same_days"] = np.nanmean(pc) if np.isfinite(pc).any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)
