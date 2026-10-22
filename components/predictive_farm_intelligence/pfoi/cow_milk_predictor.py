"""The complete Notebook 6 milk predictor, persisted, reloaded and used for herd milk.

pfoi-1.8.0-dev replaces the milk forecast of pfoi-1.2.0-dev with Notebook 6's selected
cow-yield model. Unlike pfoi-1.7.0-dev (structural milk x a tapered neural/Wood ratio),
the milk number here *is* the neural predictor's output:

    herd milk(d) = projected milking cows(d) [pfoi-1.2.0-dev herd engine]
                   x mean predicted yield per cow(d) [Notebook 6 predictor, origin cohort]

which is the same construction as the clean herd target itself (``model_input2``:
milk per recorded cow x milking cows), so no recorded sample is ever summed and called
whole-herd milk. The dependency on the 1.2.0-dev milking-cow projection is disclosed in
every artifact.

**Which Notebook 6 model.** Notebook 6 selects one model per grain (``winners.csv``):
lowest pooled cow-period WAPE over the validation block and expanding pre-test windows
(persistence excluded), then a persistence blend only if it beats that model on the
cross-fitted validation block. Test scores never enter the choice. Only the **monthly**
protocol matches a forecast from one fixed origin: its features are frozen on the 1st
of the month and it predicts every recorded day of that month (leads 0-30 days). The
daily winner is a one-day-ahead *updated* prediction and the weekly winner re-reads the
records every Monday; both would need records after the origin, so neither is used for
the fixed-origin page forecast. Days after the first month are outside anything
Notebook 6 validated and are published as **unsupported**, never extrapolated.

**What is persisted** (``predictor.json`` + ``weights.pt``, no per-animal value):
selection and its source files (SHA-256), tuned and fixed training settings, feature
names, design columns and the scaler, Wood fixed effects + variance components +
smearing, Kalman parameters, every ensemble member's weights, blend weights, training
cutoff, data scope, aggregate training counts and code provenance. The Wood cow
intercepts are *not* stored: they are the exact BLUP ``n s2u / (n s2u + s2e) x mean
residual`` of each cow's own pre-origin training records and are recomputed at
inference from the stored variance components (verified against statsmodels in the
reload check). Cow numbers are per-load ranks, so storing them would be meaningless as
well as row-level.

**Future cow-days at the origin.** The cohort is every cow with a record in the
``cohort_days`` before the origin and at least ``MIN_ORIGIN_HISTORY`` records in her
current lactation. Her future days in the supported month get DIM and age advanced
from her last record, the same parity, no yield, no sensors and no THI (all event,
sensor and THI features are measured strictly before the origin, as in Notebook 6).
Days past DIM 400 (Notebook 6's scoring limit; in practice dried off) are dropped. Cows
that calve, enter or have under three records at the origin are not in the cohort:
their yield is represented only through the cohort mean, while the herd engine counts
them. Source availability of the origin's year is carried forward from the previous
complete year when the year to date is below the per-year record threshold (Notebook 6
judged whole years; a forecast cannot).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .cow_accuracy import (DATA_SCOPES, LEVEL_FEATURES, MIN_COWS_PER_DAY, MIN_ORIGIN_HISTORY,
                           SCOPE_TEST_NAMES, TRAIN_START, _add_level_features, _design,
                           _lactation_ids, apply_blend, exclude_recording_gap,
                           prepare_accuracy_frame, recalibrate, recalibrate_by_group)

PREDICTOR_SCHEMA = "pfoi.neural-milk-predictor.v1"
FORECAST_SCHEMA = "pfoi.neural-milk-forecast.v1"
NEURAL_MILK_VERSION = "pfoi-1.8.0-dev"
SOURCE_NOTEBOOK = "notebooks/06_cow_yield_torch.ipynb (pfoi-cow-yield-torch-1.6.0-dev, torch v3)"
FIXED_ORIGIN_GRAIN = "monthly"
MAX_DIM = 400
COHORT_DAYS = 28
MIN_SOURCE_RECORDS = 100  # Notebook 6 MIN_SOURCE_RECORDS_PER_YEAR
# Notebook 6 settings (cell 1): every final fit uses these model options and training
# limits; tuning supplies the remaining network settings.
NOTEBOOK6_OPTIONS = {"ensemble": 3, "use_kalman": True, "use_gru": True, "gru_seeds": 1,
                     "seq_len": 16, "use_quantile": True, "robust_training": True}
NOTEBOOK6_TRAINING = {"max_epochs": 250, "min_epochs": 50, "stop_drop_pp": 0.5,
                      "stop_patience": 15}
NOTEBOOK6_DROPOUT = 0.3
FAMILIES = ("persistence_last_yield", "wood_mixed", "kalman_state", "torch_mlp_small",
            "torch_mlp_large", "torch_gru", "torch_q50")
STAGES = ("wood_curve", "herd_recalibrated_curve", "model_raw", "model_recalibrated",
          "final")


# --------------------------------------------------------------------------- selection

def split_model_name(model: str) -> tuple[str, str]:
    """('torch_mlp_large', '_grp') for 'torch_mlp_large_grp'."""
    for suffix in ("_recal", "_grp"):
        if model.endswith(suffix):
            return model[: -len(suffix)], suffix
    return model, ""


@dataclass(frozen=True)
class Selection:
    """Notebook 6's validation-selected model for one grain, and how it was trained."""
    grain: str
    model: str                       # e.g. torch_mlp_large_grp, or blend
    base_model: str                  # model the blend mixes with persistence (= model otherwise)
    family: str
    variant: str                     # "", "_recal" or "_grp"
    params: dict
    options: dict
    data_scope: str
    blend_weights: dict | None = None
    selection_metric: str = ("pooled cow-period WAPE (validation + expanding pre-test "
                             "windows; persistence excluded), blend only if it beats the "
                             "base on cross-fitted validation WAPE")
    sources: dict = field(default_factory=dict)  # file name -> sha256
    selection_scores: dict = field(default_factory=dict)  # aggregate validation scores

    def fit_options(self) -> dict:
        """Notebook 6 options, fitting only the network family the selection needs."""
        return {**self.options, "use_gru": self.family == "torch_gru",
                "use_quantile": self.family == "torch_q50"}

    def architectures(self) -> tuple[str, ...]:
        return (self.family,) if self.family in ("torch_mlp_small", "torch_mlp_large") else ()


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selection_from_notebook6(run_dir, grain: str = FIXED_ORIGIN_GRAIN,
                             blend_weights_file=None, data_scope: str = "clean") -> Selection:
    """Read Notebook 6's own selection outputs (aggregate CSVs) from its ``OUT_DIR``.

    ``winners.csv`` gives the chosen model per grain; ``tuning_torch_trials.csv`` (sorted
    best first by the notebook) the tuned settings, then Notebook 6's fixed training
    limits override them exactly as in its cell 2. A blend winner needs its weight table
    (``blend_weights_table(BLEND_SPEC)``, aggregate), because the notebook does not save it.
    """
    run_dir = Path(run_dir)
    if data_scope not in DATA_SCOPES:
        raise ValueError(f"unknown data scope {data_scope!r}")
    if SCOPE_TEST_NAMES[data_scope] not in run_dir.parts:
        raise ValueError(f"{run_dir} is not a Notebook 6 run for data scope {data_scope!r} "
                         f"(expected {SCOPE_TEST_NAMES[data_scope]} in the path)")
    if "synthetic_only" in run_dir.parts:
        raise ValueError("this is the synthetic Notebook 6 run; select from the Farm X run")
    winners_file = run_dir / "winners.csv"
    if not winners_file.is_file():
        raise FileNotFoundError(f"{winners_file} not found: run Notebook 6 sections 1-3 first")
    winners = pd.read_csv(winners_file)
    row = winners[winners["grain"] == grain]
    if len(row) != 1:
        raise ValueError(f"winners.csv has {len(row)} rows for grain {grain!r}")
    row = row.iloc[0]
    model = str(row["model"])
    base = str(row.get("pooled_base", model)) if model == "blend" else model
    family, variant = split_model_name(base)
    if family not in FAMILIES:
        raise ValueError(f"unsupported Notebook 6 model {base!r}")
    sources = {"winners.csv": _sha256(winners_file)}
    params = {**NOTEBOOK6_TRAINING, "dropout": NOTEBOOK6_DROPOUT}
    trials_file = run_dir / "tuning_torch_trials.csv"
    if trials_file.is_file():
        from .cow_torch import DEFAULT_PARAMS, INT_PARAMS

        best = pd.read_csv(trials_file).sort_values("cv_accuracy_pct", ascending=False).iloc[0]
        params = {k: (int(best[k]) if k in INT_PARAMS else float(best[k]))
                  for k in DEFAULT_PARAMS if k in best}
        params["hidden_large"] = [int(v) for v in str(best["hidden"]).strip("()").split(",")
                                  if v.strip()]
        params.update(NOTEBOOK6_TRAINING)  # cell 2: TRAINING overrides all but dropout
        sources["tuning_torch_trials.csv"] = _sha256(trials_file)
    weights = None
    if model == "blend":
        if blend_weights_file is None:
            raise ValueError("Notebook 6 chose a persistence blend for this grain; pass its "
                             "weight table (aggregate CSV of blend_weights_table(BLEND_SPEC))")
        table = pd.read_csv(blend_weights_file)
        table = table[table["grain"] == grain]
        if table.empty or set(table["base_model"]) != {base}:
            raise ValueError("blend weight table does not match the selected grain and base")
        weights = {str(b): float(w) for b, w in zip(table["days_since_record"],
                                                    table["weight_on_model"])}
        sources[Path(blend_weights_file).name] = _sha256(Path(blend_weights_file))
    scores = {k: (float(row[k]) if pd.notna(row.get(k)) else None)
              for k in ("accuracy_pct", "within_10pct", "bias_pct", "skill_vs_persistence_pct",
                        "wape_pct") if k in row}
    return Selection(grain=grain, model=model, base_model=base, family=family, variant=variant,
                     params=params, options=dict(NOTEBOOK6_OPTIONS), data_scope=data_scope,
                     blend_weights=weights, sources=sources,
                     selection_scores={"block": "validation (cow-period)", **scores})


