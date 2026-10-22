"""LSTM-attention specialist used where pfoi-1.2.1-dev says ``low`` confidence (G2 Track A2).

User request (2026-10-22): when the stability gate flags instability, a deep-learning model makes the
milk forecast instead of 1.2.0-dev. 1.2.1-dev's confidence flag (``gate_intervals.attach_gate``: G1
logistic gate, p > 0.5 = ``low``) decides where; everywhere else 1.2.0-dev is unchanged.

The model (``lstm_attn``):

* **Short-term memory:** an LSTM reads the last ``LOOKBACK`` = 56 days before the forecast date.
* **Sensitive to major changes:** an additive attention layer weights the days it reads (so a sudden
  step can dominate), the inputs carry day-on-day change, yield per cow and milking cows relative to
  their 28-day level, and training windows whose last 7 days moved away from the 28-day level get a
  larger loss weight (``1 + |log(L7 / L28)| / change_scale``, capped at ``max_weight``).
* **Trained on the whole history, not in order:** every past day is one independent window, both milk
  sources are pooled (the target is scale-free: log(litres / R), R = mean of the trusted days of the
  current source in the 28 days before the forecast date) and the windows are shuffled every epoch.
* **Its own forecast:** a 98-day daily path of herd litres, R x exp(output), |output| <= 1. It does not
  start from 1.2.0-dev or the engine. Periods covered: day 1-14, week 1-13, month 1-3.

Leakage: refitted once per fold year Y (2019-2023). Training windows have origins before 1 July Y-1
and targets masked from 1 July Y-1; validation (early stopping only) has origins in [1 July Y-1,
1 January Y) and targets masked from 1 January Y. Forecasts at origins in Y use only days before the
origin. The test block (2024 onward) is never read. Five seeds are averaged.

Keep rule (fixed 2026-10-22, before any real-data run; unchanged from G2 Track A plus week 13):
on the periods the gate scored (trusted, fold years 2019-2023), share within +-10 %: the mean over
Track A cells rises by at least 2 points, no Track A cell falls by more than 1 point, 2019 falls by at
most 1 point, and week 13 falls by at most 1 point.

Herd-level aggregates only. Nothing here opens a database; the caller passes the frames.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .gate import daily_signals
from .gate_intervals import attach_gate
from .specialists import A_MAX_CELL_FALL, TRACK_A_CELLS, _keyed, gated_switch, matched_hits, track_a_rule

LOOKBACK = 56
REF_DAYS = 28
MIN_REF = 14
H = 98
MAX_LOG = 1.0     # output bounded to x0.37 .. x2.7 of the recent level
Z_CLIP = 5.0
SEQ = ("log_level", "trusted", "log_change", "log_ypc_rel", "log_cows_rel", "identified_share")
STATIC = ("src_delpro", "source_age_years", "trusted_share_28d", "doy_sin", "doy_cos", "change_7_28",
          "abs_change_7_28", "volatility_28d", "log_ypc_level", "cows_change_90d")
LSTM_CELLS = TRACK_A_CELLS + (("weekly", 13),)
MODEL = "lstm_attn"
GATED = "gated_lstm"
FOLD_YEARS = (2019, 2020, 2021, 2022, 2023)


@dataclass(frozen=True)
class LSTMConfig:
    """Fixed before any real-data run; not tuned on development scores."""
    hidden: int = 32
    attn: int = 16
    dropout: float = 0.1
    lr: float = 1e-3
    weight_decay: float = 1e-4
    batch: int = 64
    max_epochs: int = 150
    patience: int = 15
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    val_months: int = 6
    change_scale: float = 0.05
    max_weight: float = 4.0
    min_train: int = 200
    fold_years: tuple[int, ...] = field(default=FOLD_YEARS)


# --------------------------------------------------------------------------- daily arrays

@dataclass
class Daily:
    days: list            # calendar dates
    litres: np.ndarray
    trusted: np.ndarray   # bool
    ypc: np.ndarray       # litres per recorded milking cow (trusted days), else nan
    cows: np.ndarray
    ids: np.ndarray
    source: np.ndarray    # object, None when unknown
    pos: dict

    @classmethod
    def from_frame(cls, daily: pd.DataFrame) -> "Daily":
        sig = daily_signals(daily)
        d = daily.copy()
        d.index = pd.to_datetime(d["date"])
        d = d[~d.index.duplicated()].reindex(sig.index)
        litres = pd.to_numeric(d["target_litres"], errors="coerce").to_numpy(dtype=float)
        days = list(sig.index.date)
        return cls(days, litres, sig["trusted"].to_numpy(dtype=bool), np.exp(sig["log_ypc"].to_numpy(dtype=float)),
                   sig["milking"].to_numpy(dtype=float), sig["ids"].to_numpy(dtype=float),
                   sig["source"].to_numpy(dtype=object), {x: i for i, x in enumerate(days)})


@dataclass
class Samples:
    origin: np.ndarray   # dates
    seq: np.ndarray      # (N, LOOKBACK, len(SEQ))
    stat: np.ndarray     # (N, len(STATIC))
    y: np.ndarray        # (N, H) log(actual / R)
    m: np.ndarray        # (N, H) 1 where y counts
    w: np.ndarray        # (N,) change weight
    ref: np.ndarray      # (N,) R, litres per day

    def __len__(self) -> int:
        return len(self.origin)


def _empty() -> Samples:
    return Samples(np.array([], dtype=object), np.zeros((0, LOOKBACK, len(SEQ))), np.zeros((0, len(STATIC))),
                   np.zeros((0, H)), np.zeros((0, H)), np.zeros(0), np.zeros(0))


def _safe_log(a, b) -> float:
    return float(np.log(a / b)) if np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0 else 0.0


def build_samples(dl: Daily, origins, target_end: date | None, cfg: LSTMConfig = LSTMConfig()) -> Samples:
    """Windows at ``origins``. Inputs use days before each origin; targets are trusted days of the
    origin's source in o .. o+H-1 before ``target_end`` (``None``: no targets, for forecasting)."""
    rows = {k: [] for k in ("origin", "seq", "stat", "y", "m", "w", "ref")}
    n = len(dl.days)
    for o in origins:
        i = dl.pos.get(o)
        if i is None or i < LOOKBACK:
            continue
        lo = i - LOOKBACK
        tr = dl.trusted[lo:i]
        if not tr.any():
            continue
        cur = dl.source[lo:i][tr][-1]
        g = tr & (dl.source[lo:i] == cur)
        g28 = g[-REF_DAYS:]
        if g28.sum() < MIN_REF:
            continue
        R = float(dl.litres[i - REF_DAYS:i][g28].mean())
        r_ypc = float(np.nanmean(dl.ypc[i - REF_DAYS:i][g28]))
        r_cows = float(np.nanmean(dl.cows[i - REF_DAYS:i])) if np.isfinite(dl.cows[i - REF_DAYS:i]).any() else np.nan
        if not R > 0:
            continue
        lit = dl.litres[lo:i]
        level = np.where(g, np.log(np.where(g, lit, 1.0) / R), 0.0)
        change = np.zeros(LOOKBACK)
        both = g[1:] & g[:-1]
        change[1:] = np.where(both, level[1:] - level[:-1], 0.0)
        ypc = dl.ypc[lo:i]
        ypc_rel = np.where(g & np.isfinite(ypc), np.log(np.where(g & np.isfinite(ypc), ypc, 1.0) / r_ypc), 0.0)
        cows = dl.cows[lo:i]
        cows_ok = np.isfinite(cows) & (cows > 0) & np.isfinite(r_cows) & (r_cows > 0)
        cows_rel = np.where(cows_ok, np.log(np.where(cows_ok, cows, 1.0) / (r_cows if r_cows > 0 else 1.0)), 0.0)
        ids = np.nan_to_num(dl.ids[lo:i], nan=0.0)
        seq = np.stack([level, g.astype(float), change, ypc_rel, cows_rel, ids], axis=1)
        g7 = g[-7:]
        ch = _safe_log(lit[-7:][g7].mean(), R) if g7.any() else 0.0
        b28 = both[-(REF_DAYS - 1):]
        vol = float(np.std(change[-(REF_DAYS - 1):][b28])) if b28.sum() >= 2 else 0.0
        other = np.nonzero((dl.source[:i] != cur) & (dl.source[:i] != None))[0]  # noqa: E711
        age = (i - other[-1]) if len(other) else i
        c_now = np.nanmean(dl.cows[i - 7:i]) if np.isfinite(dl.cows[i - 7:i]).any() else np.nan
        c_then = np.nanmean(dl.cows[max(0, i - 97):max(1, i - 90)]) if i >= 97 and \
            np.isfinite(dl.cows[i - 97:i - 90]).any() else np.nan
        doy = 2 * np.pi * o.timetuple().tm_yday / 365.25
        stat = [float(cur == "delpro"), min(age / 365.0, 5.0), float(tr[-REF_DAYS:].mean()), np.sin(doy),
                np.cos(doy), ch, abs(ch), vol, np.log(r_ypc) if r_ypc > 0 else 0.0, _safe_log(c_now, c_then)]
        y, m = np.zeros(H), np.zeros(H)
        if target_end is not None:
            for h in range(H):
                j = i + h
                if j >= n or dl.days[j] >= target_end:
                    break
                if dl.trusted[j] and dl.source[j] == cur and dl.litres[j] > 0:
                    y[h], m[h] = np.log(dl.litres[j] / R), 1.0
        rows["origin"].append(o)
        rows["seq"].append(seq)
        rows["stat"].append(np.nan_to_num(np.asarray(stat, dtype=float)))
        rows["y"].append(y)
        rows["m"].append(m)
        rows["w"].append(1.0 + min(cfg.max_weight - 1.0, abs(ch) / cfg.change_scale))
        rows["ref"].append(R)
    if not rows["origin"]:
        return _empty()
    return Samples(np.array(rows["origin"], dtype=object), np.stack(rows["seq"]), np.stack(rows["stat"]),
                   np.stack(rows["y"]), np.stack(rows["m"]), np.asarray(rows["w"]), np.asarray(rows["ref"]))


