"""DelPro-only milk target (user request 2026-10-22).

The published target (``day_panel.target_*``) is shipped litres until July 2022 and DelPro litres
after. The two are different measures: DelPro captured 65-106 % of shipped litres, drifting over
time, and shipments fell about 59 % from August 2020 to June 2022 while DelPro fell about 32 %.
This option scores and calibrates the milk model on **DelPro litres only**, wherever they exist
(from August 2020), so one measuring stick is used throughout.

Daily DelPro target (rules fixed before any real-data run):

* litres = ``milk_delpro_total`` (identified + unidentified litres) where it is above zero;
  source ``delpro``; days without DelPro litres have no target (missing, never zero);
* scoreable only when: no data gap; identified share >= 0.2 (the project's "verified" rule,
  ``episodes.VERIFIED_MIN_SHARE``); at most 20 litres per recorded milking cow; and not
  suspiciously low (below half the mean of the earlier scoreable days in the previous 28 days,
  at least 7 of them; past days only, as the ETL's ``is_suspect_low``).

``DelProTargetSource`` wraps any herd source and serves this frame from ``target_daily``, so the
level k, the anchor, the benchmarks and the scoring of the existing milk backtest all use it
unchanged; the engine, curve and frozen configuration hashes are untouched.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .episodes import MAX_LITRES_PER_COW_DAY, VERIFIED_MIN_SHARE

DELPRO_START = date(2020, 8, 1)
SUSPECT_LOW_SHARE = 0.5
SUSPECT_WINDOW_DAYS = 28
SUSPECT_MIN_DAYS = 7
TARGET_COLUMNS = ["date", "target_source", "target_litres", "is_scoreable", "identified_share", "data_gap"]


def delpro_target(frame: pd.DataFrame) -> pd.DataFrame:
    """Target frame (``target_daily`` columns) from daily ``milk_delpro_total``, ``milking``,
    ``identified_share`` and ``data_gap``."""
    d = frame.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d = d.sort_values("date").reset_index(drop=True)
    litres = pd.to_numeric(d["milk_delpro_total"], errors="coerce")
    cows = pd.to_numeric(d["milking"], errors="coerce")
    ids = pd.to_numeric(d["identified_share"], errors="coerce")
    gap = pd.to_numeric(d["data_gap"], errors="coerce").fillna(0) > 0
    has = litres > 0
    per_cow = (litres / cows).where(cows > 0)
    candidate = has & ~gap & (ids >= VERIFIED_MIN_SHARE) & per_cow.notna() & (per_cow <= MAX_LITRES_PER_COW_DAY)
    # suspiciously low: below half the mean of earlier candidate days in the previous 28 days
    s = pd.Series(litres.where(candidate).to_numpy(), index=pd.to_datetime(d["date"]))
    prior = s.shift(1, freq="D").rolling(f"{SUSPECT_WINDOW_DAYS}D", min_periods=SUSPECT_MIN_DAYS).mean()
    prior = prior.reindex(pd.to_datetime(d["date"])).to_numpy()
    low = np.isfinite(prior) & (litres.to_numpy() < SUSPECT_LOW_SHARE * prior)
    out = pd.DataFrame({
        "date": d["date"],
        "target_source": np.where(has, "delpro", None),
        "target_litres": litres.where(has),
        "is_scoreable": (candidate & ~low).to_numpy(),
        "identified_share": ids,
        "data_gap": d["data_gap"],
    })
    return out[TARGET_COLUMNS]


class DelProTargetSource:
    """Any herd source, but ``target_daily`` is the DelPro-only target."""

    def __init__(self, source):
        self._source = source

    def __getattr__(self, name):
        return getattr(self._source, name)

    def target_daily(self, start: date, end: date) -> pd.DataFrame:
        return delpro_target(self._source.delpro_daily(start, end))


class DelProFactory:
    """Picklable factory for worker processes: wraps the base factory's source."""

    def __init__(self, factory):
        self.factory = factory

    def __call__(self):
        return DelProTargetSource(self.factory())


def target_rule(hits: pd.DataFrame, hits_y: pd.DataFrame, record: str, delpro: str):
    """Pre-registered rule (2026-10-22), on periods trusted under both targets: the DelPro-target
    model's share within +-10 % rises at week 13, month 6 and month 12; no forecast year falls by
    more than 5 points (mean of those cells); and 2021, the year the shipment decline broke, rises."""
    from .specialists import TRACK_B_CELLS, track_b_rule

    checks, _ = track_b_rule(hits, hits_y, record, delpro)
    cells = set(TRACK_B_CELLS)
    hy = hits_y[[(g, int(h)) in cells for g, h in zip(hits_y["grain"], hits_y["horizon"])]]
    y21 = hy[hy["year"] == 2021].groupby("model")["within_10"].mean()
    v = float(y21.get(delpro, np.nan) - y21.get(record, np.nan))
    checks = pd.concat([checks, pd.DataFrame([dict(check="2021 rises (mean of the three cells)", value=v,
                                                   passed=bool(np.isfinite(v) and v > 0))])],
                       ignore_index=True)
    return checks, bool(checks["passed"].all())
