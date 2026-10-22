"""pfoi-1.2.1-dev page documents for ``compare-runs`` (files only; nothing reaches ``c1_output``).

Derived from the built ``pfoi-1.2.0-dev`` documents (``logs/pfoi/outlook/<version>/run_YYYYMM.json``),
like ``blend-outlook`` and ``neural-outlook``. Every forecast is copied **unchanged**; 1.2.1-dev only
adds how sure each one is (``gate_intervals.py``):

* ``p_gate``: probability of a miss beyond +-10 % from the stability gate (logistic, G1 settings) fitted
  on milk labels whose period had ended by the forecast date, with its signals computed from days and
  finished errors before that date; ``confidence`` = ``low`` above 0.5, else ``normal``. Herd rows get
  the mean of the milk rows' probabilities of the same grain (flag only, their range is unchanged).
* milk range (5-95 %): conformal quantiles of 1.2.0-dev's own log errors finished by the forecast date,
  same grain, the nearest scored horizon at or above the row's, **only from past forecasts with the same
  flag** (each past forecast flagged by the gate fitted before its own year); at least 19 such errors,
  else all past errors of that cell; with fewer than 19 in all, the document's own range is kept.
* a ``gate`` key records the rule, threshold and calibration sizes for audit.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .gate import (GateConfig, GateFeatures, LOGISTIC_DEFAULT, fit_predict_gate, forward_gate, label_rows)
from .gate_intervals import FLAG_THRESHOLD, MIN_CAL, VERSION
from .outlook import period_starts
from .periods import period_bounds

SERIES = "milk_litres"
GRAIN_MODEL = {"day": "daily", "week": "weekly", "month": "monthly"}
SCORED = {"daily": (1, 7, 14), "weekly": (1, 4, 8, 13), "monthly": (1, 3, 6, 12)}
LEVEL = 0.9
RULE = ("gate p > 0.5 = low confidence; milk 5-95 % range from 1.2.0-dev's own past log errors with the "
        "same confidence (conformal, at least 19), else all past errors of that grain and horizon")


def period_end(start: date, grain: str) -> date:
    if grain == "day":
        return start + timedelta(days=1)
    if grain == "week":
        return start + timedelta(days=7)
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def _scored(grain_model: str, h: int) -> int:
    hs = SCORED[grain_model]
    above = [x for x in hs if x >= h]
    return above[0] if above else hs[-1]


def calibration_flags(labels: pd.DataFrame, X: pd.DataFrame, last_year: int, cfg: GateConfig) -> pd.Series:
    """Out-of-sample gate probability of every label (each year's gate fitted on earlier labels)."""
    pred, _ = forward_gate(labels, X, cfg, fold_years=tuple(range(2019, last_year + 1)))
    if not len(pred):
        return pd.Series(np.nan, index=labels.index)
    key = ["grain", "horizon", "origin", "period_start"]
    p = pred.set_index(key)["p_logistic"]
    return pd.Series(p.reindex(pd.MultiIndex.from_frame(labels[key])).to_numpy(), index=labels.index)


def _conformal(err: np.ndarray, level: float = LEVEL) -> tuple[float, float]:
    n = len(err)
    lv = min(1.0, level * (n + 1) / n)
    return float(np.quantile(err, (1 - lv) / 2)), float(np.quantile(err, (1 + lv) / 2))


def gate_document(doc: dict, labels: pd.DataFrame, X: pd.DataFrame, feats: GateFeatures,
                  cal_p: pd.Series, seed: int = 17) -> dict:
    """A copy of ``doc`` as pfoi-1.2.1-dev: same forecasts, confidence flags, gate-conditional milk ranges."""
    out = copy.deepcopy(doc)
    origin = date.fromisoformat(str(doc["origin_date"])[:10])
    ends = pd.to_datetime(labels["period_end"]).dt.date
    train = labels[ends <= origin]
    audit = {"rule": RULE, "threshold": FLAG_THRESHOLD, "level": LEVEL, "rows": []}
    # gate probability for every page grain x scored horizon at this forecast date
    q = [(g, h) for g in ("day", "week", "month") for h in SCORED[GRAIN_MODEL[g]]]
    rows = pd.DataFrame([dict(origin=origin, grain=GRAIN_MODEL[g], horizon=h) for g, h in q])
    starts = period_starts(origin)  # weeks start on the first Monday on/after the forecast date
    rows["horizon_days"] = [(period_bounds(starts[g], g, int(h))[1] - origin).days
                            for g, h in zip(rows["grain"], rows["horizon"])]
    p = {}
    if len(train) >= 100 and 0 < train["miss"].sum() < len(train):
        Xte = feats.matrix(rows)
        prob = fit_predict_gate("logistic", dict(LOGISTIC_DEFAULT), train, X.loc[train.index], rows, Xte, seed)
        p = {(g, int(h)): float(v) for g, h, v in zip(rows["grain"], rows["horizon"], prob)}
    by_grain = {g: float(np.mean([v for (gg, _), v in p.items() if gg == g])) for g in GRAIN_MODEL.values()
                if any(gg == g for gg, _ in p)}
    # calibration errors: finished by the forecast date, with their own out-of-sample flag
    cal = labels.assign(p=cal_p.to_numpy())
    cal = cal[(ends <= origin) & cal["p"].notna()]
    cal_flag = np.where(cal["p"] > FLAG_THRESHOLD, "low", "normal")
    for r in out.get("outlook", []):
        gm = GRAIN_MODEL.get(r.get("grain"))
        if gm is None:
            continue
        h = _scored(gm, int(r["horizon"]))
        pg = p.get((gm, h), by_grain.get(gm)) if r.get("series") == SERIES else by_grain.get(gm)
        r["model_version"] = VERSION
        if pg is None or not np.isfinite(pg):
            r["p_gate"], r["confidence"] = None, None
            continue
        r["p_gate"] = round(pg, 4)
        r["confidence"] = "low" if pg > FLAG_THRESHOLD else "normal"
        if r.get("series") != SERIES:
            continue
        cell = (cal["grain"] == gm).to_numpy() & (cal["horizon"] == h).to_numpy()
        same = cell & (cal_flag == r["confidence"])
        use = same if same.sum() >= MIN_CAL else cell
        info = {"grain": r["grain"], "horizon": r["horizon"], "p_gate": r["p_gate"], "confidence": r["confidence"],
                "n_same_flag": int(same.sum()), "n_cell": int(cell.sum())}
        if use.sum() >= MIN_CAL:
            lo, hi = _conformal(cal.loc[use, "log_err"].to_numpy(dtype=float))
            f = float(r["forecast"])
            r["lower"], r["upper"] = round(f * np.exp(lo), 3), round(f * np.exp(hi), 3)
            info["range"] = "same flag" if same.sum() >= MIN_CAL else "all past errors"
        else:
            info["range"] = "kept 1.2.0-dev range (fewer than 19 past errors)"
        audit["rows"].append(info)
    out["model_version"] = VERSION
    out["gate"] = audit
    im = dict(out.get("interval_method") or {})
    im["gate"] = RULE
    out["interval_method"] = im
    return out


def run(out_dir, source_version: str, errors: pd.DataFrame, daily: pd.DataFrame,
        origins: list[str] | None = None, markov: bool = True) -> int:
    """Write ``outlook/pfoi-1.2.1-dev/run_YYYYMM.json`` for every built source document; files only."""
    out_dir = Path(out_dir)
    src, dst = out_dir / "outlook" / source_version, out_dir / "outlook" / VERSION
    files = sorted(src.glob("run_*.json"))
    if origins:
        wanted = {date.fromisoformat(o).strftime("%Y%m") for o in origins}
        files = [f for f in files if f.stem.split("_")[1] in wanted]
    if not files:
        print(f"no run_*.json for {source_version} in {src} (run build-outlook first)")
        return 1
    cfg = GateConfig(markov=markov)
    labels = label_rows(errors, "milk_baseline_adaptive")
    feats = GateFeatures(daily, labels, cfg)
    X = feats.matrix(labels)
    last_year = max(int(f.stem.split("_")[1][:4]) for f in files)
    cal_p = calibration_flags(labels, X, last_year, cfg)
    dst.mkdir(parents=True, exist_ok=True)
    print(f"{source_version} -> {VERSION} (same forecasts; gate confidence and gate-conditional milk ranges)")
    for f in files:
        doc = json.loads(f.read_text())
        new = gate_document(doc, labels, X, feats, cal_p)
        (dst / f.name).write_text(json.dumps(new, default=str))
        milk = [r for r in new.get("outlook", []) if r.get("series") == SERIES and r.get("confidence")]
        low = sum(r["confidence"] == "low" for r in milk)
        print(f"  {f.stem.split('_')[1]}: milk rows {len(milk)}, low confidence {low}")
    print(f"Wrote {len(files)} documents to {dst}/. Compare with: compare-runs --origins ... "
          f"--base pfoi-1.1.0 --candidate {source_version} --also {VERSION}")
    return 0