def selection_to_json(sel: Selection) -> dict:
    return asdict(sel)


def selection_from_json(d: dict) -> Selection:
    return Selection(**d)


# ------------------------------------------------------------------ origin cohort

def origin_safe_events(events: dict | None, origin: date,
                       min_records: int = MIN_SOURCE_RECORDS) -> dict | None:
    """Events strictly before the origin, and source availability known at the origin.

    ``availability`` (``source_availability_sql``) counts whole calendar years from the
    full table, so the origin's own year would reveal records not yet made. At the
    origin, years after it are dropped and the origin's year takes the count of the
    previous complete year (0 if none): a source is "available" this year only if it
    was recorded last year (documented assumption, same at every origin).
    """
    if events is None:
        return None
    out = {}
    cut = pd.Timestamp(origin)
    for key in ("health", "treatments"):
        e = events.get(key)
        if e is not None and len(e):
            e = e[pd.to_datetime(e["event_date"]) < cut].copy()
        out[key] = e
    a = events.get("availability")
    if a is not None and len(a):
        year = (origin - timedelta(days=1)).year
        a = a[a["year"] < year].copy()
        prev = a[a["year"] == year - 1][["source", "records"]]
        a = pd.concat([a, prev.assign(year=year)], ignore_index=True)
    out["availability"] = a
    return out


