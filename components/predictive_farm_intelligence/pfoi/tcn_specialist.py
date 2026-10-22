"""Change-sensitive structural TCN for direct weekly and monthly milk forecasts.

This is an experimental candidate, not a published PFOI model.  It keeps the current
``milk_baseline_adaptive`` forecast as the biological structure and learns a bounded
log correction for eight target cells: weeks 1/4/8/13 and months 1/3/6/12.

Every input is a herd-level daily aggregate dated before the forecast origin.  A causal
temporal convolutional encoder reads 112 days, then horizon-specific stable and shock
experts are blended by a continuous learned gate.  Explicit changes in milk per cow,
milking cows, total herd, herd flows and mastitis make abrupt changes visible without asking
the network to infer ratios from raw levels.  A small causal online adapter subsequently
uses only this candidate's completed earlier errors; it never uses an unfinished target.

The network is refitted once per fold year (2019--2023).  Training and validation target
periods must have ended before their cutoffs, and the 2024+ test block is never read.
Nothing in this module opens a database; callers pass aggregate frames.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .gate import daily_signals
from .episodes import VERIFIED_BANDS
from .specialists import A_MAX_CELL_FALL, A_MAX_STABLE_FALL, A_STABLE_YEAR, MISS_TOL, _keyed, matched_hits

LOOKBACK = 112
REF_DAYS = 28
MIN_REF = 14
Z_CLIP = 5.0
CELLS = (("weekly", 1), ("weekly", 4), ("weekly", 8), ("weekly", 13),
         ("monthly", 1), ("monthly", 3), ("monthly", 6), ("monthly", 12))
CELL_INDEX = {c: i for i, c in enumerate(CELLS)}
MODEL = "structural_gated_tcn"
FOLD_YEARS = (2019, 2020, 2021, 2022, 2023)

SEQ = (
    "log_milk_rel", "trusted", "log_milk_change", "log_ypc_rel", "log_milking_rel",
    "log_herd_rel", "exit_rate", "entry_rate", "calving_rate", "abortion_rate",
    "mastitis_rate", "health_recorded", "thi_scaled", "weather_complete", "identified_share",
)
CHANGE = (
    "milk_change_7_28", "ypc_change_7_28", "cows_change_7_28", "herd_change_7_28",
    "exit_change_7_28", "mastitis_change_7_28",
)
BASE_STATIC = (
    "src_delpro", "source_age_years", "trusted_share_28d", "doy_sin", "doy_cos",
    *CHANGE, *(f"abs_{x}" for x in CHANGE),
)
BASE_FORECAST_STATIC = tuple(f"base_{g}_{h}" for g, h in CELLS)
BASE_MASK_STATIC = tuple(f"base_mask_{g}_{h}" for g, h in CELLS)
STATIC = BASE_STATIC + BASE_FORECAST_STATIC + BASE_MASK_STATIC


@dataclass(frozen=True)
class TCNConfig:
    """Fixed settings for the first real-data evaluation; do not tune after seeing it."""
    channels: int = 32
    dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32)
    kernel: int = 3
    dropout: float = 0.1
    lr: float = 1e-3
    weight_decay: float = 1e-4
    batch: int = 64
    max_epochs: int = 150
    patience: int = 15
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    val_months: int = 6
    min_train: int = 60
    change_scale: float = 0.10
    max_weight: float = 4.0
    max_log_short: float = float(np.log(2.0))
    max_log_long: float = float(np.log(1.5))
    adapter_days: int = 180
    adapter_half_life: float = 60.0
    adapter_min: int = 3
    adapter_max_log: float = float(np.log(1.25))
    shock_threshold: float = 0.10
    device: str = "cpu"
    fold_years: tuple[int, ...] = field(default=FOLD_YEARS)


@dataclass
class Daily:
    days: list[date]
    litres: np.ndarray
    trusted: np.ndarray
    log_ypc: np.ndarray
    milking: np.ndarray
    herd: np.ndarray
    exits: np.ndarray
    entries: np.ndarray
    calvings: np.ndarray
    abortions: np.ndarray
    mastitis: np.ndarray
    sessions: np.ndarray
    blood_alarms: np.ndarray
    conductivity_alarms: np.ndarray
    health_recorded: np.ndarray
    thi: np.ndarray
    weather_complete: np.ndarray
    ids: np.ndarray
    source: np.ndarray
    pos: dict[date, int]

    @classmethod
    def from_frame(cls, daily: pd.DataFrame) -> "Daily":
        sig = daily_signals(daily)
        raw = daily.copy()
        raw.index = pd.to_datetime(raw["date"])
        raw = raw[~raw.index.duplicated()].reindex(sig.index)

        def num(name: str) -> np.ndarray:
            if name not in raw:
                return np.full(len(raw), np.nan)
            return pd.to_numeric(raw[name], errors="coerce").to_numpy(dtype=float)

        weather = num("weather_is_complete")
        mastitis = num("mastitis_episodes")
        sessions = num("n_sessions")
        blood = num("n_blood_alarms")
        conductivity = num("n_conductivity_alarms")
        # Zero diagnoses are evidence only on a day with an explicit health/sensor record.
        # Positive observations remain evidence even when older extracts lack n_sessions.
        health_recorded = ((np.isfinite(sessions) & (sessions > 0)) |
                           (np.isfinite(mastitis) & (mastitis > 0)) |
                           (np.isfinite(blood) & (blood > 0)) |
                           (np.isfinite(conductivity) & (conductivity > 0)))
        return cls(
            days=list(sig.index.date),
            litres=num("target_litres"),
            trusted=sig["trusted"].to_numpy(dtype=bool),
            log_ypc=sig["log_ypc"].to_numpy(dtype=float),
            milking=sig["milking"].to_numpy(dtype=float),
            herd=sig["n_herd"].to_numpy(dtype=float),
            exits=num("exits"),
            entries=num("external_entries"),
            calvings=num("calvings"),
            abortions=num("real_abortions"),
            mastitis=mastitis,
            sessions=sessions,
            blood_alarms=blood,
            conductivity_alarms=conductivity,
            health_recorded=np.asarray(health_recorded, dtype=bool),
            thi=num("thi_mean"),
            weather_complete=np.isfinite(weather) & (weather > 0),
            ids=sig["ids"].to_numpy(dtype=float),
            source=sig["source"].to_numpy(dtype=object),
            pos={d: i for i, d in enumerate(sig.index.date)},
        )


@dataclass
class Samples:
    origin: np.ndarray
    seq: np.ndarray
    stat: np.ndarray
    y: np.ndarray
    m: np.ndarray
    w: np.ndarray
    shock: np.ndarray

    def __len__(self) -> int:
        return len(self.origin)

    def labelled(self) -> "Samples":
        take = self.m.sum(axis=1) > 0
        return Samples(*(getattr(self, k)[take] for k in ("origin", "seq", "stat", "y", "m", "w", "shock")))


def _empty() -> Samples:
    return Samples(np.array([], dtype=object), np.zeros((0, LOOKBACK, len(SEQ))),
                   np.zeros((0, len(STATIC))), np.zeros((0, len(CELLS))), np.zeros((0, len(CELLS))),
                   np.zeros(0), np.zeros(0))


def _finite_mean(x: np.ndarray) -> float:
    return float(np.nanmean(x)) if np.isfinite(x).any() else np.nan


def _safe_log_ratio(a: float, b: float) -> float:
    return float(np.log(a / b)) if np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0 else 0.0


def _rate(events: np.ndarray, exposure: np.ndarray) -> np.ndarray:
    ok = np.isfinite(events) & np.isfinite(exposure) & (exposure > 0) & (events >= 0)
    return np.where(ok, np.log1p(1000.0 * np.where(ok, events, 0.0) / np.where(ok, exposure, 1.0)), 0.0)


def _trusted_stock(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Reject an isolated >2x stock jump; accept it once a second observation confirms it."""
    x = np.asarray(values, dtype=float).copy()
    ok = np.isfinite(x) & (x > 0)
    for i in range(1, len(x)):
        if not (ok[i] and ok[i - 1]) or abs(np.log(x[i] / x[i - 1])) <= np.log(2.0):
            continue
        confirmed = i + 1 < len(x) and ok[i + 1] and abs(np.log(x[i + 1] / x[i])) <= np.log(1.25)
        if not confirmed:
            ok[i] = False
    return np.where(ok, x, np.nan), ok


