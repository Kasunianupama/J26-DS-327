"""Page documents for the neural model and persistence, for ``compare-runs`` charts. Files only.

``build-outlook`` writes one document per forecast date (``logs/pfoi/outlook/<version>/run_YYYYMM.json``).
This copies a built document and replaces only its **milk** forecasts, so every version drawn by
``compare-runs --also`` shares the same recorded history and recorded outcome:

* ``pfoi-neural-dev``: the neural model's daily path at that forecast date (``neural`` command,
  ``neural_paths_*.csv``; stage 2 uses the stage-1 -> stage-2 transfer model). Its path is 98 days, so
  it covers days 1-14, weeks 1-13 and months 1-3; longer months are left out, never filled in. It has
  no 5-95 % range yet (lower = upper), so coverage is not scored for it.
* ``persistence``: the last complete scoreable week before the forecast date carried forward (litres
  per day x days in the period), the benchmark the models must beat.

Herd series, attribution and the recorded outcome are left as they are. Nothing reaches ``c1_output``.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .blend_outlook import last_complete_week
from .outlook import period_starts
from .periods import period_bounds

SERIES = "milk_litres"
GRAIN_MODEL = {"day": "daily", "week": "weekly", "month": "monthly"}
NEURAL_VERSION = "pfoi-neural-dev"
PERSISTENCE_VERSION = "persistence"


def _replace_milk(doc: dict, version: str, value_of) -> dict:
    """Copy of ``doc`` whose milk rows are ``value_of(grain, start, end)`` (None = row dropped)."""
    out = copy.deepcopy(doc)
    origin = date.fromisoformat(str(doc["origin_date"])[:10])
    starts = period_starts(origin)
    rows = []
    for r in out.get("outlook", []):
        if r["series"] != SERIES:
            rows.append(r)
            continue
        gm = GRAIN_MODEL[r["grain"]]
        s, e = period_bounds(starts[gm], gm, int(r["horizon"]))
        v = value_of(r["grain"], s, e)
        if v is None:
            continue
        rows.append(dict(r, forecast=round(float(v), 3), lower=round(float(v), 3),
                         upper=round(float(v), 3), model_version=version, quality_flag="ok"))
    out["outlook"] = rows
    out["corrections"] = [c for c in out.get("corrections", []) if c.get("series") != SERIES]
    out["model_version"] = version
    return out


def neural_document(doc: dict, path: pd.Series) -> dict:
    """``path``: litres per day indexed by date, starting at the forecast date."""
    def value(_grain, s, e):
        part = path.loc[(path.index >= s) & (path.index < e)]
        return float(part.sum()) if len(part) == (e - s).days else None

    out = _replace_milk(doc, NEURAL_VERSION, value)
    out["neural"] = {"note": "GRU + herd-engine path, two-stage split (docs/pp1_plan.md); "
                             "no 5-95 % range yet", "path_days": int(len(path))}
    return out


def persistence_document(doc: dict) -> dict | None:
    origin = date.fromisoformat(str(doc["origin_date"])[:10])
    week = last_complete_week(doc, origin)
    if week is None:
        return None
    per_day = week[1] / 7.0
    out = _replace_milk(doc, PERSISTENCE_VERSION, lambda _g, s, e: per_day * (e - s).days)
    out["persistence"] = {"week_start": week[0].isoformat(), "litres_per_day": per_day}
    return out


def load_paths(neural_dir) -> pd.DataFrame:
    files = sorted(Path(neural_dir).glob("neural_paths_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"no neural_paths_*.csv in {neural_dir} (run the neural command first)")
    p = pd.read_csv(files[-1])
    for c in ("origin", "date"):
        p[c] = pd.to_datetime(p[c]).dt.date
    return p


def path_at(paths: pd.DataFrame, origin: date) -> pd.Series | None:
    """The transfer model's path where it exists (stage 2), else the stage model's own."""
    p = paths[paths["origin"] == origin]
    for model in ("neural_transfer", "neural"):
        q = p[p["model"] == model]
        if len(q):
            return q.set_index("date")["litres"].sort_index()
    return None


def run(out_dir, source_version: str, neural_dir, origins: list[str] | None = None) -> int:
    out_dir = Path(out_dir)
    src = out_dir / "outlook" / source_version
    files = sorted(src.glob("run_*.json"))
    if origins:
        wanted = {date.fromisoformat(o).strftime("%Y%m") for o in origins}
        files = [f for f in files if f.stem.split("_")[1] in wanted]
    if not files:
        print(f"no run_*.json for {source_version} in {src} (run build-outlook first)")
        return 1
    paths = load_paths(neural_dir)
    dst = {v: out_dir / "outlook" / v for v in (NEURAL_VERSION, PERSISTENCE_VERSION)}
    for d in dst.values():
        d.mkdir(parents=True, exist_ok=True)
    written = {v: 0 for v in dst}
    for f in files:
        doc = json.loads(f.read_text())
        origin = date.fromisoformat(str(doc["origin_date"])[:10])
        path = path_at(paths, origin)
        if path is None:
            print(f"  {origin}: no neural forecast (not a first-of-month date in a test part)")
        else:
            (dst[NEURAL_VERSION] / f.name).write_text(json.dumps(neural_document(doc, path)))
            written[NEURAL_VERSION] += 1
        pd_doc = persistence_document(doc)
        if pd_doc is None:
            print(f"  {origin}: no persistence (no complete recorded week before the date)")
        else:
            (dst[PERSISTENCE_VERSION] / f.name).write_text(json.dumps(pd_doc))
            written[PERSISTENCE_VERSION] += 1
    print(f"Wrote {written[NEURAL_VERSION]} {NEURAL_VERSION} and {written[PERSISTENCE_VERSION]} "
          f"{PERSISTENCE_VERSION} documents from {source_version} (files only; nothing written to the database).")
    return 0
