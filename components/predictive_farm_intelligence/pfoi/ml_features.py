"""Features for the direct machine-learning forecaster (``ml_direct.py``).

One row per origin x grain x horizon x series. Every input is dated before the origin:

* history features slice the daily panel and the milk target strictly before the origin
  (``history_features`` raises ``LeakageError`` otherwise);
* composition and the pregnancy pipeline come from the same as-of snapshots the herd
  engine uses (``day_cell`` on the day before the origin, gestation clocks with the
  pregnancy-check lag), each passed through ``data.check_before``;
* "same period last year" features are clipped to days before the origin.

Targets are period totals (milk, events) or period means (stocks) after the origin,
complete periods only. Milk periods must be scoreable on every day and from one source,
as in ``backtest_milk.period_actual``. Herd level only: no animal keys enter or leave.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .backtest_herd import EVENT_SERIES, STOCK_SERIES
from .categories import DIM_BANDS
from .data import DATA_START, LeakageError, SnapshotSource, check_before, snapshot_dates
from .periods import HORIZONS, period_bounds

MILK = "herd_milk"
# Mean gestation length (external biology, fixed): expected calving = conception + 280 days.
GESTATION_DAYS = 280
MAX_DUE_DAYS = 400
HISTORY_DAYS = 400
MIN_HISTORY_DAYS = 365
# Training uses every horizon up to the longest scored one; scoring uses HORIZONS only.
TRAIN_HORIZONS = {"monthly": tuple(range(1, 13)), "weekly": tuple(range(1, 14)),
                  "daily": tuple(range(1, 15))}
GRAINS_BY_ORIGIN = {"monthly": ("monthly",), "weekly": ("weekly", "daily")}
DEFAULT_SERIES = (MILK, "milking", "n_herd", "calvings", "dry_offs", "real_abortions",
                  "deaths", "culls", "sales")
META_COLUMNS = ("origin", "grain", "horizon", "period_start", "period_end", "series", "kind",
                "actual", "source", "base", "same_source")


def series_kind(series: str) -> str:
    if series == MILK:
        return "milk"
    if series in STOCK_SERIES:
        return "stock"
    if series in EVENT_SERIES:
        return "event"
    raise ValueError(f"unknown series {series!r}")


def daily_frame(panel: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Daily herd panel plus milk target on a complete calendar; milk only on scoreable days."""
    p = panel.copy()
    t = target[["date", "target_source", "target_litres", "is_scoreable", "identified_share"]].copy()
    p["date"], t["date"] = pd.to_datetime(p["date"]), pd.to_datetime(t["date"])
    f = p.merge(t, on="date", how="outer").set_index("date").sort_index()
    f = f.reindex(pd.date_range(f.index.min(), f.index.max(), freq="D"))
    ok = f["is_scoreable"].astype("boolean").fillna(False).astype(bool) & f["target_litres"].notna()
    f["ok"] = ok
    f["milk"] = f["target_litres"].where(ok)
    return f


def _mean(s: pd.Series) -> float:
    v = pd.to_numeric(s, errors="coerce").dropna()
    return float(v.mean()) if len(v) else np.nan


def _log_ratio(a: float, b: float) -> float:
    return float(np.log(a / b)) if np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0 else np.nan


def _days_since(mask: pd.Series, origin: pd.Timestamp) -> float:
    hit = mask[mask]
    return float((origin - hit.index.max()).days) if len(hit) else float(HISTORY_DAYS)