def _recent_change(values: np.ndarray, valid: np.ndarray | None = None) -> float:
    """Log(last 7-day level / last 28-day level), with missing values ignored."""
    x = np.asarray(values, dtype=float)
    ok = np.isfinite(x) if valid is None else np.isfinite(x) & np.asarray(valid, dtype=bool)
    a = _finite_mean(np.where(ok[-7:], x[-7:], np.nan))
    b = _finite_mean(np.where(ok[-28:], x[-28:], np.nan))
    return _safe_log_ratio(a, b)


def _event_change(events: np.ndarray, exposure: np.ndarray, recorded: np.ndarray | None = None) -> float:
    ok = np.isfinite(events) & np.isfinite(exposure) & (exposure > 0)
    if recorded is not None:
        ok &= recorded
    def r(sl: slice) -> float:
        use = ok[sl]
        return float(np.nansum(events[sl][use]) / np.nansum(exposure[sl][use])) if use.any() else np.nan
    return _safe_log_ratio(r(slice(-7, None)) + 1e-6, r(slice(-28, None)) + 1e-6)


def _window(dl: Daily, origin: date, base_at_origin: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, float] | None:
    i = dl.pos.get(origin)
    if i is None or i < LOOKBACK:
        return None
    lo = i - LOOKBACK
    tr = dl.trusted[lo:i]
    if not tr.any():
        return None
    cur = dl.source[lo:i][tr][-1]
    same = tr & (dl.source[lo:i] == cur)
    same28 = same[-REF_DAYS:]
    if same28.sum() < MIN_REF:
        return None

    litres = dl.litres[lo:i]
    ypc = np.exp(dl.log_ypc[lo:i])
    cows, cows_valid = _trusted_stock(dl.milking[lo:i])
    herd, herd_valid = _trusted_stock(dl.herd[lo:i])
    R = _finite_mean(np.where(same[-REF_DAYS:], litres[-REF_DAYS:], np.nan))
    r_ypc = _finite_mean(np.where(same[-REF_DAYS:], ypc[-REF_DAYS:], np.nan))
    r_cows = _finite_mean(cows[-REF_DAYS:])
    r_herd = _finite_mean(herd[-REF_DAYS:])
    if not np.isfinite(R) or R <= 0:
        return None

    level = np.where(same, np.log(np.where(same, litres, R) / R), 0.0)
    change = np.zeros(LOOKBACK)
    both = same[1:] & same[:-1]
    change[1:] = np.where(both, level[1:] - level[:-1], 0.0)
    ypc_rel = np.where(same & np.isfinite(ypc) & (ypc > 0),
                       np.log(np.where(same & np.isfinite(ypc) & (ypc > 0), ypc, r_ypc) / r_ypc), 0.0)
    cows_ok = np.isfinite(cows) & (cows > 0) & np.isfinite(r_cows) & (r_cows > 0)
    herd_ok = np.isfinite(herd) & (herd > 0) & np.isfinite(r_herd) & (r_herd > 0)
    cows_rel = np.where(cows_ok, np.log(np.where(cows_ok, cows, r_cows) / r_cows), 0.0)
    herd_rel = np.where(herd_ok, np.log(np.where(herd_ok, herd, r_herd) / r_herd), 0.0)
    health = dl.health_recorded[lo:i]
    weather = dl.weather_complete[lo:i]
    seq = np.stack([
        level, same.astype(float), change, ypc_rel, cows_rel, herd_rel,
        _rate(dl.exits[lo:i], herd), _rate(dl.entries[lo:i], herd), _rate(dl.calvings[lo:i], herd),
        _rate(dl.abortions[lo:i], herd),
        _rate(dl.mastitis[lo:i], cows), health.astype(float),
        np.where(weather & np.isfinite(dl.thi[lo:i]), (dl.thi[lo:i] - 70.0) / 10.0, 0.0),
        weather.astype(float), np.nan_to_num(dl.ids[lo:i], nan=0.0),
    ], axis=1)

    changes = [
        _recent_change(litres, same), _recent_change(ypc, same), _recent_change(cows, cows_valid),
        _recent_change(herd, herd_valid), _event_change(dl.exits[lo:i], herd),
        _event_change(dl.mastitis[lo:i], cows, health),
    ]
    previous = np.nonzero((dl.source[:i] != cur) & (dl.source[:i] != None))[0]  # noqa: E711
    source_age = i - previous[-1] if len(previous) else i
    doy = 2.0 * np.pi * origin.timetuple().tm_yday / 365.25
    stat = [float(cur == "delpro"), min(source_age / 365.0, 5.0), float(tr[-REF_DAYS:].mean()),
            np.sin(doy), np.cos(doy), *changes, *(abs(x) for x in changes)]
    keyed = _keyed(base_at_origin)
    keyed = keyed.drop_duplicates(["grain", "horizon"]).set_index(["grain", "horizon"])
    for cell in CELLS:
        if cell in keyed.index and float(keyed.loc[cell, "forecast"]) > 0:
            row = keyed.loc[cell]
            days = max((row["period_end"] - row["period_start"]).days, 1)
            stat.append(_safe_log_ratio(float(row["forecast"]) / days, R))
        else:
            stat.append(0.0)
    stat.extend(float(cell in keyed.index) for cell in CELLS)
    shock = float(max(abs(x) for x in changes[:4]))
    return np.nan_to_num(seq, nan=0.0, posinf=Z_CLIP, neginf=-Z_CLIP), np.nan_to_num(stat), shock


