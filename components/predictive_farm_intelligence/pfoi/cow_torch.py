"""PyTorch-only individual-cow yield models on the Apple GPU (notebook 06).

Same protocol and features as notebook 05 (gap excluded, 75/5/20 split, origin-safe
health/treatment/sensor/level features, walk-forward daily/weekly/monthly), but every
learned correction is a PyTorch network trained on ``device`` ("auto" = Apple GPU via
MPS when present).

This module never imports LightGBM or the random forest. On macOS PyTorch crashes in a
process where LightGBM has trained (two OpenMP runtimes), so notebook 06 must run in its
own kernel; :func:`assert_torch_safe_process` stops early if LightGBM is already loaded.

Model (v2, 2026-10-22):

- **base:** the Wood mixed curve, recalibrated walk-forward to the herd's recent level
  (``wood_mixed_recal``; past outcomes only). The networks learn a bounded log
  correction *to this base*, so they no longer have to learn the level themselves;
- **training:** standardised features clipped to +-5 SD (no wild extrapolation on
  sources that only start late in training); up to ``max_epochs`` (250) epochs with
  dropout 0.3; every 10th calendar week of the training block is held out to monitor
  accuracy in litres (spread through all regimes). Training stops only when that
  accuracy stays more than ``stop_drop_pp`` (0.5) percentage points below its best for
  ``stop_patience`` (15) consecutive epochs, and never before ``min_epochs`` (50); the best
  epoch's weights are kept; the learning rate halves when accuracy stalls for
  ``lr_patience`` epochs;
- **cleaner training targets:** training rows whose yield is under 60% of the median
  of the cow's neighbouring records (same lactation) are likely partial records (e.g.
  one of two milkings); they are left out of *training* only. Every row is still
  forecast and scored, so the test is unchanged;
- **Kalman level:** a per-cow state-space model (``cow_kalman``) gives each cow's
  current deviation from the base and its uncertainty, known at the origin. It is a
  candidate on its own (``kalman_state``) and two extra inputs for every network;
- **candidates:** persistence; Wood; ``kalman_state``; ``torch_mlp_small`` and
  ``torch_mlp_large`` (each an average of ``ensemble`` networks with different seeds);
  ``torch_gru`` (a GRU over the cow's last ``seq_len`` same-lactation records plus the
  static inputs); ``torch_q50`` (median of a 10/50/90% quantile network, whose 10-90%
  range is kept as a prediction interval). Every candidate also as ``_recal`` (herd
  level) and ``_grp`` (parity x DIM level);
- **out-of-fold training predictions** (optional, ``oof=True``) for the blend weights.

MPS kernels are not bitwise deterministic: repeated runs agree closely, not exactly.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .cow_accuracy import (BASE_FEATURES, LEVEL_FEATURES, TRAIN_START, AccuracyModels,
                           CowSplit, _add_level_features, _design, fit_wood_mixed,
                           prepare_accuracy_frame, prepare_cowdays, recalibrate,
                           recalibrate_by_group)
from .cow_kalman import fit_kalman, kalman_at_origin

TORCH_MODEL_NAME = "pfoi-cow-yield-torch-1.6.0-dev"
ARCHITECTURES = {"torch_mlp_small": (64, 32), "torch_mlp_large": (256, 128, 64)}
DEFAULT_PARAMS = dict(dropout=0.3, lr=1e-3, weight_decay=1e-4, batch_size=2048,
                      max_epochs=250, min_epochs=50, stop_drop_pp=0.5, stop_patience=15,
                      lr_patience=5, min_lr=1e-6)
INT_PARAMS = {"batch_size", "max_epochs", "min_epochs", "stop_patience", "lr_patience"}
# Model options (not tuned): ensemble size, GRU settings, which extra models to fit.
MODEL_OPTIONS = dict(ensemble=3, use_kalman=True, use_gru=True, gru_seeds=1, seq_len=16,
                     gru_hidden=32, use_quantile=True, robust_training=True,
                     partial_ratio=0.6)
QUANTILES = (0.1, 0.5, 0.9)
CLIP = 0.7
FEATURE_CLIP_SD = 5.0
STOP_EVERY_WEEKS = 10   # every 10th calendar week of training = early-stopping set
OOF_FOLDS = 3


def assert_torch_safe_process() -> None:
    if "lightgbm" in sys.modules:
        raise RuntimeError("LightGBM is loaded in this process; PyTorch would crash here on "
                           "macOS. Restart the kernel and run notebook 06 on its own.")


def resolve_device(device: str = "auto") -> str:
    import torch

    if device == "auto":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    return device


@dataclass
class _Scaler:
    """Median-impute (with missing indicators), standardise and clip, fitted on training."""
    columns: list[str]
    medians: np.ndarray
    means: np.ndarray
    stds: np.ndarray
    indicator: np.ndarray

    @classmethod
    def fit(cls, x: pd.DataFrame) -> "_Scaler":
        a = x.to_numpy(dtype=np.float64)
        med = np.nanmedian(np.where(np.isfinite(a), a, np.nan), axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        ind = np.isnan(a).any(axis=0)
        filled = np.where(np.isnan(a), med, a)
        full = np.hstack([filled, np.isnan(a[:, ind]).astype(float)])
        mean, std = full.mean(axis=0), full.std(axis=0)
        return cls(list(x.columns), med, mean, np.where(std > 0, std, 1.0), ind)

    def transform(self, x: pd.DataFrame) -> np.ndarray:
        a = x[self.columns].to_numpy(dtype=np.float64)
        filled = np.where(np.isnan(a), self.medians, a)
        full = np.hstack([filled, np.isnan(a[:, self.indicator]).astype(float)])
        z = (full - self.means) / self.stds
        return np.clip(z, -FEATURE_CLIP_SD, FEATURE_CLIP_SD).astype(np.float32)


def _build(n_in: int, hidden: tuple[int, ...], dropout: float):
    import torch.nn as nn

    layers, width = [], n_in
    for h in hidden:
        layers += [nn.Linear(width, h), nn.ReLU(), nn.Dropout(dropout)]
        width = h
    layers.append(nn.Linear(width, 1))
    return nn.Sequential(*layers)


def _week_index(dates: pd.Series) -> np.ndarray:
    d = pd.to_datetime(dates)
    return ((d - d.min()).dt.days // 7).to_numpy()


def _modules():
    """PyTorch module classes (built lazily so importing this file never loads torch)."""
    import torch
    import torch.nn as nn

    class MLP(nn.Module):
        def __init__(self, n_in, hidden, dropout, n_out=1):
            super().__init__()
            self.net = _build(n_in, hidden, dropout)
            if n_out != 1:
                self.net[-1] = nn.Linear(self.net[-1].in_features, n_out)

        def forward(self, x):
            return self.net(x)

    class GRUNet(nn.Module):
        """GRU over the cow's recent records + MLP over the static inputs."""
        def __init__(self, n_static, n_step, hidden, dropout):
            super().__init__()
            self.gru = nn.GRU(n_step, hidden, batch_first=True)
            self.static = nn.Sequential(nn.Linear(n_static, 64), nn.ReLU(), nn.Dropout(dropout))
            self.head = nn.Sequential(nn.Linear(hidden + 64, 32), nn.ReLU(),
                                      nn.Dropout(dropout), nn.Linear(32, 1))

        def forward(self, x, seq):
            _, h = self.gru(seq)
            return self.head(torch.cat([h[-1], self.static(x)], dim=1))

    return MLP, GRUNet


