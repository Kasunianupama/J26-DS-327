"""The page document: one frozen-model run in the shape the React page reads (`PfoiRun`
in frontend/src/data/pfoi/contract.ts).

It is built from the same frozen run as the c1_output tables and translated to the
page's vocabulary (grain day/week/month; series milk_litres, total_herd, ...; quality
high/moderate/limited). Everything is herd level. Stored in c1_output.run_document and
served by the backend; until it exists the page shows its labelled demo run.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .attribution import mastitis_rates, without_new_conceptions
from .backtest_herd import summarise
from .backtest_milk import summarise_milk
from .data import DATA_START, add_months, check_before, month_start
from .categories import STATES
from .herd_engine import project
from .outlook import RECONCILED_MODEL, FrozenRun, run_interval_table
from .record_status import record_status
from .periods import period_bounds
from .rates import ENTRY_FROM_STATES, EXIT_TO_STATES

GRAIN = {"daily": "day", "weekly": "week", "monthly": "month"}
PAGE_HORIZONS = {"day": (1, 7, 14), "week": (1, 4, 8, 13), "month": (1, 3, 6, 12)}
# page series -> (daily projection columns, stock?, model and series in the backtest errors)
SERIES = {
    "milk_litres": (("herd_milk",), False, ("milk_baseline", "herd_milk")),
    "milking": (("milking",), True, ("herd_engine", "milking")),
    "dry": (("dry_open", "dry_pregnant"), True, ("herd_engine", "dry_pregnant")),
    "heifers": (("heifers_open", "heifers_pregnant"), True, ("herd_engine", "heifers_pregnant")),
    "calves": (("calves",), True, ("herd_engine", "calves")),
    # bulls and animals of unknown state: part of n_herd, so the five stocks add up to it
    "other": (("bulls", "unknown_state"), True, ("herd_engine", "bulls")),
    "total_herd": (("n_herd",), True, ("herd_engine", "n_herd")),
    "calvings": (("calvings",), False, ("herd_engine", "calvings")),
    "dry_offs": (("dry_offs",), False, ("herd_engine", "dry_offs")),
    "abortions": (("real_abortions",), False, ("herd_engine", "real_abortions")),
    "deaths": (("deaths",), False, ("herd_engine", "deaths")),
    "culls_sales": (("culls", "sales"), False, ("herd_engine", "culls")),
    "entries": (("external_entries",), False, ("herd_engine", "external_entries")),
}
BACKTEST_MODELS = {"milk_baseline": "pfoi", "herd_engine": "pfoi", "persistence": "persistence",
                   "seasonal_naive": "seasonal_naive", "sarima": "sarima"}
BACKTEST_SERIES = {"herd_milk": "milk_litres", "milking": "milking", "n_herd": "total_herd",
                   "calvings": "calvings", "real_abortions": "abortions", "dry_offs": "dry_offs"}
GENERATIONS = ("0", "1", "2", "3+")

# Page groups for herd moves. Moves inside one group (heifer open -> in calf) are not moves.
# "herd" = the group is not recorded; "lost_pregnancy" = the animal stays in its group.
GROUP_OF_STATE = {"calf": "calves", "heifer_open": "heifers", "heifer_pregnant": "heifers",
                  "milking": "milking", "dry_open": "dry", "dry_pregnant": "dry",
                  "bull": "other", "unknown": "other"}
EXIT_GROUP = {"deaths": "died", "culls": "culled_sold", "sales": "culled_sold"}


def _iso(d) -> str:
    return pd.Timestamp(d).date().isoformat()


def _quality(flag: str, grain: str, h: int, has_interval: bool) -> str:
    if flag != "ok" or not has_interval:
        return "limited"
    third = {"day": 7, "week": 4, "month": 3}[grain]
    return "moderate" if h > third else "high"


def _period_value(daily: pd.DataFrame, cols, stock: bool) -> float:
    v = daily[list(cols)].sum(axis=1)
    return float(v.mean() if stock else v.sum())


def _weekly_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build_page_run(source, run: FrozenRun, attribution: pd.DataFrame,
                   backtests: dict[tuple[str, str], pd.DataFrame], core_version: str | None,
                   realised_until: date | None = None, evidence: dict | None = None,
                   interval_errors: pd.DataFrame | None = None) -> dict:
    """``realised_until`` (first day without data, e.g. ``freeze.DATA_END``) adds the recorded
    outcomes of the forecast periods for display and scoring; ``None`` leaves them out."""
    origin = run.origin
    all_errors = pd.concat([e for e in backtests.values() if e is not None and len(e)], ignore_index=True) \
        if any(e is not None and len(e) for e in backtests.values()) else None
    # ``interval_errors``: the errors the outlook tables used, which include the correction
    # layer's own models (e.g. milk_baseline_adaptive); without them those series get no range
    q = run_interval_table(interval_errors if interval_errors is not None else all_errors, run)
    meta = {"model_version": run.version, "core_version": core_version or "unknown"}
    daily = run.daily
    dates = pd.to_datetime(daily["date"]).dt.date

    # mastitis: expected with the reference rate when it is available, else the recent one
    health = check_before(source.health_months(DATA_START, month_start(origin)), origin, "health_months")
    md = check_before(source.exposure(DATA_START, month_start(origin)), origin, "exposure")
    md = md[md["state"] == "milking"].groupby("month")["animal_days"].sum()
    rates = mastitis_rates(health, md, origin)
    recent_rate = rates[0][1] if rates else 0.0
    main_label, main_rate = rates[-1] if rates else ("no rate available", 0.0)

    outlook, corrections = [], []
    horizons = run.horizons()
    for grain_model, grain in GRAIN.items():
        for h in horizons[grain_model]:
            s, e = period_bounds(run.starts[grain_model], grain_model, h)
            part = daily.loc[(dates >= s) & (dates < e)]
            if len(part) != (e - s).days:
                continue
            # pfoi-1.1.1 forecasts every series daily; earlier versions only milk
            series_here = (["milk_litres"] if grain == "day" and not run.reconciled
                           else list(SERIES) + ["mastitis_episodes"])
            for sid in series_here:
                if sid == "mastitis_episodes":
                    cow_days = float(part["milking"].sum())
                    f, lo, hi = cow_days * main_rate, cow_days * min(recent_rate, main_rate), \
                        cow_days * max(recent_rate, main_rate) * 1.25
                    has = True
                else:
                    cols, stock, (model, err_series) = SERIES[sid]
                    if run.milk_withheld and "herd_milk" in cols:  # M1: nothing published
                        continue
                    raw = _period_value(part, cols, stock)
                    # correction layer column by column (identity for 1.0.0); for 1.1.1 the
                    # reconciled path, whose months equal the 1.1.0 corrected months
                    f = sum(run.period_value(grain_model, h, c, stock) for c in cols)
                    if not np.isfinite(f):  # milk withheld (M1): no number is published
                        continue
                    if abs(f - raw) > 1e-9:
                        corrections.append({"target_period": s.isoformat(), "grain": grain, "horizon": h,
                                            "series": sid, "structural": round(raw, 3),
                                            "correction": round(f - raw, 3)})
                    if run.reconciled and grain_model != "monthly":
                        # the reconciled forecast's own errors at monthly forecast dates
                        model, err_series = RECONCILED_MODEL, sid
                    else:
                        model = run.interval_model(err_series, model)
                    sub = q[(q["model"] == model) & (q["grain"] == grain_model) & (q["series"] == err_series)]
                    has = len(sub) > 0
                    if has:
                        above = sub[sub["horizon"] >= h]
                        r = above.sort_values("horizon").iloc[0] if len(above) else sub.sort_values("horizon").iloc[-1]
                        lo, hi = max(0.0, f * (1 + r["q_lo"])), f * (1 + r["q_hi"])
                    else:
                        lo = hi = f
                outlook.append({"origin_date": origin.isoformat(), "target_period": s.isoformat(),
                                "grain": grain, "horizon": h, "series": sid, "forecast": round(f, 3),
                                "lower": round(lo, 3), "upper": round(hi, 3),
                                "quality_flag": _quality(run.flag, grain, h, has), **meta})

    # attribution: milk factors (monthly) and calving split (weekly and monthly)
    attr = []
    milk = attribution[(attribution["series"] == "herd_milk_litres_per_day")
                       & (attribution["factor"] != "actual_change")]
    for r in milk.itertuples(index=False):
        if pd.notna(r.contribution):
            attr.append({"origin_date": origin.isoformat(), "target_period": _iso(r.target_period),
                         "grain": "month", "series": "milk_litres", "factor": r.factor,
                         "contribution": round(float(r.contribution), 3), **meta})
    pipe = project(run.inputs.state, without_new_conceptions(run.rates), run.horizon_days).daily
    split = pd.DataFrame({"date": dates, "total": daily["calvings"].to_numpy(),
                          "determined": pipe["calvings"].to_numpy()})
    split["rate_driven"] = split["total"] - split["determined"]
    for grain_model in ("daily", "weekly", "monthly") if run.reconciled else ("weekly", "monthly"):
        for h in horizons[grain_model]:
            s, e = period_bounds(run.starts[grain_model], grain_model, h)
            part = split[(split["date"] >= s) & (split["date"] < e)]
            if len(part) != (e - s).days:
                continue
            for factor in ("determined", "rate_driven"):
                attr.append({"origin_date": origin.isoformat(), "target_period": s.isoformat(),
                             "grain": GRAIN[grain_model], "series": "calvings", "factor": factor,
                             "contribution": round(float(part[factor].sum()), 3), **meta})

    panel = source.panel_daily(DATA_START, origin)
    actuals = _actuals(source, run, health, panel)
    moves = _moves(source, run, panel)
    # read last, after every forecast above is fixed: the only query dated on/after the origin
    realised = _realised(source, run, outlook, realised_until) if realised_until else []
    return {
        "source": "model",
        **meta,
        "origin_date": origin.isoformat(),
        "data_through": (origin - timedelta(days=1)).isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outlook": outlook,
        # pfoi-1.1.0: correction layer on top of the structural forecast that the
        # attribution explains (forecast = structural + correction); empty for pfoi-1.0.0
        "corrections": corrections,
        "attribution": attr,
        "actuals": actuals,
        "realised": realised,
        "realised_through": (realised_until - timedelta(days=1)).isoformat() if realised_until else None,
        "moves": moves,
        "replay": _replay(backtests, origin, meta),
        "revisions": [],
        "backtest": _backtest_rows(backtests),
        "qualityBands": _quality_bands(backtests),
        "generations": _generations(source, run),
        "fertility": _fertility(source),
        "coverage": _coverage(source, origin),
        "mastitis_rate_period": main_label,
        # PP1 development keys (docs/pp1_plan.md M1/M4; PFOI_OUTLOOK_CHANGES.md). Optional:
        # older documents lack them and the page shows "not available for this run".
        "record_status": record_status(run.hist.target_before(origin), panel, origin,
                                       run.milk_withheld),
        "withheld": _withheld(run),
        "interval_method": _interval_method(run),
        # only PP1 development builds (evidence given); frozen documents are unchanged
        **(_pp1_sections(source, origin, evidence, outlook) if evidence is not None else {}),
    }


def _records(frame) -> list[dict]:
    """JSON-safe records of an aggregate table (NaN -> None)."""
    if frame is None or not len(frame):
        return []
    f = frame.copy()
    for c in f.columns:
        if pd.api.types.is_datetime64_any_dtype(f[c]):
            f[c] = f[c].dt.date.astype(str)
    f = f.astype(object).where(pd.notna(f), None)
    out = []
    for r in f.to_dict("records"):
        out.append({k: (round(v, 4) if isinstance(v, float) else
                        (v.isoformat() if isinstance(v, date) else v)) for k, v in r.items()})
    return out


SCENARIO_SERIES = {"herd_milk": "milk_litres", "milking": "milking", "n_herd": "total_herd"}


def _scenarios(outlook_rows: list[dict], summary: pd.DataFrame | None) -> list[dict]:
    """1c: monthly forecasts of milk, milking cows and total herd under "like last time"
    scenarios (median response after earlier episodes of each kind, with its range and the
    number of episodes). What happened before, not a forecast that it will happen."""
    from .scenarios import KIND_LABELS, apply_scenario, narrative

    if summary is None or not len(summary) or not outlook_rows:
        return []
    o = pd.DataFrame(outlook_rows)
    o = o[o["grain"] == "month"]
    rows = []
    for model_series, page_series in SCENARIO_SERIES.items():
        ss = summary[summary["series"] == model_series] if "series" in summary else summary
        base = o[o["series"] == page_series]
        if not len(ss) or not len(base):
            continue
        base = base.assign(grain="monthly")[["grain", "horizon", "target_period", "forecast"]]
        for kind in ss["kind"].unique():
            res = apply_scenario(base, ss.drop(columns=["series"], errors="ignore"), kind)
            res = res[res["median"].notna()]
            sentence = narrative(ss, kind, "monthly", 3, series_label={
                "herd_milk": "herd milk", "milking": "milking cows", "n_herd": "total herd"}[model_series])
            for r in res.itertuples(index=False):
                rows.append({"kind": kind, "label": KIND_LABELS.get(kind, kind), "series": page_series,
                             "target_period": r.target_period, "horizon": int(r.horizon),
                             "forecast": round(float(r.forecast), 3),
                             "scenario": round(float(r.scenario_forecast), 3),
                             "low": round(float(r.scenario_low), 3), "high": round(float(r.scenario_high), 3),
                             "n_episodes": int(r.n), "sentence": sentence})
    return rows


def _pp1_sections(source, origin: date, evidence: dict, outlook_rows: list[dict] | None = None) -> dict:
    """PP1 development sections (docs/pp1_frontend_plan.md F3-F8). Each is optional: a source
    without the loader, or a missing evidence file, gives an empty section, which the page
    shows as "not available for this run". All are herd-level aggregates."""
    out = {}
    if hasattr(source, "repro_steps"):  # F5, M7
        from .repro_timing import repro_table
        steps = source.repro_steps(origin)
        out["repro_timing"] = _records(repro_table(steps, ("period",)))
    if all(hasattr(source, m) for m in ("generation_yield", "generation_days", "repro_steps")):  # F6, M8
        from .generation_outcomes import generation_outcomes
        alarms = source.generation_alarms(origin) if hasattr(source, "generation_alarms") else None
        out["generation_outcomes"] = _records(generation_outcomes(
            source.generation_yield(origin), source.generation_days(origin),
            source.repro_steps(origin), alarms))
    if hasattr(source, "driver_daily"):  # F4, M5
        from .drivers import heat_outlook
        out["heat"] = heat_outlook(source.driver_daily(DATA_START, origin), origin)
    out["scenarios"] = _scenarios(outlook_rows or [], evidence.get("scenarios"))  # 1c
    out["outage_simulation"] = _records(evidence.get("outage"))   # F3, M2
    out["evidence_ladder"] = _records(evidence.get("ladder"))     # F7
    out["feature_registry"] = _records(evidence.get("registry"))  # F8, M6
    return out


def _withheld(run: FrozenRun) -> list[dict]:
    """Series and periods with no published forecast, and why (M1)."""
    if not run.milk_withheld:
        return []
    out = []
    for grain_model, hs in run.horizons().items():
        if not hs:
            continue
        s, _ = period_bounds(run.starts[grain_model], grain_model, min(hs))
        _, e = period_bounds(run.starts[grain_model], grain_model, max(hs))
        out.append({"series": "milk_litres", "grain": GRAIN[grain_model], "from": s.isoformat(),
                    "to": e.isoformat(), "reason": run.milk_withheld})
    return out


def _interval_method(run: FrozenRun) -> dict:
    opts = run.interval_opts or {}
    scale = opts.get("scale")
    stale = opts.get("stale_days")
    return {"milk": "aci_quality_band" if opts.get("aci") else "empirical_quantiles",
            "staleness_scale": getattr(scale, "source", "not used"),
            "staleness_days": None if stale is None or not np.isfinite(stale) else float(stale)}


KEY_OF = {"day": lambda d: d, "week": _weekly_start, "month": lambda d: d.replace(day=1)}


def _n_days(k: date, grain: str) -> int:
    return (add_months(k, 1) - k).days if grain == "month" else {"day": 1, "week": 7}[grain]


def _milk_rows(t: pd.DataFrame, grain: str, start: date, end: date) -> list[dict]:
    """Herd milk per period in [start, end): litres per period, scoreable only when the period
    comes from one source and enough of its days are scoreable (80 % for a month, all otherwise)."""
    out = []
    part = t[(t["date"] >= start) & (t["date"] < end)].copy()
    part["k"] = [KEY_OF[grain](d) for d in part["date"]]
    for k, g in part.groupby("k"):
        n_days = _n_days(k, grain)
        share = g["ok"].sum() / n_days
        srcs = g.loc[g["ok"], "target_source"].unique()
        ok_period = (share >= (0.8 if grain == "month" else 1.0)) and len(srcs) == 1
        value = float(g.loc[g["ok"], "target_litres"].sum() / g["ok"].sum() * n_days) if ok_period else None
        out.append({"period": k.isoformat(), "grain": grain, "series": "milk_litres", "value": value,
                    "source": str(srcs[0]) if len(srcs) == 1 else None, "scoreable": bool(ok_period)})
    return out


def _herd_rows(panel: pd.DataFrame, grain: str, start: date, end: date) -> list[dict]:
    """Herd stocks (daily averages) and events (sums) per period in [start, end)."""
    out = []
    part = panel[(panel["date"] >= start) & (panel["date"] < end)].copy()
    part["k"] = [KEY_OF[grain](d) for d in part["date"]]
    for k, g in part.groupby("k"):
        for sid, (cols, stock, _) in SERIES.items():
            if sid == "milk_litres":
                continue
            out.append({"period": k.isoformat(), "grain": grain, "series": sid,
                        "value": round(_period_value(g, cols, stock), 3), "source": None,
                        "scoreable": True})
    return out


def _with_ok(t: pd.DataFrame) -> pd.DataFrame:
    t = t.copy()
    t["date"] = pd.to_datetime(t["date"]).dt.date
    t["ok"] = t["is_scoreable"].fillna(False).astype(bool) & t["target_litres"].notna()
    return t


def _actuals(source, run: FrozenRun, health: pd.DataFrame, panel: pd.DataFrame) -> list[dict]:
    origin = run.origin
    t = _with_ok(run.hist.target_before(origin))
    week_end = run.starts["weekly"]
    # history the page can show: every recorded day, week and month since 2015-08
    windows = {"day": (DATA_START, origin),
               "week": (DATA_START + timedelta(days=-DATA_START.weekday() % 7), week_end),  # first full week
               "month": (DATA_START, month_start(origin))}
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.date
    out = []
    for grain, (start, end) in windows.items():
        out += _milk_rows(t, grain, start, end)
    for grain, (start, end) in windows.items():
        out += _herd_rows(panel, grain, start, end)
    for r in health.itertuples(index=False):
        m = pd.Timestamp(r.month).date()
        if m >= windows["month"][0]:
            out.append({"period": m.isoformat(), "grain": "month", "series": "mastitis_episodes",
                        "value": float(r.mastitis_episodes), "source": None, "scoreable": True})
    return out


def _realised(source, run: FrozenRun, outlook: list[dict], until: date) -> list[dict]:
    """What was recorded in the forecast periods, for display and scoring only (never a model
    input: it is read after every forecast is built). Same shape and rules as ``actuals``; only
    periods that are forecast and end on or before ``until`` (first day without data) appear."""
    origin = run.origin
    targets = {(r["grain"], r["series"], r["target_period"]) for r in outlook}
    periods = {(g, p) for g, _, p in targets}
    if not periods:
        return []
    starts = {g: min(date.fromisoformat(p) for gg, p in periods if gg == g) for g, _ in periods}
    ends = {g: min(until, max(date.fromisoformat(p) + timedelta(days=_n_days(date.fromisoformat(p), g))
                              for gg, p in periods if gg == g)) for g, _ in periods}
    stop = max(ends.values())
    if stop <= origin:
        return []
    t = _with_ok(source.target_daily(origin, stop))
    panel = source.panel_daily(origin, stop).copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.date
    health = source.health_months(month_start(origin), stop)
    rows = []
    for g in starts:
        rows += _milk_rows(t, g, starts[g], ends[g])
        rows += _herd_rows(panel, g, starts[g], ends[g])  # kept only where forecast (below)
    for r in health.itertuples(index=False):
        rows.append({"period": pd.Timestamp(r.month).date().isoformat(), "grain": "month",
                     "series": "mastitis_episodes", "value": float(r.mastitis_episodes),
                     "source": None, "scoreable": True})

    def complete(r) -> bool:
        k = date.fromisoformat(r["period"])
        return k >= origin and k + timedelta(days=_n_days(k, r["grain"])) <= until

    return [r for r in rows if (r["grain"], r["series"], r["period"]) in targets and complete(r)]


def _engine_moves(part: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Moves between page groups over a slice of projected days, from the engine's flows."""
    col = lambda name: float(part[name].sum()) if name in part.columns else 0.0  # noqa: E731
    out: dict[tuple[str, str], float] = {
        ("born", "calves"): col("flow|calf|births"),          # live calves kept
        ("calves", "heifers"): col("flow|heifer_open|to_heifer"),
        ("calves", "other"): col("flow|bull|to_bull"),
        ("heifers", "milking"): -col("flow|heifer_pregnant|calving"),  # first calvings
        ("dry", "milking"): -col("flow|dry_pregnant|calving"),         # calving again
        ("milking", "dry"): -col("flow|milking|dry_off"),
    }
    # pregnancies lost: the animal stays in its group (heifers and dry cows from the
    # engine's flows; milking cows are the rest of the engine's real abortions)
    heifer_lost = -col("flow|heifer_pregnant|abortion") - col("flow|heifer_pregnant|pregnancy_loss")
    dry_lost = -col("flow|dry_pregnant|abortion") - col("flow|dry_pregnant|pregnancy_loss")
    out[("heifers", "lost_pregnancy")] = heifer_lost
    out[("dry", "lost_pregnancy")] = dry_lost
    out[("milking", "lost_pregnancy")] = max(
        0.0, col("real_abortions") + col("flow|heifer_pregnant|abortion") + col("flow|dry_pregnant|abortion"))
    for state in STATES:
        g = GROUP_OF_STATE[state]
        for kind, sink in EXIT_GROUP.items():
            out[(g, sink)] = out.get((g, sink), 0.0) - col(f"flow|{state}|{kind}")
        out[("arrived", g)] = out.get(("arrived", g), 0.0) + col(f"flow|{state}|entries")
    return out