def build_samples(dl: Daily, base: pd.DataFrame, origins, target_end: date | None,
                  cfg: TCNConfig = TCNConfig()) -> Samples:
    """Build origin windows; labels count only when their complete period ended by ``target_end``."""
    b = _keyed(base)
    b = b[[(g, int(h)) in CELL_INDEX for g, h in zip(b["grain"], b["horizon"])]]
    by_origin = {o: x for o, x in b.groupby("origin")}
    rows = {k: [] for k in ("origin", "seq", "stat", "y", "m", "w", "shock")}
    for origin in sorted(set(origins)):
        bo = by_origin.get(origin)
        if bo is None:
            continue
        win = _window(dl, origin, bo)
        if win is None:
            continue
        seq, stat, shock = win
        y, m = np.zeros(len(CELLS)), np.zeros(len(CELLS))
        if target_end is not None:
            for d in bo.to_dict("records"):
                cell = (d["grain"], int(d["horizon"]))
                j = CELL_INDEX.get(cell)
                if j is None or d["period_end"] > target_end:
                    continue
                if float(d["actual"]) > 0 and float(d["forecast"]) > 0:
                    y[j] = np.log(float(d["actual"]) / float(d["forecast"]))
                    m[j] = 1.0
        rows["origin"].append(origin)
        rows["seq"].append(seq)
        rows["stat"].append(stat)
        rows["y"].append(y)
        rows["m"].append(m)
        rows["w"].append(1.0 + min(cfg.max_weight - 1.0, shock / cfg.change_scale))
        rows["shock"].append(shock)
    if not rows["origin"]:
        return _empty()
    return Samples(np.asarray(rows["origin"], dtype=object), np.stack(rows["seq"]), np.stack(rows["stat"]),
                   np.stack(rows["y"]), np.stack(rows["m"]), np.asarray(rows["w"]),
                   np.asarray(rows["shock"]))


