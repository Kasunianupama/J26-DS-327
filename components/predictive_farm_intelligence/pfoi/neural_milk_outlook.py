"""pfoi-1.8.0-dev page documents: Notebook 6 milk + every non-milk part of pfoi-1.2.0-dev.

The Notebook 6 Farm X run (2026-10-22, user-supplied aggregates) selected
``kalman_state`` for the monthly grain: Wood curve, herd recalibration and each cow's
Kalman level; no neural network. "neural" in command names is historical.

Input: a built pfoi-1.2.0-dev page document (``run_YYYYMM.json``, never modified) and
the aggregate neural milk forecast of the same origin (``cow_milk_predictor``). Output:
a new document under ``outlook/pfoi-1.8.0-dev/`` (files only; nothing is written to
the database here).

- **Milk** rows come only from the neural forecast; each period total is the sum of
  its days of the daily path, so days, weeks and months reconcile exactly. Periods
  outside the fixed-origin support, or inside it without a prediction, get no number
  and are listed in ``withheld`` with the reason (``unsupported_horizon`` /
  ``missing_prediction:...``).
- **Retained unchanged** from 1.2.0-dev: herd counts and composition, calvings,
  dry-offs, abortions and other events, mastitis, heat/THI, moves, generations,
  fertility, coverage, repro timing, generation outcomes, the calving split, and the
  recorded actuals and outcomes (data, not model output).
- **Removed** because they describe the structural milk model, not this predictor:
  milk Shapley attribution, milk correction rows, milk backtest scores, quality bands,
  milk replay, the persistence-blend audit, the 1.7.0-dev cow correction, milk
  scenarios, the milk outage simulation and the milk evidence ladder. Their place is
  taken by ``milk_model`` (formula, provenance, exact stage decomposition, evaluation
  and explanation status). Nothing structural is presented as explaining the neural
  milk forecast.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .cow_milk_predictor import (NEURAL_MILK_VERSION, STAGES, supported_end,
                                 validate_forecast_artifact)
from .outlook import OUTLOOK_HORIZONS, period_starts
from .periods import period_bounds

SOURCE_VERSION = "pfoi-1.2.0-dev"
MILK = "milk_litres"
PAGE_GRAIN = {"daily": "day", "weekly": "week", "monthly": "month"}
REMOVED_MILK_SECTIONS = ("qualityBands", "replay", "blend", "cow_model", "outage_simulation",
                         "evidence_ladder")
FAMILY_LABELS = {
    "kalman_state": "Each cow's own recent level vs the curve (Kalman filter, decayed to the day)",
    "wood_mixed": "No adjustment (the curve is the model)",
    "persistence_last_yield": "Replaced by the cow's last recorded yield (persistence)",
}
STAGE_LABELS = {
    "wood_curve": "Wood lactation curve with each cow's own level (supporting baseline)",
    "herd_recalibrated_curve": "Walk-forward herd recalibration of the curve (baseline, "
                               "recent recorded level before the origin)",
    "model_raw": "Learned model adjustment (all model inputs together)",
    "model_recalibrated": "Recalibration of the model output (herd / parity x DIM)",
    "final": "Persistence blend (only when Notebook 6 selected a blend)",
}


def _daily(artifact: dict) -> pd.DataFrame:
    d = pd.DataFrame(artifact.get("daily") or [])
    if d.empty:
        return pd.DataFrame(columns=["date", "herd_litres", "milking", "cohort_cows"])
    d["date"] = pd.to_datetime(d["date"]).dt.date
    return d.set_index("date").sort_index()


def _end(origin: date, artifact: dict) -> date:
    """First day after the artifact's supported window (default: the origin month)."""
    to = artifact.get("supported_to")
    return date.fromisoformat(to) + timedelta(days=1) if to else supported_end(origin)


def _cell(artifact: dict, grain: str, horizon: int) -> dict | None:
    rows = [c for c in artifact.get("calibration") or [] if c.get("grain") == grain]
    exact = [c for c in rows if int(c["horizon"]) == horizon]
    return exact[0] if exact else None


def document_horizons(structural: dict | None) -> dict[str, tuple[int, ...]]:
    """Horizons per model grain published by the structural document (any series), so
    milk covers the same periods; the fixed outlook sets when the document has none."""
    out = {}
    rows = (structural or {}).get("outlook", [])
    for gm, grain in PAGE_GRAIN.items():
        hs = {int(r["horizon"]) for r in rows if r.get("grain") == grain}
        out[gm] = tuple(sorted(hs | set(OUTLOOK_HORIZONS[gm])))
    return out


