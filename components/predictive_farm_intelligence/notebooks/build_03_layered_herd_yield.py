"""Writes notebooks/03_layered_herd_yield.ipynb (outputs empty).

Layer 1 forecasts milking cows (herd), layer 2 forecasts clean litres per recorded cow
(yield); herd milk = layer 1 x layer 2. Loading, cleaning and the origin features are the
same cells as notebook 02 (taken from build_02_ml_milk_forecast.py), so both notebooks read
the data the same way. Run:
  .venv/bin/python components/predictive_farm_intelligence/notebooks/build_03_layered_herd_yield.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_02", HERE / "build_02_ml_milk_forecast.py")
_b2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_b2)


def _b2_cell(starts: str) -> str:
    hits = [s for t, s in _b2.CELLS if t == "code" and s.startswith(starts)]
    assert len(hits) == 1, starts
    return hits[0]


def _b2_md(starts: str) -> str:
    hits = [s for t, s in _b2.CELLS if t == "markdown" and s.startswith(starts)]
    assert len(hits) == 1, starts
    return hits[0]


CELLS: list[tuple[str, str]] = []


def md(s: str) -> None:
    CELLS.append(("markdown", s.strip("\n")))


def code(s: str) -> None:
    CELLS.append(("code", s.strip("\n")))


# --------------------------------------------------------------------------------------
md(r"""
# Farm X: layered milk forecast, herd × yield per cow (PFOI experiment)

The same structure as PFOI's engine (herd first, then milk per cow), with machine learning in
each layer:

| Layer | Forecasts (1–90 days ahead) | Learns from |
|---|---|---|
| **1. Herd** | milking cows | every day 2015–2026 (herd counts have no placeholder or shipped milk) |
| **2. Yield** | clean litres per recorded cow | clean milk days only, plus layer 1's forecast for the same day |
| **Combined** | herd milk = layer 1 × layer 2 | — |

Each layer picks LightGBM or Random Forest on a validation part of its own training data
(never the test). Every layer and the combination are scored on the same held-out 20 % against
persistence (carrying the last value forward). The change of every forecast splits exactly into
a herd part and a yield part (§6).

**No leakage between layers.** Layer 2 learns from layer 1 forecasts made without the days
they are scored on: for training rows in year *Y*, layer 1 is fitted only on herd rows that
ended before 1 January *Y*; for test rows, on the herd training rows.

**Experiment status:** `pfoi-nb-layers-0.1-dev`, notebook only; nothing is written to the
database. Privacy as notebook 02: herd totals per day only; placeholder and shipped milk are
never used for modelling (AGENTS.md, docs/model_input2.md §5). Exports go to
`logs/pfoi/notebook_ml/` (gitignored). **Clear all outputs before committing.**
""")

code(r"""
USE_SYNTHETIC = False        # True = fictional demo data, no database connection

# ---- fixed before any run (do not tune these on test results) ------------------------
INPUT_SCHEMA      = "model_input2"
TARGET            = "per_cow"     # layer 2 target (the loading cell of notebook 02 builds it)
CLEAN_MAX_LITRES  = 18.0          # a day above 18 L per recorded cow is removed
MIN_RECORDED_COWS = 20            # a yield day counts only if ≥ 20 cows have a clean record
MODEL_FROM        = None          # e.g. "2026-04-01": yield forecast dates only from here
HORIZON_DAYS      = 90            # 1, 2 and 3 months ahead
TEST_SHARE        = 0.20          # last 20 % of yield forecast dates = test (herd uses the same date)
HERD_ORIGIN_STEP  = 3             # herd forecast dates every 3 days (long history)
YIELD_ORIGIN_STEP = 1             # yield forecast dates every day (few clean days)
VALID_SHARE       = 0.25          # last 25 % of each layer's training dates pick its model
TOLERANCE         = 0.10
TARGET_HIT        = 0.85
MONTH_MIN_COVERAGE = 0.80         # a 30-day block is scored if ≥ 80 % of its days are recorded
CHART_DATES       = None          # forecast dates for the test charts; None = automatic
# period tests (§6b): name -> (training targets end before, test from, test to); trained only on earlier years
PERIODS           = {"2019-2021": ("2019-01-01", "2019-01-01", "2022-01-01"),
                     "2022-2026": ("2022-01-01", "2022-01-01", "2027-01-01")}
SEED              = 17
MODEL_VERSION     = "pfoi-nb-layers-0.1-dev"
LGBM_CHOICE       = "lightgbm_a"  # LightGBM setting (as notebook 02)

import sys, json, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

COMPONENT_DIR = Path.cwd().resolve()
if COMPONENT_DIR.name == "notebooks":
    COMPONENT_DIR = COMPONENT_DIR.parent
sys.path.insert(0, str(COMPONENT_DIR))
OUT_DIR = COMPONENT_DIR / "logs" / "pfoi" / "notebook_ml"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SOURCE = "demo" if USE_SYNTHETIC else "model"

pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
plt.rcParams.update({"figure.figsize": (13, 4.5), "axes.grid": True, "grid.alpha": 0.3,
                     "axes.spines.top": False, "axes.spines.right": False})
COL = {"actual": "#3b3b3b", "persistence": "#a0a0a0", "herd_only": "#2a6fdb",
       "yield_only": "#3aa66a", "layered": "#b8572a"}
if USE_SYNTHETIC:
    print("SYNTHETIC DEMO DATA: every number below is fictional (source = 'demo').")
""")

md(r"""
## 1. Import dataset and cleaning

Identical to notebook 02 §1 / §1b (same query, same cleaning, same rules).
""")
code(_b2_cell("PANEL_COLS = "))

md(r"""
## 2. Features known on the forecast date