def _torch():
    import torch
    return torch


def resolve_device(requested: str = "auto") -> str:
    """Resolve a compute backend without silently accepting an unavailable forced device."""
    torch = _torch()
    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable; use --device auto or cpu")
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS was requested but is unavailable to this Python process; use --device auto or cpu")
    if requested not in {"cpu", "cuda", "mps"}:
        raise ValueError("device must be one of auto, cpu, mps, cuda")
    return requested


class Scaler:
    """Training-only z-scores for static inputs."""
    def __init__(self, stat: np.ndarray):
        self.mu = stat.mean(axis=0)
        sd = stat.std(axis=0)
        self.sd = np.where(sd > 1e-3, sd, 1.0)

    def __call__(self, stat: np.ndarray) -> np.ndarray:
        return np.clip((stat - self.mu) / self.sd, -Z_CLIP, Z_CLIP)


def make_net(cfg: TCNConfig = TCNConfig()):
    torch = _torch()
    nn = torch.nn

    class CausalBlock(nn.Module):
        def __init__(self, in_ch: int, out_ch: int, dilation: int):
            super().__init__()
            pad = (cfg.kernel - 1) * dilation
            self.pad = pad
            self.conv = nn.Conv1d(in_ch, out_ch, cfg.kernel, dilation=dilation, padding=pad)
            self.drop = nn.Dropout(cfg.dropout)
            self.skip = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else nn.Identity()

        def forward(self, x):
            y = self.conv(x)
            if self.pad:
                y = y[..., :-self.pad]
            return torch.relu(self.skip(x) + self.drop(torch.relu(y)))

    class StructuralGatedTCN(nn.Module):
        def __init__(self):
            super().__init__()
            blocks = []
            in_ch = len(SEQ)
            for d in cfg.dilations:
                blocks.append(CausalBlock(in_ch, cfg.channels, d))
                in_ch = cfg.channels
            self.tcn = nn.Sequential(*blocks)
            self.stat = nn.Sequential(nn.Linear(len(STATIC), 32), nn.ReLU(), nn.Dropout(cfg.dropout))
            width = 2 * cfg.channels + 32
            self.stable = nn.Sequential(nn.Linear(width, 32), nn.ReLU(), nn.Linear(32, len(CELLS)))
            self.shock = nn.Sequential(nn.Linear(width, 32), nn.ReLU(), nn.Linear(32, len(CELLS)))
            self.gate = nn.Sequential(nn.Linear(width, 32), nn.ReLU(), nn.Linear(32, len(CELLS)))
            for head in (self.stable[-1], self.shock[-1]):
                nn.init.zeros_(head.weight)
                nn.init.zeros_(head.bias)
            nn.init.constant_(self.gate[-1].bias, -1.5)
            long_cells = {("weekly", 13), ("monthly", 6), ("monthly", 12)}
            limits = [cfg.max_log_long if cell in long_cells else cfg.max_log_short for cell in CELLS]
            self.register_buffer("limits", torch.tensor(limits, dtype=torch.float32))

        def forward(self, seq, stat):
            z = self.tcn(seq.transpose(1, 2))
            enc = torch.cat([z[..., -1], z.mean(dim=-1), self.stat(stat)], dim=1)
            gate = torch.sigmoid(self.gate(enc))
            raw = (1.0 - gate) * self.stable(enc) + gate * self.shock(enc)
            return self.limits * torch.tanh(raw), gate

    return StructuralGatedTCN()


