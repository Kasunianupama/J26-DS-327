"""Preview the persistence blend on built outlook documents, offline (no database, no writes to it).

``build-outlook`` writes one page document per forecast date (``logs/pfoi/outlook/<version>/run_YYYYMM.json``).
This derives a sibling version, ``<version>-blend``, from those documents:

* the daily and weekly **milk** forecasts become a weighted mix of the structural forecast and its partners
  (``blend.py``): weekly = structural + persistence, daily = structural + persistence + ETS (a damped-trend
  fit to the last recorded days, which is what lets the daily line follow recent movement). Everything else
  in the document (monthly milk, herd series, attribution, record status) is unchanged;
* each weight is proportional to 1 / MAE of that model's backtest forecasts whose target period had
  **ended by the forecast date** (``blend.skill_weights_at``); horizons between the scored ones (weekly
  1/4/8/13, daily 1/7/14) are interpolated; a partner with no forecast at this date is left out;
* persistence is the last complete scoreable week of the document's own recorded history (the daily value
  is that week's mean per day, as in the backtest benchmark); ETS is refitted on the document's daily
  history exactly as the backtest benchmark does (last 120 days, unbroken run, damped additive trend);
* the 5-95 % range is the wider of (a) the document's own range shifted to the blend and (b) the blend's
  own past-error range, so the blend never claims a tighter range than the quality-aware one it came from;
* ``correction`` rows are updated so that structural + correction still equals the shown forecast, and a
  ``blend`` key lists every weight, persistence value and n for audit.

Compare it with the other versions using ``compare-runs ... --also <version>-blend``. Nothing here reaches
``c1_output``; publishing a blended version is a separate decision (see docs/pp1_plan.md, M10).
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .adaptive import AdaptiveConfig, adaptive_corrected
from .benchmarks import ets_forecast
from .blend import interval_quantiles_at, skill_blend, skill_weights_at

GRAINS = {"week": "weekly", "day": "daily"}
PARTNERS = {"weekly": ("persistence",), "daily": ("persistence", "ets")}   # who each grain is mixed with
ETS_DAYS = 120                                                              # as in the backtest benchmark
SERIES = "milk_litres"
BACKTEST_SERIES = "herd_milk"
DEFAULT_TAG = "herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6"
ADAPTIVE = AdaptiveConfig(pooled=False, q30=0.1, tau_days=365.0)  # the pfoi-1.1.0 milk correction layer
INTERVAL_NOTE = ("blend: wider of the document's range shifted to the blend and the blend's own past-error "
                 "5-95 % range")


def load_backtest(folder, tag: str = DEFAULT_TAG) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(adaptive + persistence + ETS rows, blended rows) from the saved raw development and post-hoc errors.

    The adaptive layer is rebuilt from raw errors with past errors only, which reproduces the saved
    development file exactly; the blend weights are likewise past-only. Callers cut at the forecast date."""
    folder = Path(folder)
    parts = []
    for suffix in ("", "_posthoc"):
        for g in ("monthly", "weekly"):
            path = folder / f"milk_backtest_errors_{g}_{tag}{suffix}.csv"
            if path.exists():
                parts.append(pd.read_csv(path))
    if not parts:
        raise FileNotFoundError(f"no raw milk backtest errors for tag {tag!r} in {folder}")
    raw = pd.concat(parts, ignore_index=True)
    for c in ("origin", "period_start", "period_end"):
        raw[c] = pd.to_datetime(raw[c], format="mixed")
    adaptive = adaptive_corrected(raw, "milk_baseline", cfg=ADAPTIVE)
    frame = pd.concat([adaptive, raw[raw["model"].isin(["persistence", "ets"])]], ignore_index=True)
    blended = pd.concat([skill_blend(frame, base_model="milk_baseline_adaptive", partners=PARTNERS[g], grains=(g,))
                         for g in ("weekly", "daily")], ignore_index=True)
    return frame, blended


