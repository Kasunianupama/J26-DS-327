"""SYNTHETIC cow-day fixtures for the Layer 2 cow model. Fictional cows, not Farm X data.

Every milking cow-day of a small fictional herd, 2015-08 to 2026-08, with the recording
regimes of the real series imitated in shape only: a small, late-lactation-biased sample
with whole-herd test days (2016 to 2022-04), a gap with a few bad fragments
(2022-05 to 2025-09) and no cow records to 2026-03, a sparse restart (2026-04 to 05)
and a well-covered final stretch (2026-06 onward).

Columns: date, animal, parity_group, dim, days_pregnant, litres (NaN when not recorded),
true_litres (expected yield without day noise; known only because the data are synthetic).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

START = date(2015, 8, 1)
END = date(2026, 8, 31)
# True Wood (a, b, c per day) by parity group.
TRUE_WOOD = {"1": (6.0, 0.20, 0.0030), "2": (7.0, 0.22, 0.0035), "3+": (7.5, 0.21, 0.0036)}
COW_SD = 0.15      # log-scale cow effect
NOISE_SD = 0.10    # log-scale day noise
PREG_SLOPE = 0.002  # log drop per day pregnant beyond 150 days
# (first day, last day, recording probability, bias toward DIM > 200, yield multiplier)
REGIMES = (
    (date(2016, 1, 1), date(2022, 4, 30), 0.03, 4.0, 1.0),
    (date(2022, 5, 1), date(2025, 9, 30), 0.002, 1.0, 0.55),
    (date(2026, 4, 1), date(2026, 5, 31), 0.08, 1.0, 1.0),
    (date(2026, 6, 1), date(2026, 8, 31), 0.65, 1.0, 1.0),
)
TEST_DAY_EVERY = 91  # whole-herd test day in the first regime
TEST_DAY_P = 0.9


def true_log_yield(parity_group, dim, days_pregnant):
    a = np.array([TRUE_WOOD[p][0] for p in parity_group])
    b = np.array([TRUE_WOOD[p][1] for p in parity_group])
    c = np.array([TRUE_WOOD[p][2] for p in parity_group])
    d = np.maximum(np.asarray(dim, dtype=float), 1.0)
    late = np.maximum(np.asarray(days_pregnant, dtype=float) - 150.0, 0.0)
    return np.log(a) + b * np.log(d) - c * d - PREG_SLOPE * late


def synthetic_cowdays(n_cows: int = 160, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start, end = np.datetime64(START), np.datetime64(END)
    span = int((end - start).astype(int))
    parts = []
    for i in range(n_cows):
        calving = start + np.timedelta64(int(rng.integers(-700, span - 60)), "D")
        u = rng.normal(0.0, COW_SD)
        for lac in range(1, 5):
            conc = int(rng.integers(70, 200))
            length = conc + 220  # dry-off at about 220 days pregnant
            dim = np.arange(1, length + 1)
            days = calving + dim.astype("timedelta64[D]")
            keep = (days >= start) & (days <= end)
            if keep.any():
                parts.append(pd.DataFrame({
                    "date": days[keep], "animal": f"SYN{i:04d}",
                    "parity_group": "1" if lac == 1 else ("2" if lac == 2 else "3+"),
                    "dim": dim[keep], "days_pregnant": np.maximum(dim[keep] - conc, 0),
                    "cow_u": u,
                }))
            calving = calving + np.timedelta64(conc + 280, "D")
            if calving > end:
                break
    f = pd.concat(parts, ignore_index=True)
    f["date"] = pd.to_datetime(f["date"])
    mu = true_log_yield(f["parity_group"].to_numpy(), f["dim"], f["days_pregnant"]) + f["cow_u"]
    f["true_litres"] = np.exp(mu + NOISE_SD ** 2 / 2)
    observed = np.exp(mu + rng.normal(0.0, NOISE_SD, len(f)))
    f["litres"] = np.nan
    day_no = (f["date"] - pd.Timestamp(START)).dt.days.to_numpy()
    for first, last, p, late_bias, mult in REGIMES:
        in_r = ((f["date"] >= pd.Timestamp(first)) & (f["date"] <= pd.Timestamp(last))).to_numpy()
        prob = np.where(f["dim"].to_numpy() > 200, p * late_bias, p)
        if late_bias != 1.0:
            prob = np.where(day_no % TEST_DAY_EVERY == 0, TEST_DAY_P, prob)
        rec = in_r & (rng.random(len(f)) < prob)
        f.loc[rec, "litres"] = observed[rec] * mult
    return f.drop(columns="cow_u").sort_values(["date", "animal"]).reset_index(drop=True)