def _fit_module(net, inputs: list[np.ndarray], y: np.ndarray, fit_idx: np.ndarray,
                stop_idx: np.ndarray, params: dict, device: str, seed: int = 17,
                base: np.ndarray | None = None, litres: np.ndarray | None = None,
                quantiles: tuple[float, ...] | None = None) -> tuple[object, dict]:
    """Train ``net`` on ``fit_idx`` rows; monitor ``stop_idx`` rows (time blocks).

    The monitor is accuracy in litres (100 - WAPE of ``base * exp(output)``; the median
    column for quantile nets) when ``base``/``litres`` are given, else the loss. Training
    stops only when the monitor stays more than ``stop_drop_pp`` points below its best
    for ``stop_patience`` epochs, never before ``min_epochs``; the best weights are kept.
    """
    import torch

    torch.manual_seed(seed)
    net = net.to(device)
    xs = [torch.from_numpy(a).to(device) for a in inputs]
    yt = torch.from_numpy(y.astype(np.float32)).reshape(-1, 1).to(device)
    fit_t = torch.from_numpy(np.asarray(fit_idx)).to(device)
    stop_t = torch.from_numpy(np.asarray(stop_idx)).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=params["lr"],
                            weight_decay=params["weight_decay"])
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, mode="max", factor=0.5, patience=params.get("lr_patience", 5))
    huber = torch.nn.SmoothL1Loss(beta=0.1)  # Huber on the log ratio, robust to outliers
    if quantiles:
        q = torch.tensor(quantiles, dtype=torch.float32, device=device).reshape(1, -1)
        mid = list(quantiles).index(0.5)

        def loss_fn(out, target):  # pinball loss over all quantiles
            e = target - out
            return torch.maximum(q * e, (q - 1) * e).mean()
    else:
        mid = 0
        loss_fn = huber
    use_acc = base is not None and litres is not None and len(stop_idx) > 0
    if use_acc:
        stop_base = torch.from_numpy(base[stop_idx].astype(np.float32)).to(device)
        stop_y = torch.from_numpy(litres[stop_idx].astype(np.float32)).to(device)
    tol = params.get("stop_drop_pp", 0.5)
    gen = torch.Generator(device="cpu").manual_seed(seed)
    best, best_state, best_epoch, below, epochs = -np.inf, None, 0, 0, 0
    history = []
    for epoch in range(params["max_epochs"]):
        net.train()
        perm = fit_t[torch.randperm(len(fit_idx), generator=gen).to(device)]
        for start in range(0, len(perm), params["batch_size"]):
            idx = perm[start:start + params["batch_size"]]
            loss = loss_fn(net(*[x[idx] for x in xs]), yt[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            out = net(*[x[stop_t] for x in xs]) if len(stop_idx) else None
            if use_acc:
                pred = stop_base * torch.exp(torch.clamp(out[:, mid], -CLIP, CLIP))
                score = float(100 - 100 * (pred - stop_y).abs().sum() / stop_y.sum())
            elif out is not None:
                score = -100 * float(loss_fn(out, yt[stop_t]))
            else:
                score = 0.0
        sched.step(score)
        epochs = epoch + 1
        history.append(score)
        if score > best:
            best, best_epoch = score, epochs
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        below = below + 1 if score < best - tol else 0
        stalled = opt.param_groups[0]["lr"] < params.get("min_lr", 0.0)
        if epochs >= params.get("min_epochs", 0) and (
                below >= params.get("stop_patience", 10) or stalled):
            # Stop on a sustained accuracy drop, or once the learning rate has been
            # halved so often (< min_lr) that further epochs can no longer change anything.
            break
    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()
    return net, {"epochs": epochs, "best_epoch": best_epoch, "best_monitor": best,
                 "monitor": "accuracy_pct" if use_acc else "neg_loss",
                 "final_lr": opt.param_groups[0]["lr"], "history": history,
                 "device": device}


def train_net(x: np.ndarray, y: np.ndarray, fit_idx: np.ndarray, stop_idx: np.ndarray,
              hidden: tuple[int, ...], params: dict, device: str, seed: int = 17,
              base: np.ndarray | None = None,
              litres: np.ndarray | None = None) -> tuple[object, dict]:
    """Train one MLP correction (see :func:`_fit_module` for stopping)."""
    import torch

    torch.manual_seed(seed)
    MLP, _ = _modules()
    return _fit_module(MLP(x.shape[1], hidden, params["dropout"]), [x], y, fit_idx,
                       stop_idx, params, device, seed, base, litres)


def predict_net(net, inputs, device: str, batch: int = 65536) -> np.ndarray:
    """Forward pass in batches; ``inputs`` is one array or a list of aligned arrays."""
    import torch

    inputs = inputs if isinstance(inputs, (list, tuple)) else [inputs]
    out = []
    with torch.no_grad():
        for start in range(0, len(inputs[0]), batch):
            o = net(*[torch.from_numpy(a[start:start + batch]).to(device) for a in inputs])
            out.append(o.cpu().numpy())
    res = np.concatenate(out).astype(float)
    return res.ravel() if res.shape[1] == 1 else res


def _split_stop(train: np.ndarray, weeks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    stop = train & (weeks % STOP_EVERY_WEEKS == STOP_EVERY_WEEKS - 1)
    return np.flatnonzero(train & ~stop), np.flatnonzero(stop)


def likely_partial_records(frame: pd.DataFrame, ratio: float = 0.6) -> np.ndarray:
    """Records below ``ratio`` x the median of the cow's neighbouring same-lactation records.

    Uses records on both sides, so it is only for choosing *training targets*, never a
    feature or a scoring filter.
    """
    key = [frame["animal"], frame["lactation"]] if "lactation" in frame else [frame["animal"]]
    med = (frame.groupby(key, sort=False)["litres"]
           .transform(lambda s: s.rolling(7, center=True, min_periods=4).median()))
    return (frame["litres"] < ratio * med).fillna(False).to_numpy()


def _sequences(frame: pd.DataFrame, base: np.ndarray, seq_len: int) -> np.ndarray:
    """(rows, seq_len, 4): the cow's last ``seq_len`` same-lactation records before origin.

    Step features: log(yield / base) of that record, days from it to the predicted day
    (/60), its days in milk (/300), and a 1/0 'record present' flag. Left-padded zeros.
    """
    n = len(frame)
    animal = frame["animal"].to_numpy()
    lact = frame["lactation"].to_numpy() if "lactation" in frame else np.zeros(n)
    dates = frame["date"].to_numpy()
    hist = pd.DataFrame({"pos": np.arange(n), "animal": animal, "rec_date": dates}
                        ).sort_values("rec_date")
    left = pd.DataFrame({"row": np.arange(n), "animal": animal,
                         "origin": pd.to_datetime(frame["origin_date"]).to_numpy()
                         .astype("datetime64[ns]")}).sort_values("origin")
    m = pd.merge_asof(left, hist, left_on="origin", right_on="rec_date", by="animal",
                      allow_exact_matches=False).sort_values("row")
    last = m["pos"].fillna(-1).to_numpy().astype(np.int64)
    # Rows are sorted by cow and date, so a cow's earlier records sit just before ``last``.
    offsets = np.arange(seq_len - 1, -1, -1)
    pos = last[:, None] - offsets[None, :]
    valid = (last[:, None] >= 0) & (pos >= 0)
    pos_c = np.clip(pos, 0, n - 1)
    valid &= (animal[pos_c] == animal[:, None]) & (lact[pos_c] == lact[:, None])
    z = np.log(frame["litres"].to_numpy() / np.maximum(base, 1e-6))
    gap = ((dates[:, None] - dates[pos_c]).astype("timedelta64[D]").astype(float)) / 60.0
    dim = frame["dim"].to_numpy()[pos_c] / 300.0
    seq = np.stack([np.where(valid, z[pos_c], 0.0), np.where(valid, gap, 0.0),
                    np.where(valid, dim, 0.0), valid.astype(float)], axis=-1)
    return np.clip(seq, -5, 5).astype(np.float32)


def fit_torch_models(raw: pd.DataFrame, train_end: date, validation_end: date,
                     events: dict | None = None, min_source_records: int = 100,
                     params: dict | None = None, device: str = "auto", seed: int = 17,
                     oof: bool = False, options: dict | None = None,
                     verbose: bool = False,
                     grains: tuple[str, ...] = ("daily", "weekly", "monthly"),
                     model_names: tuple[str, ...] | None = None,
                     keep_state: bool = False,
                     **_ignored) -> AccuracyModels:
    """Walk-forward daily/weekly/monthly torch models; returns AccuracyModels.

    ``options`` override :data:`MODEL_OPTIONS` (ensemble size, GRU, quantile, Kalman,
    cleaner training targets). ``grains`` and ``model_names`` let the production
    correction fit only the daily model it actually publishes; defaults retain the
    full Notebook 6 comparison. ``grains`` may omit daily (the Wood curve and Kalman
    parameters are still fitted on the daily frame, as always). ``keep_state`` stores each
    network's scaler and CPU weights in ``fitted[name]["state"]`` so the exact predictor
    can be persisted and reloaded (``cow_milk_predictor``); it changes no prediction.
    Extra keyword arguments used by the LightGBM pipeline
    are accepted and ignored, so this can stand in for ``fit_accuracy_models``.
    """
    assert_torch_safe_process()
    import torch

    device = resolve_device(device)
    opts = {**MODEL_OPTIONS, **(options or {})}
    params = {**DEFAULT_PARAMS, **(params or {})}
    tuned = tuple(params.pop("hidden_large", ARCHITECTURES["torch_mlp_large"]))
    # The tuned shape replaces the large network unless it is just the small one again.
    architectures = {**ARCHITECTURES,
                     "torch_mlp_large": (tuned if tuned != ARCHITECTURES["torch_mlp_small"]
                                         else ARCHITECTURES["torch_mlp_large"])}
    unknown_grains = set(grains) - {"daily", "weekly", "monthly"}
    if unknown_grains or not grains:
        raise ValueError("grains must be a non-empty subset of daily/weekly/monthly")
    if model_names is not None:
        unknown_models = set(model_names) - set(architectures)
        if unknown_models:
            raise ValueError(f"unknown torch architecture(s): {sorted(unknown_models)}")
        architectures = {name: architectures[name] for name in model_names}
    MLP, GRUNet = _modules()
    started = time.perf_counter()

    def log(msg: str) -> None:
        if verbose:
            print(f"[cow-torch] {msg}", flush=True)

    def describe(name, info, rows, seconds):
        return (f"{name}: {rows:,} training rows, {seconds:.1f}s, best epoch "
                f"{info['best_epoch']} of {info['epochs']}, monitor {info['best_monitor']:.2f}%, "
                f"final lr {info['final_lr']:.1e}")

    prep = dict(train_end=train_end, validation_end=validation_end,
                evaluation_mode="walk_forward", events=events,
                min_source_records=min_source_records)
    f = prepare_accuracy_frame(raw, origin_grain="daily", **prep)
    features = BASE_FEATURES + tuple(f.attrs.get("event_features", ())) + LEVEL_FEATURES
    split = CowSplit(start=TRAIN_START, train_end=train_end, validate_end=validation_end,
                     gap_end=validation_end, recal_end=validation_end)
    t0 = time.perf_counter()
    fitting = prepare_cowdays(f, split)
    wood = fit_wood_mixed(fitting, calendar_level=True)
    wood_pred = wood.predict(fitting)
    log(f"Wood curve fitted in {time.perf_counter() - t0:.1f}s; {len(features)} features; "
        f"device={device}; options={opts}")
    kalman_params = None
    if opts["use_kalman"]:
        t0 = time.perf_counter()
        daily_base = recalibrate(f, wood_pred)
        kalman_params, kalman_table = fit_kalman(f, daily_base,
                                                 (f["period"] == "train").to_numpy(),
                                                 verbose=verbose)
        log(f"Kalman parameters chosen in {time.perf_counter() - t0:.1f}s")
    out = None
    for grain in grains:
        t0 = time.perf_counter()
        fx = f if grain == "daily" else prepare_accuracy_frame(raw, origin_grain=grain, **prep)
        fx = _add_level_features(fx, wood_pred)
        x = _design(fx, features)
        base = recalibrate(fx, wood_pred)  # walk-forward level, past outcomes only
        litres = fx["litres"].to_numpy()
        raw_preds = {"wood_mixed": wood_pred}
        fitted, intervals = {}, {}
        if kalman_params is not None:
            kf_mean, kf_sd = kalman_at_origin(fx, base, kalman_params)
            x["kf_level"], x["kf_sd"] = kf_mean, kf_sd
            raw_preds["kalman_state"] = base * np.exp(np.clip(kf_mean, -CLIP, CLIP))
            fitted["kalman_state"] = dict(kalman_params)
        train = (fx["period"] == "train").to_numpy()
        weeks = _week_index(fx["date"])
        partial = likely_partial_records(fx, opts["partial_ratio"]) if opts["robust_training"] \
            else np.zeros(len(fx), dtype=bool)
        train_fit = train & ~partial
        scaler = _Scaler.fit(x.loc[train])
        xa = scaler.transform(x)
        target = np.clip(np.log(litres / np.maximum(base, 1e-6)), -CLIP, CLIP)
        fit_idx, stop_idx = _split_stop(train_fit, weeks)
        log(f"{grain}: {int(train.sum()):,} training rows, {int((train & partial).sum()):,} "
            f"likely partial records left out of training, {x.shape[1]} inputs")

        for name, hidden in architectures.items():
            t1 = time.perf_counter()
            outs, infos = [], []
            nets = []
            for k in range(opts["ensemble"]):
                torch.manual_seed(seed + 101 * k)
                net, info = _fit_module(MLP(xa.shape[1], hidden, params["dropout"]), [xa],
                                        target, fit_idx, stop_idx, params, device,
                                        seed + 101 * k, base, litres)
                outs.append(predict_net(net, xa, device))
                infos.append(info)
                nets.append(net)
            raw_preds[name] = base * np.exp(np.clip(np.mean(outs, axis=0), -CLIP, CLIP))
            fitted[name] = {"members": infos, "best_epoch": infos[0]["best_epoch"],
                            "epochs": infos[0]["epochs"]}
            if keep_state:
                fitted[name]["state"] = _state(scaler, nets, "mlp", hidden=hidden,
                                               n_in=xa.shape[1], dropout=params["dropout"])
            log(f"{grain}: {name} {hidden} x{opts['ensemble']} seeds in "
                f"{time.perf_counter() - t1:.1f}s; first seed: "
                + describe(name, infos[0], len(fit_idx), 0).split(": ", 1)[1])

        if opts["use_gru"]:
            t1 = time.perf_counter()
            seq = _sequences(fx, base, opts["seq_len"])
            outs, infos = [], []
            nets = []
            for k in range(opts["gru_seeds"]):
                torch.manual_seed(seed + 211 * k)
                net, info = _fit_module(GRUNet(xa.shape[1], seq.shape[2], opts["gru_hidden"],
                                               params["dropout"]), [xa, seq], target, fit_idx,
                                        stop_idx, params, device, seed + 211 * k, base, litres)
                outs.append(predict_net(net, [xa, seq], device))
                infos.append(info)
                nets.append(net)
            raw_preds["torch_gru"] = base * np.exp(np.clip(np.mean(outs, axis=0), -CLIP, CLIP))
            fitted["torch_gru"] = {"members": infos, "best_epoch": infos[0]["best_epoch"],
                                   "epochs": infos[0]["epochs"]}
            if keep_state:
                fitted["torch_gru"]["state"] = _state(
                    scaler, nets, "gru", n_in=xa.shape[1], n_step=seq.shape[2],
                    gru_hidden=opts["gru_hidden"], seq_len=opts["seq_len"],
                    dropout=params["dropout"])
            log(f"{grain}: torch_gru (last {opts['seq_len']} records) in "
                f"{time.perf_counter() - t1:.1f}s; "
                + describe("gru", infos[0], len(fit_idx), 0).split(": ", 1)[1])

        if opts["use_quantile"]:
            t1 = time.perf_counter()
            qnet, info = _fit_module(MLP(xa.shape[1], ARCHITECTURES["torch_mlp_small"],
                                         params["dropout"], n_out=len(QUANTILES)), [xa],
                                     target, fit_idx, stop_idx, params, device, seed + 7,
                                     base, litres, quantiles=QUANTILES)
            q = np.sort(predict_net(qnet, xa, device), axis=1)  # no crossing quantiles
            raw_preds["torch_q50"] = base * np.exp(np.clip(q[:, 1], -CLIP, CLIP))
            intervals["torch_q50"] = (base * np.exp(np.clip(q[:, 0], -CLIP, CLIP)),
                                      base * np.exp(np.clip(q[:, 2], -CLIP, CLIP)))
            fitted["torch_q50"] = info
            if keep_state:
                info["state"] = _state(scaler, [qnet], "quantile",
                                       hidden=ARCHITECTURES["torch_mlp_small"],
                                       n_in=xa.shape[1], dropout=params["dropout"],
                                       quantiles=QUANTILES)
            log(f"{grain}: torch_q50 (10/50/90% quantiles) in {time.perf_counter() - t1:.1f}s; "
                + describe("q", info, len(fit_idx), 0).split(": ", 1)[1])

        preds = {"persistence_last_yield": fx["yield_lag1"].fillna(
            pd.Series(wood_pred, index=fx.index)).to_numpy(dtype=float)}
        for name, p in raw_preds.items():
            preds[name] = p
            preds[f"{name}_recal"] = recalibrate(fx, p)
            preds[f"{name}_grp"] = recalibrate_by_group(fx, p)
        if out is None:
            out = AccuracyModels(fx, preds, {"wood_mixed": wood, **fitted},
                                 evaluation_mode="walk_forward", features=features)
            if grain != "daily":  # production fit without the daily grain
                out.grain_frames[grain], out.grain_predictions[grain] = fx, preds
                out.grain_fitted[grain] = fitted
        else:
            out.grain_frames[grain], out.grain_predictions[grain] = fx, preds
            out.grain_fitted[grain] = fitted
        out.intervals[grain] = intervals
        log(f"{grain}: done in {time.perf_counter() - t0:.1f}s ({len(preds)} candidates)")
    log(f"all grains in {time.perf_counter() - started:.1f}s")
    return out


def _state(scaler: "_Scaler", nets: list, kind: str, **spec) -> dict:
    """Everything needed to rebuild a fitted network family without refitting."""
    return {"kind": kind, "scaler": scaler,
            "state_dicts": [{k: v.detach().cpu().clone() for k, v in n.state_dict().items()}
                            for n in nets],
            **spec}


def interval_coverage(models: AccuracyModels, block: str = "test") -> pd.DataFrame:
    """Share of scoreable cow-days inside each model's 10-90% range, and its width."""
    rows = []
    for grain, by_model in models.intervals.items():
        frame, _ = models.for_grain(grain)
        idx = ((frame["period"] == block) & frame["score_eligible"].astype(bool)).to_numpy()
        y = frame["litres"].to_numpy()[idx]
        for name, (lo, hi) in by_model.items():
            if not idx.any():
                continue
            l, h = lo[idx], hi[idx]
            rows.append({"grain": grain, "model": name, "block": block, "cow_days": int(idx.sum()),
                         "inside_10_90_pct": 100 * float(((y >= l) & (y <= h)).mean()),
                         "target_pct": 80.0, "mean_width_litres": float((h - l).mean()),
                         "below_pct": 100 * float((y < l).mean()),
                         "above_pct": 100 * float((y > h).mean())})
    return pd.DataFrame(rows)


def tune_torch(folds: list[dict], n_trials: int = 12, device: str = "auto", seed: int = 17,
               verbose: bool = False, fixed: dict | None = None) -> tuple[dict, pd.DataFrame]:
    """Random search on the expanding training folds of ``cow_tuning.build_folds``.

    Each fold is scored exactly as the real model works: a network correcting the
    recalibrated Wood base, early-stopped on every 10th week of the fold's training rows.
    ``fixed`` settings (e.g. max_epochs, stop_drop_pp) apply to every trial.
    """
    assert_torch_safe_process()
    device = resolve_device(device)
    rng = np.random.default_rng(seed)
    rows = []
    for trial in range(n_trials):
        start = {**DEFAULT_PARAMS, **(fixed or {})}
        params = dict(start) if trial == 0 else {
            **start,
            "dropout": float(rng.choice([0.2, 0.3, 0.4, 0.5])),
            "lr": float(np.exp(rng.uniform(np.log(3e-4), np.log(5e-3)))),
            "weight_decay": float(np.exp(rng.uniform(np.log(1e-6), np.log(1e-2)))),
            "batch_size": int(rng.choice([512, 1024, 2048, 4096])),
        }
        hidden = (ARCHITECTURES["torch_mlp_large"] if trial == 0
                  else [(64, 32), (128, 64), (256, 128, 64), (512, 256, 128)][int(rng.integers(4))])
        t0 = time.perf_counter()
        err = tot = 0.0
        best_epochs = []
        for fold in folds:
            if not fold["score"].any():
                continue
            train = fold["train"]
            scaler = _Scaler.fit(fold["x"].loc[train])
            xa = scaler.transform(fold["x"])
            base = fold["recal_base"]
            target = np.clip(np.log(fold["y"] / np.maximum(base, 1e-6)), -CLIP, CLIP)
            fi, si = _split_stop(train, fold["weeks"])
            net, info = train_net(xa, target, fi, si, tuple(hidden), params, device, seed,
                                  base=base, litres=fold["y"])
            best_epochs.append(info["best_epoch"])
            idx = fold["score"]
            pred = base[idx] * np.exp(np.clip(predict_net(net, xa[idx], device), -CLIP, CLIP))
            err += float(np.abs(pred - fold["y"][idx]).sum())
            tot += float(fold["y"][idx].sum())
        wape = 100 * err / tot if tot else np.nan
        rows.append({"trial": trial, "setting": "default" if trial == 0 else "random",
                     "hidden": str(tuple(hidden)), "cv_accuracy_pct": 100 - wape,
                     "mean_best_epoch": float(np.mean(best_epochs)) if best_epochs else np.nan,
                     "seconds": round(time.perf_counter() - t0, 1), **params})
        if verbose:
            print(f"[cow-torch] trial {trial:>2}: CV accuracy {100 - wape:.2f}% "
                  f"({rows[-1]['hidden']}, best epoch ~{rows[-1]['mean_best_epoch']:.0f}, "
                  f"{rows[-1]['seconds']:.1f}s)", flush=True)
    table = pd.DataFrame(rows).sort_values("cv_accuracy_pct", ascending=False).reset_index(drop=True)
    best = table.iloc[0]
    best_params = {k: (int(best[k]) if k in INT_PARAMS else float(best[k]))
                   for k in DEFAULT_PARAMS}
    best_hidden = tuple(int(v) for v in best["hidden"].strip("()").split(",") if v.strip())
    return {**best_params, "hidden_large": best_hidden}, table