def _tensors(s: Samples, scaler: Scaler):
    torch = _torch()
    t = lambda x: torch.as_tensor(np.asarray(x, dtype=np.float32))  # noqa: E731
    return t(s.seq), t(scaler(s.stat)), t(s.y), t(s.m), t(s.w)


def _on_device(tensors, device: str):
    return tuple(x.to(device) for x in tensors)


def balanced_huber(pred, y, mask, weight):
    """Huber loss averaged within each available horizon, then equally across horizons."""
    torch = _torch()
    raw = torch.nn.functional.smooth_l1_loss(pred, y, reduction="none")
    mw = mask * weight[:, None]
    den = mw.sum(dim=0)
    per_cell = (raw * mw).sum(dim=0) / den.clamp(min=1.0)
    return per_cell[den > 0].mean() if (den > 0).any() else raw.sum() * 0.0


@dataclass
class FitLog:
    epochs: int
    best_epoch: int
    train_loss: float
    val_loss: float | None


def fit(net, train: Samples, val: Samples, scaler: Scaler, seed: int,
        cfg: TCNConfig = TCNConfig()) -> FitLog:
    torch = _torch()
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = resolve_device(cfg.device)
    net.to(device)
    tr = _on_device(_tensors(train, scaler), device)
    va = _on_device(_tensors(val, scaler), device) if len(val) and val.m.sum() else None
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    best, best_state, best_epoch, wait, last, epoch = np.inf, None, 0, 0, np.nan, 0
    for epoch in range(1, cfg.max_epochs + 1):
        net.train()
        losses = []
        order = rng.permutation(len(train))
        for start in range(0, len(order), cfg.batch):
            idx = torch.as_tensor(order[start:start + cfg.batch], device=device)
            opt.zero_grad()
            loss = balanced_huber(net(tr[0][idx], tr[1][idx])[0], tr[2][idx], tr[3][idx], tr[4][idx])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            losses.append(float(loss.detach().cpu()))
        last = float(np.mean(losses)) if losses else np.nan
        if va is None:
            continue
        net.eval()
        with torch.no_grad():
            score = float(balanced_huber(net(va[0], va[1])[0], va[2], va[3],
                                         torch.ones_like(va[4])).detach().cpu())
        if score < best - 1e-7:
            best, best_epoch, wait = score, epoch, 0
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            wait += 1
            if wait >= cfg.patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    return FitLog(epoch, best_epoch or epoch, last, None if va is None else best)