def origin_history(raw: pd.DataFrame, origin: date, data_scope: str = "clean") -> pd.DataFrame:
    """Records strictly before the origin, with Notebook 6's recording-gap exclusion."""
    h = raw[pd.to_datetime(raw["date"]) < pd.Timestamp(origin)]
    return exclude_recording_gap(h, DATA_SCOPES[data_scope])


def origin_cohort(history: pd.DataFrame, origin: date, end: date,
                  cohort_days: int = COHORT_DAYS) -> tuple[pd.DataFrame, dict]:
    """Future cow-days [origin, end) for the cohort known at the origin (see module doc).

    Returns rows shaped like the restricted input (no yield) and aggregate counts.
    """
    h = history.copy()
    h["date"] = pd.to_datetime(h["date"]).astype("datetime64[ns]")
    h = h[(h["litres"] > 0) & (h["litres"] <= 18.0)]
    h = h.rename(columns={"cow_id": "animal"}).sort_values(["animal", "date"])
    h["parity_group"] = h["parity_group"].astype(str)
    h = h.reset_index(drop=True)
    h["lactation"] = _lactation_ids(h)
    n_lact = h.groupby(["animal", "lactation"]).size().rename("n_lact")
    last = h.groupby("animal", sort=False).tail(1).join(n_lact, on=["animal", "lactation"])
    recent = last["date"] >= pd.Timestamp(origin - timedelta(days=cohort_days))
    known = last["n_lact"] >= MIN_ORIGIN_HISTORY
    ok = recent & known & last["dim"].notna()
    cohort = last[ok]
    days = pd.date_range(origin, end - timedelta(days=1), freq="D")
    counts = {"cows_recorded_in_window": int(recent.sum()),
              "cows_excluded_short_history": int((recent & ~known).sum()),
              "cohort_cows": int(len(cohort)), "cohort_days": int(cohort_days)}
    if cohort.empty or not len(days):
        return pd.DataFrame(columns=["cow_id", "date", "litres", "dim", "parity_group",
                                     "age_days", "is_future"]), counts | {"future_cow_days": 0,
                                                                          "dropped_past_dim": 0}
    grid = cohort[["animal", "date", "dim", "parity_group", "age_days"]].merge(
        pd.DataFrame({"target": days}), how="cross")
    lead = (grid["target"] - grid["date"]).dt.days.astype(float)
    future = pd.DataFrame({
        "cow_id": grid["animal"].to_numpy(), "date": grid["target"].to_numpy(),
        "litres": np.nan, "dim": grid["dim"].to_numpy(float) + lead.to_numpy(),
        "parity_group": grid["parity_group"].to_numpy(),
        "age_days": pd.to_numeric(grid["age_days"], errors="coerce").to_numpy(float)
        + lead.to_numpy(),
        "is_future": True,
    })
    past_dim = future["dim"] > MAX_DIM
    counts |= {"future_cow_days": int((~past_dim).sum()), "dropped_past_dim": int(past_dim.sum())}
    return future[~past_dim].reset_index(drop=True), counts


