"""Owner-run heat-only refresh of published runs. Prints aggregate counts only.

AI agents must not run this module against a real database. Importing it does
not load environment files or create connections. Use --write to persist;
without it the command reports counts only. Other forecasts are untouched.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date, timedelta


def refreshed_heat(document: dict, source, until: date, thi_method: str = "v1") -> dict | None:
    """Compute only the new heat series, leaving the original heat outlook intact.

    With ``thi_method="v2"`` the climatology days also gain the usual chance of a hot day
    (``share_above_p75`` / ``_p90``, added fields only; existing values are unchanged)."""
    from .data import DATA_START
    from .drivers import heat_observations
    from .thi_forecast import forecast_thi, forecast_thi_daily

    original = document.get("heat")
    if not original:
        return None
    origin = date.fromisoformat(document["origin_date"])
    heat = deepcopy(original)
    lag = max(1, int(heat.get("weather_lag_days", 6)))
    # Fit before even loading later outcomes. The models independently enforce the lag.
    # v2 also needs every earlier year for the usual hot-day shares (as the page's climatology).
    start = DATA_START if thi_method == "v2" else origin - timedelta(days=1100 + lag)
    history = source.driver_daily(start, origin)
    if thi_method == "v2":
        knots = {k: heat.get(f"knot_{k}") for k in ("p75", "p90")}
        knots = knots if all(v is not None for v in knots.values()) else None
        heat["forecast"] = forecast_thi_daily(history, origin, lag, thresholds=knots)
        if knots and heat.get("climatology"):
            heat["climatology"] = _with_hot_shares(heat["climatology"], history, origin, knots)
    else:
        heat["forecast"] = forecast_thi(history, origin, lag)
    end = min(until, origin + timedelta(days=90))
    heat["realised"] = heat_observations(source.driver_daily(origin, end), origin, end) if end > origin else []
    return heat


def _with_hot_shares(clim: list[dict], history, origin: date, knots: dict) -> list[dict]:
    """Add the usual hot-day shares to existing climatology days (same rule as the page:
    complete days ending 60 days before the origin, +/-7 days of the date)."""
    import numpy as np
    import pandas as pd

    from .drivers import heat_climatology

    days = pd.to_datetime(history["date"])
    values = pd.to_numeric(history["thi_max"], errors="coerce")
    ok = history["weather_is_complete"].astype("boolean").fillna(False) & np.isfinite(values) \
        & (days <= pd.Timestamp(origin) - pd.Timedelta(days=60))
    hist = pd.Series(values[ok].to_numpy(), index=pd.DatetimeIndex(days[ok])).sort_index()
    shares = {c["date"]: c for c in heat_climatology(hist, origin, 120, 7, knots)}
    return [{**c, **{k: v for k, v in shares.get(c["date"], {}).items() if k.startswith("share_above_")}}
            for c in clim]


def refresh_documents(engine, source, until: date, origin: date | None = None, write: bool = False,
                      thi_method: str = "v1") -> dict:
    """Update heat fields atomically; optimistic comparison prevents lost concurrent edits."""
    from sqlalchemy import text

    counts = dict(runs=0, predictions=0, observations=0, unavailable=0, updated=0, conflicts=0)
    with engine.begin() as conn:
        sql = "SELECT origin_date, model_version, document FROM c1_output.run_document"
        if origin is not None:
            sql += " WHERE origin_date = :origin"
        for row in conn.execute(text(sql), {"origin": origin}).mappings().all():
            document = row["document"]
            if isinstance(document, str):
                document = json.loads(document)
            heat = refreshed_heat(document, source, until, thi_method)
            if heat is None:
                continue
            counts["runs"] += 1
            counts["predictions"] += len(heat["forecast"]["predictions"])
            counts["observations"] += len(heat["realised"])
            counts["unavailable"] += int(heat["forecast"]["status"] == "unavailable")
            if write:
                result = conn.execute(text(
                    "UPDATE c1_output.run_document SET document = jsonb_set(document, '{heat}', CAST(:heat AS jsonb)) "
                    "WHERE origin_date = :origin AND model_version = :version AND document = CAST(:original AS jsonb)"
                ), {"heat": json.dumps(heat, allow_nan=False), "origin": row["origin_date"],
                    "version": row["model_version"], "original": json.dumps(document, allow_nan=False)})
                counts["updated"] += result.rowcount
                counts["conflicts"] += int(result.rowcount == 0)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=date.fromisoformat, help="optional forecast date; default all published runs")
    parser.add_argument("--until", type=date.fromisoformat, help="first day without records (exclusive); default frozen data end")
    parser.add_argument("--write", action="store_true", help="persist heat fields in existing c1_output run documents")
    parser.add_argument("--thi-method", default="v1", choices=["v1", "v2"],
                        help="v2: seasonal curve plus learned daily changes, with hot-day chances")
    args = parser.parse_args()
    # Imports and connection creation happen only for an explicit owner invocation.
    from sqlalchemy import create_engine
    from .config import DatabaseSettings
    from .data import SqlHerdSource
    from .freeze import DATA_END

    engine = create_engine(DatabaseSettings.from_env().url)
    try:
        counts = refresh_documents(engine, SqlHerdSource.from_env(), args.until or DATA_END, args.origin, args.write,
                                    args.thi_method)
        print(json.dumps(counts, sort_keys=True))
        return 0 if counts["conflicts"] == 0 else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Database exceptions may contain connection secrets or source values.
        print("Heat refresh failed; no source values or credentials are printed.")
        raise SystemExit(1)