def predict(nets: list, samples: Samples, scaler: Scaler) -> tuple[np.ndarray, np.ndarray]:
    torch = _torch()
    device = next(nets[0].parameters()).device
    seq, stat = _on_device(_tensors(samples, scaler)[:2], str(device))
    corrections, gates = [], []
    for net in nets:
        net.eval()
        with torch.no_grad():
            correction, gate = net(seq, stat)
        corrections.append(correction.detach().cpu().numpy())
        gates.append(gate.detach().cpu().numpy())
    return np.mean(corrections, axis=0), np.mean(gates, axis=0)


def _months_before(d: date, months: int) -> date:
    return (pd.Timestamp(d) - pd.DateOffset(months=months)).date()


@dataclass
class FoldResult:
    corrections: dict[date, np.ndarray]
    gates: dict[date, np.ndarray]
    shocks: dict[date, float]
    fits: pd.DataFrame


def run_folds(dl: Daily, base: pd.DataFrame, cfg: TCNConfig = TCNConfig()) -> FoldResult:
    """Forward folds: fit before each year and forecast all eligible origins in that year."""
    b = _keyed(base)
    all_origins = sorted(set(b["origin"]))
    corrections, gates, shocks, fits = {}, {}, {}, []
    for year in cfg.fold_years:
        cut = date(year, 1, 1)
        val_start = _months_before(cut, cfg.val_months)
        train_origins = [o for o in all_origins if o < val_start]
        val_origins = [o for o in all_origins if val_start <= o < cut]
        test_origins = [o for o in all_origins if o.year == year]
        train = build_samples(dl, b, train_origins, val_start, cfg).labelled()
        val = build_samples(dl, b, val_origins, cut, cfg).labelled()
        test = build_samples(dl, b, test_origins, None, cfg)
        if len(train) < cfg.min_train or not len(test):
            fits.append(dict(fold_year=year, seed=None, train_windows=len(train), val_windows=len(val),
                             note="skipped (too few labelled windows or no origins)"))
            continue
        scaler = Scaler(train.stat)
        nets = []
        for seed in cfg.seeds:
            _torch().manual_seed(seed)
            net = make_net(cfg)
            log = fit(net, train, val, scaler, seed, cfg)
            nets.append(net)
            fits.append(dict(fold_year=year, seed=seed, train_windows=len(train), val_windows=len(val),
                             train_labels=int(train.m.sum()), val_labels=int(val.m.sum()),
                             epochs=log.epochs, best_epoch=log.best_epoch, train_huber=log.train_loss,
                             val_huber=log.val_loss, mean_change_weight=float(train.w.mean())))
        pred, gate = predict(nets, test, scaler)
        for origin, p, g, shock in zip(test.origin, pred, gate, test.shock):
            corrections[origin], gates[origin], shocks[origin] = p, g, float(shock)
    return FoldResult(corrections, gates, shocks, pd.DataFrame(fits))