def inference_input(history: pd.DataFrame, future: pd.DataFrame,
                    origin: date | None = None) -> pd.DataFrame:
    """History plus future rows in the restricted input shape (columns aligned).

    With ``origin``, every future row is forecast from that one origin (features frozen
    there) whatever its lead; without it, the monthly protocol's own origin (the 1st of
    the row's month) applies, which equals the origin inside the origin month.
    """
    h = history.copy()
    h["is_future"] = False
    f = future.reindex(columns=h.columns)
    f["is_future"] = True
    f["litres"] = np.nan
    out = pd.concat([h, f], ignore_index=True)
    if origin is not None:
        out["origin_override"] = pd.NaT
        out.loc[out["is_future"].astype(bool), "origin_override"] = pd.Timestamp(origin)
    return out


def supported_end(origin: date, months: int = 1) -> date:
    """First day after the published support: ``months`` calendar months from the origin
    (default 1 = the origin month, the only lead Notebook 6 validated)."""
    if origin.day != 1:
        raise ValueError("forecast origins are the first day of a month")
    y, m = divmod(origin.month - 1 + months, 12)
    return date(origin.year + y, m + 1, 1)


# ------------------------------------------------------------------ the predictor

def _git_provenance() -> dict:
    here = Path(__file__).resolve().parent
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, capture_output=True,
                                text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=here,
                                    capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        commit, dirty = "unknown", True
    return {"git_commit": commit or "unknown", "component_worktree_dirty": dirty}