def _moves(source, run: FrozenRun, panel: pd.DataFrame) -> list[dict]:
    """Moves between herd groups per period.

    Recorded by month: state transitions (incl. pregnant -> open as pregnancies lost for
    heifers and dry cows) and births. Recorded by day and week: dated moves from the
    lactation, calf and animal records; arrivals and pregnancies lost are herd totals there
    (group "herd"), because their group is not dated. Forecast by week and month (and by
    day for pfoi-1.1.1): the herd engine's structural flows."""
    origin = run.origin
    rows: list[dict] = []

    def emit(period: date, grain: str, moved: dict[tuple[str, str], float], forecast: bool) -> None:
        for (frm, to), v in sorted(moved.items()):
            if v > 1e-6:
                rows.append({"period": period.isoformat(), "grain": grain, "from": frm, "to": to,
                             "value": round(float(v), 3), "forecast": forecast})

    tr = check_before(source.transitions(DATA_START, month_start(origin)), origin, "transitions")
    by_month: dict[date, dict[tuple[str, str], float]] = {}
    for r in tr.itertuples(index=False):
        m = month_start(pd.Timestamp(r.month).date())
        if r.from_state in ENTRY_FROM_STATES:
            key = ("arrived", GROUP_OF_STATE.get(r.to_state))
        elif (r.from_state, r.to_state) in (("heifer_pregnant", "heifer_open"), ("dry_pregnant", "dry_open")):
            key = (GROUP_OF_STATE[r.from_state], "lost_pregnancy")
        elif r.to_state in EXIT_TO_STATES:
            key = (GROUP_OF_STATE.get(r.from_state), EXIT_GROUP[EXIT_TO_STATES[r.to_state]])
        else:
            key = (GROUP_OF_STATE.get(r.from_state), GROUP_OF_STATE.get(r.to_state))
        if None in key or key[0] == key[1]:
            continue
        acc = by_month.setdefault(m, {})
        acc[key] = acc.get(key, 0.0) + float(r.n_moved)
    if "births" in panel.columns and len(panel):
        b = panel.assign(m=[month_start(pd.Timestamp(d).date()) for d in panel["date"]]).groupby("m")["births"].sum()
        for m, v in b.items():
            if m < month_start(origin):
                acc = by_month.setdefault(m, {})
                acc[("born", "calves")] = float(v)
    for m, moved in sorted(by_month.items()):
        emit(m, "month", moved, False)

    # recorded days and weeks, from dated records
    dm = check_before(source.daily_moves(DATA_START, origin), origin, "daily_moves")
    if len(dm):
        dm = dm.assign(date=[pd.Timestamp(d).date() for d in dm["date"]])
        exits = dm["to_group"].isin(list(EXIT_TO_STATES))
        dm.loc[exits, "to_group"] = [EXIT_GROUP[EXIT_TO_STATES[t]] for t in dm.loc[exits, "to_group"]]
        dm = dm[dm["to_group"].isin(["milking", "dry", "calves", "heifers", "other", "died", "culled_sold"])]
    pd_ = panel.assign(date=[pd.Timestamp(d).date() for d in panel["date"]])
    herd = []
    for col_, frm, to in (("external_entries", "arrived", "herd"), ("real_abortions", "herd", "lost_pregnancy")):
        if col_ in pd_.columns:
            herd.append(pd.DataFrame({"date": pd_["date"], "from_group": frm, "to_group": to, "n": pd_[col_].astype(float)}))
    dated = pd.concat([dm[["date", "from_group", "to_group", "n"]]] + herd, ignore_index=True) if len(dm) or herd else dm
    week_end = run.starts["weekly"]
    for grain, keyf, end in (("day", lambda d: d, origin), ("week", _weekly_start, week_end)):
        part = dated[dated["date"] < end]
        if not len(part):
            continue
        part = part.assign(k=[keyf(d) for d in part["date"]])
        for k, g in part.groupby("k"):
            emit(k, grain, {(a, b): float(v) for (a, b), v in g.groupby(["from_group", "to_group"])["n"].sum().items()}, False)

    daily = run.daily
    dates = pd.to_datetime(daily["date"]).dt.date
    horizons = run.horizons()
    for grain_model in ("daily", "weekly", "monthly") if run.reconciled else ("weekly", "monthly"):
        for h in horizons[grain_model]:
            s, e = period_bounds(run.starts[grain_model], grain_model, h)
            part = daily.loc[(dates >= s) & (dates < e)]
            if len(part) != (e - s).days:
                continue
            emit(s, GRAIN[grain_model], _engine_moves(part), True)
    return rows


