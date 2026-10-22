"""Per-cow state-space (Kalman) model of recorded yield around a base curve.

Each recorded yield is treated as ``base * exp(level + noise)``:

- ``base`` is the walk-forward recalibrated Wood curve (known before the forecast);
- ``level`` is the cow's own deviation from it, a mean-reverting (Ornstein-Uhlenbeck)
  process: after ``d`` days it keeps a share ``phi**d`` of its value and its variance
  moves back towards ``s2`` (the spread of cow levels);
- ``noise`` is the day-to-day record noise with variance ``r`` (measured, not assumed:
  the parameters are chosen on the training block).

A Kalman filter updates each cow's level after every record, using only that record and
earlier ones. A forecast issued at origin *o* for day *t* takes the cow's filtered level
after her last record before *o* and decays it to *t*. With a fresh, precise level the
forecast follows the cow; with an old or uncertain one it falls back to the base curve.
This is the principled version of "blend persistence with the curve".

The level restarts at each new lactation. Pure numpy; no LightGBM, no PyTorch.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

PHI_GRID = (0.97, 0.985, 0.993, 0.997, 0.999)
S2_GRID = (0.005, 0.01, 0.02, 0.04, 0.08)
R_GRID = (0.02, 0.04, 0.07, 0.11, 0.16)


def _filter(cow: np.ndarray, lact: np.ndarray, day: np.ndarray, z: np.ndarray,
            phi: float, s2: float, r: float) -> tuple[np.ndarray, ...]:
    """Run the filter over records sorted by cow, date.

    Returns, per record: the one-step prediction (mean, variance) made *before* seeing
    it, and the filtered (mean, variance) *after* it.
    """
    n = len(z)
    pred_m, pred_v = np.empty(n), np.empty(n)
    filt_m, filt_v = np.empty(n), np.empty(n)
    m, v, last_day, prev_cow, prev_lact = 0.0, s2, 0, -1, -1
    for i in range(n):
        if cow[i] != prev_cow or lact[i] != prev_lact:
            m, v = 0.0, s2           # new cow or new lactation: prior
        else:
            a = phi ** (day[i] - last_day)
            m, v = a * m, a * a * v + s2 * (1 - a * a)
        pred_m[i], pred_v[i] = m, v
        if np.isfinite(z[i]):
            k = v / (v + r)
            m, v = m + k * (z[i] - m), (1 - k) * v
        filt_m[i], filt_v[i] = m, v
        last_day, prev_cow, prev_lact = day[i], cow[i], lact[i]
    return pred_m, pred_v, filt_m, filt_v


def _prepare(frame: pd.DataFrame, base: np.ndarray):
    lact = frame["lactation"] if "lactation" in frame else pd.Series(0, index=frame.index)
    order = np.lexsort((frame["date"].to_numpy(), frame["animal"].to_numpy()))
    day = (frame["date"].to_numpy().astype("datetime64[D]").astype(np.int64))
    z = np.log(frame["litres"].to_numpy() / np.maximum(base, 1e-6))
    return order, frame["animal"].to_numpy()[order], lact.to_numpy()[order], day[order], z[order]


def fit_kalman(frame: pd.DataFrame, base: np.ndarray, train: np.ndarray,
               verbose: bool = False) -> tuple[dict, pd.DataFrame]:
    """Choose (phi, s2, r) by one-step-ahead WAPE in litres on training rows."""
    order, cow, lact, day, z = _prepare(frame, base)
    tr = train[order]
    y = frame["litres"].to_numpy()[order]
    b = np.asarray(base, dtype=float)[order]
    rows = []
    for phi, s2, r in itertools.product(PHI_GRID, S2_GRID, R_GRID):
        pm, pv, _, _ = _filter(cow, lact, day, z, phi, s2, r)
        pred = b * np.exp(np.clip(pm, -0.7, 0.7))
        wape = 100 * np.abs(pred[tr] - y[tr]).sum() / y[tr].sum()
        rows.append({"phi_per_day": phi, "level_var": s2, "noise_var": r,
                     "train_accuracy_pct": 100 - wape})
    table = pd.DataFrame(rows).sort_values("train_accuracy_pct", ascending=False)
    best = table.iloc[0]
    params = {"phi": float(best["phi_per_day"]), "s2": float(best["level_var"]),
              "r": float(best["noise_var"])}
    if verbose:
        print(f"[cow-kalman] phi/day={params['phi']}, level var={params['s2']}, "
              f"noise var={params['r']} (training one-step accuracy "
              f"{best['train_accuracy_pct']:.2f}%)", flush=True)
    return params, table.reset_index(drop=True)


def kalman_at_origin(frame: pd.DataFrame, base: np.ndarray, params: dict
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Level mean and SD for each row, known at its ``origin_date`` and decayed to its date.

    Uses the cow's filtered level after her last record strictly before the origin, in
    the same lactation as the row (otherwise the prior: level 0, variance ``s2``).
    """
    order, cow, lact, day, z = _prepare(frame, base)
    _, _, fm, fv = _filter(cow, lact, day, z, params["phi"], params["s2"], params["r"])
    hist = pd.DataFrame({"animal": cow, "lact_rec": lact,
                         "rec_date": frame["date"].to_numpy()[order],
                         "m": fm, "v": fv}).sort_values("rec_date")
    left = pd.DataFrame({"row": np.arange(len(frame)), "animal": frame["animal"].to_numpy(),
                         "origin": pd.to_datetime(frame["origin_date"]).to_numpy()
                         .astype("datetime64[ns]"),
                         "lact_row": (frame["lactation"] if "lactation" in frame
                                      else pd.Series(0, index=frame.index)).to_numpy()}
                        ).sort_values("origin")
    m = pd.merge_asof(left, hist, left_on="origin", right_on="rec_date", by="animal",
                      allow_exact_matches=False).sort_values("row")
    same = (m["lact_rec"].to_numpy() == m["lact_row"].to_numpy()) & m["rec_date"].notna().to_numpy()
    has = m["rec_date"].notna().to_numpy()
    gap = np.zeros(len(frame))
    gap[has] = ((frame["date"].to_numpy()[has] - m["rec_date"].to_numpy()[has])
                .astype("timedelta64[D]").astype(float))
    a = np.where(same, params["phi"] ** gap, 0.0)  # no record: NaT gaps never reach power()
    mean = np.where(same, a * m["m"].to_numpy(), 0.0)
    var = np.where(same, a * a * m["v"].to_numpy() + params["s2"] * (1 - a * a), params["s2"])
    return mean, np.sqrt(var)


def kalman_predict(frame: pd.DataFrame, base: np.ndarray, params: dict) -> np.ndarray:
    mean, sd = kalman_at_origin(frame, base, params)
    return np.asarray(base, dtype=float) * np.exp(np.clip(mean, -0.7, 0.7))