def _by_horizon(table: pd.DataFrame, col: str, horizons: np.ndarray) -> np.ndarray | None:
    """Interpolate a per-horizon column onto ``horizons`` (held constant beyond the scored ones)."""
    if not len(table):
        return None
    return np.interp(horizons, table["horizon"].to_numpy(float), table[col].to_numpy(float))


def last_complete_week(doc: dict, origin: date) -> tuple[date, float] | None:
    """(week start, litres) of the last scoreable week that had ended by the forecast date."""
    a = pd.DataFrame(doc.get("actuals", []))
    if not len(a):
        return None
    a = a[(a["series"] == SERIES) & (a["grain"] == "week") & a["scoreable"].astype(bool) & a["value"].notna()]
    if not len(a):
        return None
    a = a.assign(period=pd.to_datetime(a["period"]).dt.date)
    a = a[a["period"] + timedelta(days=7) <= origin].sort_values("period")
    return None if not len(a) else (a["period"].iloc[-1], float(a["value"].iloc[-1]))


def ets_from_document(doc: dict, origin: date, steps: int = 14) -> np.ndarray | None:
    """Daily ETS forecast (litres per day, ``steps`` days from the forecast date) refitted on the
    document's own recorded daily milk, as the backtest benchmark does; None if it cannot be fitted."""
    a = pd.DataFrame(doc.get("actuals", []))
    if not len(a):
        return None
    a = a[(a["series"] == SERIES) & (a["grain"] == "day")]
    a = a.assign(period=pd.to_datetime(a["period"]).dt.date)
    a = a[a["period"] < origin].sort_values("period")
    if not len(a):
        return None
    v = a["value"].where(a["scoreable"].astype(bool))
    series = pd.Series(v.to_numpy(dtype=float), index=pd.to_datetime(a["period"]))
    return ets_forecast(series.iloc[-400:].iloc[-ETS_DAYS:], steps, None)


def blend_document(doc: dict, frame: pd.DataFrame, blend_rows: pd.DataFrame, min_obs: int = 8) -> dict:
    """A copy of ``doc`` with the daily and weekly milk forecasts blended; see the module docstring."""
    out = copy.deepcopy(doc)
    origin = date.fromisoformat(str(doc["origin_date"])[:10])
    week = last_complete_week(doc, origin)
    audit = {"rule": "weights proportional to 1 / past MAE of finished forecasts, over the structural "
                     "forecast and its partners (weekly: persistence; daily: persistence and ETS)",
             "interval": INTERVAL_NOTE, "grains": {}}
    outlook = out.get("outlook", [])
    corrections = out.get("corrections", [])
    if week is None or doc.get("withheld"):
        audit["skipped"] = "no complete scoreable week of recorded milk before the forecast date, or milk withheld"
    else:
        for grain, bt_grain in GRAINS.items():
            rows = [r for r in outlook if r["series"] == SERIES and r["grain"] == grain]
            if not rows:
                continue
            horizons = np.array([r["horizon"] for r in rows], dtype=float)
            pers = week[1] if grain == "week" else week[1] / 7.0
            ets = ets_from_document(doc, origin, int(horizons.max())) if "ets" in PARTNERS[bt_grain] else None
            have = tuple(p for p in PARTNERS[bt_grain] if p != "ets" or ets is not None)
            wt = skill_weights_at(frame, origin, bt_grain, BACKTEST_SERIES, partners=PARTNERS[bt_grain],
                                  available=have, min_obs=min_obs)
            base_name = "milk_baseline_adaptive"
            w_by = {n: (_by_horizon(wt, f"w_{n}", horizons) if len(wt) else None)
                    for n in (base_name, *PARTNERS[bt_grain])}
            if w_by[base_name] is None:
                w_by = {n: np.full(len(rows), 1.0 if n == base_name else 0.0) for n in w_by}
            q = interval_quantiles_at(blend_rows, origin, bt_grain, BACKTEST_SERIES)
            ql, qh = _by_horizon(q, "q_low", horizons), _by_horizon(q, "q_high", horizons)
            corr = {(c["grain"], c["horizon"]): c for c in corrections if c["series"] == SERIES}
            detail = []
            for i, r in enumerate(rows):
                f = float(r["forecast"])
                partner_value = {"persistence": pers,
                                 "ets": float(ets[int(r["horizon"]) - 1]) if ets is not None else None}
                tot = w_by[base_name][i] + sum(w_by[n][i] for n in PARTNERS[bt_grain] if partner_value[n] is not None)
                fb = (w_by[base_name][i] * f + sum(w_by[n][i] * partner_value[n]
                      for n in PARTNERS[bt_grain] if partner_value[n] is not None)) / tot
                w = float(w_by[base_name][i] / tot)
                lo = (r["lower"] + (fb - f)) if r.get("lower") is not None else None
                hi = (r["upper"] + (fb - f)) if r.get("upper") is not None else None
                if ql is not None and lo is not None:
                    lo, hi = min(lo, fb * (1 + ql[i])), max(hi, fb * (1 + qh[i]))
                r["forecast"] = fb
                if lo is not None:
                    r["lower"], r["upper"] = float(lo), float(hi)
                c = corr.get((grain, r["horizon"]))
                if c is not None:
                    c["correction"] = fb - float(c["structural"])
                detail.append({"horizon": r["horizon"], "target_period": r["target_period"], "weight": w,
                               "weights": {n: float(w_by[n][i] / tot) for n in w_by
                                           if n == base_name or partner_value.get(n) is not None},
                               "persistence": pers, "ets": partner_value["ets"],
                               "previous_forecast": f, "blended_forecast": fb})
            audit["grains"][grain] = {
                "partners": list(have), "persistence": pers, "persistence_week": week[0].isoformat(),
                "scored_horizons": wt.to_dict("records"), "rows": detail}
    version = str(doc.get("model_version", "")) + "+blend"
    out["model_version"] = version
    for r in outlook:
        r["model_version"] = version
    out["blend"] = audit
    im = dict(out.get("interval_method") or {})
    im["blend"] = INTERVAL_NOTE
    out["interval_method"] = im
    return out


