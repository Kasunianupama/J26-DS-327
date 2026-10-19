"""Layer 2: driver layer (H2) on the remaining error of the milk forecast.

The structural (or adaptive) forecast is multiplied by exp(p), where p is a ridge
regression of log(actual / forecast) on herd-level drivers: heat, rain, health records,
milking sensors, record quality and season. Rules:

* **Known at the origin.** Every feature uses only days before the origin (trailing
  windows ending the day before; climatology from earlier days). Training rows are
  forecasts whose target period had ended by the origin.
* **Cautious onboarding (feature registry).** Per origin each feature is
  ``shadow`` (fewer than ``min_rows`` training rows have it: not used), ``probation``
  (used with a ``probation_mult`` times stronger pull to zero) or ``active``. For sparse
  records (health episodes, sensors) zeros before the first record, or after recording
  stops (no record in the last ``stop_days``), mean "not recorded", not "none happened".
* **Explainable.** Few standardised features, coefficients logged per origin, so the
  contribution of each driver can be shown (and reused for scenarios).

Works on backtest error tables plus a daily driver frame (``data.driver_daily``), so it is
tested on synthetic data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import warnings
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Feature:
    name: str
    group: str             # weather | health | sensor | quality | season
    count: str | None = None  # raw count column whose recording regime decides "missing"


FEATURES = (
    Feature("thi_28d", "weather"),
    Feature("thi_anom_28d", "weather"),
    Feature("hours_thi_28d", "weather"),
    Feature("thi_clim_target", "weather"),
    Feature("rain_30d", "weather"),
    Feature("rain_90d", "weather"),
    Feature("mastitis_per_cow_28d", "health", "mastitis_episodes"),
    Feature("udder_per_cow_28d", "health", "udder_teat_episodes"),
    Feature("sessions_per_cow_28d", "sensor", "n_sessions"),
    Feature("blood_per_session_28d", "sensor", "n_blood_alarms"),
    Feature("conductivity_per_session_28d", "sensor", "n_conductivity_alarms"),
    Feature("identified_share_28d", "quality"),
    Feature("season_sin", "season"),
    Feature("season_cos", "season"),
)
SHADOW, PROBATION, ACTIVE = "shadow", "probation", "active"


@dataclass(frozen=True)
class DriverConfig:
    series: str = "herd_milk"
    groups: tuple[str, ...] = ("weather", "health", "sensor", "quality", "season")
    lam: float = 5.0              # ridge penalty (standardised features)
    probation_mult: float = 10.0
    min_rows: int = 24            # training rows with the feature before it is used
    active_rows: int = 72         # ... and before it leaves probation
    min_train: int = 24
    half_life_days: float = 730.0
    max_adj: float = 0.3          # |log adjustment| cap
    stop_days: int = 180
    clim_halfwidth: int = 14


# --------------------------------------------------------------------------- features

def _daily_frame(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    d.index = pd.to_datetime(d["date"])
    d = d.sort_index()
    d = d.reindex(pd.date_range(d.index.min(), d.index.max()))
    w = d["weather_is_complete"].astype("boolean").fillna(False).astype(bool)
    cows = d["milking"].where(d["milking"] > 0)
    sess = d["n_sessions"].where(d["n_sessions"] > 0)
    out = pd.DataFrame(index=d.index)
    out["thi"] = d["thi_mean"].where(w)
    out["hrs"] = d["hours_thi_above"].where(w)
    out["rain"] = d["rain_total_mm"].where(w)
    out["mastitis"] = d["mastitis_episodes"] / cows
    out["udder"] = d["udder_teat_episodes"] / cows
    out["sessions"] = d["n_sessions"] / cows
    out["blood"] = d["n_blood_alarms"] / sess
    out["conductivity"] = d["n_conductivity_alarms"] / sess
    out["ids"] = d["identified_share"]
    for c in ("mastitis_episodes", "udder_teat_episodes", "n_sessions", "n_blood_alarms",
              "n_conductivity_alarms"):
        out[f"cnt_{c}"] = d[c]
    return out


def _doy_dist(a: np.ndarray, b: float) -> np.ndarray:
    x = np.abs(a - b) % 365.25
    return np.minimum(x, 365.25 - x)


class FeatureBuilder:
    """Feature values for (origin, period) pairs, from days before the origin only."""

    ROLL = {"thi_28d": ("thi", 28, "mean"), "hours_thi_28d": ("hrs", 28, "mean"),
            "rain_30d": ("rain", 30, "sum"), "rain_90d": ("rain", 90, "sum"),
            "mastitis_per_cow_28d": ("mastitis", 28, "mean"),
            "udder_per_cow_28d": ("udder", 28, "mean"),
            "sessions_per_cow_28d": ("sessions", 28, "mean"),
            "blood_per_session_28d": ("blood", 28, "mean"),
            "conductivity_per_session_28d": ("conductivity", 28, "mean"),
            "identified_share_28d": ("ids", 28, "mean")}

    def __init__(self, daily: pd.DataFrame, cfg: DriverConfig = DriverConfig()):
        self.cfg = cfg
        self.d = _daily_frame(daily)
        self.rolled = {}
        for name, (col, win, how) in self.ROLL.items():
            r = self.d[col].rolling(win, min_periods=int(win * 0.5))
            self.rolled[name] = r.mean() if how == "mean" else r.sum()
        self.count_cols = {f.name: f"cnt_{f.count}" for f in FEATURES if f.count}
        self.first_record = {}
        self.recent = {}
        for name, col in self.count_cols.items():
            pos = self.d[col].fillna(0) > 0
            self.first_record[name] = pos.idxmax() if pos.any() else None
            self.recent[name] = pos.astype(float).rolling(cfg.stop_days, min_periods=1).sum()
        self.doy = self.d.index.dayofyear.to_numpy().astype(float)
        self.thi = self.d["thi"].to_numpy()

    def _at(self, series: pd.Series, day: pd.Timestamp) -> float:
        if day < series.index[0] or day > series.index[-1]:
            return np.nan
        return float(series.loc[day])

    def recorded(self, name: str, origin: date) -> bool:
        """Is this sparse record being kept at the origin (known from earlier days)?"""
        if name not in self.count_cols:
            return True
        day = pd.Timestamp(origin) - pd.Timedelta(days=1)
        first = self.first_record[name]
        if first is None or first > day:
            return False
        if first <= day - pd.Timedelta(days=self.cfg.stop_days):
            return self._at(self.recent[name], day) > 0
        return True

    def _clim(self, origin: date, center_doy: float, halfwidth: float) -> float:
        cut = len(self.d.index[self.d.index < pd.Timestamp(origin) - pd.Timedelta(days=60)])
        if cut < 365:
            return np.nan
        m = _doy_dist(self.doy[:cut], center_doy) <= halfwidth
        v = self.thi[:cut][m]
        v = v[np.isfinite(v)]
        return float(v.mean()) if len(v) >= 20 else np.nan

    def row(self, origin: date, start: date, end: date) -> dict:
        day = pd.Timestamp(origin) - pd.Timedelta(days=1)
        out = {}
        for name in self.ROLL:
            out[name] = self._at(self.rolled[name], day) if self.recorded(name, origin) else np.nan
        center = (pd.Timestamp(origin) - pd.Timedelta(days=14)).dayofyear
        clim_now = self._clim(origin, center, self.cfg.clim_halfwidth)
        out["thi_anom_28d"] = out["thi_28d"] - clim_now if np.isfinite(clim_now) else np.nan
        span = (pd.Timestamp(end) - pd.Timestamp(start)).days
        mid = pd.Timestamp(start) + pd.Timedelta(days=span / 2)
        out["thi_clim_target"] = self._clim(origin, mid.dayofyear, span / 2 + self.cfg.clim_halfwidth / 2)
        ang = 2 * np.pi * mid.dayofyear / 365.25
        out["season_sin"], out["season_cos"] = np.sin(ang), np.cos(ang)
        return out

    def matrix(self, rows: pd.DataFrame) -> pd.DataFrame:
        names = [f.name for f in FEATURES if f.group in self.cfg.groups]
        cache = {}
        vals = []
        for o, s, e in zip(rows["origin"], rows["period_start"], rows["period_end"]):
            k = (o, s, e)
            if k not in cache:
                cache[k] = self.row(o, s, e)
            vals.append([cache[k][n] for n in names])
        return pd.DataFrame(vals, columns=names, index=rows.index)


# --------------------------------------------------------------------------- model

@dataclass
class DriverResult:
    errors: pd.DataFrame           # rows of the new model
    coefficients: pd.DataFrame     # origin, grain, horizon, feature, status, coef, n_rows
    registry: pd.DataFrame = field(default_factory=pd.DataFrame)  # status counts per feature


def _ridge(Z: np.ndarray, y: np.ndarray, w: np.ndarray, lam: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(y)), Z])
    P = np.diag(np.concatenate([[0.0], lam]))
    AtW = A.T * w
    return np.linalg.solve(AtW @ A + P, AtW @ y)


def driver_layer(errors: pd.DataFrame, daily: pd.DataFrame, base_model: str,
                 new_model: str | None = None, cfg: DriverConfig = DriverConfig(),
                 builder: FeatureBuilder | None = None) -> DriverResult:
    new_model = new_model or f"{base_model}_drivers"
    rows = errors[(errors["model"] == base_model) & (errors["series"] == cfg.series)].copy()
    for col in ("origin", "period_start", "period_end"):
        rows[col] = pd.to_datetime(rows[col]).dt.date
    builder = builder or FeatureBuilder(daily, cfg)
    X = builder.matrix(rows)
    names = list(X.columns)
    f = rows["forecast"].to_numpy(dtype=float)
    a = rows["actual"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        y_all = np.where((f > 0) & (a > 0), np.log(a / f), np.nan)
    adj = np.zeros(len(rows))
    coef_rows = []
    pos = {ix: i for i, ix in enumerate(rows.index)}
    for (grain, horizon), g in rows.groupby(["grain", "horizon"]):
        gi = np.array([pos[ix] for ix in g.index])
        o = pd.to_datetime(g["origin"]).to_numpy()
        e = pd.to_datetime(g["period_end"]).to_numpy()
        Xg = X.loc[g.index].to_numpy(dtype=float)
        yg = y_all[gi]
        for u in np.unique(o):
            tr = (e <= u) & np.isfinite(yg)
            now = np.where(o == u)[0]
            if tr.sum() < cfg.min_train:
                continue
            Xt, yt = Xg[tr], yg[tr]
            w = 0.5 ** (((u - e[tr]) / np.timedelta64(1, "D")) / cfg.half_life_days)
            n_f = np.isfinite(Xt).sum(axis=0)
            with warnings.catch_warnings():  # all-missing columns give NaN, handled below
                warnings.simplefilter("ignore", RuntimeWarning)
                mu = np.nanmean(Xt, axis=0)
                sd = np.nanstd(Xt, axis=0)
            status = np.where(n_f < cfg.min_rows, SHADOW,
                              np.where(n_f < cfg.active_rows, PROBATION, ACTIVE))
            use = (status != SHADOW) & np.isfinite(sd) & (sd > 0)
            beta = np.zeros(len(names))
            b0 = float(np.average(yt, weights=w))
            if use.any():
                Z = np.where(np.isfinite(Xt[:, use]), (Xt[:, use] - mu[use]) / sd[use], 0.0)
                lam = np.where(status[use] == PROBATION, cfg.lam * cfg.probation_mult, cfg.lam)
                sol = _ridge(Z, yt, w, lam)
                b0, beta[use] = sol[0], sol[1:]
            for k in now:
                z = np.where(np.isfinite(Xg[k]) & use, (Xg[k] - mu) / np.where(sd > 0, sd, 1), 0.0)
                adj[gi[k]] = float(np.clip(b0 + z @ beta, -cfg.max_adj, cfg.max_adj))
            day = pd.Timestamp(u).date()
            for j, n in enumerate(names):
                coef_rows.append(dict(origin=day, grain=grain, horizon=int(horizon), feature=n,
                                      status=status[j], coef=float(beta[j]), n_rows=int(n_f[j])))
    out = rows.copy()
    out["forecast"] = f * np.exp(adj)
    out["error"] = out["forecast"] - out["actual"]
    out["model"] = new_model
    coefs = pd.DataFrame(coef_rows)
    reg = (coefs.groupby(["feature", "status"]).size().unstack(fill_value=0)
           if len(coefs) else pd.DataFrame())
    return DriverResult(errors=out, coefficients=coefs, registry=reg)