def _errors(backtests, kind: str, grain: str) -> pd.DataFrame | None:
    for block in ("test", "development"):
        e = backtests.get((kind, block))
        if e is not None and len(e):
            e = e[e["grain"] == grain]
            if len(e):
                return e
    return None


def _replay(backtests, origin: date, meta: dict) -> list[dict]:
    e = _errors(backtests, "milk", "monthly")
    if e is None:
        return []
    e = e[e["model"] == "milk_baseline"].copy()
    e["o"] = pd.to_datetime(e["origin"]).dt.date
    keep = sorted(o for o in e["o"].unique() if add_months(month_start(origin), -12) <= o < origin)
    rows = []
    for r in e[e["o"].isin(keep)].itertuples(index=False):
        f = float(r.forecast)
        lo = float(r.lower) if pd.notna(getattr(r, "lower", np.nan)) else f
        hi = float(r.upper) if pd.notna(getattr(r, "upper", np.nan)) else f
        rows.append({"origin_date": _iso(r.origin), "target_period": _iso(r.period_start), "grain": "month",
                     "horizon": int(r.horizon), "series": "milk_litres", "forecast": f, "lower": lo,
                     "upper": hi, "quality_flag": "limited" if str(getattr(r, "flags", "") or "") else "high",
                     **meta})
    return rows