def run(out_dir, source_version: str, origins: list[str] | None, tag: str = DEFAULT_TAG,
        min_obs: int = 8) -> int:
    """Derive ``<source_version>-blend`` documents; prints the weights, writes only JSON files."""
    out_dir = Path(out_dir)
    src = out_dir / "outlook" / source_version
    dst = out_dir / "outlook" / f"{source_version}-blend"
    files = sorted(src.glob("run_*.json"))
    if origins:
        wanted = {date.fromisoformat(o).strftime("%Y%m") for o in origins}
        files = [f for f in files if f.stem.split("_")[1] in wanted]
    if not files:
        print(f"no run_*.json for {source_version} in {src} (run build-outlook first)")
        return 1
    frame, blend_rows = load_backtest(out_dir, tag)
    dst.mkdir(parents=True, exist_ok=True)
    print(f"{source_version} -> {dst.name}: weight on the structural forecast (1 = unchanged), by forecast "
          "date; weekly 1/4/8/13 weeks ahead | daily 1/7/14 days ahead")

    def weights(g: dict, grain: str, hs: tuple[int, ...]) -> str:
        rows = {r["horizon"]: r["weight"] for r in g.get(grain, {}).get("rows", [])}
        return " ".join(f"{rows[h]:.2f}" if h in rows else "  - " for h in hs)

    for f in files:
        doc = json.loads(f.read_text())
        new = blend_document(doc, frame, blend_rows, min_obs=min_obs)
        (dst / f.name).write_text(json.dumps(new))
        g = new["blend"].get("grains", {})
        print(f"  {str(doc['origin_date'])[:10]}  week: {weights(g, 'week', (1, 4, 8, 13))}  | "
              f"day: {weights(g, 'day', (1, 7, 14))}  {new['blend'].get('skipped', '')}")
    print(f"\nWrote {len(files)} documents to {dst} (files only; nothing was written to the database).")
    return 0