def milk_periods(origin: date, artifact: dict, horizons: dict | None = None
                 ) -> tuple[list[dict], list[dict]]:
    """Milk outlook rows from the daily path, and withheld entries for the rest."""
    horizons = horizons or OUTLOOK_HORIZONS
    path = _daily(artifact)
    end = _end(origin, artifact)
    starts = period_starts(origin)
    status = artifact.get("status", "ok")
    reason_missing = "missing_prediction:" + (artifact.get("reason") or "no_cohort_forecast")
    rows, withheld = [], []
    for gm, grain in PAGE_GRAIN.items():
        for h in horizons[gm]:
            s, e = period_bounds(starts[gm], gm, h)
            days = [s + timedelta(days=i) for i in range((e - s).days)]
            if e > end:
                withheld.append((grain, h, s, e, "unsupported_horizon"))
                continue
            vals = [path["herd_litres"].get(d) if d in path.index else None for d in days]
            if status != "ok" or any(v is None or not np.isfinite(v) for v in vals):
                withheld.append((grain, h, s, e, reason_missing))
                continue
            f = float(sum(vals))
            cell = _cell(artifact, grain, h)
            if cell is not None and int(cell.get("n", 0)) > 0:
                lo, hi = f * math.exp(cell["q_lo"]), f * math.exp(cell["q_hi"])
                interval = "calibrated"
            else:
                lo = hi = f
                interval = "uncalibrated"
            rows.append({"origin_date": origin.isoformat(), "target_period": s.isoformat(),
                         "grain": grain, "horizon": h, "series": MILK,
                         "forecast": round(f, 3), "lower": round(max(lo, 0.0), 3),
                         "upper": round(max(hi, f), 3),
                         "quality_flag": "moderate" if interval == "calibrated" else "limited",
                         "interval_status": interval,
                         "source_model": "notebook6:" + str(artifact["selection"].get("model")),
                         "model_version": NEURAL_MILK_VERSION})
    # One withheld entry per grain and reason, spanning its periods.
    out = []
    for grain in PAGE_GRAIN.values():
        for reason in dict.fromkeys(r for g, *_, r in withheld if g == grain):
            part = [w for w in withheld if w[0] == grain and w[4] == reason]
            out.append({"series": MILK, "grain": grain, "from": part[0][2].isoformat(),
                        "to": (part[-1][3] - timedelta(days=1)).isoformat(), "reason": reason,
                        "horizons": [w[1] for w in part]})
    return rows, out


def stage_decomposition(origin: date, artifact: dict) -> list[dict]:
    """Exact additive split of each supported milk period total into predictor stages.

    contribution(stage k) = herd litres after stage k - after stage k-1; the first stage
    is the baseline level itself. The contributions add up to the forecast exactly.
    """
    path = _daily(artifact)
    if path.empty or artifact.get("status") != "ok":
        return []
    family = (artifact.get("selection") or {}).get("family", "")
    labels = dict(STAGE_LABELS, model_raw=FAMILY_LABELS.get(
        family, "Learned network adjustment (all model inputs together)"))
    end = _end(origin, artifact)
    starts = period_starts(origin)
    out = []
    for gm, grain in (("monthly", "month"), ("weekly", "week")):
        for h in OUTLOOK_HORIZONS[gm]:
            s, e = period_bounds(starts[gm], gm, h)
            if e > end:
                continue
            p = path[(path.index >= s) & (path.index < e)]
            if len(p) != (e - s).days or p["herd_litres"].isna().any():
                continue
            prev = 0.0
            for stage in STAGES:
                total = float(p[f"{stage}_litres"].sum())
                out.append({"target_period": s.isoformat(), "grain": grain, "horizon": h,
                            "stage": stage, "label": labels[stage],
                            "kind": "baseline" if stage in ("wood_curve",
                                                            "herd_recalibrated_curve")
                            else "learned",
                            "contribution_litres": round(total - prev, 3),
                            "level_litres": round(total, 3)})
                prev = total
            if abs(prev - float(p["herd_litres"].sum())) > 1e-6:
                raise ValueError("stage decomposition does not add up to the forecast")
    return out