@dataclass
class Predictor:
    """A fitted Notebook 6 predictor; all state needed for inference without refitting."""
    spec: dict                         # everything JSON-safe (see module doc)
    state_dicts: list = field(default_factory=list)

    @property
    def selection(self) -> Selection:
        return selection_from_json(self.spec["selection"])

    # -- persistence ------------------------------------------------------------
    def save(self, folder) -> Path:
        import torch

        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        weights = folder / "weights.pt"
        torch.save({"state_dicts": self.state_dicts}, weights)
        spec = {**self.spec, "weights_sha256": _sha256(weights)}
        (folder / "predictor.json").write_text(json.dumps(spec, indent=1))
        self.spec = spec
        return folder

    @classmethod
    def load(cls, folder) -> "Predictor":
        import torch

        folder = Path(folder)
        spec = json.loads((folder / "predictor.json").read_text())
        if spec.get("schema") != PREDICTOR_SCHEMA:
            raise ValueError("not a pfoi neural milk predictor")
        weights = folder / "weights.pt"
        if _sha256(weights) != spec.get("weights_sha256"):
            raise ValueError("weights.pt does not match predictor.json (sha256)")
        blob = torch.load(weights, map_location="cpu", weights_only=True)
        return cls(spec, blob["state_dicts"])

    # -- inference --------------------------------------------------------------
    def frame(self, raw_all: pd.DataFrame, events: dict | None) -> pd.DataFrame:
        s = self.spec
        train_end = date.fromisoformat(s["train_end"])
        return prepare_accuracy_frame(raw_all, train_end=train_end, validation_end=train_end,
                                      evaluation_mode="walk_forward", events=events,
                                      min_source_records=s["min_source_records"],
                                      origin_grain=s["selection"]["grain"])

    def _wood(self, fx: pd.DataFrame):
        """Wood model with cow intercepts recomputed as the BLUP from training rows."""
        from .cow_layer import CowSplit, WoodMixed, _train_rows, prepare_cowdays

        w = self.spec["wood"]
        train_end = date.fromisoformat(self.spec["train_end"])
        split = CowSplit(start=TRAIN_START, train_end=train_end, validate_end=train_end,
                         gap_end=train_end, recal_end=train_end)
        cow = prepare_cowdays(fx, split)
        model = WoodMixed(name="wood", cow_effect=pd.Series(dtype=float),
                          smear_known=w["smear_known"], smear_marginal=w["smear_marginal"],
                          sigma2_cow=w["sigma2_cow"], sigma2_resid=w["sigma2_resid"],
                          params=pd.Series(w["params"], dtype=float),
                          levels=tuple(w["levels"]), reference=w["reference"])
        t = _train_rows(cow)
        resid = np.log(t["litres"].to_numpy()) - model.linear(t)
        g = pd.DataFrame({"r": resid, "a": t["animal"].to_numpy()}).groupby("a")["r"]
        n, mean = g.size(), g.mean()
        s2u, s2e = w["sigma2_cow"], w["sigma2_resid"]
        model.cow_effect = (n * s2u / (n * s2u + s2e) * mean).rename("u")
        return model, cow

    def _networks(self) -> list:
        from .cow_torch import _modules

        net_spec = self.spec.get("network")
        if not net_spec:
            return []
        MLP, GRUNet = _modules()
        nets = []
        for sd in self.state_dicts:
            if net_spec["kind"] == "gru":
                net = GRUNet(net_spec["n_in"], net_spec["n_step"], net_spec["gru_hidden"],
                             net_spec["dropout"])
            else:
                net = MLP(net_spec["n_in"], tuple(net_spec["hidden"]), net_spec["dropout"],
                          n_out=len(net_spec.get("quantiles") or [0]))
            net.load_state_dict(sd)
            net.eval()
            nets.append(net)
        return nets

    def predict(self, raw_all: pd.DataFrame, events: dict | None
                ) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
        """Frame and per-stage predictions for every row (in memory only, never saved)."""
        from .cow_kalman import kalman_at_origin
        from .cow_torch import CLIP, _Scaler, _sequences, predict_net

        s, sel = self.spec, self.selection
        fx = self.frame(raw_all, events)
        wood, cow = self._wood(fx)
        wood_pred = wood.predict(cow)
        fx = _add_level_features(fx, wood_pred)
        x = _design(fx, tuple(s["features"]))
        base = recalibrate(fx, wood_pred)
        kf_mean = None
        if s.get("kalman"):
            kf_mean, kf_sd = kalman_at_origin(fx, base, s["kalman"])
            x["kf_level"], x["kf_sd"] = kf_mean, kf_sd
        stages = {"wood_curve": wood_pred, "herd_recalibrated_curve": base}
        persistence = fx["yield_lag1"].fillna(pd.Series(wood_pred, index=fx.index)).to_numpy(float)
        fam = sel.family
        if fam == "persistence_last_yield":
            raw_model = persistence
        elif fam == "wood_mixed":
            raw_model = wood_pred
        elif fam == "kalman_state":
            raw_model = base * np.exp(np.clip(kf_mean, -CLIP, CLIP))
        else:
            sc = s["scaler"]
            scaler = _Scaler(sc["columns"], np.array(sc["medians"]), np.array(sc["means"]),
                             np.array(sc["stds"]), np.array(sc["indicator"], dtype=bool))
            missing = set(scaler.columns) - set(x.columns)
            if missing:
                raise ValueError(f"inference design lacks trained inputs: {sorted(missing)}")
            xa = scaler.transform(x)
            inputs = [xa]
            if fam == "torch_gru":
                inputs.append(_sequences(fx, base, s["network"]["seq_len"]))
            outs = [predict_net(net, inputs, "cpu") for net in self._networks()]
            if fam == "torch_q50":
                q = np.sort(outs[0], axis=1)
                raw_model = base * np.exp(np.clip(q[:, 1], -CLIP, CLIP))
            else:
                raw_model = base * np.exp(np.clip(np.mean(outs, axis=0), -CLIP, CLIP))
        stages["model_raw"] = raw_model
        if sel.variant == "_recal":
            single = recalibrate(fx, raw_model)
        elif sel.variant == "_grp":
            single = recalibrate_by_group(fx, raw_model)
        else:
            single = raw_model
        stages["model_recalibrated"] = single
        final = (apply_blend(fx, single, persistence, sel.blend_weights)
                 if sel.model == "blend" else single)
        stages["final"] = np.asarray(final, dtype=float)
        stages["persistence"] = persistence
        return fx, stages


