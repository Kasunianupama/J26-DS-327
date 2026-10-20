"""Simulated milk-recording outages (M2, docs/pp1_plan.md).

How much accuracy does the milk forecast lose while records are missing, and how fast
does it come back once they return? Measured on the development block by hiding
recorded milk the model would otherwise see, while the recorded actuals are still used
for scoring:

* an outage of ``gap`` days that ended ``resumed`` days before the forecast date hides
  the target days in [origin - resumed - gap, origin - resumed);
* ``resumed = 0`` means the outage is still going on at the forecast date;
* scenario (0, 0) is the normal backtest.

Each scenario sees the same masked history for every model: the milk baseline (its k,
and the herd-fitted curve before 2020-09) and persistence. Nothing is imputed: masked
days are simply unscoreable. Real gaps are never filled; only days that were recorded are
hidden, and only recorded actuals are scored.

Limit (stated in every report): only milk is hidden. Herd records stay complete, while
in the real 2024-25 outage calvings went unrecorded too, so these results are optimistic
for real outages.

User-run command (prints herd-level aggregates only, writes them under ``--out``):

    python -m components.predictive_farm_intelligence.pfoi.outage_sim --preset pfoi-1.1 --every 2 --jobs 0
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest_herd import TEST_START, check_block, development_origins
from .backtest_milk import BASELINE, SERIES, _target_frame, benchmark_series, period_actual
from .benchmarks import persistence_value
from .config import EngineConfig
from .data import DATA_START, SnapshotSource, load_origin_inputs, prefetch_snapshots
from .herd_engine import project
from .milk_baseline import (
    FITTED_FROM, MilkConfig, MilkHistory, MilkWithheld, anchor_k, prepare_milk,
)
from .parallel import map_origins, resolve_jobs
from .periods import HORIZONS, horizon_days, period_bounds
from .rates import estimate_rates

GAPS = (28, 90, 180)
RESUMED = (0, 3, 7, 14)
PERSISTENCE = "persistence"
GRAINS_BY_ORIGIN = {"monthly": ("monthly",), "weekly": ("weekly", "daily")}
LIMIT_NOTE = ("Only milk records are hidden; herd records stay complete. Real outages also "
              "lose herd records, so these results are optimistic.")


def scenarios(gaps=GAPS, resumed=RESUMED) -> list[tuple[int, int]]:
    """(gap days, resumed days): the normal case first, then every combination."""
    return [(0, 0)] + [(g, r) for g in gaps for r in resumed if g > 0]


def mask_target(target: pd.DataFrame, origin: date, gap: int, resumed: int) -> pd.DataFrame:
    """Copy of ``target`` with the days in [origin - resumed - gap, origin - resumed) hidden."""
    t = target.copy()
    if gap <= 0:
        return t
    d = pd.to_datetime(t["date"]).dt.date
    hide = (d >= origin - timedelta(days=resumed + gap)) & (d < origin - timedelta(days=resumed))
    t.loc[hide, "is_scoreable"] = False
    t.loc[hide, "target_litres"] = np.nan
    return t


def record_freshness(target: pd.DataFrame, origin: date, lookback: int = 28) -> tuple[float, int]:
    """(days since the last trusted day, trusted days in the last ``lookback`` days)."""
    d = pd.to_datetime(target["date"]).dt.date
    ok = target["is_scoreable"].fillna(False).astype(bool) & target["target_litres"].notna() & (d < origin)
    if not ok.any():
        return np.nan, 0
    last = max(d[ok])
    fresh = int((ok & (d >= origin - timedelta(days=lookback))).sum())
    return float((origin - last).days), fresh


def _persistence(t: pd.DataFrame, origin: date, grain: str, h: int) -> float | None:
    """Persistence as in ``backtest_milk.benchmark_forecasts`` (daily uses the last week)."""
    s, e = period_bounds(origin, grain, h)
    series = benchmark_series(t, origin, "monthly" if grain == "monthly" else "weekly")
    p = persistence_value(series)
    if p is None:
        return None
    return p if grain == "daily" else p * (e - s).days


def _arrays_key(setup) -> str:
    a = setup.arrays
    return hashlib.sha1(a.open_.tobytes() + a.preg.tobytes()).hexdigest()


@dataclass
class _Ctx:
    source: object
    cfg: EngineConfig
    milk_cfg: MilkConfig
    hist: MilkHistory
    t_full: pd.DataFrame
    grains: tuple[str, ...]
    score_until: date
    scen: tuple[tuple[int, int], ...]
    # Curves from per-cow data (origins from 2020-09) do not depend on the hidden milk days,
    # so they are shared across scenarios; earlier herd-fitted curves are refitted per mask.
    curve_cache: dict | None = None


def _score_origin(c: _Ctx, origin: date) -> tuple[list[dict], list[dict]]:
    """Error rows and one status row per scenario for one forecast date."""
    inputs = load_origin_inputs(c.source, origin, c.cfg)
    rates = estimate_rates(inputs.rate_inputs, c.cfg)
    H = max(horizon_days(origin, g, max(HORIZONS[g])) for g in c.grains)
    projections: dict[str, pd.DataFrame] = {}
    rows, status = [], []
    for gap, resumed in c.scen:
        masked = mask_target(c.hist.target, origin, gap, resumed)
        hist = replace(c.hist, target=masked)
        t = _target_frame(masked)
        stale, fresh = record_freshness(masked, origin)
        st = dict(origin=origin, gap_days=gap, resumed_days=resumed, staleness_days=stale,
                  fresh_days=fresh, outcome="forecast", k_source=None)
        daily = None
        try:
            if c.curve_cache is None:
                c.curve_cache = {}
            cache = c.curve_cache if origin >= FITTED_FROM else None
            setup = prepare_milk(c.source, origin, c.milk_cfg, hist, cache=cache)
            anchor_k(setup, hist.target_before(origin), inputs.state, c.milk_cfg)
            key = _arrays_key(setup)
            if key not in projections:
                projections[key] = project(inputs.state, rates, H, milk_curve=setup.arrays).daily
            proj = projections[key]
            daily = proj.assign(litres=setup.k * proj["curve_litres"])
            st["k_source"] = setup.k_source
            st["flags"] = ";".join(setup.flags)
        except MilkWithheld as w:
            st["outcome"] = f"withheld ({w.reason})"
        except ValueError:
            st["outcome"] = "skipped (no usable months for k)"
        status.append(st)
        ddates = None if daily is None else pd.to_datetime(daily["date"]).dt.date
        for grain in c.grains:
            for h in HORIZONS[grain]:
                s, e = period_bounds(origin, grain, h)
                if e > c.score_until:
                    continue
                act = period_actual(c.t_full, s, e)  # recorded actuals, never masked
                if act is None:
                    continue
                preds = {}
                if daily is not None:
                    preds[BASELINE] = float(daily.loc[(ddates >= s) & (ddates < e), "litres"].sum())
                p = _persistence(t, origin, grain, h)
                if p is not None:
                    preds[PERSISTENCE] = p
                for model, v in preds.items():
                    rows.append(dict(origin=origin, grain=grain, horizon=h, period_start=s,
                                     period_end=e, series=SERIES, model=model, forecast=v,
                                     actual=act[0], source=act[1], gap_days=gap,
                                     resumed_days=resumed, staleness_days=stale,
                                     fresh_days=fresh))
    return rows, status


def _ctx(source_factory, snapshots, cfg, milk_cfg, hist, t_full, grains, score_until, scen) -> _Ctx:
    return _Ctx(SnapshotSource(source_factory(), snapshots), cfg, milk_cfg, hist, t_full,
                grains, score_until, scen)


@dataclass
class OutageResult:
    errors: pd.DataFrame
    status: pd.DataFrame


def run_outage_sim(source, origin_grain: str = "weekly", cfg: EngineConfig | None = None,
                   milk_cfg: MilkConfig | None = None, origins: list[date] | None = None,
                   scen: list[tuple[int, int]] | None = None, score_until: date = TEST_START,
                   jobs: int = 1, source_factory=None, progress=None) -> OutageResult:
    """Development block only (origins and targets before 2024-01)."""
    cfg = cfg or EngineConfig()
    milk_cfg = milk_cfg or MilkConfig(k_mode="anchor_first")
    origins = origins if origins is not None else development_origins(origin_grain)
    check_block(origins, score_until, "development")
    if jobs > 1 and source_factory is None:
        raise ValueError("jobs > 1 needs a source_factory so each process opens its own source")
    scen = tuple(scen or scenarios())
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, score_until),
                       target=source.target_daily(DATA_START, score_until))
    t_full = _target_frame(hist.target)
    grains = GRAINS_BY_ORIGIN[origin_grain]
    snapshots = prefetch_snapshots(source, origins, cfg)
    serial = (_Ctx(SnapshotSource(source, snapshots), cfg, milk_cfg, hist, t_full, grains,
                   score_until, scen) if jobs <= 1 else None)
    results = map_origins(origins, _score_origin, _ctx,
                          (source_factory, snapshots, cfg, milk_cfg, hist, t_full, grains,
                           score_until, scen),
                          jobs=jobs, progress=progress, serial_ctx=serial)
    rows, status = [], []
    for r, s in results:
        rows += r
        status += s
    errors = pd.DataFrame(rows)
    if len(errors):
        errors["error"] = errors["forecast"] - errors["actual"]
    return OutageResult(errors=errors, status=pd.DataFrame(status))


# ------------------------------------------------------------------ summaries (aggregates)

KEYS = ["gap_days", "resumed_days", "grain", "horizon", "model"]


def summarise(errors: pd.DataFrame) -> pd.DataFrame:
    """n, MAE, bias and WAPE per scenario x grain x horizon x model."""
    if not len(errors):
        return pd.DataFrame()
    e = errors.assign(abs_err=errors["error"].abs())
    g = e.groupby(KEYS)
    out = pd.DataFrame({"n": g.size(), "mae": g["abs_err"].mean(), "bias": g["error"].mean(),
                        "wape_pct": 100 * g["abs_err"].sum() / g["actual"].sum()})
    return out.reset_index()


def outage_cost(errors: pd.DataFrame) -> pd.DataFrame:
    """Per scenario: MAE of the milk baseline relative to (a) the same forecasts without an
    outage and (b) persistence under the same outage, on identical periods."""
    if not len(errors):
        return pd.DataFrame()
    pk = ["origin", "grain", "horizon", "period_start"]
    base = errors[(errors["model"] == BASELINE)]
    normal = base[(base["gap_days"] == 0)][pk + ["error"]].rename(columns={"error": "err_normal"})
    pers = errors[errors["model"] == PERSISTENCE][pk + ["gap_days", "resumed_days", "error"]]
    pers = pers.rename(columns={"error": "err_persistence"})
    m = base.merge(normal, on=pk).merge(pers, on=pk + ["gap_days", "resumed_days"])
    m = m.assign(a=m["error"].abs(), an=m["err_normal"].abs(), ap=m["err_persistence"].abs())
    g = m.groupby(["gap_days", "resumed_days", "grain", "horizon"])
    out = pd.DataFrame({"n": g.size(), "mae": g["a"].mean(),
                        "ratio_to_no_outage": g["a"].mean() / g["an"].mean(),
                        "ratio_to_persistence": g["a"].mean() / g["ap"].mean(),
                        "bias": g["error"].mean()})
    return out.reset_index()


def status_table(status: pd.DataFrame) -> pd.DataFrame:
    """Per scenario: forecast dates, how many were forecast / withheld (by reason)."""
    if not len(status):
        return pd.DataFrame()
    t = status.groupby(["gap_days", "resumed_days", "outcome"]).size().unstack(fill_value=0)
    t.insert(0, "origins", t.sum(axis=1))
    return t.reset_index()


def staleness_table(errors: pd.DataFrame, bins=(0, 2, 8, 15, 29, 91, 181, 10_000)) -> pd.DataFrame:
    """Relative error spread of the milk baseline by days since the last trusted day (M4)."""
    b = errors[errors["model"] == BASELINE].copy()
    if not len(b):
        return pd.DataFrame()
    b["stale_band"] = pd.cut(b["staleness_days"], bins=list(bins), right=False)
    b["log_ratio"] = np.log(b["actual"] / b["forecast"]).where((b["actual"] > 0) & (b["forecast"] > 0))
    g = b.groupby(["grain", "horizon", "stale_band"], observed=True)["log_ratio"]
    q = g.quantile([0.05, 0.5, 0.95]).unstack()
    q.columns = ["q05", "q50", "q95"]
    return pd.concat([g.size().rename("n"), g.std().rename("sd"), q], axis=1).reset_index()


# ------------------------------------------------------------------ command (user-run)

def main(argv=None) -> int:
    from .freeze import FROZEN_ENGINE, V11_ENGINE
    from .data import SqlHerdSource

    p = argparse.ArgumentParser(description="Simulated milk-recording outages, development block.")
    p.add_argument("--grain", default="weekly", choices=["weekly", "monthly"],
                   help="weekly origins score weeks and days; monthly origins score months")
    p.add_argument("--preset", default="pfoi-1.1", choices=["pfoi-1.1", "pfoi-1.0"])
    p.add_argument("--k", default="anchor_first", choices=["anchor_first", "anchored"])
    p.add_argument("--anchor-gate", default="off", choices=["on", "off"],
                   help="M3: anchor only on verified days")
    p.add_argument("--gaps", type=int, nargs="+", default=list(GAPS))
    p.add_argument("--resumed", type=int, nargs="+", default=list(RESUMED))
    p.add_argument("--every", type=int, default=1, help="use every n-th origin")
    p.add_argument("--jobs", type=int, default=1, help="0 = CPU cores - 1")
    p.add_argument("--out", default="logs/pfoi")
    args = p.parse_args(argv)

    cfg = V11_ENGINE if args.preset == "pfoi-1.1" else FROZEN_ENGINE
    milk_cfg = MilkConfig(k_mode=args.k, anchor_gate=args.anchor_gate == "on")
    factory = partial(SqlHerdSource.from_env, cell_table=cfg.cell_table,
                      conception_known=cfg.conception_known)
    source = factory()  # user-run only; tests use synthetic sources
    origins = development_origins(args.grain, args.every)
    jobs = resolve_jobs(args.jobs)

    def progress(i, n, o):
        if i % 20 == 0:
            print(f"  origin {i + 1}/{n} ({o})", file=sys.stderr)

    res = run_outage_sim(source, args.grain, cfg, milk_cfg, origins,
                         scenarios(args.gaps, args.resumed), jobs=jobs,
                         source_factory=factory, progress=progress)
    tag = f"{args.preset}_{milk_cfg.tag()}_{args.grain}_every{args.every}"
    out = Path(args.out) / "outage_sim"
    out.mkdir(parents=True, exist_ok=True)
    tables = {"summary": summarise(res.errors), "outage_cost": outage_cost(res.errors),
              "status": status_table(res.status), "staleness": staleness_table(res.errors)}
    for name, table in tables.items():
        table.to_csv(out / f"outage_{name}_{tag}.csv", index=False)
    pd.set_option("display.width", 200)
    print(f"\nSimulated outages, development block ({len(origins)} {args.grain} origins). {LIMIT_NOTE}")
    print("\n=== forecast dates per scenario (forecast / withheld / skipped) ===")
    print(tables["status"].to_string(index=False))
    print("\n=== outage cost: milk baseline MAE vs no outage and vs persistence, same periods ===")
    print(tables["outage_cost"].round(3).to_string(index=False))
    print("\n=== error spread by days since the last trusted milk day (for M4) ===")
    print(tables["staleness"].round(4).to_string(index=False))
    print(f"\nFiles in {out}/ (aggregates only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