def compose_document(structural: dict, artifact: dict) -> dict:
    """The pfoi-1.8.0-dev page document (see module doc)."""
    origin = date.fromisoformat(str(structural["origin_date"])[:10])
    validate_forecast_artifact(artifact, origin)
    src_version = structural.get("model_version", SOURCE_VERSION)
    doc = copy.deepcopy(structural)
    milk_rows, withheld = milk_periods(origin, artifact, document_horizons(structural))
    kept = [r for r in doc.get("outlook", []) if r.get("series") != MILK]
    for r in kept:
        r["source_model"] = src_version
        r["model_version"] = NEURAL_MILK_VERSION
    doc["outlook"] = kept + milk_rows
    doc["corrections"] = [r for r in doc.get("corrections", []) if r.get("series") != MILK]
    doc["attribution"] = [dict(r, model_version=NEURAL_MILK_VERSION, source_model=src_version)
                          for r in doc.get("attribution", []) if r.get("series") != MILK]
    doc["backtest"] = [r for r in doc.get("backtest", []) if r.get("series") != MILK]
    if "scenarios" in doc:
        doc["scenarios"] = [r for r in doc["scenarios"] if r.get("series") != MILK]
    for key in REMOVED_MILK_SECTIONS:
        doc.pop(key, None)
    doc["withheld"] = [w for w in doc.get("withheld") or [] if w.get("series") != MILK] + withheld
    method = dict(doc.get("interval_method") or {})
    method["milk"] = ("calibrated_on_own_prior_errors" if any(
        r["interval_status"] == "calibrated" for r in milk_rows) else "uncalibrated")
    method.pop("cow_model", None)
    doc["interval_method"] = method
    sel = artifact.get("selection") or {}
    n_cells = len(artifact.get("calibration") or [])
    doc["milk_model"] = {
        "model_version": NEURAL_MILK_VERSION,
        "status": artifact.get("status"), "reason": artifact.get("reason"),
        "selected_model": sel.get("model"), "base_model": sel.get("base_model"),
        "model_family": sel.get("family"),
        "is_neural_network": str(sel.get("family", "")).startswith("torch_"),
        "selection_grain": sel.get("grain"), "selection_metric": sel.get("selection_metric"),
        "selection_scores": sel.get("selection_scores"),
        "formula": artifact.get("formula"), "protocol": artifact.get("protocol"),
        "supported_from": artifact.get("supported_from"),
        "supported_to": artifact.get("supported_to"),
        "dependency": "milking-cow counts are the pfoi-1.2.0-dev herd-engine forecast",
        "predictor": artifact.get("predictor"), "cohort": artifact.get("cohort"),
        "milking_path": artifact.get("milking_path"),
        "reload_check": artifact.get("reload_check"),
        "decomposition": stage_decomposition(origin, artifact),
        "decomposition_note": ("Exact split of the forecast into the predictor's stages. "
                               "Baseline stages are the Wood curve and its recent-level "
                               "recalibration; learned stages are what the network and its "
                               "recalibration add. Model associations, not causal effects."),
        "explanation": {"status": "not yet assessed",
                        "note": "feature-level explanation of this predictor is a separate step"},
        "evaluation": {"status": "not yet evaluated",
                       "note": "rolling-origin herd-total evaluation is a separate step"},
        "intervals": (f"{n_cells} calibration cells from this predictor's own prior errors"
                      if n_cells else "uncalibrated: lower = upper = forecast; no range claimed"),
    }
    doc["provenance"] = {
        "document": NEURAL_MILK_VERSION,
        "milk_litres": f"{NEURAL_MILK_VERSION} (Notebook 6 {sel.get('model')}) x "
                       f"{src_version} milking cows",
        "herd, events, mastitis, heat, moves, generations, fertility": src_version,
        "actuals, realised, record_status, coverage": "recorded data (model independent)",
        "removed_structural_milk_sections": ["milk attribution", "milk corrections",
                                             "milk backtest", *REMOVED_MILK_SECTIONS,
                                             "milk scenarios"],
    }
    doc["source_documents"] = {"structural": src_version,
                               "structural_generated_at": structural.get("generated_at")}
    doc["model_version"] = NEURAL_MILK_VERSION
    return doc


def milk_summary(doc: dict) -> dict:
    """Counts only: published milk rows by grain and withheld reasons."""
    rows = [r for r in doc.get("outlook", []) if r.get("series") == MILK]
    by = {g: sum(1 for r in rows if r["grain"] == g) for g in PAGE_GRAIN.values()}
    return {"origin": doc.get("origin_date"), "milk_rows": by,
            "withheld": sorted({w["reason"] for w in doc.get("withheld", [])
                                if w.get("series") == MILK})}