def day_range(a: date, b: date) -> list[date]:
    return [a + timedelta(days=k) for k in range((b - a).days)]


# --------------------------------------------------------------------------- model

def _torch():
    import torch
    return torch


class Scaler:
    """z-scores of the static features, from training windows only."""

    def __init__(self, stat: np.ndarray):
        self.mu = stat.mean(axis=0)
        sd = stat.std(axis=0)
        self.sd = np.where(sd > 1e-3, sd, 1.0)

    def __call__(self, stat: np.ndarray) -> np.ndarray:
        return np.clip((stat - self.mu) / self.sd, -Z_CLIP, Z_CLIP)


def make_net(cfg: LSTMConfig = LSTMConfig()):
    torch = _torch()
    nn = torch.nn

    class AttnLSTM(nn.Module):
        """LSTM over 56 days -> additive attention (query = last hidden state) -> head with the static
        features -> bounded daily log path. The head starts at zero (no learned move yet)."""

        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(len(SEQ), cfg.hidden, batch_first=True)
            self.key = nn.Linear(cfg.hidden, cfg.attn, bias=False)
            self.query = nn.Linear(cfg.hidden, cfg.attn)
            self.score = nn.Linear(cfg.attn, 1, bias=False)
            self.stat = nn.Sequential(nn.Linear(len(STATIC), 32), nn.ReLU())
            self.head = nn.Sequential(nn.Linear(2 * cfg.hidden + 32, 128), nn.ReLU(), nn.Dropout(cfg.dropout),
                                      nn.Linear(128, H))
            nn.init.zeros_(self.head[-1].weight)
            nn.init.zeros_(self.head[-1].bias)

        def forward(self, seq, stat):
            hs, _ = self.lstm(seq)
            last = hs[:, -1]
            e = self.score(torch.tanh(self.key(hs) + self.query(last)[:, None, :])).squeeze(-1)
            a = torch.softmax(e, dim=1)
            ctx = (a[..., None] * hs).sum(dim=1)
            z = torch.cat([last, ctx, self.stat(stat)], dim=1)
            return MAX_LOG * torch.tanh(self.head(z)), a

    return AttnLSTM()


