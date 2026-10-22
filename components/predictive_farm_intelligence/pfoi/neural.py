"""Neural milk model: GRU memory over recent milk + herd state + herd-engine path.

User decision (2026-10-21): the persistence blend (M10/T1) is rejected; the next model is
a learned one under an explicit two-stage chronological split with transfer learning:

  stage 1 (shipment records)  train 2015-08 .. 2017-12   test 2018-01 .. 2019-12
  stage 2 (DelPro records)    train 2020-08 .. 2022-12   test 2023-01 .. data end
                              (initialised from the stage-1 weights)

The last six months of each training span are validation (early stopping only). A sample
belongs to the part that contains its origin, and its targets are masked from the end of
that part on, so no training loss ever sees a validation or test day, and no validation
loss sees a test day (the embargo). Inputs at origin ``o`` use days before ``o`` only; the
engine path comes from the latest weekly engine run at or before ``o``.

The network predicts log(litres / R) for the 98 days o .. o+97, where R is the mean of the
scoreable days in the 28 days before ``o`` (scale-free, so the shipment era can teach the
DelPro era). Its output is added to the engine's own path, so it starts from the herd
engine and learns what curve x k misses. Five seeds are averaged.

Herd-level aggregates only. Nothing here opens a database; the caller passes a source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .backtest_milk import _Ctx, _milk_ctx, _target_frame, benchmark_forecasts, period_actual
from .config import EngineConfig
from .data import DATA_START, SnapshotSource, load_origin_inputs, prefetch_snapshots
from .freeze import DATA_END
from .herd_engine import project
from .milk_baseline import MilkConfig, MilkHistory, MilkWithheld, anchor_k, prepare_milk
from .parallel import map_origins
from .periods import HORIZONS, period_bounds
from .rates import estimate_rates

LOOKBACK = 56     # days of milk the GRU reads
REF_DAYS = 28     # level R = mean of scoreable days in this window
MIN_REF = 14      # scoreable days needed in the REF_DAYS window
H = 98            # days forecast: 13 weeks from the first Monday, or 3 calendar months
ENGINE_H = H + 7  # an engine run on Monday o' must cover o .. o+90 for o up to o'+6
SERIES = "herd_milk"
MAX_CORRECTION = 0.5   # |log| correction the net may add: x0.61 .. x1.65 of its base
MAX_ENGINE_LOG = 1.0   # engine paths beyond x0.37 .. x2.7 of the recent level are not trusted
Z_CLIP = 5.0           # scaled static features are clipped to +-5 sd of training
DIM_SHARES = ("0-60", "61-150", "151-305", "305+")
PARITY_SHARES = ("1", "2", "3+")
STATIC = ("src_delpro", "milking_trend", *(f"dim_{b}" for b in DIM_SHARES),
          *(f"parity_{p}" for p in PARITY_SHARES), "dry_preg_per_milking",
          "heifer_preg_per_milking", "calvings_28d_per_milking", "doy_sin", "doy_cos",
          "ref_ok_share", "engine_available", "engine_level_gap")


@dataclass(frozen=True)
class Stage:
    name: str
    source: str        # record source the stage learns and is tested on
    train_start: date
    val_start: date    # validation = [val_start, train_end), early stopping only
    train_end: date
    test_start: date
    test_end: date


STAGES = (
    Stage("stage1_shipment", "shipment", date(2015, 8, 1), date(2017, 7, 1), date(2018, 1, 1),
          date(2018, 1, 1), date(2020, 1, 1)),
    Stage("stage2_delpro", "delpro", date(2020, 8, 1), date(2022, 7, 1), date(2023, 1, 1),
          date(2023, 1, 1), DATA_END),
)
PARTS = ("train", "val", "test")


def part_bounds(stage: Stage, part: str) -> tuple[date, date]:
    """[start, end) of a split part; origins and targets of that part stay inside it."""
    return {"train": (stage.train_start, stage.val_start),
            "val": (stage.val_start, stage.train_end),
            "test": (stage.test_start, stage.test_end)}[part]


def check_split(stages: tuple[Stage, ...] = STAGES) -> None:
    """Parts are ordered, non-empty and never overlap (within and across stages)."""
    spans = []
    for s in stages:
        for part in PARTS:
            a, b = part_bounds(s, part)
            if not a < b:
                raise ValueError(f"{s.name} {part} is empty")
            spans.append((a, b, f"{s.name}:{part}"))
    spans.sort()
    for (a1, b1, n1), (a2, _, n2) in zip(spans, spans[1:]):
        if a2 < b1:
            raise ValueError(f"split parts overlap: {n1} and {n2}")


# ---------------------------------------------------------------- data (aggregates)

def daily_frame(source, start: date = DATA_START, end: date = DATA_END) -> pd.DataFrame:
    """One row per day: target, herd stocks and the milking mix (herd-level aggregates)."""
    t = _target_frame(source.target_daily(start, end))
    p = source.panel_daily(start, end)
    p["date"] = pd.to_datetime(p["date"]).dt.date
    p = p.set_index("date")
    mix = source.milking_mix_daily(start, end)
    mix["date"] = pd.to_datetime(mix["date"]).dt.date
    dim = mix.pivot_table(index="date", columns="dim_band", values="n", aggfunc="sum")
    par = mix.pivot_table(index="date", columns="parity_group", values="n", aggfunc="sum")
    days = pd.Index([start + timedelta(days=i) for i in range((end - start).days)], name="date")
    f = pd.DataFrame(index=days)
    f["litres"] = t["target_litres"].reindex(days).astype(float)
    f["ok"] = t["ok"].reindex(days).astype("boolean").fillna(False).astype(bool)
    f["src"] = t["target_source"].reindex(days)
    for col in ("milking", "dry_pregnant", "heifers_pregnant", "calvings"):
        f[col] = p[col].reindex(days).astype(float) if col in p else np.nan
    known = dim.reindex(columns=list(DIM_SHARES)).fillna(0.0).reindex(days)
    tot = known.sum(axis=1).replace(0, np.nan)
    for b in DIM_SHARES:
        f[f"dim_{b}"] = known[b] / tot
    pk = par.reindex(columns=list(PARITY_SHARES)).fillna(0.0).reindex(days)
    ptot = pk.sum(axis=1).replace(0, np.nan)
    for q in PARITY_SHARES:
        f[f"parity_{q}"] = pk[q] / ptot
    return f


def _engine_path(c: _Ctx, origin: date):
    """Engine milk path (litres per day, ENGINE_H days from ``origin``) or None."""
    try:
        setup = prepare_milk(c.source, origin, c.milk_cfg, c.hist, c.cache)
        inputs = load_origin_inputs(c.source, origin, c.cfg)
        anchor_k(setup, c.hist.target_before(origin), inputs.state, c.milk_cfg)
    except (ValueError, MilkWithheld):
        return None
    rates = estimate_rates(inputs.rate_inputs, c.cfg)
    proj = project(inputs.state, rates, ENGINE_H, milk_curve=setup.arrays)
    d = proj.daily
    return pd.DataFrame(dict(run=origin, date=pd.to_datetime(d["date"]).dt.date,
                             litres=setup.k * d["curve_litres"].to_numpy()))


def engine_paths(source, mondays: list[date], cfg: EngineConfig, mcfg: MilkConfig,
                 jobs: int = 1, source_factory=None, progress=None) -> pd.DataFrame:
    """Herd-engine milk paths at each Monday (columns run, date, litres)."""
    hist = MilkHistory(cowdays=source.milking_cowdays(DATA_START, DATA_END),
                       target=source.target_daily(DATA_START, DATA_END))
    t = _target_frame(hist.target)
    snaps = prefetch_snapshots(source, mondays, cfg)
    serial = (_Ctx(SnapshotSource(source, snaps), cfg, mcfg, hist, t, ("daily",), DATA_END, {})
              if jobs <= 1 else None)
    out = map_origins(mondays, _engine_path, _milk_ctx,
                      (source_factory, snaps, cfg, mcfg, hist, t, ("daily",), DATA_END),
                      jobs=jobs, progress=progress, serial_ctx=serial)
    frames = [p for p in out if p is not None]
    if not frames:
        return pd.DataFrame(columns=["run", "date", "litres"])
    return pd.concat(frames, ignore_index=True)


def mondays(start: date, end: date) -> list[date]:
    d = start + timedelta(days=(7 - start.weekday()) % 7)
    out = []
    while d < end:
        out.append(d)
        d += timedelta(days=7)
    return out


# ---------------------------------------------------------------- samples

@dataclass
class Samples:
    origin: np.ndarray   # dates
    seq: np.ndarray      # (N, LOOKBACK, 2): log(litres / R), scoreable mask
    stat: np.ndarray     # (N, len(STATIC))
    eng: np.ndarray      # (N, H, 2): engine log(path / R), available mask
    y: np.ndarray        # (N, H) log(actual / R)
    m: np.ndarray        # (N, H) 1 where y counts
    ref: np.ndarray      # (N,) R in litres per day

    def __len__(self) -> int:
        return len(self.origin)

    def take(self, idx) -> "Samples":
        return Samples(*(getattr(self, k)[idx] for k in
                         ("origin", "seq", "stat", "eng", "y", "m", "ref")))


def _engine_index(paths: pd.DataFrame) -> dict[date, pd.Series]:
    return {run: g.set_index("date")["litres"] for run, g in paths.groupby("run")}


def build_samples(f: pd.DataFrame, paths: pd.DataFrame, origins: list[date],
                  source: str, target_end: date) -> Samples:
    """Samples at ``origins`` for one record source. Inputs use days before each origin;
    targets are the days o .. o+H-1 before ``target_end`` with that source, else masked."""
    eng_by_run = _engine_index(paths)
    runs = sorted(eng_by_run)
    lit, ok, src = f["litres"].to_numpy(), f["ok"].to_numpy(), f["src"].to_numpy()
    pos = {d: i for i, d in enumerate(f.index)}
    rows = {k: [] for k in ("origin", "seq", "stat", "eng", "y", "m", "ref")}
    for o in origins:
        i = pos.get(o)
        if i is None or i < REF_DAYS:
            continue
        good = ok[i - REF_DAYS:i] & (src[i - REF_DAYS:i] == source)
        if good.sum() < MIN_REF:
            continue
        R = float(np.mean(lit[i - REF_DAYS:i][good]))
        if not R > 0:
            continue
        lo = max(0, i - LOOKBACK)
        seq = np.zeros((LOOKBACK, 2))
        w = slice(lo, i)
        g = ok[w] & (src[w] == source) & (lit[w] > 0)
        vals = np.where(g, np.log(np.where(g, lit[w], 1.0) / R), 0.0)
        seq[LOOKBACK - (i - lo):, 0], seq[LOOKBACK - (i - lo):, 1] = vals, g
        # targets o .. o+H-1, masked at target_end, at other sources and unscoreable days
        y, m = np.zeros(H), np.zeros(H)
        for h in range(H):
            j = i + h
            d = o + timedelta(days=h)
            if j < len(lit) and d < target_end and ok[j] and src[j] == source and lit[j] > 0:
                y[h], m[h] = np.log(lit[j] / R), 1.0
        # engine: latest run at or before o (a run on o uses days before o only)
        eng = np.zeros((H, 2))
        k = np.searchsorted(runs, o, side="right") - 1
        gap, has = 0.0, 0.0
        if k >= 0:
            path = eng_by_run[runs[k]]
            vals = path.reindex([o + timedelta(days=h) for h in range(H)]).to_numpy(dtype=float)
            if np.isfinite(vals).all() and (vals > 0).all():
                lv = np.log(vals / R)
                if np.abs(lv).max() <= MAX_ENGINE_LOG:  # an implausible engine level is left out
                    eng[:, 0], eng[:, 1] = lv, 1.0
                    gap, has = float(lv[0]), 1.0
        prev = f.iloc[i - 1]
        mk = f["milking"].iloc[i - REF_DAYS:i].mean()
        milking = prev["milking"]
        doy = 2 * np.pi * o.timetuple().tm_yday / 365.25
        stat = [float(source == "delpro"),
                np.log(milking / mk) if milking > 0 and mk > 0 else 0.0,
                *(prev[f"dim_{b}"] for b in DIM_SHARES),
                *(prev[f"parity_{q}"] for q in PARITY_SHARES),
                prev["dry_pregnant"] / milking if milking > 0 else 0.0,
                prev["heifers_pregnant"] / milking if milking > 0 else 0.0,
                f["calvings"].iloc[i - REF_DAYS:i].sum() / milking if milking > 0 else 0.0,
                np.sin(doy), np.cos(doy), good.mean(), has, gap]
        rows["origin"].append(o)
        rows["seq"].append(seq)
        rows["stat"].append(np.nan_to_num(np.asarray(stat, dtype=float)))
        rows["eng"].append(eng)
        rows["y"].append(y)
        rows["m"].append(m)
        rows["ref"].append(R)
    if not rows["origin"]:
        return Samples(np.array([], dtype=object), np.zeros((0, LOOKBACK, 2)),
                       np.zeros((0, len(STATIC))), np.zeros((0, H, 2)), np.zeros((0, H)),
                       np.zeros((0, H)), np.zeros(0))
    return Samples(np.array(rows["origin"], dtype=object), *(np.stack(rows[k]) for k in
                   ("seq", "stat", "eng", "y", "m")), np.asarray(rows["ref"]))


def stage_samples(f: pd.DataFrame, paths: pd.DataFrame, stage: Stage, part: str) -> Samples:
    """Daily origins of one split part; targets masked from the part's end on."""
    a, b = part_bounds(stage, part)
    origins = [a + timedelta(days=i) for i in range((b - a).days)]
    return build_samples(f, paths, origins, stage.source, b)