def history_features(f: pd.DataFrame, origin: date) -> dict | None:
    """Levels, recent changes and data quality from the days before ``origin``."""
    o = pd.Timestamp(origin)
    h = f.loc[o - timedelta(days=HISTORY_DAYS): o - timedelta(days=1)]
    if len(h) and h.index.max() >= o:
        raise LeakageError("history_features: uses data dated on/after the origin")
    if len(h) < MIN_HISTORY_DAYS:
        return None
    milk, cows = h["milk"], h["milking"].astype(float)
    m7, m28, m91, m365 = (_mean(milk.iloc[-n:]) for n in (7, 28, 91, 365))
    c28 = _mean(cows.iloc[-28:])
    ypc28 = m28 / c28 if c28 and np.isfinite(c28) and c28 > 0 else np.nan
    c_prev = _mean(cows.iloc[-119:-91])
    ypc_prev = _mean(milk.iloc[-119:-91]) / c_prev if c_prev and c_prev > 0 else np.nan
    src = h["target_source"].dropna()
    current = src.iloc[-1] if len(src) else None
    out = dict(
        milk_level=m28, log_milk_level=np.log(m28) if m28 > 0 else np.nan,
        milk_r7_28=_log_ratio(m7, m28), milk_r28_91=_log_ratio(m28, m91),
        milk_r91_365=_log_ratio(m91, m365),
        milk_ok_share_28=float(h["ok"].iloc[-28:].mean()),
        yield_per_cow_28=ypc28, yield_per_cow_trend=_log_ratio(ypc28, ypc_prev),
        source_delpro=float(current == "delpro") if current is not None else np.nan,
        days_since_source_change=_days_since(src.ne(current), o) if current is not None else np.nan,
        days_since_unscoreable=_days_since(~h["ok"], o),
        identified_share_28=_mean(h["identified_share"].iloc[-28:]),
    )
    for col in STOCK_SERIES:
        s = h[col].astype(float)
        level = float(s.iloc[-1])
        out[f"{col}_level"] = level
        out[f"{col}_r28"] = float(np.log((level + 1) / (s.iloc[-29] + 1)))
        out[f"{col}_r91"] = float(np.log((level + 1) / (s.iloc[-92] + 1)))
    for col in EVENT_SERIES:
        s = h[col].astype(float)
        out[f"{col}_d91"] = float(s.iloc[-91:].mean())
        out[f"{col}_d365"] = float(s.iloc[-365:].mean())
    out["_current_source"] = current
    return out


@dataclass
class Snapshot:
    features: dict
    due_cows: np.ndarray      # expected calvings of pregnant cows by day after the origin
    due_heifers: np.ndarray   # heifers with a service old enough to be checked, by due day


def _due(clock: pd.DataFrame) -> np.ndarray:
    """Expected calving day after the origin from gestation days on the day before it."""
    out = np.zeros(MAX_DUE_DAYS)
    if clock is None or not len(clock) or "gest" not in clock:
        return out
    c = clock[clock["gest"].notna()]
    days = np.clip(GESTATION_DAYS - c["gest"].to_numpy(dtype=float) - 1, 0, MAX_DUE_DAYS - 1)
    np.add.at(out, days.astype(int), c["n"].to_numpy(dtype=float))
    return out


def snapshot_features(cells: pd.DataFrame, milking_clock: pd.DataFrame, dry_clock: pd.DataFrame,
                      heifer_clock: pd.DataFrame) -> Snapshot:
    """Herd composition and pregnancy pipeline from the as-of aggregates."""
    milk = cells[cells["state"] == "milking"]
    nm = float(milk["n"].sum())
    share = lambda col, v: float(milk.loc[milk[col] == v, "n"].sum() / nm) if nm > 0 else np.nan  # noqa: E731
    feats = {f"milking_parity_{p}": share("parity_group", p) for p in ("1", "2", "3+")}
    feats.update({f"milking_dim_{b}": share("dim_band", b) for b in DIM_BANDS})
    total = float(cells["n"].sum())
    farm_born = cells.loc[cells["generation_group"].isin(["1", "2", "3+"]), "n"].sum()
    feats["farm_born_share"] = float(farm_born / total) if total > 0 else np.nan
    mc = milking_clock
    w = mc["n"].to_numpy(dtype=float) if len(mc) else np.array([])
    feats["milking_mean_dim"] = float(np.average(mc["dim"], weights=w)) if w.sum() > 0 else np.nan
    feats["milking_pregnant_share"] = (float(mc.loc[mc["gest"].notna(), "n"].sum() / w.sum())
                                       if w.sum() > 0 else np.nan)
    due_cows = _due(milking_clock) + _due(dry_clock)
    due_heifers = _due(heifer_clock)
    feats["due_cows_90"] = float(due_cows[:90].sum())
    feats["due_heifers_90"] = float(due_heifers[:90].sum())
    return Snapshot(feats, due_cows, due_heifers)


def load_snapshot(source, origin: date, cfg) -> Snapshot:
    """The four as-of aggregates for ``origin``, with the leakage guard (as ``load_origin_inputs``)."""
    asof, known_until = snapshot_dates(origin, cfg)
    cells = check_before(source.cells_on(asof), origin, "cells_on")
    milking = check_before(source.milking_clock(asof, known_until), origin, "milking_clock")
    dry = check_before(source.dry_clock(asof, known_until), origin, "dry_clock")
    heifer = check_before(source.heifer_clock(asof, known_until, cfg.pregnancy_check_lag_days),
                          known_until, "heifer_clock")
    return snapshot_features(cells, milking, dry, heifer)