def _tensors(s: Samples, scaler: Scaler):
    torch = _torch()
    t = lambda a: torch.as_tensor(np.asarray(a, dtype=np.float32))  # noqa: E731
    return t(s.seq), t(scaler(s.stat)), t(s.y), t(s.m), t(s.w)


def weighted_l1(pred, y, m, w):
    mw = m * w[:, None]
    return ((pred - y).abs() * mw).sum() / mw.sum().clamp(min=1.0)


@dataclass
class FitLog:
    epochs: int
    best_epoch: int
    train_loss: float
    val_loss: float | None


def fit(net, train: Samples, val: Samples, scaler: Scaler, seed: int, cfg: LSTMConfig = LSTMConfig()) -> FitLog:
    """Adam on change-weighted masked L1; windows shuffled every epoch; early stopping on the
    (unweighted) validation L1 when validation has targets."""
    torch = _torch()
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    seq, stat, y, m, w = _tensors(train, scaler)
    va = _tensors(val, scaler) if len(val) and val.m.sum() > 0 else None
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    best, best_state, best_epoch, wait, tl, epoch = np.inf, None, 0, 0, np.nan, 0
    for epoch in range(1, cfg.max_epochs + 1):
        net.train()
        order = rng.permutation(len(train))
        losses = []
        for b in range(0, len(order), cfg.batch):
            idx = torch.as_tensor(order[b:b + cfg.batch])
            opt.zero_grad()
            loss = weighted_l1(net(seq[idx], stat[idx])[0], y[idx], m[idx], w[idx])
            loss.backward()
            opt.step()
            losses.append(float(loss.detach()))
        tl = float(np.mean(losses)) if losses else np.nan
        if va is None:
            continue
        net.eval()
        with torch.no_grad():
            vl = float(weighted_l1(net(va[0], va[1])[0], va[2], va[3], torch.ones_like(va[4])))
        if vl < best - 1e-6:
            best, best_epoch, wait = vl, epoch, 0
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        else:
            wait += 1
            if wait >= cfg.patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    return FitLog(epoch, best_epoch or epoch, tl, None if va is None else best)