# ---------------------------------------------------------------- model

def _torch():
    import torch
    return torch


class Scaler:
    """z-scores of the static features from training samples only."""

    def __init__(self, stat: np.ndarray):
        self.mu = stat.mean(axis=0) if len(stat) else np.zeros(len(STATIC))
        sd = stat.std(axis=0) if len(stat) else np.ones(len(STATIC))
        # a feature almost constant in training (e.g. no engine path yet) is not blown up later
        self.sd = np.where(sd > 0.05, sd, 1.0)

    def __call__(self, stat: np.ndarray) -> np.ndarray:
        return np.clip((stat - self.mu) / self.sd, -Z_CLIP, Z_CLIP)


def make_net(hidden: int = 32):
    torch = _torch()
    nn = torch.nn

    class MilkNet(nn.Module):
        """GRU over the past 56 days + static herd state + engine path -> bounded correction
        (|log| <= MAX_CORRECTION) added to the engine's log path (or to persistence, 0,
        when there is no path)."""

        def __init__(self):
            super().__init__()
            self.gru = nn.GRU(2, hidden, batch_first=True)
            self.eng = nn.Sequential(nn.Linear(2 * H, 64), nn.ReLU())
            self.head = nn.Sequential(nn.Linear(hidden + len(STATIC) + 64, 128), nn.ReLU(),
                                      nn.Dropout(0.1), nn.Linear(128, H))
            nn.init.zeros_(self.head[-1].weight)
            nn.init.zeros_(self.head[-1].bias)

        def forward(self, seq, stat, eng):
            _, h = self.gru(seq)
            z = torch.cat([h[-1], stat, self.eng(eng.flatten(1))], dim=1)
            return eng[:, :, 0] * eng[:, :, 1] + MAX_CORRECTION * torch.tanh(self.head(z))

    return MilkNet()