def tcn_rows(base: pd.DataFrame, folds: FoldResult, cfg: TCNConfig = TCNConfig(),
             model: str = MODEL, online: bool = True) -> pd.DataFrame:
    """Apply direct corrections and a causal adapter learned from completed prior candidate errors."""
    b = _keyed(base)
    b = b[[(g, int(h)) in CELL_INDEX for g, h in zip(b["grain"], b["horizon"])]]
    rows = []
    history: dict[tuple[str, int], list[dict]] = {c: [] for c in CELLS}
    for d in b.sort_values(["origin", "grain", "horizon", "period_start"]).to_dict("records"):
        origin = d["origin"]
        cell = (d["grain"], int(d["horizon"]))
        if origin not in folds.corrections:
            continue
        j = CELL_INDEX[cell]
        raw = float(d["forecast"]) * np.exp(float(folds.corrections[origin][j]))
        adjustment = 0.0
        if online:
            eligible = [x for x in history[cell] if x["period_end"] <= origin and
                        (origin - x["period_end"]).days <= cfg.adapter_days and
                        x["actual"] > 0 and x["raw"] > 0]
            if len(eligible) >= cfg.adapter_min:
                age = np.asarray([(origin - x["period_end"]).days for x in eligible], dtype=float)
                weight = np.exp(-np.log(2.0) * age / cfg.adapter_half_life)
                error = np.log(np.asarray([x["actual"] for x in eligible]) /
                               np.asarray([x["raw"] for x in eligible]))
                adjustment = float(np.clip(np.average(error, weights=weight),
                                           -cfg.adapter_max_log, cfg.adapter_max_log))
        d.update(model=model, raw_tcn_forecast=raw, online_adjustment=adjustment,
                 shock_gate=float(folds.gates[origin][j]), shock_score=folds.shocks[origin],
                 forecast=raw * np.exp(adjustment))
        d["error"] = d["forecast"] - d["actual"]
        rows.append(d)
        history[cell].append(dict(period_end=d["period_end"], actual=float(d["actual"]), raw=raw))
    return pd.DataFrame(rows)