def run(out_dir, origins: list[str], source_version: str = SOURCE_VERSION) -> list[Path]:
    root = Path(out_dir) / "outlook"
    dest = root / NEURAL_MILK_VERSION
    written = []
    for o in origins:
        origin = date.fromisoformat(o)
        src = root / source_version / f"run_{origin:%Y%m}.json"
        art = dest / f"neural_milk_{origin:%Y%m}.json"
        for p in (src, art):
            if not p.is_file():
                raise FileNotFoundError(f"missing {p}")
        doc = compose_document(json.loads(src.read_text()), json.loads(art.read_text()))
        target = dest / f"run_{origin:%Y%m}.json"
        target.write_text(json.dumps(doc, indent=1))
        written.append(target)
    return written


UNCHANGED_SECTIONS = ("actuals", "realised", "moves", "heat", "generations", "fertility",
                      "coverage", "repro_timing", "generation_outcomes", "record_status",
                      "feature_registry", "mastitis_rate_period", "realised_through")


def verify_document(structural: dict, doc: dict, artifact: dict) -> list[dict]:
    """Checks that ``doc`` is ``structural`` with only the milk replaced (aggregates).

    One row per check: name, ok, detail. Used before any database write.
    """
    import hashlib

    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("version", doc.get("model_version") == NEURAL_MILK_VERSION, doc.get("model_version"))
    add("same origin", doc.get("origin_date") == structural.get("origin_date"), doc.get("origin_date"))
    key = lambda r: (r["grain"], int(r["horizon"]), r["series"])  # noqa: E731
    vals = ("target_period", "forecast", "lower", "upper", "quality_flag")
    a = {key(r): tuple(r.get(v) for v in vals) for r in structural.get("outlook", []) if r["series"] != MILK}
    b = {key(r): tuple(r.get(v) for v in vals) for r in doc.get("outlook", []) if r["series"] != MILK}
    diff = sum(1 for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    add("non-milk forecasts identical to source", diff == 0 and len(a) == len(b),
        f"{len(a)} rows in source, {len(b)} in document, {diff} differ")
    strip = lambda rows: sorted(json.dumps({k: v for k, v in r.items()  # noqa: E731
                                            if k not in ("model_version", "source_model")},
                                           sort_keys=True) for r in rows if r.get("series") != MILK)
    add("non-milk attribution identical", strip(structural.get("attribution", []))
        == strip(doc.get("attribution", [])), f"{len(doc.get('attribution', []))} rows")
    same = [s for s in UNCHANGED_SECTIONS if structural.get(s) == doc.get(s)]
    add("data and non-milk sections identical", len(same) == len(UNCHANGED_SECTIONS),
        ", ".join(s for s in UNCHANGED_SECTIONS if s not in same) or "all equal")
    path = _daily(artifact)
    end = _end(date.fromisoformat(doc["origin_date"]), artifact)
    worst, outside = 0.0, 0
    for r in (x for x in doc.get("outlook", []) if x["series"] == MILK):
        gm = {v: k for k, v in PAGE_GRAIN.items()}[r["grain"]]
        s, e = period_bounds(period_starts(date.fromisoformat(doc["origin_date"]))[gm], gm, int(r["horizon"]))
        outside += e > end
        total = float(path.loc[(path.index >= s) & (path.index < e), "herd_litres"].sum())
        worst = max(worst, abs(total - float(r["forecast"])))
    n_milk = sum(1 for x in doc.get("outlook", []) if x["series"] == MILK)
    add("milk rows = sum of the predictor's daily path", worst <= 0.01, f"{n_milk} rows, max diff {worst:.4f} L")
    add("no milk outside the supported window", outside == 0, f"supported to {artifact.get('supported_to')}")
    rc = artifact.get("reload_check") or {}
    add("predictor reload check passed", artifact.get("status") != "ok" or rc.get("passed") is True,
        f"max diff {rc.get('max_abs_diff_litres')}")
    p = artifact.get("predictor") or {}
    add("predictor provenance present", artifact.get("status") != "ok" or bool(p.get("weights_sha256")),
        f"model {(artifact.get('selection') or {}).get('model')}, weights {str(p.get('weights_sha256'))[:12]}")
    add("milk forecast present", n_milk > 0, artifact.get("reason") or "")
    checks.append({"check": "document sha256", "ok": True,
                   "detail": hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]})
    return checks