def predict(nets: list, s: Samples, scaler: Scaler) -> tuple[np.ndarray, np.ndarray]:
    """Mean log path (N, H) and mean attention weights (N, LOOKBACK) over the ensemble."""
    torch = _torch()
    seq, stat = _tensors(s, scaler)[:2]
    paths, attn = [], []
    for net in nets:
        net.eval()
        with torch.no_grad():
            p, a = net(seq, stat)
        paths.append(p.numpy())
        attn.append(a.numpy())
    return np.mean(paths, axis=0), np.mean(attn, axis=0)


# --------------------------------------------------------------------------- folds

def _months_before(d: date, months: int) -> date:
    return (pd.Timestamp(d) - pd.DateOffset(months=months)).date()


@dataclass
class FoldResult:
    paths: dict          # origin -> (R, log path of length H)
    fits: pd.DataFrame   # fold year x seed: epochs, losses, window counts
    attention: pd.DataFrame  # fold year x lag: mean attention weight (herd-level aggregate)


def run_folds(dl: Daily, predict_origins, cfg: LSTMConfig = LSTMConfig()) -> FoldResult:
    """Per fold year: fit the seeds on windows that ended before the year, forecast its origins."""
    first = dl.days[0]
    wanted = sorted(set(predict_origins))
    paths, fits, attn = {}, [], []
    for Y in cfg.fold_years:
        cut = date(Y, 1, 1)
        vs = _months_before(cut, cfg.val_months)
        train = build_samples(dl, day_range(first, vs), vs, cfg)
        val = build_samples(dl, day_range(vs, cut), cut, cfg)
        origins = [o for o in wanted if o.year == Y]
        if len(train) < cfg.min_train or not origins:
            fits.append(dict(fold_year=Y, seed=None, train_windows=len(train), val_windows=len(val),
                             note="skipped (too few training windows or no origins)"))
            continue
        scaler = Scaler(train.stat)
        nets = []
        for seed in cfg.seeds:
            _torch().manual_seed(seed)  # initial weights depend on the seed only (reproducible runs)
            net = make_net(cfg)
            log = fit(net, train, val, scaler, seed, cfg)
            nets.append(net)
            fits.append(dict(fold_year=Y, seed=seed, train_windows=len(train), val_windows=len(val),
                             train_target_days=int(train.m.sum()), epochs=log.epochs, best_epoch=log.best_epoch,
                             train_l1=log.train_loss, val_l1=log.val_loss,
                             mean_change_weight=float(train.w.mean())))
        test = build_samples(dl, origins, None, cfg)
        if not len(test):
            continue
        logp, a = predict(nets, test, scaler)
        for o, R, p in zip(test.origin, test.ref, logp):
            paths[o] = (float(R), p)
        mean_a = a.mean(axis=0)
        attn += [dict(fold_year=Y, lag_days=LOOKBACK - k, mean_attention=float(mean_a[k]))
                 for k in range(LOOKBACK)]
    return FoldResult(paths, pd.DataFrame(fits), pd.DataFrame(attn))


