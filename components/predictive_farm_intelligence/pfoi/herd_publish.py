"""Export and publish the combined herd milk model (notebook 09) without rerunning it.

1. ``export_bundle`` (notebook cell D) writes a self-contained folder: ``c1_outlook.csv``,
   ``c1_attribution.csv``, ``c1_history.csv`` (shared ``c1_output`` contract, validated),
   ``run_document.json`` (page vocabulary) and ``manifest.json`` (model version, origin,
   row counts, SHA-256 of every file).
2. ``publish_bundle`` (notebook cell E, or the terminal) checks the bundle against its
   manifest and the contract, then writes it to ``c1_output`` as role ``farmx_model``
   (settings from the root ``.env``). It replaces only rows of the same origin and
   model version (``outlook.write_outlook`` / ``write_run_document``).

The page shows the newest run document, so the document is **merged** into the latest
published full run document first: this model replaces the milk rows (outlook,
attribution, back-test, replay, actuals), the herd series it forecasts, and adds its own
keys (record status, withheld, evidence ladder, reliability markers, alternatives, …);
every other panel (generations, fertility, reproduction, heat, …) is kept as published.
Without a published document, the required page keys are added empty.

Descriptive panels (heat, breeding, herd make-up, mastitis) show nothing dated before the
validation start (the day after ``selection_train_end``): ``complete_document`` builds them
from that date only, and ``restrict_panels`` trims any document again before it is written.

Dry run by default: nothing is written unless ``publish=True`` / ``--publish``.

Terminal:
    python -m components.predictive_farm_intelligence.pfoi.herd_publish <bundle folder>
    python -m components.predictive_farm_intelligence.pfoi.herd_publish <bundle folder> --publish
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .herd_frontend import C1_SERIES, PAGE_GRAIN, PAGE_SERIES

C1_QUALITY = {"high": "ok", "moderate": "beyond_reliability_marker", "limited": "untested_or_stale"}
C1_ATTR_SERIES = "herd_milk_litres_per_day"   # milk attribution name used by pfoi.attribution
BACK_GRAIN = {v: k for k, v in PAGE_GRAIN.items()}
BACK_SERIES = {"milk_litres": "herd_milk", "total_herd": "n_herd"}
OUR_KEYS = ("record_status", "withheld", "interval_method", "evidence_ladder",
            "horizon_reliability", "milk_model", "cow06_input", "herd_path", "reproducibility",
            "alternatives")
DATED_KEYS = ("outlook", "attribution", "actuals", "realised", "realised_through", "replay",
              "revisions", "backtest", "moves", "record_status", "withheld", "scenarios")
REQUIRED_EMPTY = {"outlook": [], "attribution": [], "actuals": [], "replay": [], "revisions": [],
                  "backtest": [], "generations": [], "fertility": [], "coverage": [],
                  "mastitis_rate_period": ""}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def history_rows(doc: dict) -> pd.DataFrame:
    """c1_output.history rows from the document's actuals (milk and herd series)."""
    a = pd.DataFrame(doc.get("actuals") or [])
    if a.empty:
        return pd.DataFrame(columns=["origin_date", "period", "grain", "series", "actual",
                                     "quality_flag", "model_version", "core_version"])
    a = a[a["series"].isin(["milk_litres", *C1_SERIES])]
    return pd.DataFrame({
        "origin_date": doc["origin_date"], "period": a["period"],
        "grain": a["grain"].map(BACK_GRAIN), "series": a["series"].replace(BACK_SERIES),
        "actual": a["value"],
        "quality_flag": np.where(a["value"].isna(), "gap", np.where(a["scoreable"], "ok", "partial")),
        "model_version": doc["model_version"], "core_version": doc.get("core_version")})