def _backtest_rows(backtests) -> list[dict]:
    """Scores per block x model x grain x horizon x series. With pfoi-1.1.1 path errors
    (kind "path"), the model's day and week scores are those of the reconciled forecast that
    is published (monthly forecast dates, every scored horizon up to 12 months)."""
    rows = []
    path_blocks = {block for (kind, block), e in backtests.items()
                   if kind == "path" and e is not None and len(e)}
    for (kind, block), e in backtests.items():
        if e is None or not len(e):
            continue
        if kind == "path":
            rows += _path_backtest_rows(e, block)
            continue
        if block in path_blocks:  # day/week model scores come from the reconciled path
            e = e[~((e["grain"].isin(["daily", "weekly"])) & e["model"].isin(["milk_baseline", "herd_engine"]))]
        if kind == "milk":
            s = summarise_milk(e)
            s["series"] = "herd_milk"
            cov = s["coverage_pct"] / 100.0
        else:
            s = summarise(e)
            cov = pd.Series(np.nan, index=s.index)
        s = s.assign(cov=cov)
        for r in s.itertuples(index=False):
            grain = GRAIN.get(r.grain)
            if (r.model not in BACKTEST_MODELS or r.series not in BACKTEST_SERIES or grain is None
                    or int(r.horizon) not in PAGE_HORIZONS[grain]):
                continue
            rows.append({"block": block, "model": BACKTEST_MODELS[r.model], "grain": grain,
                         "horizon": int(r.horizon), "series": BACKTEST_SERIES[r.series],
                         "mae": float(r.mae), "rmse": float(r.rmse), "bias": float(r.bias),
                         "coverage": None if pd.isna(r.cov) else float(r.cov), "n_origins": int(r.n)})
    return rows


