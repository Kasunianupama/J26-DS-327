"""Estimate the engine's daily hazards from aggregate counts in a trailing window.

Inputs are aggregates only (event counts and animal-days at risk), already restricted
by the loaders to dates before the origin. Small cells are shrunk toward a pooled
rate with an empirical-Bayes beta-binomial prior (method of moments), following
St-Pierre et al. 2001.

Every fallback (missing table, too few events) is recorded in ``RateSet.notes`` so a
backtest can report which origins used assumed rather than measured rates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .categories import COW_PARITIES, DIM_BANDS, EXIT_TYPES, STATES
from .config import EngineConfig
from .herd_engine import N_GEST, RateSet

# Values of state_transition_month.to_state / from_state that mean leaving or
# entering the herd. ASSUMPTION until checked against the published vocabulary.
EXIT_TO_STATES = {
    "death": "deaths", "dead": "deaths", "died": "deaths",
    "cull": "culls", "culled": "culls", "slaughter": "culls",
    "sale": "sales", "sold": "sales",
}
ENTRY_FROM_STATES = {"entry", "external", "external_entry", "purchase", "purchased", "outside"}

MIN_DISTRIBUTION_COUNT = 20
DEFAULT_GESTATION = (281.0, 6.0)  # mean, sd in days, used only when too few records
DEFAULT_DRY_PERIOD = 60
DEFAULTS = {  # assumed daily hazards, used only when the source table is empty
    "calf_to_heifer": 1.0 / 365.0,
    "conc_heifer": 1.0 / 120.0,
    "conc_dry": 1.0 / 120.0,
}


@dataclass
class RateInputs:
    """Aggregate inputs for one origin and window (see data.load_rate_inputs)."""

    origin: date
    window_start: date
    exposure: pd.DataFrame  # month, state, parity_group, dim_band, generation_group, animal_days
    transitions: pd.DataFrame  # month, from_state, to_state, n_moved (complete months)
    panel: pd.DataFrame  # month, days, <event columns>
    cow_open: pd.DataFrame  # parity_group, dim_band, open_days, conceptions, open_dry_offs
    preg_milking_days: float
    dryoff_gest: pd.DataFrame  # gest, n
    gestation: pd.DataFrame  # gest, n


def eb_shrink(events, exposure, prior_rate: float | None = None,
              default_prior: float = 3650.0) -> np.ndarray:
    """Beta-binomial empirical-Bayes shrinkage of per-cell daily rates.

    ``events`` and ``exposure`` (animal-days) are arrays over cells. Returns
    (events + m * p0) / (exposure + m), with p0 the pooled rate (or ``prior_rate``)
    and m the prior strength from the method of moments. Cells without exposure get p0.
    """
    x = np.asarray(events, dtype=float)
    n = np.asarray(exposure, dtype=float)
    total_n = n[n > 0].sum()
    p0 = prior_rate if prior_rate is not None else (x.sum() / total_n if total_n > 0 else 0.0)
    if p0 <= 0 or total_n <= 0:
        return np.full(x.shape, max(p0, 0.0))
    m = default_prior
    pos = n > 0
    if pos.sum() >= 2:
        r = x[pos] / n[pos]
        var_w = float((n[pos] * (r - p0) ** 2).sum() / total_n)
        sampling = p0 * (1 - p0) * pos.sum() / total_n
        tau2 = var_w - sampling
        m = p0 * (1 - p0) / tau2 - 1.0 if tau2 > 0 else 1e9
        m = float(np.clip(m, 0.0, 1e9))
    return (x + m * p0) / (np.where(pos, n, 0.0) + m)


def hazard_from_counts(counts: np.ndarray, smooth_days: int = 7) -> np.ndarray:
    """Discrete hazard h[t] = f[t] / S[t] from a (smoothed) histogram of event times."""
    f = np.asarray(counts, dtype=float)
    if smooth_days > 1 and f.sum() > 0:
        kernel = np.ones(smooth_days) / smooth_days
        f = np.convolve(f, kernel, mode="same")
    surv = np.cumsum(f[::-1])[::-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.where(surv > 0, f / surv, 0.0)
    return np.clip(h, 0.0, 1.0)


def _hist(frame: pd.DataFrame) -> np.ndarray:
    out = np.zeros(N_GEST)
    if len(frame):
        g = frame["gest"].astype(int).clip(0, N_GEST - 1).to_numpy()
        np.add.at(out, g, frame["n"].to_numpy(dtype=float))
    return out


def _normal_pmf(mean: float, sd: float) -> np.ndarray:
    t = np.arange(N_GEST)
    pmf = np.exp(-0.5 * ((t - mean) / sd) ** 2)
    return pmf / pmf.sum()


def conception_per_ai(inp: RateInputs, default: float = 0.25) -> float:
    """Share of inseminations that become a pregnancy in the window (herd level).

    Conceptions = cow conceptions while milking + heifer and dry-cow conceptions from
    the transition table; inseminations = day_panel.ais. Clipped to [0.05, 0.9].
    """
    ais = float(inp.panel["ais"].sum()) if len(inp.panel) else 0.0
    conc = float(inp.cow_open["conceptions"].sum()) if len(inp.cow_open) else 0.0
    tr = inp.transitions
    if len(tr):
        mask = ((tr["from_state"] == "heifer_open") & (tr["to_state"] == "heifer_pregnant")) | (
            (tr["from_state"] == "dry_open") & (tr["to_state"] == "dry_pregnant"))
        conc += float(tr.loc[mask, "n_moved"].sum())
    if ais <= 0 or conc <= 0:
        return default
    return float(np.clip(conc / ais, 0.05, 0.9))


def max_live_gestation(gestation: pd.DataFrame, quantile: float = 0.99,
                       default: int = 300) -> int:
    """Longest plausible live pregnancy: the 99th percentile of recorded gestations."""
    if not len(gestation) or gestation["n"].sum() < MIN_DISTRIBUTION_COUNT:
        return default
    g = gestation.sort_values("gest")
    cum = g["n"].cumsum() / g["n"].sum()
    return int(g.loc[cum >= quantile, "gest"].iloc[0])


def estimate_rates(inp: RateInputs, cfg: EngineConfig | None = None) -> RateSet:
    cfg = cfg or EngineConfig()
    notes: list[str] = []
    exp = inp.exposure
    E_all = exp.groupby("state")["animal_days"].sum().reindex(STATES, fill_value=0.0)
    tr = inp.transitions.copy()
    tr_months = set(tr["month"]) if len(tr) else set()
    E_tr = (
        exp[exp["month"].isin(tr_months)].groupby("state")["animal_days"].sum()
        .reindex(STATES, fill_value=0.0)
    )
    panel = inp.panel[[c for c in inp.panel.columns if c != "month"]].sum()
    if not len(inp.panel) or panel.get("days", 0) <= 0:
        raise ValueError("no panel days before the origin: cannot estimate rates")

    def moved(src: str, dst: str) -> float:
        if not len(tr):
            return 0.0
        return float(tr.loc[(tr["from_state"] == src) & (tr["to_state"] == dst), "n_moved"].sum())

    def trans_rate(src: str, dst: str, key: str) -> float:
        if not len(tr) or E_tr[src] <= 0:
            notes.append(f"{key}: no transitions/exposure in window, assumed {DEFAULTS[key]:.5f}/day")
            return DEFAULTS[key]
        return moved(src, dst) / E_tr[src]

    # exits
    exit_rates: dict[str, dict[str, float]] = {s: {} for s in STATES}
    tr_exit = tr[tr["to_state"].isin(EXIT_TO_STATES)] if len(tr) else tr
    if len(tr_exit):
        tr_exit = tr_exit.assign(kind=tr_exit["to_state"].map(EXIT_TO_STATES))
        for kind in EXIT_TYPES:
            x = (tr_exit[tr_exit["kind"] == kind].groupby("from_state")["n_moved"].sum()
                 .reindex(STATES, fill_value=0.0))
            rates = eb_shrink(x.to_numpy(), E_tr.to_numpy(), default_prior=cfg.default_prior_days)
            for s, r in zip(STATES, rates):
                exit_rates[s][kind] = float(r)
    else:
        herd_days = float(E_all.sum())
        notes.append("exits: no exit transitions found; herd-level exit rates applied to every state")
        for kind in EXIT_TYPES:
            r = float(panel.get(kind, 0.0)) / herd_days if herd_days > 0 else 0.0
            for s in STATES:
                exit_rates[s][kind] = r

    # cow conception by parity x DIM band, shrunk toward the band rate
    co = inp.cow_open
    conc_cow = np.zeros((len(COW_PARITIES), len(DIM_BANDS)))
    dry_open_cow = np.zeros(len(DIM_BANDS))
    if len(co) and co["open_days"].sum() > 0:
        band_tot = co.groupby("dim_band")[["open_days", "conceptions", "open_dry_offs"]].sum()
        band_tot = band_tot.reindex(DIM_BANDS, fill_value=0.0)
        overall_conc = band_tot["conceptions"].sum() / band_tot["open_days"].sum()
        for b, band in enumerate(DIM_BANDS):
            sub = (co[co["dim_band"] == band].groupby("parity_group")[["conceptions", "open_days"]]
                   .sum().reindex(COW_PARITIES, fill_value=0.0))
            bd = band_tot.loc[band, "open_days"]
            p0 = band_tot.loc[band, "conceptions"] / bd if bd > 0 else overall_conc
            conc_cow[:, b] = eb_shrink(sub["conceptions"].to_numpy(), sub["open_days"].to_numpy(),
                                       prior_rate=p0, default_prior=cfg.default_prior_days)
        dry_open_cow = eb_shrink(band_tot["open_dry_offs"].to_numpy(),
                                 band_tot["open_days"].to_numpy(),
                                 default_prior=cfg.default_prior_days)
    else:
        notes.append("cow conception/dry-off: no open milking days in window, rates set to 0")

    # gestation length -> calving hazard
    gest_counts = _hist(inp.gestation)
    if gest_counts.sum() >= MIN_DISTRIBUTION_COUNT:
        calve = hazard_from_counts(gest_counts, smooth_days=3)
    else:
        notes.append(f"gestation: <{MIN_DISTRIBUTION_COUNT} records, assumed normal{DEFAULT_GESTATION}")
        calve = hazard_from_counts(_normal_pmf(*DEFAULT_GESTATION), smooth_days=1)

    # dry-off of pregnant cows by gestation day
    dry_counts = _hist(inp.dryoff_gest)
    if dry_counts.sum() >= MIN_DISTRIBUTION_COUNT:
        dry_preg = hazard_from_counts(dry_counts)
    else:
        target = int(DEFAULT_GESTATION[0] - DEFAULT_DRY_PERIOD)
        notes.append(f"pregnant dry-off: <{MIN_DISTRIBUTION_COUNT} records, assumed at gestation day {target}")
        dry_preg = np.zeros(N_GEST)
        dry_preg[target] = 1.0

    preg_days = E_all["heifer_pregnant"] + E_all["dry_pregnant"] + inp.preg_milking_days
    abortion = float(panel.get("real_abortions", 0.0)) / preg_days if preg_days > 0 else 0.0

    # Pregnancy losses beyond real abortions (e.g. pregnancies not confirmed at a later
    # check), from the transition table: pregnant -> open for heifers and dry cows.
    def extra_loss(src: str, dst: str) -> float:
        if not len(tr) or E_tr[src] <= 0:
            return 0.0
        return max(0.0, moved(src, dst) / E_tr[src] - abortion)

    heifer_loss = extra_loss("heifer_pregnant", "heifer_open")
    dry_loss = extra_loss("dry_pregnant", "dry_open")

    calvings = float(panel.get("calvings", 0.0))
    births_per_calving = float(panel.get("births", 0.0)) / calvings if calvings > 0 else 0.5
    if calvings <= 0:
        notes.append("births: no calvings in window, assumed 0.5 calves retained per calving")

    open_days = E_all["heifer_open"] + E_all["dry_open"] + (co["open_days"].sum() if len(co) else 0.0)
    ai_open = float(panel.get("ais", 0.0)) / open_days if open_days > 0 else 0.0

    entry_per_day = float(panel.get("external_entries", 0.0)) / float(panel["days"])
    entry_shares = {cfg.default_entry_state: 1.0}
    if len(tr):
        ent = tr[tr["from_state"].isin(ENTRY_FROM_STATES) & tr["to_state"].isin(STATES)]
        if ent["n_moved"].sum() > 0:
            entry_shares = ent.groupby("to_state")["n_moved"].sum().to_dict()
    if entry_per_day > 0 and entry_shares == {cfg.default_entry_state: 1.0}:
        notes.append(f"entries: state of entering animals unknown, assigned to {cfg.default_entry_state}")

    return RateSet(
        exit=exit_rates,
        calf_to_heifer=trans_rate("calf", "heifer_open", "calf_to_heifer"),
        conc_heifer=trans_rate("heifer_open", "heifer_pregnant", "conc_heifer"),
        conc_dry=trans_rate("dry_open", "dry_pregnant", "conc_dry"),
        conc_cow=conc_cow,
        dry_open_cow=dry_open_cow,
        dry_preg_by_gest=dry_preg,
        calve_by_gest=calve,
        abortion=abortion,
        heifer_loss=heifer_loss,
        dry_loss=dry_loss,
        births_per_calving=births_per_calving,
        ai_open=ai_open,
        entry_per_day=entry_per_day,
        entry_shares=entry_shares,
        entry_dim=cfg.entry_dim,
        entry_gestation=cfg.entry_gestation,
        notes=tuple(notes),
    )


def rate_summary(r: RateSet) -> pd.DataFrame:
    """Annualised herd-level rates for a sanity check (aggregates only)."""
    rows = [(f"exit_{k}:{s}", v * 365) for s, d in r.exit.items() for k, v in d.items()]
    rows += [
        ("calf_to_heifer", r.calf_to_heifer * 365),
        ("conc_heifer", r.conc_heifer * 365),
        ("conc_dry", r.conc_dry * 365),
        ("abortion_per_pregnant_year", r.abortion * 365),
        ("extra_loss_heifer_pregnant_year", r.heifer_loss * 365),
        ("extra_loss_dry_pregnant_year", r.dry_loss * 365),
        ("ai_per_open_year", r.ai_open * 365),
        ("births_per_calving", r.births_per_calving),
        ("entries_per_year", r.entry_per_day * 365),
    ]
    rows += [(f"conc_cow:{p}:{b}", r.conc_cow[i, j] * 365)
             for i, p in enumerate(COW_PARITIES) for j, b in enumerate(DIM_BANDS)]
    rows += [(f"dry_off_open:{b}", r.dry_open_cow[j] * 365) for j, b in enumerate(DIM_BANDS)]
    pmf = np.empty(N_GEST)
    surv = 1.0
    for t, h in enumerate(r.calve_by_gest):
        pmf[t] = surv * h
        surv *= 1 - h
    rows.append(("mean_gestation_days", float((np.arange(N_GEST) * pmf).sum())))
    return pd.DataFrame(rows, columns=["rate", "value"])