# --------------------------------------------------------------------------- rows, switch, rule

def lstm_rows(base: pd.DataFrame, paths: dict, model: str = MODEL, cells=LSTM_CELLS) -> pd.DataFrame:
    """``model`` rows on the base model's periods: R x sum of exp(log path) over the period's days,
    for periods inside the 98-day path and in ``cells``."""
    b = _keyed(base).drop_duplicates(["grain", "horizon", "origin", "period_start"])
    keep = set(cells)
    rows = []
    for d in b.to_dict("records"):
        if (d["grain"], int(d["horizon"])) not in keep or d["origin"] not in paths:
            continue
        a, e = (d["period_start"] - d["origin"]).days, (d["period_end"] - d["origin"]).days
        if a < 0 or e > H:
            continue
        R, p = paths[d["origin"]]
        d.update(model=model, forecast=float(R * np.exp(p[a:e]).sum()))
        rows.append(d)
    out = pd.DataFrame(rows)
    if len(out):
        out["error"] = out["forecast"] - out["actual"]
    return out


def confidence_switch(base: pd.DataFrame, lstm: pd.DataFrame, probs: pd.DataFrame,
                      cells=LSTM_CELLS) -> pd.DataFrame:
    """1.2.0-dev rows with the LSTM forecast where pfoi-1.2.1-dev's confidence is ``low``."""
    flagged = attach_gate(base, probs)
    p = flagged[["grain", "horizon", "origin", "period_start", "p_gate"]]
    return gated_switch(base, lstm, p, gate="gate", threshold=0.5, cells=cells, new_model=GATED)


def lstm_rule(hits: pd.DataFrame, hits_y: pd.DataFrame, base: str, new: str = GATED):
    """Pre-registered rule: the G2 Track A rule plus week 13 falling by at most 1 point."""
    checks, _ = track_a_rule(hits, hits_y, base, new)
    c = hits[(hits["grain"] == "weekly") & (hits["horizon"] == 13)].set_index("model")["within_10"]
    v = float(c.get(new, np.nan) - c.get(base, np.nan))
    extra = pd.DataFrame([dict(check=f"week 13 falls <= {A_MAX_CELL_FALL:.2f}", value=v,
                               passed=bool(np.isfinite(v) and v >= -A_MAX_CELL_FALL - 1e-12))])
    checks = pd.concat([checks, extra], ignore_index=True)
    return checks, bool(checks["passed"].all())


@dataclass
class LSTMResult:
    lstm: pd.DataFrame
    gated: pd.DataFrame
    hits: pd.DataFrame
    hits_y: pd.DataFrame
    hits_low: pd.DataFrame     # only the low-confidence periods the LSTM replaced
    hits_ungated: pd.DataFrame
    checks: pd.DataFrame
    keep: bool
    fits: pd.DataFrame
    attention: pd.DataFrame


def run_lstm_specialist(base: pd.DataFrame, daily: pd.DataFrame, probs: pd.DataFrame,
                        base_model: str = "milk_baseline_adaptive", cfg: LSTMConfig = LSTMConfig()) -> LSTMResult:
    b = _keyed(base[base["model"] == base_model])
    b = b[pd.to_datetime(b["origin"]).dt.year.isin(cfg.fold_years)]
    dl = Daily.from_frame(daily[pd.to_datetime(daily["date"]) < pd.Timestamp(date(max(cfg.fold_years) + 1, 1, 1))])
    folds = run_folds(dl, sorted(set(b["origin"])), cfg)
    rows = lstm_rows(b, folds.paths)
    gated = confidence_switch(b, rows, probs) if len(rows) else b.assign(model=GATED, switched=False)
    pair = {base_model: b, GATED: gated}
    hits = matched_hits(pair, keys_from=probs)
    hits_y = matched_hits(pair, keys_from=probs, by_year=True)
    sw = gated[gated["switched"]]
    hits_low = matched_hits({base_model: b, MODEL: rows}, keys_from=sw) if len(sw) else pd.DataFrame()
    hits_un = matched_hits({base_model: b, MODEL: rows}, keys_from=probs) if len(rows) else pd.DataFrame()
    checks, keep = lstm_rule(hits, hits_y, base_model)
    return LSTMResult(rows, gated, hits, hits_y, hits_low, hits_un, checks, keep, folds.fits, folds.attention)