def fit_predictor(raw_all: pd.DataFrame, events: dict | None, origin: date,
                  selection: Selection, *, device: str = "auto", seed: int = 17,
                  verbose: bool = False, fit_fn=None, notebook_run: str | None = None,
                  ) -> tuple[Predictor, pd.DataFrame, np.ndarray]:
    """Refit the selected Notebook 6 model on records strictly before ``origin``.

    ``raw_all`` = :func:`origin_history` + future rows (:func:`inference_input`). Returns
    the predictor, the fitted frame and the fit-time final predictions (for the reload
    check only).
    """
    if fit_fn is None:
        from .cow_torch import fit_torch_models as fit_fn
    hist = raw_all[~raw_all["is_future"].astype(bool)]
    if (pd.to_datetime(hist["date"]) >= pd.Timestamp(origin)).any():
        raise ValueError("training input contains records on or after the forecast origin")
    train_end = origin - timedelta(days=1)
    models = fit_fn(raw_all, train_end=train_end, validation_end=train_end, events=events,
                    min_source_records=MIN_SOURCE_RECORDS, params=dict(selection.params),
                    device=device, seed=seed, options=selection.fit_options(), verbose=verbose,
                    grains=(selection.grain,), model_names=selection.architectures(),
                    keep_state=True)
    frame, preds = models.for_grain(selection.grain)
    fitted = models.grain_fitted.get(selection.grain, models.fitted)
    wood = models.fitted["wood_mixed"]
    single = np.asarray(preds[selection.base_model], dtype=float)
    final = (apply_blend(frame, single, preds["persistence_last_yield"], selection.blend_weights)
             if selection.model == "blend" else single)
    state = (fitted.get(selection.family) or {}).get("state")
    network, state_dicts, scaler = None, [], None
    if state is not None:
        sc = state["scaler"]
        scaler = {"columns": list(sc.columns), "medians": sc.medians.tolist(),
                  "means": sc.means.tolist(), "stds": sc.stds.tolist(),
                  "indicator": sc.indicator.astype(bool).tolist()}
        network = {k: (list(v) if isinstance(v, tuple) else v) for k, v in state.items()
                   if k not in ("scaler", "state_dicts")}
        state_dicts = state["state_dicts"]
    train = frame[(frame["period"] == "train") & ~frame["is_future"].astype(bool)]
    members = (fitted.get(selection.family) or {}).get("members") or []
    spec = {
        "schema": PREDICTOR_SCHEMA,
        "model_version": NEURAL_MILK_VERSION,
        "source_notebook": SOURCE_NOTEBOOK,
        "notebook_run": notebook_run,
        "origin_date": origin.isoformat(),
        "train_end": train_end.isoformat(),
        "outcomes_used_through": train_end.isoformat(),
        "data_scope": selection.data_scope,
        "recording_gap_excluded": [d.isoformat() for d in DATA_SCOPES[selection.data_scope]],
        "min_source_records": MIN_SOURCE_RECORDS,
        "selection": selection_to_json(selection),
        "features": list(models.features),
        "event_features": list(frame.attrs.get("event_features", ())),
        "dropped_sensors": list(frame.attrs.get("dropped_sensors", [])),
        "scaler": scaler,
        "network": network,
        "wood": {"params": {k: float(v) for k, v in wood.params.items()},
                 "levels": list(wood.levels), "reference": wood.reference,
                 "smear_known": float(wood.smear_known),
                 "smear_marginal": float(wood.smear_marginal),
                 "sigma2_cow": float(wood.sigma2_cow), "sigma2_resid": float(wood.sigma2_resid),
                 "cow_intercepts": "not stored; BLUP recomputed from pre-origin training rows"},
        "kalman": fitted.get("kalman_state") or models.fitted.get("kalman_state"),
        "training": {"cow_days": int(len(train)), "cows": int(train["animal"].nunique()),
                     "first_day": str(pd.to_datetime(train["date"]).min().date()) if len(train) else None,
                     "last_day": str(pd.to_datetime(train["date"]).max().date()) if len(train) else None,
                     "members": [{"epochs": m.get("epochs"), "best_epoch": m.get("best_epoch"),
                                  "training_monitor_accuracy_pct": m.get("best_monitor")}
                                 for m in (members if isinstance(members, list) else [])],
                     "monitor_note": ("training monitor = accuracy on every 10th week of the "
                                      "training block, used for early stopping; it is not "
                                      "held-out forecast accuracy")},
        "seed": seed,
        "fit_device": str(device),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **_git_provenance(),
    }
    return Predictor(spec, state_dicts), frame, final


