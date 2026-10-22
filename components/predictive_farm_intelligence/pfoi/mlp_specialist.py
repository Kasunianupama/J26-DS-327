"""Compact yield-per-cow specialist for low-confidence milk forecasts.

The learned quantity is yield per recorded milking cow, never total herd milk. At issue
time the prediction is composed structurally as projected mean milking cows multiplied by
predicted litres per cow per day and the number of days. A large projected herd change is
therefore applied in full; only the yield residual is bounded.

The neural model uses 40 causal summaries and a 32 -> 16 network. A small histogram
gradient-boosted tree is evaluated beside it on exactly the same features. Training origins
are weekly Mondays, including calendar-month targets, and forward folds stop before 2024.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .episodes import VERIFIED_BANDS
from .gate import KEYS
from .gate_intervals import attach_gate
from .specialists import _keyed, gated_switch
from .tcn_specialist import CELLS, CELL_INDEX, FOLD_YEARS, Daily, resolve_device

MODEL = "summary_yield_mlp"
TREE_MODEL = "summary_yield_gbt"
GATED = "confidence_gated_yield_mlp"
GATED_TREE = "confidence_gated_yield_gbt"
LOOKBACK = 112
WINDOWS = (3, 7, 14, 28)

FEATURES = tuple(
    [f"{signal}_change_{days}d" for signal in ("milk", "ypc", "milking", "herd") for days in WINDOWS]
    + [f"{signal}_slope_28d" for signal in ("milk", "ypc", "milking", "herd")]
    + [f"{signal}_volatility_28d" for signal in ("milk", "ypc", "milking")]
    + [f"mastitis_per_100_cows_{days}d" for days in (7, 28)]
    + [f"health_recorded_share_{days}d" for days in (7, 28)]
    + [f"sessions_per_100_cows_{days}d" for days in (7, 28)]
    + [f"blood_alarms_per_cow_{days}d" for days in (7, 28)]
    + [f"conductivity_alarms_per_cow_{days}d" for days in (7, 28)]
    + ["days_since_reliable_health"]
    + [f"{signal}_current_to_28d" for signal in ("milk", "ypc", "milking", "herd")]
    + ["doy_sin", "doy_cos"]
)


@dataclass(frozen=True)
class MLPConfig:
    hidden: tuple[int, ...] = (32, 16)
    dropout: float = 0.10
    lr: float = 1e-3
    weight_decay: float = 1e-3
    batch: int = 64
    max_epochs: int = 150
    patience: int = 15
    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    val_months: int = 6
    min_train: int = 80
    min_target_share: float = 0.80
    yield_log_limit: float = float(np.log(1.5))
    device: str = "cpu"
    fold_years: tuple[int, ...] = field(default=FOLD_YEARS)


@dataclass
class YieldSamples:
    origin: np.ndarray
    x: np.ndarray
    y: np.ndarray
    m: np.ndarray
    ref_ypc: np.ndarray

    def __len__(self) -> int:
        return len(self.origin)

    def labelled(self) -> "YieldSamples":
        take = self.m.sum(axis=1) > 0
        return YieldSamples(*(getattr(self, name)[take]
                              for name in ("origin", "x", "y", "m", "ref_ypc")))


def _empty() -> YieldSamples:
    return YieldSamples(np.array([], dtype=object), np.zeros((0, len(FEATURES))),
                        np.zeros((0, len(CELLS))), np.zeros((0, len(CELLS))), np.zeros(0))


def _finite_mean(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmean(x)) if np.isfinite(x).any() else np.nan


def _log_ratio(a: float, b: float) -> float:
    return float(np.log(a / b)) if np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0 else 0.0


def _change(x: np.ndarray, valid: np.ndarray, days: int) -> float:
    recent = _finite_mean(np.where(valid[-days:], x[-days:], np.nan))
    prior = _finite_mean(np.where(valid[-2 * days:-days], x[-2 * days:-days], np.nan))
    return _log_ratio(recent, prior)


def _slope(x: np.ndarray, valid: np.ndarray) -> float:
    values = np.asarray(x[-28:], dtype=float)
    ok = np.asarray(valid[-28:], dtype=bool) & np.isfinite(values) & (values > 0)
    if ok.sum() < 7:
        return 0.0
    return float(np.polyfit(np.arange(28, dtype=float)[ok], np.log(values[ok]), 1)[0] * 28.0)


def _volatility(x: np.ndarray, valid: np.ndarray) -> float:
    values = np.asarray(x[-28:], dtype=float)
    ok = np.asarray(valid[-28:], dtype=bool) & np.isfinite(values) & (values > 0)
    return float(np.std(np.diff(np.log(values[ok])))) if ok.sum() >= 7 else 0.0


def _current_ratio(x: np.ndarray, valid: np.ndarray) -> float:
    values = np.asarray(x, dtype=float)
    ok = np.asarray(valid, dtype=bool) & np.isfinite(values) & (values > 0)
    positions = np.flatnonzero(ok)
    mean = _finite_mean(np.where(ok[-28:], values[-28:], np.nan))
    return _log_ratio(values[positions[-1]], mean) if len(positions) else 0.0


def _per_exposure(events: np.ndarray, cows: np.ndarray, recorded: np.ndarray, days: int,
                  scale: float) -> float:
    e, c, r = events[-days:], cows[-days:], recorded[-days:]
    ok = r & np.isfinite(e) & np.isfinite(c) & (c > 0) & (e >= 0)
    return float(scale * e[ok].sum() / c[ok].sum()) if ok.any() and c[ok].sum() > 0 else 0.0


def summary_features(dl: Daily, origin: date) -> tuple[np.ndarray, float] | None:
    """Return forty causal summaries plus the past-28-day yield reference."""
    i = dl.pos.get(origin)
    if i is None or i < LOOKBACK:
        return None
    lo = i - LOOKBACK
    trusted = dl.trusted[lo:i]
    if trusted[-28:].sum() < 14:
        return None
    source = dl.source[lo:i]
    current = source[trusted][-1]
    milk_ok = trusted & (source == current)
    milk, cows, herd = dl.litres[lo:i], dl.milking[lo:i], dl.herd[lo:i]
    ypc = np.where(milk_ok & np.isfinite(cows) & (cows > 0), milk / cows, np.nan)
    stock_ok = np.isfinite(cows) & (cows > 0)
    herd_ok = np.isfinite(herd) & (herd > 0)
    ref = _finite_mean(np.where(milk_ok[-28:], ypc[-28:], np.nan))
    if not np.isfinite(ref) or ref <= 0:
        return None

    signals = ((milk, milk_ok), (ypc, milk_ok), (cows, stock_ok), (herd, herd_ok))
    out = [_change(x, ok, days) for x, ok in signals for days in WINDOWS]
    out.extend(_slope(x, ok) for x, ok in signals)
    out.extend(_volatility(x, ok) for x, ok in signals[:3])
    recorded = dl.health_recorded[lo:i]
    out.extend(_per_exposure(dl.mastitis[lo:i], cows, recorded, days, 100.0) for days in (7, 28))
    out.extend(float(recorded[-days:].mean()) for days in (7, 28))
    for events, scale in ((dl.sessions[lo:i], 100.0), (dl.blood_alarms[lo:i], 1.0),
                          (dl.conductivity_alarms[lo:i], 1.0)):
        out.extend(_per_exposure(events, cows, recorded, days, scale) for days in (7, 28))
    seen = np.flatnonzero(recorded)
    out.append(float(min(365, LOOKBACK - 1 - seen[-1])) if len(seen) else 365.0)
    out.extend(_current_ratio(x, ok) for x, ok in signals)
    angle = 2.0 * np.pi * origin.timetuple().tm_yday / 365.25
    out.extend((np.sin(angle), np.cos(angle)))
    return np.nan_to_num(np.asarray(out, dtype=float), nan=0.0, posinf=10.0, neginf=-10.0), ref


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def _target_bounds(origin: date, cell: tuple[str, int]) -> tuple[date, date]:
    grain, horizon = cell
    if grain == "weekly":
        start = origin + timedelta(days=7 * (horizon - 1))
        return start, start + timedelta(days=7)
    first = origin if origin.day == 1 else _add_months(origin.replace(day=1), 1)
    return _add_months(first, horizon - 1), _add_months(first, horizon)


def _target_ypc(dl: Daily, start: date, end: date, target_end: date | None,
                min_share: float) -> float:
    if target_end is None or end > target_end:
        return np.nan
    positions = [dl.pos.get(start + timedelta(days=k)) for k in range((end - start).days)]
    if any(i is None for i in positions):
        return np.nan
    take = np.asarray(positions, dtype=int)
    ok = dl.trusted[take] & np.isfinite(dl.milking[take]) & (dl.milking[take] > 0)
    if ok.mean() < min_share:
        return np.nan
    sources = {x for x in dl.source[take][ok] if x is not None}
    if len(sources) != 1:
        return np.nan
    cow_days = float(dl.milking[take][ok].sum())
    return float(dl.litres[take][ok].sum() / cow_days) if cow_days > 0 else np.nan


def build_samples(dl: Daily, origins, target_end: date | None,
                  cfg: MLPConfig = MLPConfig()) -> YieldSamples:
    rows = {name: [] for name in ("origin", "x", "y", "m", "ref_ypc")}
    for origin in sorted(set(origins)):
        built = summary_features(dl, origin)
        if built is None:
            continue
        x, ref = built
        y, mask = np.zeros(len(CELLS)), np.zeros(len(CELLS))
        for j, cell in enumerate(CELLS):
            start, end = _target_bounds(origin, cell)
            actual = _target_ypc(dl, start, end, target_end, cfg.min_target_share)
            if np.isfinite(actual) and actual > 0:
                y[j], mask[j] = np.log(actual / ref), 1.0
        rows["origin"].append(origin)
        rows["x"].append(x)
        rows["y"].append(y)
        rows["m"].append(mask)
        rows["ref_ypc"].append(ref)
    if not rows["origin"]:
        return _empty()
    return YieldSamples(np.asarray(rows["origin"], dtype=object), np.stack(rows["x"]),
                        np.stack(rows["y"]), np.stack(rows["m"]), np.asarray(rows["ref_ypc"]))


class SummaryScaler:
    def __init__(self, x: np.ndarray):
        self.mu = x.mean(axis=0) if len(x) else np.zeros(len(FEATURES))
        sd = x.std(axis=0) if len(x) else np.ones(len(FEATURES))
        self.sd = np.where(sd > 1e-3, sd, 1.0)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return np.clip((x - self.mu) / self.sd, -5.0, 5.0)


def _torch():
    import torch
    return torch


def make_net(cfg: MLPConfig = MLPConfig()):
    torch = _torch()
    nn = torch.nn
    layers: list = []
    width = len(FEATURES)
    for hidden in cfg.hidden:
        layers.extend([nn.Linear(width, hidden), nn.ReLU(), nn.Dropout(cfg.dropout)])
        width = hidden
    layers.append(nn.Linear(width, len(CELLS)))
    body = nn.Sequential(*layers)

    class YieldMLP(nn.Module):
        def __init__(self):
            super().__init__()
            self.body = body
            nn.init.zeros_(self.body[-1].weight)
            nn.init.zeros_(self.body[-1].bias)

        def forward(self, x):
            return cfg.yield_log_limit * torch.tanh(self.body(x))

    return YieldMLP()


@dataclass
class FitLog:
    epochs: int
    best_epoch: int
    train_loss: float
    val_loss: float | None


def _masked_huber(pred, y, mask):
    torch = _torch()
    raw = torch.nn.functional.smooth_l1_loss(pred, y, reduction="none")
    den = mask.sum(dim=0)
    per_cell = (raw * mask).sum(dim=0) / den.clamp(min=1.0)
    return per_cell[den > 0].mean() if (den > 0).any() else raw.sum() * 0.0


def fit(net, train: YieldSamples, val: YieldSamples, scaler: SummaryScaler, seed: int,
        cfg: MLPConfig = MLPConfig()) -> FitLog:
    torch = _torch()
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    device = resolve_device(cfg.device)
    net.to(device)
    tensor = lambda x: torch.as_tensor(np.asarray(x, dtype=np.float32), device=device)  # noqa: E731
    tr = tensor(scaler(train.x)), tensor(train.y), tensor(train.m)
    va = (tensor(scaler(val.x)), tensor(val.y), tensor(val.m)) if len(val) and val.m.sum() else None
    opt = torch.optim.AdamW(net.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    best, state, best_epoch, wait, last, epoch = np.inf, None, 0, 0, np.nan, 0
    for epoch in range(1, cfg.max_epochs + 1):
        net.train()
        losses = []
        order = rng.permutation(len(train))
        for start in range(0, len(order), cfg.batch):
            idx = torch.as_tensor(order[start:start + cfg.batch], device=device)
            opt.zero_grad()
            loss = _masked_huber(net(tr[0][idx]), tr[1][idx], tr[2][idx])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
            losses.append(float(loss.detach().cpu()))
        last = float(np.mean(losses)) if losses else np.nan
        if va is None:
            continue
        net.eval()
        with torch.no_grad():
            score = float(_masked_huber(net(va[0]), va[1], va[2]).detach().cpu())
        if score < best - 1e-7:
            best, best_epoch, wait = score, epoch, 0
            state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            wait += 1
            if wait >= cfg.patience:
                break
    if state is not None:
        net.load_state_dict(state)
    return FitLog(epoch, best_epoch or epoch, last, None if va is None else best)


def predict(nets: list, samples: YieldSamples, scaler: SummaryScaler) -> np.ndarray:
    torch = _torch()
    device = str(next(nets[0].parameters()).device)
    x = torch.as_tensor(scaler(samples.x), dtype=torch.float32, device=device)
    out = []
    for net in nets:
        net.eval()
        with torch.no_grad():
            out.append(net(x).detach().cpu().numpy())
    return np.mean(out, axis=0)


def _tree_predict(train: YieldSamples, test: YieldSamples, scaler: SummaryScaler,
                  cfg: MLPConfig) -> np.ndarray:
    from sklearn.ensemble import HistGradientBoostingRegressor

    x_train, x_test = scaler(train.x), scaler(test.x)
    out = np.zeros((len(test), len(CELLS)))
    for j in range(len(CELLS)):
        use = train.m[:, j] > 0
        if use.sum() < 20:
            continue
        model = HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=7, learning_rate=0.05,
                                              l2_regularization=1.0, random_state=17)
        model.fit(x_train[use], train.y[use, j])
        out[:, j] = np.clip(model.predict(x_test), -cfg.yield_log_limit, cfg.yield_log_limit)
    return out


def _months_before(d: date, months: int) -> date:
    return _add_months(d.replace(day=1), -months)


def _mondays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(7 - start.weekday()) % 7)
    out = []
    while d < end:
        out.append(d)
        d += timedelta(days=7)
    return out


@dataclass
class YieldFoldResult:
    mlp: dict[date, np.ndarray]
    tree: dict[date, np.ndarray]
    ref_ypc: dict[date, float]
    fits: pd.DataFrame


def run_folds(dl: Daily, score_origins, cfg: MLPConfig = MLPConfig()) -> YieldFoldResult:
    mlp, tree, refs, logs = {}, {}, {}, []
    first = dl.days[0] + timedelta(days=LOOKBACK)
    for year in cfg.fold_years:
        cut = date(year, 1, 1)
        val_start = _months_before(cut, cfg.val_months)
        train = build_samples(dl, _mondays(first, val_start), val_start, cfg).labelled()
        val = build_samples(dl, _mondays(val_start, cut), cut, cfg).labelled()
        test = build_samples(dl, [o for o in score_origins if o.year == year], None, cfg)
        if len(train) < cfg.min_train or not len(test):
            logs.append(dict(fold_year=year, seed=None, train_windows=len(train), val_windows=len(val),
                             note="skipped (too few weekly windows or no score origins)"))
            continue
        scaler = SummaryScaler(train.x)
        nets = []
        for seed in cfg.seeds:
            _torch().manual_seed(seed)
            net = make_net(cfg)
            log = fit(net, train, val, scaler, seed, cfg)
            nets.append(net)
            logs.append(dict(fold_year=year, seed=seed, train_windows=len(train), val_windows=len(val),
                             train_labels=int(train.m.sum()), val_labels=int(val.m.sum()),
                             parameters=sum(p.numel() for p in net.parameters()), epochs=log.epochs,
                             best_epoch=log.best_epoch, train_huber=log.train_loss,
                             val_huber=log.val_loss))
        mp, tp = predict(nets, test, scaler), _tree_predict(train, test, scaler, cfg)
        for origin, m, t, ref in zip(test.origin, mp, tp, test.ref_ypc):
            mlp[origin], tree[origin], refs[origin] = m, t, float(ref)
    return YieldFoldResult(mlp, tree, refs, pd.DataFrame(logs))


def structural_rows(base: pd.DataFrame, herd: pd.DataFrame, predictions: dict[date, np.ndarray],
                    refs: dict[date, float], model: str) -> pd.DataFrame:
    """Compose predicted yield with the herd engine's unbounded projected cow path."""
    b, h = _keyed(base), _keyed(herd)
    h = h[(h["series"] == "milking") & (h["model"] == "herd_engine")]
    cows = h.drop_duplicates(KEYS).set_index(KEYS)["forecast"]
    rows = []
    for d in b.to_dict("records"):
        cell, origin = (d["grain"], int(d["horizon"])), d["origin"]
        key = tuple(d[k] for k in KEYS)
        if cell not in CELL_INDEX or origin not in predictions or key not in cows.index:
            continue
        projected_cows = float(cows.loc[key])
        if not np.isfinite(projected_cows) or projected_cows < 0:
            continue
        days = (d["period_end"] - d["period_start"]).days
        ypc = refs[origin] * np.exp(float(predictions[origin][CELL_INDEX[cell]]))
        d.update(model=model, projected_milking_cows=projected_cows,
                 predicted_yield_per_cow=ypc, forecast=projected_cows * ypc * days)
        d["error"] = d["forecast"] - d["actual"]
        rows.append(d)
    return pd.DataFrame(rows)