def _path_backtest_rows(e: pd.DataFrame, block: str) -> list[dict]:
    e = e[(e["model"] == RECONCILED_MODEL) & e["series"].isin(list(BACKTEST_SERIES.values()))]
    rows = []
    for (g, h, sid), x in e.groupby(["grain", "horizon", "series"]):
        cov = x["covered"].dropna() if "covered" in x else pd.Series(dtype=float)
        rows.append({"block": block, "model": "pfoi", "grain": GRAIN[g], "horizon": int(h), "series": sid,
                     "mae": float(x["error"].abs().mean()), "rmse": float(np.sqrt((x["error"] ** 2).mean())),
                     "bias": float(x["error"].mean()),
                     "coverage": float(cov.astype(float).mean()) if len(cov) else None,
                     "n_origins": int(len(x))})
    return rows


def _quality_bands(backtests) -> list[dict]:
    e = _errors(backtests, "milk", "monthly")
    if e is None:
        return []
    e = e[e["model"] == "milk_baseline"].copy()
    flags = e.get("flags", pd.Series("", index=e.index)).fillna("").astype(str)
    e["band"] = np.where(flags != "", "limited", np.where(e["horizon"] >= 6, "moderate", "high"))
    rows = []
    for band in ("high", "moderate", "limited"):
        g = e[e["band"] == band]
        if not len(g):
            continue
        rows.append({"band": band, "mae_pct": float(100 * (g["error"].abs() / g["actual"]).mean()),
                     "coverage": float(g["covered"].mean()) if g["covered"].notna().any() else 0.0,
                     "n_periods": int(len(g))})
    return rows