def export_bundle(out_dir, doc: dict, c1_outlook: pd.DataFrame, c1_attribution: pd.DataFrame) -> dict:
    """Write the bundle and its manifest; returns the manifest."""
    from shared.schemas.pfoi_outlook import AttributionRow, HistoryRow, OutlookRow

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    o = c1_outlook.copy()
    if len(o):
        o["quality_flag"] = o["quality_flag"].map(C1_QUALITY).fillna(o["quality_flag"])
    a = c1_attribution.copy()
    if len(a):
        a.loc[a["series"] == "herd_milk", "series"] = C1_ATTR_SERIES
    h = history_rows(doc)
    for frame, model in ((o, OutlookRow), (a, AttributionRow), (h, HistoryRow)):
        for rec in frame.astype(object).where(frame.notna(), None).to_dict("records"):
            model(**rec)
    files = {"c1_outlook.csv": o, "c1_attribution.csv": a, "c1_history.csv": h}
    for name, frame in files.items():
        frame.to_csv(out / name, index=False)
    (out / "run_document.json").write_text(json.dumps(doc, indent=1, default=str))
    manifest = {"model_version": doc["model_version"], "origin_date": doc["origin_date"],
                "data_through": doc.get("data_through"), "source": doc.get("source"),
                "core_version": doc.get("core_version"),
                "config_hash": (doc.get("reproducibility") or {}).get("config_hash"),
                "rows": {k: len(v) for k, v in files.items()},
                "sha256": {n: _sha(out / n) for n in (*files, "run_document.json")}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def load_bundle(folder) -> dict:
    """Read a bundle and check every file against the manifest."""
    f = Path(folder)
    manifest = json.loads((f / "manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        if _sha(f / name) != digest:
            raise ValueError(f"{name} changed after export (checksum mismatch)")
    read = lambda n: pd.read_csv(f / n, keep_default_na=True)  # noqa: E731
    return {"manifest": manifest, "outlook": read("c1_outlook.csv"),
            "attribution": read("c1_attribution.csv"), "history": read("c1_history.csv"),
            "document": json.loads((f / "run_document.json").read_text())}


def merge_document(base: dict | None, ours: dict) -> dict:
    """``ours`` laid over the published full document ``base`` (see module docstring)."""
    doc = dict(REQUIRED_EMPTY)
    base = dict(base or {})
    if base and str(base.get("origin_date")) != str(ours.get("origin_date")):
        # another forecast date: keep only its undated panels (generations, fertility, ...)
        for k in DATED_KEYS:
            base.pop(k, None)
    doc.update(base)
    our_series = {r["series"] for r in ours.get("outlook", [])}
    keep = lambda rows, key="series": [r for r in rows or [] if r.get(key) not in our_series]  # noqa: E731
    doc["outlook"] = keep(doc.get("outlook")) + ours.get("outlook", [])
    doc["actuals"] = keep(doc.get("actuals")) + ours.get("actuals", [])
    if "realised" in ours:
        doc["realised"] = keep(doc.get("realised")) + (ours.get("realised") or [])
    doc["replay"] = keep(doc.get("replay")) + ours.get("replay", [])
    doc["backtest"] = keep(doc.get("backtest")) + ours.get("backtest", [])
    doc["attribution"] = [r for r in doc.get("attribution") or [] if r.get("series") != "milk_litres"] \
        + ours.get("attribution", [])
    for k in ("realised_through", "run_kind"):
        if k in ours:
            doc[k] = ours[k]
    for k in OUR_KEYS:
        if k in ours:
            doc[k] = ours[k]
    for k in ("source", "model_version", "core_version", "origin_date", "data_through", "generated_at"):
        doc[k] = ours.get(k, doc.get(k))
    doc["merged_from"] = (base or {}).get("model_version")
    return doc


MODEL_SPECIFIC = ("corrections", "blend", "qualityBands", "cow_model", "outage_simulation",
                  "feature_registry", "scenarios")


def herd_only_run(source, origin):
    """The herd engine's run at ``origin`` (``FROZEN_ENGINE``), without any milk model: milk
    is this model's, so the page builder's milk is marked as supplied elsewhere and skipped.
    (The full frozen run also calibrates the old milk model, which can fail where that model
    has no usable months; nothing here depends on it.)"""
    import numpy as np

    from .data import DATA_START, load_origin_inputs
    from .freeze import FROZEN_ENGINE, version_label
    from .herd_engine import project
    from .milk_baseline import MilkHistory
    from .outlook import OUTLOOK_HORIZONS, FrozenRun, period_starts
    from .periods import period_bounds
    from .rates import estimate_rates

    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, origin),
                       target=source.target_daily(DATA_START, origin))
    inputs = load_origin_inputs(source, origin, FROZEN_ENGINE)
    rates = estimate_rates(inputs.rate_inputs, FROZEN_ENGINE)
    starts = period_starts(origin)
    horizon_days = max((period_bounds(starts[g], g, max(h))[1] - origin).days
                       for g, h in OUTLOOK_HORIZONS.items())
    proj = project(inputs.state, rates, horizon_days)
    daily = proj.daily.assign(herd_milk=np.nan)
    return FrozenRun(origin, hist, None, inputs, rates, proj, daily, starts, horizon_days, "ok",
                     version_label(FROZEN_ENGINE), milk_withheld="milk supplied by this model")


def validation_start(doc: dict) -> date | None:
    """First day after selection training (``reproducibility.selection_train_end``), or None."""
    end = (doc.get("reproducibility") or {}).get("selection_train_end")
    return date.fromisoformat(str(end)[:10]) + timedelta(days=1) if end else None


def _month_ceil(d: date) -> date:
    """First month start on or after ``d``: monthly panels start at a whole month."""
    return d if d.day == 1 else (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _iso_date(v) -> date:
    return date.fromisoformat(str(v)[:10])


class FromValidation:
    """``source`` for the page builder, with the descriptive panels limited to the validation
    window: breeding loaders from ``since`` (one period), fertility as known at ``asof``,
    health months and herd exposure from the first whole month from ``since`` (mastitis rate
    and history, herd make-up). Every other loader (herd engine, weather for the heat
    climatology and THI forecast) is the source's own."""

    def __init__(self, source, since: date, asof: date):
        self._src, self.since, self.asof = source, since, asof
        self.first_month = _month_ceil(since)

    def __getattr__(self, name):
        return getattr(self._src, name)

    def _months(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty or "month" not in frame:
            return frame
        keep = [_iso_date(pd.Timestamp(m).date()) >= self.first_month for m in frame["month"]]
        return frame[keep].reset_index(drop=True)

    def repro_steps(self, asof):
        return self._src.repro_steps(asof, since=self.since)

    def generation_yield(self, asof):
        return self._src.generation_yield(asof, since=self.since)

    def generation_days(self, asof):
        return self._src.generation_days(asof, since=self.since)

    def generation_alarms(self, asof):
        return self._src.generation_alarms(asof, since=self.since)

    def generation_fertility(self):
        return self._src.generation_fertility(asof=self.asof, since=self.since)

    def health_months(self, start, end):
        return self._months(self._src.health_months(start, end))

    def exposure(self, start, origin):
        return self._months(self._src.exposure(start, origin))


_RATE_FROM = re.compile(r"\((\d{4}-\d{2}) to (\d{4}-\d{2})\)")


def restrict_panels(doc: dict, since: date | None = None) -> dict:
    """Drop every heat, breeding, herd make-up and mastitis row dated before ``since``
    (default: the document's validation start). Breeding rows are kept only for the window
    period (``window_label``); older documents' calendar periods (2015-2019, ...) go. A
    mastitis forecast is kept only when its rate period starts in the window. Forecast
    rows after the origin are not touched. Returns a new document."""
    from .data import window_label

    since = since or validation_start(doc)
    if since is None or not doc.get("origin_date"):
        return doc
    doc = dict(doc)
    origin = _iso_date(doc["origin_date"])
    label, first = window_label(since, origin), _month_ceil(since)
    for key in ("repro_timing", "generation_outcomes"):
        if key in doc:
            doc[key] = [r for r in doc[key] or [] if r.get("period") == label]
    if "fertility" in doc:
        doc["fertility"] = [r for r in doc["fertility"] or [] if r.get("period_label") == label]
    if "generations" in doc:
        doc["generations"] = [r for r in doc["generations"] or []
                              if r.get("projected") or _iso_date(r["period"]) >= first]
    if doc.get("heat"):
        heat = dict(doc["heat"])
        heat["recent"] = [d for d in heat.get("recent") or [] if _iso_date(d["date"]) >= since]
        if origin - timedelta(days=8) < since:   # the recent-heat summaries would use earlier days
            heat["hot_run_days"] = heat["heat_load_7d"] = None
        doc["heat"] = heat
    for key in ("actuals", "realised"):
        if key in doc:
            doc[key] = [r for r in doc[key] or [] if r.get("series") != "mastitis_episodes"
                        or _iso_date(r["period"]) >= first]
    rate = _RATE_FROM.search(str(doc.get("mastitis_rate_period") or ""))
    if rate is None or rate.group(1) < f"{first:%Y-%m}":
        doc["outlook"] = [r for r in doc.get("outlook") or [] if r.get("series") != "mastitis_episodes"]
        doc["mastitis_rate_period"] = ""   # the page then says no expected episodes are shown
    doc["panels_window"] = {"from": str(since), "to": str(origin - timedelta(days=1)), "label": label,
                            "note": "heat, breeding, herd make-up and mastitis: nothing before the "
                                    "validation start"}
    return doc


def complete_document(source, ours: dict, realised_until=None) -> dict:
    """``ours`` made self-contained: the panels this model does not produce itself
    (generations, fertility, coverage, herd moves, reproduction, heat, mastitis, the calving
    split, bulls / abortions / entries) are computed **at this forecast date from core**
    with the page builder and the herd engine settings this model uses for herd movement
    (``FROZEN_ENGINE``); every milk number and the nine herd series stay this model's.
    Nothing is copied from a stored document of another model. Heat, breeding, herd
    make-up and mastitis start at the validation start (``FromValidation``,
    ``restrict_panels``)."""
    from .page_run import build_page_run

    import inspect

    o = _iso_date(ours["origin_date"])
    since = validation_start(ours)
    if since is not None and "since" not in inspect.signature(source.repro_steps).parameters:
        raise RuntimeError("the data source predates the validation-window panels (pfoi.data was "
                           "imported before the update): restart the kernel and run again")
    run = herd_only_run(source, o)
    empty = pd.DataFrame(columns=["origin_date", "target_period", "grain", "series", "factor",
                                  "contribution", "kind"])
    page_source = FromValidation(source, since, o) if since is not None else source
    base = build_page_run(page_source, run, empty, {}, ours.get("core_version"),
                          realised_until=realised_until, evidence={})
    rate = _RATE_FROM.search(str(base.get("mastitis_rate_period") or ""))
    if since is not None and rate and rate.group(1) < f"{_month_ceil(since):%Y-%m}":
        # the rate's health months were cut at the validation start: name the months used
        base["mastitis_rate_period"] = (f"records since the validation start "
                                        f"({_month_ceil(since):%Y-%m} to {rate.group(2)})")
    for k in MODEL_SPECIFIC:
        base.pop(k, None)
    # The page builder's own milk rows come from a different milk model: drop them all.
    for k in ("outlook", "actuals", "realised", "replay", "backtest"):
        base[k] = [r for r in base.get(k) or [] if r.get("series") != "milk_litres"]
    base["attribution"] = [r for r in base.get("attribution") or [] if r.get("series") != "milk_litres"]
    base["origin_date"] = str(o)
    doc = merge_document(base, ours)
    doc["merged_from"] = None
    doc["panels_from"] = {"computed_at": str(o), "herd_engine": run.version,
                          "panels": ["generations", "fertility", "coverage", "moves", "repro_timing",
                                     "generation_outcomes", "heat", "mastitis_episodes",
                                     "calvings determined / rate-driven", "other", "abortions",
                                     "entries"],
                          "note": "computed from core for this run; no other model's document used"}
    return restrict_panels(doc, since)


def _engine():
    from sqlalchemy import create_engine

    from .config import DatabaseSettings

    return create_engine(DatabaseSettings.from_env().url, pool_pre_ping=True)


def core_version_from_db(engine) -> str | None:
    """Latest published core version (publish.publish_log.version), or None."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT MAX(version)::text FROM publish.publish_log")).first()
        return None if row is None or row[0] is None else str(row[0])
    except Exception:  # noqa: BLE001 - table not readable here
        return None


def latest_document(engine, schema: str = "c1_output", exclude: str | None = None,
                    origin: str | None = None) -> dict | None:
    """The published page document of another model version to merge into: the same
    forecast date if one exists, else the newest one."""
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT document FROM {schema}.run_document "
                                "WHERE model_version <> :v "
                                "ORDER BY (origin_date = CAST(:o AS date)) DESC, origin_date DESC, "
                                "created_at DESC LIMIT 1"),
                           {"v": exclude or "", "o": origin or "1900-01-01"}).first()
    return None if row is None else (row[0] if isinstance(row[0], dict) else json.loads(row[0]))


class InsideTrainingPeriod(ValueError):
    """A forecast date the published model was trained on: never published as a forecast."""


def check_out_of_sample(doc: dict) -> None:
    """Raise ``InsideTrainingPeriod`` for a walk-forward run or a forecast date on or before
    the end of selection training recorded in the document (the training set)."""
    kind = str(doc.get("run_kind") or "")
    train_end = (doc.get("reproducibility") or {}).get("selection_train_end")
    origin = str(doc.get("origin_date"))[:10]
    if kind.startswith("walk-forward"):
        raise InsideTrainingPeriod(f"{origin}: walk-forward run inside the training period")
    if train_end and origin <= str(train_end)[:10]:
        raise InsideTrainingPeriod(f"{origin}: inside the training period (training ends {train_end})")


def publish_bundle(folder, publish: bool = False, engine=None, merge: bool = False,
                   schema: str = "c1_output") -> dict:
    """Check the bundle, merge the document and (only with ``publish``) write it."""
    from .outlook import write_outlook, write_run_document

    b = load_bundle(folder)
    m = b["manifest"]
    check_out_of_sample(b["document"])
    if m.get("source") == "demo" and publish:
        raise ValueError("synthetic (demo) bundle: not published to c1_output")
    for name, frame in (("outlook", b["outlook"]), ("attribution", b["attribution"]), ("history", b["history"])):
        if frame["model_version"].nunique() > 1 or frame["origin_date"].nunique() > 1:
            raise ValueError(f"{name}: more than one model version or origin in the bundle")
    if m["rows"].get("c1_outlook.csv", 0) == 0 and not b["document"].get("withheld") and publish:
        raise ValueError("the bundle has no forecast rows (milk withheld and no herd path at the "
                         "origin?): nothing to publish")
    report = {"model_version": m["model_version"], "origin_date": m["origin_date"],
              "rows": m["rows"], "published": False}
    if engine is None and (publish or merge):
        engine = _engine()
    base = latest_document(engine, schema, exclude=m["model_version"], origin=m["origin_date"]) if merge else None
    doc = restrict_panels(merge_document(base, b["document"]))
    core = b["document"].get("core_version")
    if not core and engine is not None:
        core = core_version_from_db(engine)
        if core:   # stamp the missing core version on every row written
            for frame in (b["outlook"], b["attribution"], b["history"]):
                frame["core_version"] = core
            doc["core_version"] = core
    report["core_version"] = core
    report["merged_into"] = doc.get("merged_from")
    if publish:
        counts = write_outlook(engine, b["outlook"], b["attribution"], b["history"], schema)
        write_run_document(engine, doc, schema)
        report.update(published=True, written=counts)
    return report


def publish_all(root, publish: bool = False, engine=None, merge: bool = False,
                prune: bool = False) -> pd.DataFrame:
    """Every bundle under ``root`` (one folder per forecast date), oldest date first.
    ``prune``: also delete this model version's rows for forecast dates that are not in
    ``root`` (e.g. walk-forward dates published earlier); only with ``publish``."""
    folders = sorted(p.parent for p in Path(root).glob("*/manifest.json"))
    if engine is None and (publish or merge):
        engine = _engine()
    rows = []
    for f in folders:
        try:
            r = publish_bundle(f, publish=publish, engine=engine, merge=merge)
        except InsideTrainingPeriod as e:   # never published; reported instead
            rows.append({"folder": f.name, "origin_date": f.name, "rows": 0, "merged_into": None,
                         "published": False, "note": f"refused: {e}"})
            continue
        rows.append({"folder": f.name, "origin_date": r["origin_date"], "rows": sum(r["rows"].values()),
                     "merged_into": r.get("merged_into"), "published": r["published"], "note": ""})
    out = pd.DataFrame(rows)
    ok = out[~out["note"].str.startswith("refused")] if len(out) else out
    if prune and publish and len(ok):
        version = json.loads((folders[0] / "manifest.json").read_text())["model_version"]
        out.attrs["pruned"] = prune_dates(engine, version, list(ok["origin_date"]))
    return out


def prune_dates(engine, model_version: str, keep: list[str], schema: str = "c1_output") -> dict:
    """Delete this model version's rows for forecast dates not in ``keep``; returns counts."""
    from sqlalchemy import text

    counts = {}
    with engine.begin() as conn:
        for table in ("outlook", "attribution", "history", "run_document"):
            r = conn.execute(text(f"DELETE FROM {schema}.{table} WHERE model_version = :v "
                                  "AND NOT (CAST(origin_date AS text) = ANY(:keep))"),
                             {"v": model_version, "keep": [str(k)[:10] for k in keep]})
            counts[table] = getattr(r, "rowcount", None)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check (and with --publish write) a notebook 09 bundle to c1_output.")
    ap.add_argument("bundle", help="a bundle folder, or with --all a folder of bundles (…/frontend/bundles)")
    ap.add_argument("--all", action="store_true", help="publish every bundle in the folder (one per date)")
    ap.add_argument("--publish", action="store_true", help="write to c1_output (default: dry run)")
    ap.add_argument("--merge-old", action="store_true",
                    help="(not recommended) merge into another model's published document")
    ap.add_argument("--prune", action="store_true",
                    help="with --all --publish: delete this model's dates that are not in the folder")
    args = ap.parse_args(argv)
    if args.all:
        t = publish_all(args.bundle, publish=args.publish, merge=args.merge_old, prune=args.prune)
        print(t.to_string(index=False))
        if t.attrs.get("pruned"):
            print("Deleted rows for dates not in the folder:", t.attrs["pruned"])
    else:
        report = publish_bundle(args.bundle, publish=args.publish, merge=args.merge_old)
        print(json.dumps(report, indent=1, default=str))
    if not args.publish:
        print("Dry run: nothing written. Add --publish to write to c1_output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