def tcn_rule(hits: pd.DataFrame, hits_y: pd.DataFrame, shock_hits: pd.DataFrame,
             base: str, new: str = MODEL) -> tuple[pd.DataFrame, bool]:
    """Rule fixed before the first real-data run."""
    piv = hits.pivot_table(index=["grain", "horizon"], columns="model", values="within_10")
    diff = piv[new] - piv[base]
    stable = hits_y[hits_y["year"] == A_STABLE_YEAR].groupby("model")["within_10"].mean()
    stable_change = float(stable.get(new, np.nan) - stable.get(base, np.nan))
    if len(shock_hits):
        shock_totals = (shock_hits.assign(weighted=lambda x: x["within_10"] * x["n"])
                        .groupby("model")[["weighted", "n"]].sum())
        shock = shock_totals["weighted"] / shock_totals["n"]
    else:
        shock = pd.Series(dtype=float)
    shock_change = float(shock.get(new, np.nan) - shock.get(base, np.nan))
    shock_n = int(shock_hits[shock_hits["model"] == new]["n"].sum()) if len(shock_hits) else 0
    checks = pd.DataFrame([
        dict(check="mean over weekly/monthly cells rises >= 0.02", value=float(diff.mean()),
             passed=bool(diff.mean() >= 0.02)),
        dict(check=f"no cell falls > {A_MAX_CELL_FALL:.2f}", value=float(diff.min()),
             passed=bool(diff.min() >= -A_MAX_CELL_FALL - 1e-12)),
        dict(check=f"{A_STABLE_YEAR} (stable) falls <= {A_MAX_STABLE_FALL:.2f}", value=stable_change,
             passed=bool(np.isfinite(stable_change) and stable_change >= -A_MAX_STABLE_FALL - 1e-12)),
        dict(check="shock-origin weighted hit rate rises", value=shock_change,
             passed=bool(shock_n >= 16 and np.isfinite(shock_change) and shock_change > 0)),
    ])
    return checks, bool(checks["passed"].all())


@dataclass
class TCNResult:
    candidate: pd.DataFrame
    hits: pd.DataFrame
    hits_y: pd.DataFrame
    shock_hits: pd.DataFrame
    checks: pd.DataFrame
    keep: bool
    fits: pd.DataFrame
    gate_summary: pd.DataFrame


def run_tcn_specialist(base: pd.DataFrame, daily: pd.DataFrame,
                       base_model: str = "milk_baseline_adaptive",
                       cfg: TCNConfig = TCNConfig()) -> TCNResult:
    history = _keyed(base[(base["model"] == base_model)])
    if "band" in history:
        history = history[history["band"].isin(VERIFIED_BANDS)]
    # Earlier development rows are training examples.  Only fold-year rows are scored.
    b = history[pd.to_datetime(history["origin"]).dt.year.isin(cfg.fold_years)]
    cutoff = pd.Timestamp(date(max(cfg.fold_years) + 1, 1, 1))
    dl = Daily.from_frame(daily[pd.to_datetime(daily["date"]) < cutoff])
    folds = run_folds(dl, history, cfg)
    candidate = tcn_rows(b, folds, cfg)
    hits = matched_hits({base_model: b, MODEL: candidate})
    hits_y = matched_hits({base_model: b, MODEL: candidate}, by_year=True)
    shock_keys = candidate[candidate["shock_score"] >= cfg.shock_threshold]
    shock_hits = matched_hits({base_model: b, MODEL: candidate}, keys_from=shock_keys) if len(shock_keys) else pd.DataFrame()
    checks, keep = tcn_rule(hits, hits_y, shock_hits, base_model)
    if len(candidate):
        gate_summary = (candidate.assign(year=pd.to_datetime(candidate["origin"]).dt.year)
                        .groupby(["year", "grain", "horizon"])
                        .agg(n=("forecast", "size"), mean_shock_score=("shock_score", "mean"),
                             mean_shock_gate=("shock_gate", "mean"),
                             mean_abs_online_adjustment=("online_adjustment", lambda x: float(np.abs(x).mean())))
                        .reset_index())
    else:
        gate_summary = pd.DataFrame()
    return TCNResult(candidate, hits, hits_y, shock_hits, checks, keep, folds.fits, gate_summary)