def _tensors(s: Samples, scaler: Scaler):
    torch = _torch()
    t = lambda a: torch.as_tensor(a, dtype=torch.float32)
    return t(s.seq), t(scaler(s.stat)), t(s.eng), t(s.y), t(s.m)


def masked_l1(pred, y, m):
    return ((pred - y).abs() * m).sum() / m.sum().clamp(min=1.0)


@dataclass
class FitLog:
    epochs: int
    best_epoch: int
    train_loss: float
    val_loss: float | None


def fit(net, train: Samples, val: Samples, scaler: Scaler, seed: int, lr: float = 1e-3,
        max_epochs: int = 200, patience: int = 20, batch: int = 64) -> FitLog:
    """Adam on masked L1 of log ratios; early stopping on validation when it has targets."""
    torch = _torch()
    torch.manual_seed(seed)
    g = np.random.default_rng(seed)
    tr = _tensors(train, scaler)
    va = _tensors(val, scaler) if len(val) and val.m.sum() > 0 else None
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    best, best_state, best_epoch, wait, tl = np.inf, None, 0, 0, np.nan
    for epoch in range(1, max_epochs + 1):
        net.train()
        order = g.permutation(len(train))
        losses = []
        for b in range(0, len(order), batch):
            idx = torch.as_tensor(order[b:b + batch])
            opt.zero_grad()
            loss = masked_l1(net(tr[0][idx], tr[1][idx], tr[2][idx]), tr[3][idx], tr[4][idx])
            loss.backward()
            opt.step()
            losses.append(float(loss.detach()))
        tl = float(np.mean(losses)) if losses else np.nan
        if va is None:
            continue
        net.eval()
        with torch.no_grad():
            vl = float(masked_l1(net(*va[:3]), va[3], va[4]))
        if vl < best - 1e-6:
            best, best_epoch, wait = vl, epoch, 0
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        else:
            wait += 1
            if wait >= patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    return FitLog(epoch, best_epoch or epoch, tl, None if va is None else best)