def continuous_metrics(frames: dict[str, pd.DataFrame], keys_from: pd.DataFrame | None = None) -> pd.DataFrame:
    """MAE, median APE, bias, mean log error and MAE reduction on identical periods."""
    keyed = {name: _keyed(frame).drop_duplicates(KEYS).set_index(KEYS) for name, frame in frames.items()}
    common = None
    for frame in keyed.values():
        common = frame.index if common is None else common.intersection(frame.index)
    if keys_from is not None:
        common = common.intersection(_keyed(keys_from).drop_duplicates(KEYS).set_index(KEYS).index)
    rows = []
    for name, frame in keyed.items():
        g = frame.loc[common].reset_index()
        g = g[(g["actual"] > 0) & (g["forecast"] > 0)]
        for (grain, horizon), part in g.groupby(["grain", "horizon"]):
            error = part["forecast"] - part["actual"]
            ape = error.abs() / part["actual"]
            rows.append(dict(grain=grain, horizon=int(horizon), model=name, n=len(part),
                             within_10=float((ape <= 0.10 + 1e-9).mean()),
                             mae=float(error.abs().mean()), median_ape=float(ape.median()),
                             bias=float(error.mean()),
                             mean_log_error=float(np.log(part["forecast"] / part["actual"]).mean())))
    out = pd.DataFrame(rows)
    if not len(out):
        return out
    base_name = next(iter(frames))
    base = out[out["model"] == base_name].set_index(["grain", "horizon"])["mae"]
    out["mae_reduction_vs_base"] = [1.0 - r.mae / base.get((r.grain, r.horizon), np.nan)
                                     for r in out.itertuples()]
    return out