def _generations(source, run: FrozenRun) -> list[dict]:
    origin = run.origin
    rows = []
    exp = check_before(source.exposure(add_months(month_start(origin), -24), month_start(origin)),
                       origin, "exposure")
    cows = exp[exp["state"].isin(["milking", "dry_open", "dry_pregnant"])
               & exp["generation_group"].isin(GENERATIONS)]
    for m, g in cows.groupby("month"):
        tot = g["animal_days"].sum()
        for gen, gg in g.groupby("generation_group"):
            rows.append({"period": _iso(m), "generation": gen, "share": float(gg["animal_days"].sum() / tot),
                         "projected": False})
    proj = project(run.inputs.state, run.rates, (add_months(origin, 12) - origin).days, record_cells=True)
    c = proj.cells[proj.cells["state"].isin(["milking", "dry_open", "dry_pregnant"])
                   & proj.cells["generation_group"].isin(GENERATIONS)].copy()
    c["month"] = [d.replace(day=1) for d in pd.to_datetime(c["date"]).dt.date]
    for m, g in c.groupby("month"):
        tot = g["n"].sum()
        for gen, gg in g.groupby("generation_group"):
            rows.append({"period": m.isoformat(), "generation": gen, "share": float(gg["n"].sum() / tot),
                         "projected": True})
    return rows


def _fertility(source) -> list[dict]:
    f = source.generation_fertility()
    f = f[f["generation_group"].isin(GENERATIONS)]
    return [{"period_label": str(r.calving_period), "generation": str(r.generation_group),
             "services_per_conception": float(r.services_per_conception or 0),
             "abortion_pct": float(r.pct_aborted or 0)} for r in f.itertuples(index=False)]


def _coverage(source, origin: date) -> list[dict]:
    c = check_before(source.data_coverage(origin), origin, "data_coverage")
    return [{"year": int(r.year), "reliable_cow_days": int(r.reliable_cow_days),
             "milk_days_scoreable_pct": float(r.milk_days_scoreable_pct),
             "weather_complete_pct": float(r.weather_complete_pct),
             "health_records": int(r.health_records)} for r in c.itertuples(index=False)]