def verify_reload(predictor_dir, raw_all: pd.DataFrame, events: dict | None,
                  fit_frame: pd.DataFrame, fit_final: np.ndarray,
                  tolerance_litres: float = 0.02) -> tuple[Predictor, pd.DataFrame,
                                                          dict[str, np.ndarray], dict]:
    """Reload the saved predictor, rerun inference and compare with the fit (aggregates)."""
    loaded = Predictor.load(predictor_dir)
    fx, stages = loaded.predict(raw_all, events)
    if len(fx) != len(fit_frame) or not (
            (fx["animal"].to_numpy() == fit_frame["animal"].to_numpy()).all()
            and (fx["date"].to_numpy() == fit_frame["date"].to_numpy()).all()):
        raise ValueError("reloaded frame rows differ from the fitted frame")
    fut = fx["is_future"].to_numpy(bool)
    diff = np.abs(stages["final"] - np.asarray(fit_final, float))
    audit = {"rows_compared": int(len(diff)), "future_rows_compared": int(fut.sum()),
             "max_abs_diff_litres": float(np.nanmax(diff)) if len(diff) else 0.0,
             "mean_abs_diff_litres": float(np.nanmean(diff)) if len(diff) else 0.0,
             "tolerance_litres": tolerance_litres}
    audit["passed"] = bool(audit["max_abs_diff_litres"] <= tolerance_litres)
    if not audit["passed"]:
        raise ValueError(f"reloaded predictor differs from the fitted one: {audit}")
    return loaded, fx, stages, audit


# ------------------------------------------------------------------ herd adapter

def milking_path(structural_outlook: pd.DataFrame, origin: date, end: date
                 ) -> tuple[pd.DataFrame, dict]:
    """Daily milking-cow path [origin, end) consistent with pfoi-1.2.0-dev's published counts.

    1.2.0-dev publishes milking cows daily for days 1-14 and as a monthly mean. Days
    1-14 are taken as published; the remaining days of the month get the constant that
    makes the month's mean equal the published monthly mean exactly. Weekly means are
    compared in the audit (aggregates).
    """
    o = structural_outlook.copy()
    grain = o["grain"].astype(str).str.lower().map({"day": "daily", "week": "weekly",
                                                   "month": "monthly"}).fillna(
        o["grain"].astype(str).str.lower())
    o = o.assign(grain=grain, start=pd.to_datetime(o["target_period"]).dt.date)
    o = o[o["series"] == "milking"]
    n_days = (end - origin).days
    days = [origin + timedelta(days=i) for i in range(n_days)]
    daily = o[o["grain"] == "daily"].set_index("start")["forecast"].astype(float)
    month = o[(o["grain"] == "monthly") & (o["start"] == origin)]["forecast"]
    audit = {"source": "pfoi-1.2.0-dev milking forecast", "daily_published_days": 0}
    if all(d in daily.index for d in days):
        values = np.array([daily[d] for d in days])
        audit["daily_published_days"] = n_days
    else:
        if len(month) != 1 or (end - origin).days != (supported_end(origin) - origin).days:
            raise ValueError("structural outlook lacks the milking forecast needed for the "
                             "first month")
        known = [d for d in days if d in daily.index]
        if known != days[:len(known)]:
            raise ValueError("published daily milking forecasts are not continuous")
        rest = n_days - len(known)
        total = float(month.iloc[0]) * n_days
        fill = (total - sum(daily[d] for d in known)) / rest if rest else 0.0
        if fill < 0:
            raise ValueError("published milking forecasts are inconsistent (negative fill)")
        values = np.array([daily[d] for d in known] + [fill] * rest)
        audit.update(daily_published_days=len(known), filled_days=rest,
                     fill_value=round(fill, 3))
    path = pd.DataFrame({"date": days, "milking": values})
    weekly = o[o["grain"] == "weekly"]
    diffs = []
    for r in weekly.itertuples(index=False):
        part = path[(path["date"] >= r.start) & (path["date"] < r.start + timedelta(days=7))]
        if len(part) == 7:
            diffs.append(abs(float(part["milking"].mean()) - float(r.forecast)))
    audit["weekly_mean_max_abs_diff_cows"] = round(max(diffs), 3) if diffs else None
    if len(month) == 1 and n_days == (supported_end(origin) - origin).days:
        audit["monthly_mean_abs_diff_cows"] = round(abs(values.mean() - float(month.iloc[0])), 6)
    return path, audit