def _aggregate(rows: pd.DataFrame, model: str) -> dict[str, float]:
    part = rows[rows["model"] == model]
    n = part["n"].sum()
    return {name: (float(np.average(part[col], weights=part["n"])) if n else np.nan)
            for name, col in (("mae", "mae"), ("median", "median_ape"),
                              ("bias", "bias"), ("log", "mean_log_error"))}


def acceptance_rule(base: pd.DataFrame, candidate: pd.DataFrame, keys_from: pd.DataFrame,
                    base_name: str, candidate_name: str) -> tuple[pd.DataFrame, bool]:
    """Frozen development rule for a low-confidence specialist; 2024+ is not involved."""
    metrics = continuous_metrics({base_name: base, candidate_name: candidate}, keys_from)
    a, b = _aggregate(metrics, base_name), _aggregate(metrics, candidate_name)
    wanted = _keyed(keys_from).drop_duplicates(KEYS).set_index(KEYS).index
    yearly = {}
    for name, frame in ((base_name, base), (candidate_name, candidate)):
        f = _keyed(frame).drop_duplicates(KEYS).set_index(KEYS).reindex(wanted).dropna(subset=["forecast", "actual"])
        q = f.reset_index()
        q["year"] = pd.to_datetime(q["origin"]).dt.year
        yearly[name] = q.groupby("year").apply(
            lambda z: float((z.forecast - z.actual).abs().mean()), include_groups=False)
    yr = pd.concat(yearly, axis=1).dropna()
    worst = float((yr[candidate_name] / yr[base_name] - 1.0).max()) if len(yr) else np.nan
    checks = pd.DataFrame([
        dict(check="MAE is lower", value=a["mae"] - b["mae"], passed=b["mae"] < a["mae"]),
        dict(check="median APE is lower", value=a["median"] - b["median"], passed=b["median"] < a["median"]),
        dict(check="absolute bias does not rise", value=abs(a["bias"]) - abs(b["bias"]), passed=abs(b["bias"]) <= abs(a["bias"])),
        dict(check="absolute mean log error does not rise", value=abs(a["log"]) - abs(b["log"]), passed=abs(b["log"]) <= abs(a["log"])),
        dict(check="no development year MAE rises more than 5%", value=worst, passed=np.isfinite(worst) and worst <= 0.05 + 1e-12),
    ])
    return checks, bool(len(metrics) and checks["passed"].all())