The origin features of notebook 02 §3 (every feature uses days before the forecast date).
Layer 1 uses only the herd ones (stocks, pregnancy pipeline, events, lactation mix, weather,
health, season); layer 2 uses all of them, including the recent yield level, plus layer 1's
forecast of the change in milking cows for the target day.
""")
code(_b2_cell("def roll_mean(s, w):"))

code(r"""
LEADS = np.arange(1, HORIZON_DAYS + 1)
MILK_PREFIXES = ("lvl_", "mom_", "cv_28", "per_cow", "scoreable_share", "days_since_gap",
                 "days_since_record", "recorded_cows_share", "clean_cows", "removed_share")


def refresh_series():
    # series and anchors from the current panel / FEAT (called again if the calendar is extended)
    global herd, yld, herd_anchor, yld_anchor, C7
    herd = panel["milking"].astype(float).where(panel["milking"] > 0)
    yld = panel["y"]                                      # clean litres per recorded cow
    herd_anchor = herd.shift(1)                           # milking cows the day before
    yld_anchor = FEAT["level_7d"]                         # mean of the last 7 clean yield days
    C7 = {"herd": herd.rolling(7, center=True, min_periods=3).mean(), "yield": Y_C7}


refresh_series()
HERD_ORIGIN = [c for c in FEAT.columns if not c.startswith(MILK_PREFIXES) and c != "level_7d"]
YIELD_ORIGIN = [c for c in FEAT.columns if c != "level_7d"]
CAL = ["lead", "tgt_doy_sin", "tgt_doy_cos", "last_year_change"]
L1_FEATURES = HERD_ORIGIN + CAL
L2_FEATURES = YIELD_ORIGIN + CAL + ["tgt_weekday", "l1_change"]