def herd_daily(frame: pd.DataFrame, stages: dict[str, np.ndarray], milking: pd.DataFrame,
               min_cows: int = MIN_COWS_PER_DAY) -> pd.DataFrame:
    """Aggregate the future cohort predictions to herd milk per day (no animal column).

    ``herd_litres = milking x mean predicted yield per cohort cow``; days with fewer than
    ``min_cows`` cohort cows get no forecast. Stage columns give the herd litres at each
    step of the predictor (wood curve -> herd recalibration -> learned model ->
    recalibration -> blend), so their differences are exact additive contributions.
    """
    fut = (frame["is_future"].astype(bool) & frame["score_eligible"].astype(bool)).to_numpy()
    d = pd.DataFrame({"date": pd.to_datetime(frame["date"]).dt.date.to_numpy()[fut]})
    for name in STAGES:
        d[name] = np.asarray(stages[name], float)[fut]
    g = d.groupby("date")
    per_cow = g[list(STAGES)].mean()
    per_cow["cohort_cows"] = g.size()
    out = milking.set_index("date").join(per_cow, how="left")
    out["cohort_cows"] = out["cohort_cows"].fillna(0).astype(int)
    ok = out["cohort_cows"] >= min_cows
    out["yield_per_cow"] = out["final"].where(ok)
    out["herd_litres"] = (out["milking"] * out["final"]).where(ok)
    for name in STAGES:
        out[f"{name}_litres"] = (out["milking"] * out[name]).where(ok)
    out = out.drop(columns=list(STAGES)).reset_index()
    return out


def build_forecast_artifact(origin: date, predictor: Predictor, daily: pd.DataFrame,
                            cohort_counts: dict, milking_audit: dict, reload_audit: dict,
                            status: str = "ok", reason: str | None = None, months: int = 1,
                            calibration: list | None = None,
                            calibration_source: str | None = None) -> dict:
    """The aggregate milk forecast file the composer reads (no per-animal values)."""
    rows = []
    for r in daily.itertuples(index=False):
        row = {"date": r.date.isoformat(), "milking": round(float(r.milking), 4),
               "cohort_cows": int(r.cohort_cows)}
        for k in ("yield_per_cow", "herd_litres", *[f"{s}_litres" for s in STAGES]):
            v = getattr(r, k, None)
            row[k] = None if v is None or not np.isfinite(v) else round(float(v), 4)
        rows.append(row)
    sel = predictor.spec["selection"] if predictor is not None else {}
    return {
        "schema": FORECAST_SCHEMA,
        "model_version": NEURAL_MILK_VERSION,
        "origin_date": origin.isoformat(),
        "status": status, "reason": reason,
        "supported_from": origin.isoformat(),
        "supported_to": (supported_end(origin, months) - timedelta(days=1)).isoformat(),
        "supported_months": months,
        "protocol": ("fixed origin: Notebook 6 monthly-grain protocol, features frozen at "
                     "the origin; Notebook 6 validated leads 0-30 days" + (
                         f"; months 2-{months} published on rolling-origin backtest evidence"
                         if months > 1 else "; later periods unsupported")),
        "formula": "herd_litres(d) = milking(d) [pfoi-1.2.0-dev] x mean predicted yield "
                   "per cohort cow(d) [Notebook 6 predictor]",
        "selection": sel,
        "predictor": None if predictor is None else {
            k: predictor.spec.get(k) for k in ("train_end", "outcomes_used_through",
                                               "data_scope", "recording_gap_excluded",
                                               "training", "git_commit",
                                               "component_worktree_dirty", "weights_sha256",
                                               "notebook_run", "created_at")},
        "cohort": cohort_counts,
        "milking_path": milking_audit,
        "reload_check": reload_audit,
        "daily": rows,
        "calibration": [c if isinstance(c, dict) else asdict(c) for c in (calibration or [])],
        "calibration_source": calibration_source,
        "interval_status": "calibrated_monthly_from_own_backtest" if calibration else "uncalibrated",
    }


def validate_forecast_artifact(a: dict, origin: date | None = None) -> None:
    if a.get("schema") != FORECAST_SCHEMA:
        raise ValueError("unsupported neural milk forecast artifact")
    o = date.fromisoformat(a["origin_date"])
    if origin is not None and o != origin:
        raise ValueError(f"artifact origin {o} does not match {origin}")
    p = a.get("predictor") or {}
    if p.get("outcomes_used_through") and date.fromisoformat(p["outcomes_used_through"]) >= o:
        raise ValueError("predictor used outcomes on or after the origin")
    allowed = {"date", "milking", "cohort_cows", "yield_per_cow", "herd_litres",
               *[f"{s}_litres" for s in STAGES]}
    for r in a.get("daily", []):
        if set(r) - allowed:
            raise ValueError(f"artifact daily row has unsupported keys {sorted(set(r) - allowed)}")
        if r["cohort_cows"] and 0 < r["cohort_cows"] < MIN_COWS_PER_DAY and r["herd_litres"] is not None:
            raise ValueError("a forecast day rests on fewer cows than the disclosure minimum")