@dataclass
class MLPResult:
    candidate: pd.DataFrame
    tree: pd.DataFrame
    gated: pd.DataFrame
    gated_tree: pd.DataFrame
    metrics_low: pd.DataFrame
    checks_mlp: pd.DataFrame
    checks_tree: pd.DataFrame
    keep_mlp: bool
    keep_tree: bool
    fits: pd.DataFrame


def run_mlp_specialist(base: pd.DataFrame, herd: pd.DataFrame, daily: pd.DataFrame,
                       probs: pd.DataFrame, base_model: str = "milk_baseline_adaptive",
                       cfg: MLPConfig = MLPConfig()) -> MLPResult:
    history = _keyed(base[base["model"] == base_model])
    if "band" in history:
        history = history[history["band"].isin(VERIFIED_BANDS)]
    scored = history[pd.to_datetime(history["origin"]).dt.year.isin(cfg.fold_years)]
    cutoff = pd.Timestamp(date(max(cfg.fold_years) + 1, 1, 1))
    dl = Daily.from_frame(daily[pd.to_datetime(daily["date"]) < cutoff])
    folds = run_folds(dl, sorted(set(scored["origin"])), cfg)
    candidate = structural_rows(scored, herd, folds.mlp, folds.ref_ypc, MODEL)
    tree = structural_rows(scored, herd, folds.tree, folds.ref_ypc, TREE_MODEL)
    flagged = attach_gate(scored, probs)
    gate_probs = flagged[["grain", "horizon", "origin", "period_start", "p_gate"]]
    gated = gated_switch(scored, candidate, gate_probs, gate="gate", threshold=0.5,
                         cells=CELLS, new_model=GATED)
    gated_tree = gated_switch(scored, tree, gate_probs, gate="gate", threshold=0.5,
                              cells=CELLS, new_model=GATED_TREE)
    switched = gated[gated["switched"]]
    metrics = continuous_metrics({base_model: scored, MODEL: candidate, TREE_MODEL: tree}, switched)
    checks_mlp, keep_mlp = acceptance_rule(scored, candidate, switched, base_model, MODEL)
    checks_tree, keep_tree = acceptance_rule(scored, tree, switched, base_model, TREE_MODEL)
    return MLPResult(candidate, tree, gated, gated_tree, metrics, checks_mlp, checks_tree,
                     keep_mlp, keep_tree, folds.fits)