def predict(nets: list, s: Samples, scaler: Scaler) -> np.ndarray:
    """Mean log ratio over the ensemble, shape (N, H)."""
    torch = _torch()
    x = _tensors(s, scaler)
    outs = []
    for net in nets:
        net.eval()
        with torch.no_grad():
            outs.append(net(*x[:3]).numpy())
    return np.mean(outs, axis=0)


# ---------------------------------------------------------------- scoring

def score_rows(f: pd.DataFrame, s: Samples, logp: np.ndarray, model: str, stage: Stage,
               paths: pd.DataFrame, with_benchmarks: bool) -> list[dict]:
    """Backtest-style error rows at Monday test origins (daily 1/7/14, weekly 1/4/8/13).
    A period counts only if every day is scoreable, one source, and before the test end."""
    t = f.rename(columns={"litres": "target_litres", "src": "target_source"})
    eng = _engine_index(paths)
    rows = []
    for n, o in enumerate(s.origin):
        if o.weekday() != 0:
            continue
        path = pd.Series(s.ref[n] * np.exp(logp[n]), index=[o + timedelta(days=h) for h in range(H)])
        preds: dict[tuple[str, str, int], float] = {}
        for grain in ("daily", "weekly"):
            for h in HORIZONS[grain]:
                a, b = period_bounds(o, grain, h)
                preds[(model, grain, h)] = float(path.loc[a:b - timedelta(days=1)].sum())
                if with_benchmarks and o in eng:
                    e = eng[o].loc[a:b - timedelta(days=1)]
                    if len(e) == (b - a).days:
                        preds[("milk_baseline", grain, h)] = float(e.sum())
            if with_benchmarks:
                for bm, h, v in benchmark_forecasts(t, o, grain, HORIZONS[grain]):
                    preds[(bm, grain, h)] = v
        for (mdl, grain, h), v in preds.items():
            a, b = period_bounds(o, grain, h)
            if b > stage.test_end:
                continue
            act = period_actual(t, a, b)
            if act is None or act[1] != stage.source:
                continue
            rows.append(dict(stage=stage.name, origin=o, grain=grain, horizon=h, period_start=a,
                             period_end=b, series=SERIES, model=mdl, forecast=v, actual=act[0],
                             source=act[1]))
    return rows