def period_features(origin: date, start: date, end: date, snap: Snapshot | None) -> dict:
    a, b = (start - origin).days, (end - origin).days
    mid = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
    out = dict(lead_days=float(a), period_days=float(b - a),
               month_sin=float(np.sin(2 * np.pi * mid.month / 12)),
               month_cos=float(np.cos(2 * np.pi * mid.month / 12)),
               weekday=float(start.weekday()) if b - a == 1 else np.nan)
    if snap is not None:
        lo, hi = min(a, MAX_DUE_DAYS), min(b, MAX_DUE_DAYS)
        out["due_cows_period"] = float(snap.due_cows[lo:hi].sum() / (b - a))
        out["due_heifers_period"] = float(snap.due_heifers[lo:hi].sum() / (b - a))
        # cows calving shortly before the period start are early in lactation during it
        out["fresh_cows_at_start"] = float((snap.due_cows + snap.due_heifers)[max(0, lo - 60):lo].sum())
        out["due_before_start"] = float((snap.due_cows + snap.due_heifers)[:lo].sum())
    return out


class _Cum:
    """Prefix sums over the daily frame: window totals and day counts in O(1)."""

    def __init__(self, f: pd.DataFrame, cols: tuple[str, ...]):
        self.t0, self.n = f.index[0], len(f)
        self.sum, self.cnt = {}, {}
        for c in cols:
            v = pd.to_numeric(f[c], errors="coerce").to_numpy(dtype=float)
            ok = np.isfinite(v)
            self.sum[c] = np.concatenate([[0.0], np.cumsum(np.where(ok, v, 0.0))])
            self.cnt[c] = np.concatenate([[0], np.cumsum(ok)])
        self.delpro = np.concatenate([[0], np.cumsum((f["target_source"] == "delpro").to_numpy())])

    def idx(self, d) -> int:
        return (pd.Timestamp(d) - self.t0).days

    def window(self, col: str, s, e, clip: bool = True) -> tuple[float, int]:
        """(total, days with a value) over [s, e)."""
        i, j = self.idx(s), self.idx(e)
        if clip:
            i, j = min(max(i, 0), self.n), min(max(j, 0), self.n)
        if i < 0 or j > self.n or j <= i:
            return 0.0, 0
        return float(self.sum[col][j] - self.sum[col][i]), int(self.cnt[col][j] - self.cnt[col][i])

    def mean(self, col: str, s, e) -> float:
        tot, n = self.window(col, s, e)
        return tot / n if n else np.nan


def _ly_ratio(cum: _Cum, col: str, origin: date, start: date, end: date) -> float:
    """Last year's change from the same origin to the same window (days before the origin only)."""
    s, e = start - timedelta(days=365), min(end - timedelta(days=365), origin)
    if e <= s:
        return np.nan
    window = cum.mean(col, s, e)
    ref = cum.mean(col, origin - timedelta(days=393), origin - timedelta(days=365))
    if col != "milk":
        return float(np.log((window + 0.1) / (ref + 0.1))) if np.isfinite(window) and np.isfinite(ref) else np.nan
    return _log_ratio(window, ref)


def _actual(cum: _Cum, series: str, start: date, end: date) -> tuple[float, str | None] | None:
    """Period total (milk, events) or mean (stocks); None unless every day has a value
    (milk: every day scoreable and from one source)."""
    days = (end - start).days
    col = "milk" if series == MILK else series
    tot, n = cum.window(col, start, end, clip=False)
    if n != days:
        return None
    if series == MILK:
        i, j = cum.idx(start), cum.idx(end)
        delpro = int(cum.delpro[j] - cum.delpro[i])
        if delpro not in (0, days):
            return None
        return tot, "delpro" if delpro else "shipment"
    return (tot / days if series in STOCK_SERIES else tot), None


def _base(series: str, hist: dict, days: int) -> float:
    """The level each target is expressed against (known at the origin)."""
    kind = series_kind(series)
    if kind == "milk":
        return hist["milk_level"]
    if kind == "stock":
        return hist[f"{series}_level"]
    rate = (hist[f"{series}_d365"] * 365 + 0.5) / 365.5  # trailing daily rate, never exactly 0
    return rate * days


