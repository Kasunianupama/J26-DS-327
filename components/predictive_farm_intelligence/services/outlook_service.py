"""Serves Component 1 (PFOI) outputs from c1_output to the backend.

Reads only c1_output (as the backend's farmx_api login) and only when the environment
variable PFOI_OUTLOOK_DB=on, so tests and machines without the published schema never
open a connection. Without data it returns a small deterministic demo, labelled
``source = "demo"``; demo values are fictional.
"""
from __future__ import annotations

import json
import os
from datetime import date
from math import pi, sin
from typing import Callable

DEMO_ORIGIN = date(2026, 8, 1)
DEMO_VERSION = "pfoi-demo"


def _month(d: date, k: int) -> date:
    y, m = divmod(d.month - 1 + k, 12)
    return date(d.year + y, m + 1, 1)


class OutlookService:
    def __init__(self, engine_factory: Callable[[], object] | None = None, enabled: bool | None = None):
        self._factory = engine_factory
        self.enabled = (os.environ.get("PFOI_OUTLOOK_DB", "off") == "on") if enabled is None else enabled
        self._engine = None

    def _query(self, sql: str, **params) -> list[dict]:
        from sqlalchemy import text

        if self._engine is None:
            if self._factory is None:
                from backend.app.database.connection import create_database_engine

                self._factory = create_database_engine
            self._engine = self._factory()
        with self._engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(text(sql), params)]

    def _safe(self, sql: str, **params) -> list[dict] | None:
        if not self.enabled:
            return None
        try:
            return self._query(sql, **params)
        except Exception:  # noqa: BLE001 - not published here: fall back to the demo
            return None

    # ------------------------------------------------------------- page document
    def latest_run(self) -> dict | None:
        return self.run()

    def run(self, origin: date | None = None) -> dict | None:
        """The page document of one forecast date (newest build), or of the latest date."""
        if origin is None:
            rows = self._safe("SELECT document FROM c1_output.run_document "
                              "ORDER BY origin_date DESC, created_at DESC LIMIT 1")
        else:
            rows = self._safe("SELECT document FROM c1_output.run_document WHERE origin_date = :o "
                              "ORDER BY created_at DESC LIMIT 1", o=origin)
        if not rows:
            return None
        doc = rows[0]["document"]
        return json.loads(doc) if isinstance(doc, str) else doc

    def run_origins(self) -> list[dict]:
        """Forecast dates with a published page document (newest build per date), oldest first.
        ``realised_through`` is the last data day whose outcomes the document holds (or None)."""
        rows = self._safe(
            "SELECT DISTINCT ON (origin_date) origin_date, model_version, "
            "document->>'realised_through' AS realised_through "
            "FROM c1_output.run_document ORDER BY origin_date, created_at DESC") or []
        return [{"origin_date": str(r["origin_date"]), "model_version": r["model_version"],
                 "realised_through": r["realised_through"]} for r in rows]

    # ------------------------------------------------------------- contract tables
    def _latest_origin(self) -> tuple[date, str] | None:
        rows = self._safe("SELECT origin_date, model_version FROM c1_output.outlook "
                          "ORDER BY origin_date DESC, created_at DESC LIMIT 1")
        return (rows[0]["origin_date"], rows[0]["model_version"]) if rows else None

    def outlook(self, grain: str | None = None, series: str | None = None) -> dict:
        latest = self._latest_origin()
        if latest:
            origin, version = latest
            rows = self._safe(
                "SELECT * FROM c1_output.outlook WHERE origin_date = :o AND model_version = :v "
                "AND (:g IS NULL OR grain = :g) AND (:s IS NULL OR series = :s) "
                "ORDER BY grain, series, horizon", o=origin, v=version, g=grain, s=series) or []
            hist = self._safe(
                "SELECT * FROM c1_output.history WHERE origin_date = :o AND model_version = :v "
                "AND (:s IS NULL OR series = :s) ORDER BY series, period", o=origin, v=version, s=series) or []
            return {"source": "model", "origin_date": origin, "model_version": version,
                    "core_version": rows[0]["core_version"] if rows else None,
                    "outlook": rows, "history": hist}
        return self._demo_outlook(grain, series)

    def attribution(self, series: str | None = None, kind: str | None = None) -> dict:
        latest = self._latest_origin()
        if latest:
            origin, version = latest
            rows = self._safe(
                "SELECT * FROM c1_output.attribution WHERE origin_date = :o AND model_version = :v "
                "AND (:s IS NULL OR series = :s) AND (:k IS NULL OR kind = :k) "
                "ORDER BY series, target_period, factor", o=origin, v=version, s=series, k=kind) or []
            return {"source": "model", "origin_date": origin, "attribution": rows}
        return self._demo_attribution(series)

    # ------------------------------------------------------------- demo (fictional)
    def _demo_outlook(self, grain, series) -> dict:
        rows = []
        if grain in (None, "monthly") and series in (None, "herd_milk"):
            for h in range(1, 13):
                f = 30000 + 2500 * sin(2 * pi * h / 12)
                rows.append(dict(origin_date=DEMO_ORIGIN, target_period=_month(DEMO_ORIGIN, h - 1),
                                 grain="monthly", horizon=h, series="herd_milk", forecast=round(f, 1),
                                 lower=round(f * 0.85, 1), upper=round(f * 1.15, 1), quality_flag="ok",
                                 model_version=DEMO_VERSION, core_version=None))
        return {"source": "demo", "origin_date": DEMO_ORIGIN, "model_version": DEMO_VERSION,
                "core_version": None, "outlook": rows, "history": []}

    def _demo_attribution(self, series) -> dict:
        rows = []
        if series in (None, "herd_milk_litres_per_day"):
            for h, factor in enumerate(("herd_size", "parity_mix", "stage_mix", "pregnancy_mix", "yield_level")):
                rows.append(dict(origin_date=DEMO_ORIGIN, target_period=DEMO_ORIGIN, grain="monthly",
                                 series="herd_milk_litres_per_day", factor=factor,
                                 contribution=float([-40, 10, -15, -2, 0][h]), kind="forecast",
                                 model_version=DEMO_VERSION, core_version=None))
        return {"source": "demo", "origin_date": DEMO_ORIGIN, "attribution": rows}


outlook_service = OutlookService()