def summarise(errors: pd.DataFrame) -> pd.DataFrame:
    """n, MAE, bias and MAE ratio to persistence on identical periods, per stage/grain/h."""
    if errors.empty:
        return pd.DataFrame()
    e = errors.assign(abs_err=(errors["forecast"] - errors["actual"]).abs(),
                      err=errors["forecast"] - errors["actual"])
    keys = ["stage", "grain", "horizon", "origin", "period_start"]
    per_stage = e.groupby("stage")["model"].transform("nunique")
    e = e[e.groupby(keys)["model"].transform("nunique") == per_stage]
    out = (e.groupby(["stage", "grain", "horizon", "model"])
           .agg(n=("abs_err", "size"), mae=("abs_err", "mean"), bias=("err", "mean"))
           .reset_index())
    pers = out[out["model"] == "persistence"].set_index(["stage", "grain", "horizon"])["mae"]
    out["ratio_to_persistence"] = [r.mae / pers.get((r.stage, r.grain, r.horizon), np.nan)
                                   for r in out.itertuples()]
    return out


# ---------------------------------------------------------------- the two-stage run

@dataclass
class NeuralResult:
    errors: pd.DataFrame
    summary: pd.DataFrame
    fits: pd.DataFrame       # one row per stage x variant x seed (losses, epochs)
    counts: pd.DataFrame     # samples and scored target days per stage x part
    nets: dict               # (stage, variant) -> list of fitted networks
    paths: pd.DataFrame      # daily forecast paths at first-of-month test origins (page documents)