def feature_origins(start: date, end: date) -> list[date]:
    """Mondays and first-of-month days in [start, end)."""
    out, d = [], start
    while d < end:
        if d.weekday() == 0 or d.day == 1:
            out.append(d)
        d += timedelta(days=1)
    return out


def origin_grains(origin: date) -> tuple[str, ...]:
    g = ()
    if origin.day == 1:
        g += GRAINS_BY_ORIGIN["monthly"]
    if origin.weekday() == 0:
        g += GRAINS_BY_ORIGIN["weekly"]
    return g


def build_table(f: pd.DataFrame, origins: list[date], series: tuple[str, ...],
                snapshots: dict[date, Snapshot] | None, label_end: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(meta, X): one row per origin x grain x training horizon x series with a complete
    target ending on or before ``label_end``. ``snapshots`` = None leaves out the
    composition and pipeline features (ablation)."""
    cum = _Cum(f, ("milk", *[c for c in series if c != MILK]))
    meta, rows = [], []
    for origin in origins:
        hist = history_features(f, origin)
        if hist is None:
            continue
        snap = snapshots.get(origin) if snapshots is not None else None
        if snapshots is not None and snap is None:
            continue
        current = hist.pop("_current_source")
        common = dict(hist, **(snap.features if snap is not None else {}))
        for grain in origin_grains(origin):
            for h in TRAIN_HORIZONS[grain]:
                start, end = period_bounds(origin, grain, h)
                if end > label_end:
                    continue
                pf = period_features(origin, start, end, snap)
                for s in series:
                    act = _actual(cum, s, start, end)
                    if act is None:
                        continue
                    days = (end - start).days
                    base = _base(s, common, days)
                    if not np.isfinite(base) or (series_kind(s) == "milk" and base <= 0):
                        continue
                    col = "milk" if s == MILK else s
                    meta.append(dict(origin=origin, grain=grain, horizon=h, period_start=start,
                                     period_end=end, series=s, kind=series_kind(s), actual=act[0],
                                     source=act[1], base=base,
                                     same_source=act[1] is None or act[1] == current))
                    rows.append(dict(common, **pf, ly_ratio=_ly_ratio(cum, col, origin, start, end)))
    return pd.DataFrame(meta, columns=list(META_COLUMNS)), pd.DataFrame(rows)


def load_snapshots(source, origins: list[date], cfg) -> dict[date, Snapshot]:
    """Snapshots for every origin, batched through ``prefetch_snapshots`` when the source can."""
    from .data import prefetch_snapshots

    snap_source = SnapshotSource(source, prefetch_snapshots(source, origins, cfg))
    out = {}
    for o in origins:
        if o <= DATA_START + timedelta(days=31):
            continue
        out[o] = load_snapshot(snap_source, o, cfg)
    return out


# Feature groups for the SHAP summary (prefix -> group)
FEATURE_GROUPS = (
    ("milk_", "recent milk"), ("log_milk_level", "recent milk"), ("yield_per_cow", "yield per cow"),
    ("source_", "data quality"), ("days_since", "data quality"), ("identified_share", "data quality"),
    ("milking_parity", "parity mix"), ("milking_dim", "lactation stage mix"),
    ("milking_mean_dim", "lactation stage mix"), ("milking_pregnant", "pregnancy pipeline"),
    ("due_", "pregnancy pipeline"), ("fresh_cows", "pregnancy pipeline"),
    ("farm_born", "herd composition"), ("lead_days", "horizon"), ("period_days", "horizon"),
    ("month_", "season"), ("weekday", "season"), ("ly_ratio", "season"),
)


def feature_group(name: str) -> str:
    for prefix, group in FEATURE_GROUPS:
        if name.startswith(prefix):
            return group
    if any(name.startswith(c + "_") for c in STOCK_SERIES):
        return "herd counts"
    if any(name.startswith(c + "_") for c in EVENT_SERIES):
        return "recent event rates"
    return "other"


def scored(meta: pd.DataFrame) -> pd.Series:
    """Rows at the reported horizons (HORIZONS) of their grain."""
    return pd.Series([h in HORIZONS[g] for g, h in zip(meta["grain"], meta["horizon"])],
                     index=meta.index, dtype=bool)