def layer_rows(kind: str, origins: pd.DatetimeIndex, with_target: bool = True) -> pd.DataFrame:
    # origin x lead rows for one layer; target day = origin + lead - 1
    series, anchor, cols = ((herd, herd_anchor, HERD_ORIGIN) if kind == "herd"
                            else (yld, yld_anchor, YIELD_ORIGIN))
    idx = panel.index
    pos = idx.get_indexer(origins)
    o_pos = np.repeat(pos, len(LEADS))
    lead = np.tile(LEADS, len(pos))
    t_pos = o_pos + lead - 1
    t_dates = idx[o_pos] + pd.to_timedelta(lead - 1, unit="D")
    rows = pd.DataFrame(FEAT[cols].to_numpy(dtype=float)[o_pos], columns=cols)
    rows["origin"] = idx[o_pos]
    rows["target_date"] = t_dates
    rows["lead"] = lead
    rows["month_ahead"] = (lead - 1) // 30 + 1
    doy = t_dates.dayofyear.values
    rows["tgt_doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    rows["tgt_doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    rows["tgt_weekday"] = t_dates.weekday.values
    ly_t = C7[kind].reindex(t_dates - pd.Timedelta(days=365)).values
    ly_o = anchor.reindex(idx[o_pos] - pd.Timedelta(days=365)).values
    with np.errstate(divide="ignore", invalid="ignore"):
        rows["last_year_change"] = np.log(ly_t / ly_o)
    rows.loc[~np.isfinite(rows["last_year_change"]), "last_year_change"] = np.nan
    rows["anchor"] = anchor.values[o_pos]
    if with_target:
        inside = t_pos < len(idx)
        actual = np.full(len(rows), np.nan)
        actual[inside] = series.values[t_pos[inside]]
        rows["actual"] = actual
        with np.errstate(divide="ignore", invalid="ignore"):
            rows["y_ratio"] = np.log(rows["actual"] / rows["anchor"])
        h_t = np.full(len(rows), np.nan)
        h_t[inside] = herd.values[t_pos[inside]]
        rows["herd_at_target"] = h_t
    return rows


idx = panel.index
herd_start = herd.first_valid_index() + pd.Timedelta(days=365)
herd_origins = idx[(idx >= herd_start) & herd_anchor.notna().values][::HERD_ORIGIN_STEP]
H = layer_rows("herd", herd_origins)
H = H[np.isfinite(H["y_ratio"])].reset_index(drop=True)

y_start = yld.first_valid_index() + pd.Timedelta(days=60)
if MODEL_FROM is not None:
    y_start = max(y_start, pd.Timestamp(MODEL_FROM))
y_origins = idx[(idx >= y_start) & yld_anchor.notna().values & herd_anchor.notna().values][::YIELD_ORIGIN_STEP]
Y = layer_rows("yield", y_origins)
HX = layer_rows("herd", y_origins)          # layer 1 inputs for the same rows (same order)
keep = np.isfinite(Y["y_ratio"]) & np.isfinite(HX["y_ratio"])
Y, HX = Y[keep].reset_index(drop=True), HX[keep].reset_index(drop=True)

print(f"layer 1 (herd):  {H['origin'].nunique():,} forecast dates, {len(H):,} rows, {len(L1_FEATURES)} features")
print(f"layer 2 (yield): {Y['origin'].nunique():,} forecast dates, {len(Y):,} rows, {len(L2_FEATURES)} features")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 3. Train / test split (80:20, chronological, one date for both layers)

The split date is the first date of the last 20 % of **yield** forecast dates, and the herd
layer uses the same date, so both layers are tested on the same period. Training rows whose
target day is on or after the split date are removed (purge).
""")

code(r"""
y_dates = np.sort(Y["origin"].unique())
split_date = pd.Timestamp(y_dates[int(len(y_dates) * (1 - TEST_SHARE))])
H_tr = H[(H["origin"] < split_date) & (H["target_date"] < split_date)].reset_index(drop=True)
H_te = H[H["origin"] >= split_date].reset_index(drop=True)
y_tr_mask = (Y["origin"] < split_date) & (Y["target_date"] < split_date)
y_te_mask = Y["origin"] >= split_date
print(f"split date: {split_date:%Y-%m-%d}")
print(f"herd : train {len(H_tr):,} rows ({H_tr['origin'].min():%Y-%m-%d} .. {H_tr['target_date'].max():%Y-%m-%d}), "
      f"test {len(H_te):,} rows")
print(f"yield: train {int(y_tr_mask.sum()):,} rows, test {int(y_te_mask.sum()):,} rows "
      f"({Y.loc[y_te_mask, 'origin'].min():%Y-%m-%d} .. {Y.loc[y_te_mask, 'target_date'].max():%Y-%m-%d})")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 4. Models and training

Both layers predict the log ratio to their anchor (milking cows the day before; the 7-day
yield level), with recency weights (half-life 730 days), as in notebook 02. Each layer tries
LightGBM and Random Forest; the last `VALID_SHARE` of its training dates (purged) picks the one
with the higher share within ±10 %. The chosen model is then refitted on all its training rows.
""")
code(_b2_cell("def recency_weight("))

code(r"""
CANDIDATES = {"lightgbm": lambda: make_lgbm(LGBM_CHOICE), "random_forest": make_rf}


def fit_xy(factory, X: pd.DataFrame, y: pd.Series, dates: pd.Series):
    model = factory()
    w = recency_weight(dates, dates.max())
    if hasattr(model, "steps"):
        model.fit(X, y, **{f"{model.steps[-1][0]}__sample_weight": w})
    else:
        model.fit(X, y, sample_weight=w)
    return model


def hit(pred_ratio, true_ratio) -> float:
    return float(np.mean(np.abs(np.exp(np.asarray(pred_ratio) - np.asarray(true_ratio)) - 1) <= TOLERANCE))


def pick(df: pd.DataFrame, feats: list[str], name: str):
    o = np.sort(df["origin"].unique())
    cut = pd.Timestamp(o[int(len(o) * (1 - VALID_SHARE))])
    tr = df[(df["origin"] < cut) & (df["target_date"] < cut)]
    va = df[df["origin"] >= cut]
    scores, preds = {"persistence": hit(0.0, va["y_ratio"])}, {}
    for m, factory in CANDIDATES.items():
        preds[m] = fit_xy(factory, tr[feats], tr["y_ratio"], tr["target_date"]).predict(va[feats])
        scores[m] = hit(preds[m], va["y_ratio"])
    best = max(CANDIDATES, key=scores.get)
    print(f"{name}: validation from {cut:%Y-%m-%d} ({len(tr):,} train / {len(va):,} validation rows); "
          + ", ".join(f"{k} {v:.1%}" for k, v in scores.items()) + f" -> {best}")
    return best, va.assign(pred=preds[best])


t0 = time.time()
# layer 1: pick and fit on herd training rows
L1_BEST, l1_valid = pick(H_tr, L1_FEATURES, "layer 1 (herd)")
L1 = fit_xy(CANDIDATES[L1_BEST], H_tr[L1_FEATURES], H_tr["y_ratio"], H_tr["target_date"])

# layer 1 forecasts for the yield rows, out of sample (see top of the notebook)
Y["l1_change"] = np.nan
for yr_ in sorted(Y.loc[y_tr_mask, "origin"].dt.year.unique()):
    cut = min(pd.Timestamp(year=int(yr_), month=1, day=1), split_date)
    tr = H[(H["origin"] < cut) & (H["target_date"] < cut)]
    sel = y_tr_mask & (Y["origin"].dt.year == yr_)
    if len(tr) < 1000:
        print(f"  {yr_}: too little herd history before {cut:%Y-%m-%d}; layer 1 input left empty")
        continue
    m1 = fit_xy(CANDIDATES[L1_BEST], tr[L1_FEATURES], tr["y_ratio"], tr["target_date"])
    Y.loc[sel, "l1_change"] = m1.predict(HX.loc[sel, L1_FEATURES])
Y.loc[y_te_mask, "l1_change"] = L1.predict(HX.loc[y_te_mask, L1_FEATURES])

# layer 2: pick and fit on yield training rows
Y_tr = Y[y_tr_mask].reset_index(drop=True)
L2_BEST, l2_valid = pick(Y_tr, L2_FEATURES, "layer 2 (yield)")
L2 = fit_xy(CANDIDATES[L2_BEST], Y_tr[L2_FEATURES], Y_tr["y_ratio"], Y_tr["target_date"])
print(f"trained in {time.time() - t0:.0f} s")

# 80 % range of the combined forecast from validation errors (layer 1 out of sample + layer 2)
hx_tr = HX[y_tr_mask].reset_index(drop=True)
va_i = l2_valid.index
comb_resid = ((l2_valid["y_ratio"] - l2_valid["pred"])
              + (hx_tr.loc[va_i, "y_ratio"] - Y_tr.loc[va_i, "l1_change"]))
RANGE_Q = (pd.DataFrame({"m": l2_valid["month_ahead"], "r": comb_resid}).dropna()
           .groupby("m")["r"].quantile([0.10, 0.90]).unstack()
           .reindex(range(1, HORIZON_DAYS // 30 + 2)).ffill().bfill())
print("80 % range of the layered forecast (log ratio), by month ahead:"); display(RANGE_Q.round(3))


def range_q(valid: pd.DataFrame) -> pd.DataFrame:
    r = valid["y_ratio"] - valid["pred"]
    return (r.groupby(valid["month_ahead"]).quantile([0.10, 0.90]).unstack()
            .reindex(range(1, HORIZON_DAYS // 30 + 2)).ffill().bfill())


RANGE_L1, RANGE_L2 = range_q(l1_valid), range_q(l2_valid)     # each layer's own range (charts)
""")

# --------------------------------------------------------------------------------------
md(r"""
## 5. Testing and evaluation (held-out 20 %)

Share within ±10 % (target ≥ 85 %), accuracy = 1 − WAPE, bias and skill against persistence,
by month ahead and grain (daily; weekly = 7-day means, all 7 days recorded; monthly = 30-day
means with ≥ 80 % of days recorded). Four herd-milk forecasts are compared:

| Name | Herd (milking cows) | Yield (litres per cow) | What it shows |
|---|---|---|---|
| `persistence` | last day | last 7 days | benchmark |
| `herd_only` | layer 1 | last 7 days | what layer 1 adds |
| `yield_only` | last day | layer 2 | what layer 2 adds |
| `layered` | layer 1 | layer 2 | the full model |

Herd milk recorded = clean litres per recorded cow × milking cows on the target day (the
`model_input2` §5 estimate, no placeholder).
""")

code(r"""
def score_models(df: pd.DataFrame, models: list[str], base: str, by: str = "month_ahead") -> pd.DataFrame:
    out = []
    for key, g in df.groupby(by):
        a = g["actual"].values
        base_mae = np.mean(np.abs(g[base].values - a))
        for m in models:
            err = g[m].values - a
            out.append({by: key, "model": m, "n": len(g),
                        "within_10pct": np.mean(np.abs(err / a) <= TOLERANCE),
                        "accuracy_1_wape": 1 - np.abs(err).sum() / np.abs(a).sum(),
                        "bias_pct": err.sum() / a.sum(),
                        "skill_vs_persistence": 1 - np.mean(np.abs(err)) / base_mae if base_mae > 0 else np.nan})
    return pd.DataFrame(out, columns=[by, "model", "n", "within_10pct", "accuracy_1_wape", "bias_pct",
                                      "skill_vs_persistence"])


def blocks(df: pd.DataFrame, size: int, n_blocks: int, cols: list[str], min_cov: float = 1.0) -> pd.DataFrame:
    d = df[df["lead"] <= size * n_blocks].copy()
    d["block"] = (d["lead"] - 1) // size + 1
    g = d.groupby(["origin", "block"])
    out = g[cols + ["actual"]].mean()
    out["n_days"] = g.size()
    return out[out["n_days"] >= int(np.ceil(size * min_cov))].reset_index()


def grains(df: pd.DataFrame, models: list[str], base: str) -> dict[str, pd.DataFrame]:
    wk = blocks(df, 7, 12, models)
    wk["month_ahead"] = (wk["block"] - 1) // 4 + 1
    mo = blocks(df, 30, HORIZON_DAYS // 30, models, MONTH_MIN_COVERAGE).rename(columns={"block": "month_ahead"})
    return {"daily": score_models(df, models, base), "weekly": score_models(wk, models, base),
            "monthly": score_models(mo, models, base)}


def show(scores: dict[str, pd.DataFrame], models: list[str], title: str) -> None:
    for grain, s in scores.items():
        print(f"\n{title}, {grain}: share within ±{TOLERANCE:.0%} by month ahead, %")
        if s.empty:
            print("  (no scored period in the test window)")
        else:
            display((s.pivot(index="model", columns="month_ahead", values="within_10pct").loc[models] * 100).round(1))


# layer 1 alone: milking cows, all herd test dates
l1_te = H_te.assign(persistence=H_te["anchor"],
                    layer1=H_te["anchor"] * np.exp(L1.predict(H_te[L1_FEATURES])))
S1 = grains(l1_te, ["persistence", "layer1"], "persistence")
show(S1, ["persistence", "layer1"], "LAYER 1 milking cows")

# layer 2 alone: litres per recorded cow
Y_te = Y[y_te_mask].reset_index(drop=True)
HX_te = HX[y_te_mask].reset_index(drop=True)
r2 = L2.predict(Y_te[L2_FEATURES])
l2_te = Y_te.assign(persistence=Y_te["anchor"], layer2=Y_te["anchor"] * np.exp(r2))
S2 = grains(l2_te, ["persistence", "layer2"], "persistence")
show(S2, ["persistence", "layer2"], "LAYER 2 litres per recorded cow")

# combined herd milk
herd_f = HX_te["anchor"] * np.exp(Y_te["l1_change"])
yld_f = Y_te["anchor"] * np.exp(r2)
comb = pd.DataFrame({"origin": Y_te["origin"], "target_date": Y_te["target_date"], "lead": Y_te["lead"],
                     "month_ahead": Y_te["month_ahead"],
                     "actual": Y_te["actual"] * Y_te["herd_at_target"],
                     "persistence": HX_te["anchor"] * Y_te["anchor"],
                     "herd_only": herd_f * Y_te["anchor"],
                     "yield_only": HX_te["anchor"] * yld_f,
                     "layered": herd_f * yld_f})
comb = comb[np.isfinite(comb["actual"])].reset_index(drop=True)
comb["lower_80"] = comb["layered"] * np.exp(RANGE_Q[0.10].reindex(comb["month_ahead"]).values)
comb["upper_80"] = comb["layered"] * np.exp(RANGE_Q[0.90].reindex(comb["month_ahead"]).values)
CMODELS = ["persistence", "herd_only", "yield_only", "layered"]
S3 = grains(comb, CMODELS, "persistence")
show(S3, CMODELS, "COMBINED herd milk")
print("\nCOMBINED, daily: skill against persistence (> 0 = better)")
display(S3["daily"].pivot(index="model", columns="month_ahead", values="skill_vs_persistence").loc[CMODELS].round(3))
print("\nCOMBINED, daily: accuracy = 1 - WAPE and bias")
display(S3["daily"].pivot(index="model", columns="month_ahead", values=["accuracy_1_wape", "bias_pct"]).loc[CMODELS].round(3))
cov = ((comb["actual"] >= comb["lower_80"]) & (comb["actual"] <= comb["upper_80"])).groupby(comb["month_ahead"]).mean()
print("\nShare of recorded days inside the layered 80 % range (nominal 0.80):"); display(cov.to_frame("coverage"))
""")

# --------------------------------------------------------------------------------------
md(r"""
### 5b. Forecasts on unseen test data vs what was recorded

One figure per test forecast date, in the PFOI page style: weekly means of the recorded history,
the recorded outcome after the forecast date (dots, never seen by the models), each layer's
forecast (dashed) and its 80 % range from validation errors. The models are the ones trained
on the training 80 % only. Set `CHART_DATES` in §0 to choose the dates.
""")

code(_b2.CHART_HELPERS + r"""


def layered_path(o: pd.Timestamp) -> pd.DataFrame:
    fh = layer_rows("herd", pd.DatetimeIndex([o]), with_target=False)
    fy = layer_rows("yield", pd.DatetimeIndex([o]), with_target=False)
    c1 = L1.predict(fh[L1_FEATURES])
    fy["l1_change"] = c1
    c2 = L2.predict(fy[L2_FEATURES])
    m = fy["month_ahead"]
    q1, q2, q3 = RANGE_L1.reindex(m), RANGE_L2.reindex(m), RANGE_Q.reindex(m)
    out = pd.DataFrame(index=pd.DatetimeIndex(fy["target_date"]))
    out["cows"] = fh["anchor"].values * np.exp(c1)
    out["cows_lo"] = out["cows"] * np.exp(q1[0.10].values); out["cows_hi"] = out["cows"] * np.exp(q1[0.90].values)
    out["yield"] = fy["anchor"].values * np.exp(c2)
    out["yield_lo"] = out["yield"] * np.exp(q2[0.10].values); out["yield_hi"] = out["yield"] * np.exp(q2[0.90].values)
    out["milk"] = out["cows"] * out["yield"]
    out["milk_lo"] = out["milk"] * np.exp(q3[0.10].values); out["milk_hi"] = out["milk"] * np.exp(q3[0.90].values)
    return out


herd_milk = yld * herd
dates_ = chart_dates(Y_te["origin"], yld, CHART_DATES)
for o in dates_:
    f = layered_path(o)
    end = f.index.max()
    hist = slice(o - pd.Timedelta(days=364), o - pd.Timedelta(days=1))
    fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    forecast_panel(ax[0], "Herd milk = layer 1 × layer 2", herd_milk.loc[hist], herd_milk.loc[o:end],
                   f["milk"], f["milk_lo"], f["milk_hi"], o, "layered", COL["layered"], "litres per day")
    forecast_panel(ax[1], f"Milking cows (layer 1, {L1_BEST})", herd.loc[hist], herd.loc[o:end],
                   f["cows"], f["cows_lo"], f["cows_hi"], o, "layer 1", COL["herd_only"], "cows")
    forecast_panel(ax[2], f"Litres per recorded cow (layer 2, {L2_BEST})", yld.loc[hist], yld.loc[o:end],
                   f["yield"], f["yield_lo"], f["yield_hi"], o, "layer 2", COL["yield_only"], "litres per cow per day")
    ax[0].legend(fontsize=8, loc="upper left", ncol=2)
    ax[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.suptitle(f"Forecast date {o:%Y-%m-%d}: {MODEL_VERSION} on unseen data (herd level; 80 % ranges)" +
                 ("  [SYNTHETIC DEMO]" if USE_SYNTHETIC else ""), fontsize=11)
    plt.tight_layout()
    fig.savefig(CHART_DIR / f"nb03_test_{o:%Y%m%d}{'_demo' if USE_SYNTHETIC else ''}.png", dpi=130)
    plt.show()
print("chart dates:", ", ".join(f"{d:%Y-%m-%d}" for d in dates_), f"| saved to {CHART_DIR}")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 6. Explainability

**Herd vs yield split.** Every layered forecast is the anchor × herd change × yield change, so
in log terms the change from persistence is exactly `log(layer 1 / cows yesterday) +
log(layer 2 / 7-day yield)`. The table shows the mean signed and absolute size of each part by
month ahead on the test rows: which layer moves the forecast.

**Inside each layer.** LightGBM TreeSHAP (`pred_contrib=True`) summed into factor groups; the
parts add up exactly to each layer's output (checked). If a layer selected Random Forest, its
LightGBM twin, trained on the same rows, is explained.
""")

code(r"""
parts = pd.DataFrame({"month_ahead": Y_te["month_ahead"], "herd_part": Y_te["l1_change"], "yield_part": r2})
split = parts.groupby("month_ahead").agg(herd_mean=("herd_part", "mean"), yield_mean=("yield_part", "mean"),
                                         herd_abs=("herd_part", lambda x: x.abs().mean()),
                                         yield_abs=("yield_part", lambda x: x.abs().mean()))
split["herd_share_of_change"] = split["herd_abs"] / (split["herd_abs"] + split["yield_abs"])
print("Change from persistence, log units (0.01 ≈ 1 %):"); display(split.round(4))

GROUPS = {
    "recent yield level": ["lvl_", "mom_", "cv_28"],
    "layer 1 forecast": ["l1_change"],
    "herd stocks": ["milking", "n_herd", "dry_open", "calves"],
    "pregnancy pipeline": ["pipe_", "dry_pregnant", "heifers_pregnant"],
    "events": ["calvings_", "dry_offs_", "exits_", "entries_", "abortions_"],
    "lactation mix": ["share_par", "share_dim"],
    "weather": ["thi_", "rain_"],
    "health / sensors": ["mastitis", "alarm", "sessions_per_cow"],
    "record quality": ["scoreable", "days_since", "recorded_cows", "clean_cows", "removed_share"],
    "season / lead": ["tgt_", "lead", "last_year"],
}


def group_of(f: str) -> str:
    for g, keys in GROUPS.items():
        if any(f.startswith(k) or k in f for k in keys):
            return g
    return "other"


def shap_groups(model, X: pd.DataFrame, months: pd.Series) -> pd.DataFrame:
    contrib = model.predict(X, pred_contrib=True)
    assert np.allclose(contrib.sum(axis=1), model.predict(X), atol=1e-6), "SHAP parts do not add up"
    s = pd.DataFrame(np.abs(contrib[:, :-1]), columns=X.columns)
    g = s.T.groupby(s.columns.map(group_of)).sum().T
    g["month_ahead"] = months.values
    imp = g.groupby("month_ahead").mean().T
    return imp.div(imp.sum(axis=0), axis=1)


def lgbm_of(best, model, X, y, d):
    return model if best == "lightgbm" else fit_xy(CANDIDATES["lightgbm"], X, y, d)


s1 = H_te.sample(min(20000, len(H_te)), random_state=SEED)
s2 = Y_te.sample(min(20000, len(Y_te)), random_state=SEED)
imp1 = shap_groups(lgbm_of(L1_BEST, L1, H_tr[L1_FEATURES], H_tr["y_ratio"], H_tr["target_date"]),
                   s1[L1_FEATURES], s1["month_ahead"])
imp2 = shap_groups(lgbm_of(L2_BEST, L2, Y_tr[L2_FEATURES], Y_tr["y_ratio"], Y_tr["target_date"]),
                   s2[L2_FEATURES], s2["month_ahead"])
print("Additivity check passed for both layers.")
fig, ax = plt.subplots(1, 2, figsize=(15, 5))
imp1.sort_values(imp1.columns[0]).plot.barh(ax=ax[0]); ax[0].set_title("Layer 1 (milking cows): share of mean |SHAP|")
imp2.sort_values(imp2.columns[0]).plot.barh(ax=ax[1]); ax[1].set_title("Layer 2 (litres per cow): share of mean |SHAP|")
plt.tight_layout(); plt.show()
""")

# --------------------------------------------------------------------------------------
md(r"""
## 6b. Period tests: 2019–2021 and 2022–2026

Two fixed test windows (`PERIODS` in §0). For each window both layers are picked and trained
**only on rows whose target day is before the window starts** (layer 2's layer-1 inputs are
out of sample in the same yearly way as §4), then scored on forecast dates inside the window
whose targets also fall inside it. Milking cows (layer 1) cover every year; clean litres per cow
(layer 2, and so herd milk) are missing for most of 2022–2025, so those are scored on the days
that exist. Charts show the layers trained before each window.
""")

code(r"""
PERIOD_RESULTS = {}
for pname, (train_end, t_from, t_to) in PERIODS.items():
    E, P0, P1 = pd.Timestamp(train_end), pd.Timestamp(t_from), pd.Timestamp(t_to)
    h_tr = H[(H["origin"] < E) & (H["target_date"] < E)].reset_index(drop=True)
    h_te = H[(H["origin"] >= P0) & (H["origin"] < P1) & (H["target_date"] < P1)].reset_index(drop=True)
    ytr = (Y["origin"] < E) & (Y["target_date"] < E)
    yte = (Y["origin"] >= P0) & (Y["origin"] < P1) & (Y["target_date"] < P1)
    print(f"\n=== {pname}: herd train {len(h_tr):,} / test {len(h_te):,} rows; yield train {int(ytr.sum()):,} / test {int(yte.sum()):,} rows "
          f"(yield test years: {', '.join(str(y) for y in sorted(Y.loc[yte, 'target_date'].dt.year.unique())) or 'none'})")
    if len(h_tr) < 2000 or not len(h_te):
        print("  skipped: not enough herd rows"); continue
    b1, v1 = pick(h_tr, L1_FEATURES, f"  layer 1 ({pname})")
    m1 = fit_xy(CANDIDATES[b1], h_tr[L1_FEATURES], h_tr["y_ratio"], h_tr["target_date"])
    p1 = h_te.assign(persistence=h_te["anchor"], layer1=h_te["anchor"] * np.exp(m1.predict(h_te[L1_FEATURES])))
    out = {"layer1": grains(p1, ["persistence", "layer1"], "persistence")}
    show(out["layer1"], ["persistence", "layer1"], f"{pname} LAYER 1 milking cows")
    if int(ytr.sum()) >= 2000 and int(yte.sum()):
        Yp = Y.copy()
        Yp["l1_change"] = np.nan
        for yr_ in sorted(Yp.loc[ytr, "origin"].dt.year.unique()):
            cut = min(pd.Timestamp(year=int(yr_), month=1, day=1), E)
            trh = H[(H["origin"] < cut) & (H["target_date"] < cut)]
            sel = ytr & (Yp["origin"].dt.year == yr_)
            if len(trh) >= 1000:
                Yp.loc[sel, "l1_change"] = fit_xy(CANDIDATES[b1], trh[L1_FEATURES], trh["y_ratio"],
                                                  trh["target_date"]).predict(HX.loc[sel, L1_FEATURES])
        Yp.loc[yte, "l1_change"] = m1.predict(HX.loc[yte, L1_FEATURES])
        y_tr_p = Yp[ytr].reset_index(drop=True)
        b2, _ = pick(y_tr_p, L2_FEATURES, f"  layer 2 ({pname})")
        m2 = fit_xy(CANDIDATES[b2], y_tr_p[L2_FEATURES], y_tr_p["y_ratio"], y_tr_p["target_date"])
        y_te_p, hx_te_p = Yp[yte].reset_index(drop=True), HX[yte].reset_index(drop=True)
        r2p = m2.predict(y_te_p[L2_FEATURES])
        p2 = y_te_p.assign(persistence=y_te_p["anchor"], layer2=y_te_p["anchor"] * np.exp(r2p))
        out["layer2"] = grains(p2, ["persistence", "layer2"], "persistence")
        show(out["layer2"], ["persistence", "layer2"], f"{pname} LAYER 2 litres per recorded cow")
        hf, yf = hx_te_p["anchor"] * np.exp(y_te_p["l1_change"]), y_te_p["anchor"] * np.exp(r2p)
        cb = pd.DataFrame({"origin": y_te_p["origin"], "target_date": y_te_p["target_date"], "lead": y_te_p["lead"],
                           "month_ahead": y_te_p["month_ahead"], "actual": y_te_p["actual"] * y_te_p["herd_at_target"],
                           "persistence": hx_te_p["anchor"] * y_te_p["anchor"], "herd_only": hf * y_te_p["anchor"],
                           "yield_only": hx_te_p["anchor"] * yf, "layered": hf * yf})
        cb = cb[np.isfinite(cb["actual"])].reset_index(drop=True)
        out["layered"] = grains(cb, CMODELS, "persistence")
        show(out["layered"], CMODELS, f"{pname} COMBINED herd milk")
        # charts: herd milk, cows and litres per cow from the layers trained before the window
        for o in chart_dates(y_te_p["origin"], yld, None):
            fh = layer_rows("herd", pd.DatetimeIndex([o]), with_target=False)
            fy = layer_rows("yield", pd.DatetimeIndex([o]), with_target=False)
            c1 = m1.predict(fh[L1_FEATURES]); fy["l1_change"] = c1
            c2 = m2.predict(fy[L2_FEATURES])
            ix = pd.DatetimeIndex(fy["target_date"])
            cows = pd.Series(fh["anchor"].values * np.exp(c1), index=ix)
            ypc = pd.Series(fy["anchor"].values * np.exp(c2), index=ix)
            hist = slice(o - pd.Timedelta(days=364), o - pd.Timedelta(days=1)); end = ix.max()
            fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
            forecast_panel(ax[0], "Herd milk = layer 1 × layer 2", (yld * herd).loc[hist], (yld * herd).loc[o:end],
                           cows * ypc, None, None, o, "layered", COL["layered"], "litres per day")
            forecast_panel(ax[1], f"Milking cows (layer 1, {b1})", herd.loc[hist], herd.loc[o:end],
                           cows, None, None, o, "layer 1", COL["herd_only"], "cows")
            forecast_panel(ax[2], f"Litres per recorded cow (layer 2, {b2})", yld.loc[hist], yld.loc[o:end],
                           ypc, None, None, o, "layer 2", COL["yield_only"], "litres per cow per day")
            ax[0].legend(fontsize=8, loc="upper left", ncol=2)
            fig.suptitle(f"Forecast date {o:%Y-%m-%d}: layers trained before {E:%Y} (period test {pname})"
                         + ("  [SYNTHETIC DEMO]" if USE_SYNTHETIC else ""), fontsize=11)
            plt.tight_layout(); fig.savefig(CHART_DIR / f"nb03_period_{pname}_{o:%Y%m%d}{'_demo' if USE_SYNTHETIC else ''}.png", dpi=130)
            plt.show()
    else:
        print(f"  layer 2 / herd milk not scored in {pname}: too few clean milk rows before or inside the window")
    PERIOD_RESULTS[pname] = out
""")

# --------------------------------------------------------------------------------------
md(r"""
## 7. Prediction from the latest data

Both layers are refitted on every row with a known outcome (layer 2 with its out-of-sample
layer 1 inputs), then forecast the next `HORIZON_DAYS` days from the day after the last clean
yield day: milking cows (layer 1), litres per cow (layer 2) and herd milk (layered), daily and
weekly (Monday weeks), with the 80 % range from §4. Exported in the `c1_output.outlook` row
shape to `logs/pfoi/notebook_ml/`.
""")

code(r"""
L1_full = fit_xy(CANDIDATES[L1_BEST], H[L1_FEATURES], H["y_ratio"], H["target_date"])
Y_known = Y                                   # layer 1 inputs are out of sample (§4)
L2_full = fit_xy(CANDIDATES[L2_BEST], Y_known[L2_FEATURES], Y_known["y_ratio"], Y_known["target_date"])

last_clean = yld.last_valid_index()
origin = last_clean + pd.Timedelta(days=1)
if origin not in panel.index:                  # extend the calendar so the origin row exists
    panel = panel.reindex(pd.date_range(panel.index.min(), origin, freq="D"))
    FEAT = origin_features(panel)
    Y_C7 = panel["y"].rolling(7, center=True, min_periods=3).mean()
    refresh_series()
fy = layer_rows("yield", pd.DatetimeIndex([origin]), with_target=False)
fh = layer_rows("herd", pd.DatetimeIndex([origin]), with_target=False)
fy["l1_change"] = L1_full.predict(fh[L1_FEATURES])
r_y = L2_full.predict(fy[L2_FEATURES])
fut = pd.DataFrame({"target_date": fy["target_date"], "lead": fy["lead"], "month_ahead": fy["month_ahead"],
                    "milking": fh["anchor"] * np.exp(fy["l1_change"]),
                    "milk_per_cow": fy["anchor"] * np.exp(r_y)})
fut["milk_litres"] = fut["milking"] * fut["milk_per_cow"]
q = RANGE_Q.reindex(fut["month_ahead"])
fut["milk_lower"] = fut["milk_litres"] * np.exp(q[0.10].values)
fut["milk_upper"] = fut["milk_litres"] * np.exp(q[0.90].values)
print(f"forecast date {origin:%Y-%m-%d} (last clean yield day {last_clean:%Y-%m-%d}); "
      f"layer 1 {L1_BEST}, layer 2 {L2_BEST} ({MODEL_VERSION}), source = {SOURCE}")
print(f"cows yesterday {fh['anchor'].iloc[0]:,.0f}; 7-day yield {fy['anchor'].iloc[0]:.2f} L per recorded cow")
fut["week_start"] = fut["target_date"] - pd.to_timedelta(fut["target_date"].dt.weekday, unit="D")
cols = ["milking", "milk_per_cow", "milk_litres", "milk_lower", "milk_upper"]
monthly_fc = fut.groupby("month_ahead")[cols].mean()
weekly_fc = fut.groupby("week_start")[cols].mean().assign(days=fut.groupby("week_start").size())
print("Forecast by month ahead (mean per day):"); display(monthly_fc)
print("Weekly forecast (mean per day; first / last week may be partial):"); display(weekly_fc)

hist = (yld * herd).loc[origin - pd.Timedelta(days=120): origin]
fig, ax = plt.subplots(figsize=(13, 4.5))
ax.plot(hist.index, hist.values, color=COL["actual"], lw=0.9, label="recorded (clean estimate)")
ax.fill_between(fut["target_date"], fut["milk_lower"], fut["milk_upper"], color=COL["layered"], alpha=0.18, lw=0, label="80 % range")
ax.plot(fut["target_date"], fut["milk_litres"], color=COL["layered"], lw=1.8, label="layered daily")
ax.step(weekly_fc.index, weekly_fc["milk_litres"], where="post", color="#333", lw=1, ls=":", label="weekly mean")
ax.axvline(origin, color="#888", lw=0.8)
ax.set_title(f"Herd milk: layer 1 × layer 2 from {origin:%Y-%m-%d}" + ("  [SYNTHETIC DEMO]" if USE_SYNTHETIC else ""))
ax.legend(loc="upper left"); plt.tight_layout(); plt.show()

quality = lambda h: "high" if h <= 7 else ("moderate" if h <= 30 else "limited")
out_rows = []
for series, col, lo, hi in (("milking", "milking", None, None), ("milk_per_cow", "milk_per_cow", None, None),
                            ("milk_litres", "milk_litres", "milk_lower", "milk_upper")):
    for grain, frame in (("day", fut.set_index("target_date")), ("week", weekly_fc)):
        for i, (period, r) in enumerate(frame.iterrows(), start=1):
            h = int(r["lead"]) if grain == "day" else i
            out_rows.append({"origin_date": f"{origin:%Y-%m-%d}", "target_period": f"{period:%Y-%m-%d}",
                             "grain": grain, "horizon": h, "series": series,
                             "forecast": round(float(r[col]), 2),
                             "lower": round(float(r[lo]), 2) if lo else None,
                             "upper": round(float(r[hi]), 2) if hi else None,
                             "quality_flag": quality(h if grain == "day" else 7 * h),
                             "model_version": MODEL_VERSION, "core_version": INPUT_SCHEMA})
""")

# --------------------------------------------------------------------------------------
md(r"""
## 8. Summary against the targets

Printed from the tables above. Frontend readiness uses the same fixed rule as notebook 02:
the layered month-1 daily **and** weekly forecasts need ≥ 85 % within ±10 % and positive skill
against persistence.
""")

code(r"""
def _ok(s_, m) -> bool:
    r = s_[(s_["model"] == m) & (s_["month_ahead"] == 1)]
    return bool(len(r)) and r["within_10pct"].iloc[0] >= TARGET_HIT and r["skill_vs_persistence"].iloc[0] > 0


READY = _ok(S3["daily"], "layered") and _ok(S3["weekly"], "layered")
lines = [f"Layered model: layer 1 = {L1_BEST}, layer 2 = {L2_BEST}   |   test from {split_date:%Y-%m-%d}   |   source = {SOURCE}", ""]
for label, S, m in (("layer 1 milking cows", S1, "layer1"), ("layer 2 litres/cow ", S2, "layer2"),
                    ("layered herd milk   ", S3, "layered")):
    for grain, s_ in S.items():
        t = s_[s_["model"] == m].set_index("month_ahead")
        p = s_[s_["model"] == "persistence"].set_index("month_ahead")
        if t.empty:
            lines.append(f"⚪ {label} {grain:7s}: no scored period in the test window")
        for mo, r in t.iterrows():
            ok = "✅" if r["within_10pct"] >= TARGET_HIT else "❌"
            lines.append(f"{ok} {label} {grain:7s} month {mo}: within ±10 % = {r['within_10pct']:.1%} "
                         f"(persistence {p.loc[mo, 'within_10pct']:.1%}), skill {r['skill_vs_persistence']:+.2f}, n = {int(r['n'])}")
    lines.append("")
lines.append(("✅ FRONTEND READY" if READY else "❌ NOT FRONTEND READY") +
             f": layered month-1 daily and weekly need ≥ {TARGET_HIT:.0%} within ±10 % and positive skill vs persistence")
print("\n".join(lines))

payload = {"source": SOURCE, "model_version": MODEL_VERSION, "layer1": L1_BEST, "layer2": L2_BEST,
           "frontend_ready": bool(READY), "unit": "per day (weekly rows = mean per day)",
           "basis": "herd milk = layer 1 milking cows x layer 2 clean litres per recorded cow; no placeholder or shipped milk",
           "outlook": out_rows}
stamp = f"{origin:%Y%m%d}" + ("_demo" if USE_SYNTHETIC else "")
(OUT_DIR / f"forecast_layers_{stamp}.json").write_text(json.dumps(payload, indent=1))
pd.concat([S.assign(grain=g, layer=lbl) for lbl, SS in (("layer1", S1), ("layer2", S2), ("layered", S3))
           for g, S in SS.items()]).assign(source=SOURCE).to_csv(OUT_DIR / f"test_metrics_layers_{stamp}.csv", index=False)
print("written:", *(p.name for p in sorted(OUT_DIR.glob(f"*layers_{stamp}*"))), sep="\n  ")
""")

md(r"""
**Reporting rules.** Quote the numbers as printed, including any ❌. The thresholds in §0 stay
fixed. Persistence is a benchmark only and is never blended into the forecast.
""")


def build(path: Path) -> None:
    nb = {
        "cells": [
            {"cell_type": t, "metadata": {}, "source": s.splitlines(keepends=True),
             **({"execution_count": None, "outputs": []} if t == "code" else {})}
            for t, s in CELLS
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    out = HERE / "03_layered_herd_yield.ipynb"
    build(out)
    print(f"wrote {out} ({len(CELLS)} cells)")