def run_neural(f: pd.DataFrame, paths: pd.DataFrame, seeds: tuple[int, ...] = (0, 1, 2, 3, 4),
               max_epochs: int = 200, patience: int = 20,
               stages: tuple[Stage, ...] = STAGES) -> NeuralResult:
    """Stage 1 from scratch; stage 2 both fine-tuned from stage 1 (transfer) and from
    scratch, so the value of transfer is measured, not assumed. Test parts are only
    predicted, never trained or early-stopped on."""
    check_split(stages)
    errors, fits, counts, nets_out, paths_out = [], [], [], {}, []
    prev: tuple[list, Scaler] | None = None
    for si, stage in enumerate(stages):
        parts = {p: stage_samples(f, paths, stage, p) for p in PARTS}
        for p, s in parts.items():
            counts.append(dict(stage=stage.name, part=p, samples=len(s),
                               target_days=int(s.m.sum()), engine_share=float(s.stat[:, -2].mean())
                               if len(s) else np.nan))
        if len(parts["train"]) == 0:
            continue
        variants = {"neural_scratch": None}
        if prev is not None:
            variants = {"neural_transfer": prev, **variants}
        for variant, init in variants.items():
            scaler = init[1] if init else Scaler(parts["train"].stat)
            nets = []
            for k, seed in enumerate(seeds):
                net = make_net()
                lr = 1e-3
                if init:
                    net.load_state_dict(init[0][k].state_dict())
                    lr = 3e-4
                log = fit(net, parts["train"], parts["val"], scaler, seed, lr=lr,
                          max_epochs=max_epochs, patience=patience)
                fits.append(dict(stage=stage.name, model=variant, seed=seed, epochs=log.epochs,
                                 best_epoch=log.best_epoch, train_l1=log.train_loss,
                                 val_l1=log.val_loss))
                nets.append(net)
            nets_out[(stage.name, variant)] = (nets, scaler)
            test = parts["test"]
            if len(test):
                logp = predict(nets, test, scaler)
                errors += score_rows(f, test, logp, variant, stage, paths,
                                     with_benchmarks=(variant == "neural_scratch"))
                for n, o in enumerate(test.origin):
                    if o.day == 1:
                        paths_out += [dict(stage=stage.name, model=variant, origin=o,
                                           date=o + timedelta(days=h),
                                           litres=float(test.ref[n] * np.exp(logp[n, h])))
                                      for h in range(H)]
        # stage 1 has only one variant; later stages pass on the transfer chain if present
        prev = nets_out.get((stage.name, "neural_transfer")) or nets_out[(stage.name, "neural_scratch")]
    err = pd.DataFrame(errors)
    pth = pd.DataFrame(paths_out, columns=["stage", "model", "origin", "date", "litres"])
    if len(stages) > 1:
        pth.loc[(pth["stage"] == stages[0].name) & (pth["model"] == "neural_scratch"), "model"] = "neural"
    if len(err):
        err["error"] = err["forecast"] - err["actual"]
        if len(stages) > 1:  # stage 1 is a scratch model; name it for what it is
            err.loc[(err["stage"] == stages[0].name) & (err["model"] == "neural_scratch"),
                    "model"] = "neural"
    return NeuralResult(err, summarise(err), pd.DataFrame(fits), pd.DataFrame(counts), nets_out, pth)
