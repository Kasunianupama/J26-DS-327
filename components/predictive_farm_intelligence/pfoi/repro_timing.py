"""Reproductive timing (M7, docs/pp1_plan.md): calving -> first recorded service -> known
conception -> maintained pregnancy -> next calving, at herd level.

Inputs are counts by step, day and status (``data.SqlHerdSource.repro_steps``); nothing
here sees an animal. Statistics treat the record honestly:

* a cow still open (or still pregnant) at the as-of date is **censored**, not a failure;
* leaving the herd is a **competing event**, reported as its own cumulative share
  (Aalen-Johansen), never as "not conceived";
* "first AI" is the first *recorded* service: no record is not proof of no service.

``engine_conception_cif`` gives the same curve implied by the engine's rates (conception,
dry-off and exit hazards by days in milk), so the engine's reproductive timing can be
checked against the record. Descriptive associations only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .categories import COW_PARITIES
from .herd_engine import BAND_OF_DIM, N_DIM

EVENT, LEFT, CENSORED = "event", "left_herd", "censored"
CHECKPOINTS = (60, 100, 150, 200, 300)
STEPS = ("first_ai", "conception", "calving_interval")


def aalen_johansen(counts: pd.DataFrame, horizon: int = 999) -> pd.DataFrame:
    """Per day 0..horizon: at risk, events, exits, survival and cumulative incidences.

    ``counts`` has columns day, status (event / left_herd / censored), n. Ties on a day are
    ordered events, exits, then censoring (the usual convention)."""
    c = counts.groupby(["day", "status"])["n"].sum().unstack(fill_value=0.0)
    for col in (EVENT, LEFT, CENSORED):
        if col not in c:
            c[col] = 0.0
    c = c.reindex(range(horizon + 1), fill_value=0.0)
    total = float(c[[EVENT, LEFT, CENSORED]].to_numpy().sum())
    leaving = (c[EVENT] + c[LEFT] + c[CENSORED]).to_numpy()
    at_risk = total - np.concatenate([[0.0], np.cumsum(leaving)[:-1]])
    s, cif_e, cif_l = 1.0, 0.0, 0.0
    rows = []
    for d in range(horizon + 1):
        n, e, l = at_risk[d], float(c.at[d, EVENT]), float(c.at[d, LEFT])
        if n > 0:
            cif_e += s * e / n
            cif_l += s * l / n
            s *= 1.0 - (e + l) / n
        rows.append((d, n, e, l, s, cif_e, cif_l))
    return pd.DataFrame(rows, columns=["day", "at_risk", "events", "left", "survival",
                                       "cif_event", "cif_left"])


def step_summary(counts: pd.DataFrame, checkpoints=CHECKPOINTS) -> dict:
    """n; the first day the cumulative share with the event reaches 25 / 50 / 75 % (None if
    it never does, e.g. when many cows leave first); the share by each checkpoint; the share
    censored and the cumulative share that left the herd first."""
    n = float(counts["n"].sum())
    if n <= 0:
        return {"n": 0}
    aj = aalen_johansen(counts)
    med = aj.loc[aj["cif_event"] >= 0.5, "day"]
    out = {"n": int(n),
           "median_days": int(med.iloc[0]) if len(med) else None,
           "censored_share": float(counts.loc[counts["status"] == CENSORED, "n"].sum() / n),
           "left_herd_share": float(aj["cif_left"].iloc[-1])}
    for d in checkpoints:
        out[f"by_{d}d"] = float(aj.loc[d, "cif_event"])
    q = aj[aj["cif_event"] > 0]
    out["p25_days"] = int(aj.loc[aj["cif_event"] >= 0.25, "day"].iloc[0]) if (aj["cif_event"] >= 0.25).any() else None
    out["p75_days"] = int(aj.loc[aj["cif_event"] >= 0.75, "day"].iloc[0]) if (aj["cif_event"] >= 0.75).any() else None
    out["first_event_day"] = int(q["day"].iloc[0]) if len(q) else None
    return out


def pregnancy_outcomes(counts: pd.DataFrame) -> dict:
    """Shares of known conceptions that calved, were lost, left the herd or are pending.

    ``*_share`` are over all known conceptions (pending ones included, as ``censored``).
    ``calved_of_resolved`` / ``lost_of_resolved`` are over pregnancies whose outcome is
    known (calved, lost or left the herd): a pregnancy still running at the as-of date is
    not a failure, so the plain shares understate calving when many are pending."""
    n = float(counts["n"].sum())
    g = counts.groupby("status")["n"].sum()
    out = {"n": int(n)}
    for k in ("calved", "lost", LEFT, CENSORED):
        out[f"{k}_share"] = float(g.get(k, 0.0) / n) if n else None
    resolved = float(g.get("calved", 0.0) + g.get("lost", 0.0) + g.get(LEFT, 0.0))
    out["n_resolved"] = int(resolved)
    out["calved_of_resolved"] = float(g.get("calved", 0.0) / resolved) if resolved else None
    out["lost_of_resolved"] = float(g.get("lost", 0.0) / resolved) if resolved else None
    return out


def repro_table(steps: pd.DataFrame, by=("period",)) -> pd.DataFrame:
    """One row per group and step (aggregates only)."""
    rows = []
    for key, g in steps.groupby(list(by)):
        key = key if isinstance(key, tuple) else (key,)
        base = dict(zip(by, key))
        for step in STEPS:
            part = g[g["step"] == step]
            if len(part):
                rows.append({**base, "step": step, **step_summary(part)})
        preg = g[g["step"] == "pregnancy"]
        if len(preg):
            rows.append({**base, "step": "pregnancy", **pregnancy_outcomes(preg)})
    return pd.DataFrame(rows)


def engine_conception_cif(rates, parity: str = "2", horizon: int = 400) -> pd.DataFrame:
    """Cumulative share of fresh cows (one parity group) that conceive or leave, by day in
    milk, implied by the engine's daily hazards: milking open -> conception / dry-off / exit;
    dry open -> conception (dry-cow rate) / exit. Same competing-risk reading as above."""
    p = COW_PARITIES.index(parity)
    conc = rates.conc_cow[p, BAND_OF_DIM[:N_DIM]].astype(float)
    if getattr(rates, "conc_dim_shape", None) is not None:
        conc = np.clip(conc * rates.conc_dim_shape[:N_DIM], 0.0, 1.0)
    exit_m = np.full(N_DIM, sum(rates.exit.get("milking", {}).values()))
    if getattr(rates, "milk_exit_cell", None) is not None:  # measured exits of open milking cows
        exit_m = np.clip(rates.milk_exit_cell[p, BAND_OF_DIM[:N_DIM], 0], 0.0, 1.0)
    exit_d = sum(rates.exit.get("dry_open", {}).values())
    dry = rates.dry_open_cow[BAND_OF_DIM[:N_DIM]]
    milk, dry_open, cif_c, cif_l = 1.0, 0.0, 0.0, 0.0
    rows = []
    for d in range(horizon + 1):
        c_m, l_m = milk * conc[d], milk * exit_m[d]
        c_d, l_d = dry_open * rates.conc_dry, dry_open * exit_d
        to_dry = (milk - c_m - l_m) * dry[d]
        milk = milk - c_m - l_m - to_dry
        dry_open = dry_open - c_d - l_d + to_dry
        cif_c += c_m + c_d
        cif_l += l_m + l_d
        rows.append((d, cif_c, cif_l))
    return pd.DataFrame(rows, columns=["day", "cif_event", "cif_left"])


def compare_engine(steps: pd.DataFrame, rates, parity: str = "2",
                   checkpoints=CHECKPOINTS) -> pd.DataFrame:
    """Recorded vs engine-implied share conceived by each checkpoint (one parity group)."""
    rec = steps[(steps["step"] == "conception") & (steps["parity_group"] == parity)]
    if not len(rec):
        return pd.DataFrame()
    aj = aalen_johansen(rec)
    eng = engine_conception_cif(rates, parity, max(checkpoints))
    return pd.DataFrame([{"parity_group": parity, "day": d,
                          "recorded_conceived": float(aj.loc[d, "cif_event"]),
                          "engine_conceived": float(eng.loc[d, "cif_event"]),
                          "recorded_left": float(aj.loc[d, "cif_left"]),
                          "engine_left": float(eng.loc[d, "cif_left"])} for d in checkpoints])
