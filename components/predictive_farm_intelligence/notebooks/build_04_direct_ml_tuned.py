"""Writes notebooks/04_direct_ml_tuned.ipynb (outputs empty).

pfoi-1.4 direct machine-learning forecaster, rebuilt on model_input2 with the clean variables
(no placeholder or shipped milk, pregnancy counts without hindsight), wider feature engineering
and LightGBM hyper-parameter search by time-series cross-validation. Loading and cleaning are
the same cell as notebook 02 (taken from build_02_ml_milk_forecast.py). Run:
  .venv/bin/python components/predictive_farm_intelligence/notebooks/build_04_direct_ml_tuned.py
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


CELLS: list[tuple[str, str]] = []


def md(s: str) -> None:
    CELLS.append(("markdown", s.strip("\n")))


def code(s: str) -> None:
    CELLS.append(("code", s.strip("\n")))


# --------------------------------------------------------------------------------------
md(r"""
# Farm X: direct machine-learning forecaster, tuned (pfoi-1.4 design on model_input2)

The pfoi-1.4.0-dev experiment (`docs/ml_direct.md`) rebuilt on the new dataset:

* **one model per series**, every grain and horizon pooled (horizon and period length are
  features): daily 1–30 days, weekly 1–13 weeks, monthly (30-day) 1–6 months ahead;
* **ten series**: litres per recorded cow, herd milk (per cow × milking cows), milking cows,
  total herd, calvings, dry-offs, abortions, deaths, culls, sales;
* **relative targets**: milk and stocks as the log ratio to their level on the forecast date;
  events as Poisson counts starting from the trailing 365-day rate (the rate is the offset);
* **proper variables** (what changed from 1.4):
  * milk = identified-cow records ≤ 18 L only; placeholder (unidentified herd-total) and
    shipped milk are never used (AGENTS.md, `docs/model_input2.md` §5);
  * pregnancy counts come from `day_cell_known` (pregnant only once knowable), not the
    hindsight `day_panel` columns;
  * everything a feature uses is dated before the forecast date;
* **more feature engineering**: lags, rolling means / spreads / ranges, exponentially weighted
  levels, momentum, year-on-year change, the same period last year, an insemination window
  that points at calvings due in the target period, lactation-stage mix, heat load, sensors and
  record quality;
* **hyper-parameter tuning**: random search over LightGBM settings, scored by purged
  time-series cross-validation inside the training 80 % only; the 1.4 default settings are
  always one of the candidates, so the table shows what tuning adds;
* **80:20 chronological split** per series; the test 20 % is used once, after tuning.

Experiment only (`pfoi-1.4.1-nb-dev`): nothing is written to the database. Herd totals per day
only; exports to `logs/pfoi/notebook_ml/` (gitignored). **Clear all outputs before committing.**
""")

code(r"""
USE_SYNTHETIC = False        # True = fictional demo data, no database connection

# ---- fixed before any run (do not tune these on test results) ------------------------
INPUT_SCHEMA      = "model_input2"
TARGET            = "per_cow"     # used by the shared loading cell (clean litres per recorded cow)
CLEAN_MAX_LITRES  = 18.0          # a day above 18 L per recorded cow is removed
MIN_RECORDED_COWS = 20            # a milk day counts only if ≥ 20 cows have a clean record
SERIES = {"milk_per_cow": "milk", "herd_milk": "milk", "milking": "stock", "n_herd": "stock",
          "calvings": "event", "dry_offs": "event", "real_abortions": "event", "deaths": "event",
          "culls": "event", "sales": "event"}
# grain: (period length in days, horizons trained, horizons scored)
GRAINS = {"day": (1, list(range(1, 31)), [1, 7, 14, 30]),
          "week": (7, list(range(1, 14)), [1, 4, 8, 13]),
          "month": (30, list(range(1, 7)), [1, 2, 3, 6])}
ORIGIN_STEP       = {"milk": 2, "stock": 7, "event": 7}   # a forecast date every N days
MIN_MILK_COVERAGE = 0.80          # a milk period counts if ≥ 80 % of its days are recorded
TEST_SHARE        = 0.20
CV_FOLDS          = 3             # purged expanding time-series folds inside the training 80 %
N_TRIALS          = 12            # random LightGBM settings tried per series (plus the 1.4 default)
TOLERANCE         = 0.10
TARGET_HIT        = 0.85
SEED              = 17
MODEL_VERSION     = "pfoi-1.4.1-nb-dev"
CHART_DATES       = None          # forecast dates for the page-style charts; None = automatic
# period tests (§7b): name -> (training targets end by, test from, test to); each window is trained
# only on the years before it and re-tuned there (no peeking at the test years)
PERIODS = {"2019-2021": ("2019-01-01", "2019-01-01", "2022-01-01"),
           "2022-2026": ("2022-01-01", "2022-01-01", "2027-01-01")}
N_TRIALS_PERIOD   = 6
LGBM_14 = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40,
               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0)   # pfoi-1.4 settings
SEARCH_SPACE = {"n_estimators": [200, 400, 800, 1200], "learning_rate": [0.01, 0.02, 0.03, 0.05, 0.1],
                "num_leaves": [7, 15, 31, 63], "min_child_samples": [20, 40, 80, 160, 320],
                "subsample": [0.6, 0.8, 1.0], "colsample_bytree": [0.4, 0.6, 0.8, 1.0],
                "reg_lambda": [0.0, 1.0, 5.0, 20.0], "reg_alpha": [0.0, 0.5, 2.0],
                "max_depth": [-1, 4, 6, 8], "loss": ["l2", "l1", "huber"]}   # loss: milk / stocks only

import sys, json, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.stats import poisson
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import QuantileTransformer, StandardScaler
import lightgbm as lgb

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

COMPONENT_DIR = Path.cwd().resolve()
if COMPONENT_DIR.name == "notebooks":
    COMPONENT_DIR = COMPONENT_DIR.parent
sys.path.insert(0, str(COMPONENT_DIR))
OUT_DIR = COMPONENT_DIR / "logs" / "pfoi" / "notebook_ml"
CHART_DIR = OUT_DIR / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)
SOURCE = "demo" if USE_SYNTHETIC else "model"
RNG = np.random.default_rng(SEED)
pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
pd.set_option("display.width", 200)
plt.rcParams.update({"figure.figsize": (13, 4.5), "axes.grid": True, "grid.alpha": 0.3,
                     "axes.spines.top": False, "axes.spines.right": False})
if USE_SYNTHETIC:
    print("SYNTHETIC DEMO DATA: every number below is fictional (source = 'demo').")
""")

md(r"""
## 1. Import dataset and cleaning

Same cell as notebook 02 §1 / §1b: `model_input2.day_panel` (herd totals per day), the
milking-cow mix from `day_cell`, and the pregnancy stocks from `day_cell_known`. Milk is the
clean identified-cow series only.
""")
code(_b2_cell("PANEL_COLS = "))

# --------------------------------------------------------------------------------------
md(r"""
## 2. Dataset description: the ten series by year

Means per day for milk and stocks, totals for events; `milk_days` = days with a clean
per-cow value (≥ 20 recorded cows). Aggregates only.
""")

code(r"""
herd = panel["milking"].astype(float).where(panel["milking"] > 0)
y_pc = panel["clean_per_cow"].where(panel["clean_day"])
DAILY = {"milk_per_cow": y_pc, "herd_milk": y_pc * herd, "milking": herd,
         "n_herd": panel["n_herd"].astype(float).where(panel["n_herd"] > 0)}
for e in ("calvings", "dry_offs", "real_abortions", "deaths", "culls", "sales"):
    DAILY[e] = panel[e].astype(float)

yr = panel.index.year
desc = pd.DataFrame({name: (s.groupby(yr).sum() if SERIES[name] == "event" else s.groupby(yr).mean())
                     for name, s in DAILY.items()})
desc["milk_days"] = y_pc.notna().groupby(yr).sum()
desc["ais"] = panel["ais"].groupby(yr).sum()
desc.index.name = "year"
display(desc.round(2))
""")

# --------------------------------------------------------------------------------------
md(r"""
## 3. Feature engineering (everything known on the forecast date)

For a forecast date *o*, every feature uses days **before** *o* (series shifted by one day before
any window). Rows are *o* × grain × horizon; the target period is
`[o + L·(h−1), o + L·h)` with period length L = 1 / 7 / 30 days.

| Group | Features |
|---|---|
| own history (each series) | means over 7 / 14 / 28 / 91 / 182 / 365 days; momentum ratios 7/28, 28/91, 91/365; spread (std / mean) 28 and 91; 28-day min and max relative to the level; exponentially weighted levels (half-life 7, 28, 91) relative to the level; lags at 1, 7, 14 and 28 days relative to the level; year-on-year change of the 28-day mean; share of recorded days |
| herd stocks | milking, total herd, dry pregnant / open, heifers pregnant / open (known only), calves, bulls, each with 28- and 91-day change |
| pregnancy pipeline | known pregnant dry cows and heifers per milking cow; dry share; **inseminations 270–290 days before the target period** (cows that may calve in it), counting only inseminations already recorded |
| event rates | every event per day over 30, 91 and 365 days |
| lactation mix | parity shares, days-in-milk shares, a mean-DIM proxy |
| heat / weather | THI 7 / 28 / 91-day mean, heat hours 28 days, rain 28 / 91 days (past only) |
| health / sensors | mastitis 91 days, blood and conductivity alarms per session, sessions per cow |
| record quality | clean recorded cows, recorded / milking cows, share of > 18 L records, share of clean milk days |
| target period | grain, horizon, days to the period start, period length, season of the period (sin/cos, 2 harmonics), the **same period last year** relative to last year's level |
""")

code(r"""
def roll(s, w, how="mean", mp=None):
    r = s.rolling(w, min_periods=mp if mp is not None else max(2, w // 4))
    return getattr(r, how)()


def lr(a, b):
    return np.log(a / b).replace([np.inf, -np.inf], np.nan)


def shared_features(p: pd.DataFrame) -> pd.DataFrame:
    past = p.shift(1)
    F = pd.DataFrame(index=p.index)
    for c in ["milking", "n_herd", "dry_pregnant", "dry_open", "heifers_pregnant", "heifers_open", "calves", "bulls"]:
        F[f"st_{c}"] = past[c]
        F[f"st_{c}_chg28"] = lr(past[c] + 1, past[c].shift(28) + 1)
        F[f"st_{c}_chg91"] = lr(past[c] + 1, past[c].shift(91) + 1)
    m = past["milking"].replace(0, np.nan)
    F["pipe_dry_preg_per_milking"] = past["dry_pregnant"] / m
    F["pipe_heifer_preg_per_milking"] = past["heifers_pregnant"] / m
    dry = past["dry_pregnant"] + past["dry_open"]
    F["pipe_dry_share"] = dry / (dry + past["milking"]).replace(0, np.nan)
    for c in ["calvings", "dry_offs", "ais", "real_abortions", "deaths", "culls", "sales", "entries"]:
        for w in (30, 91, 365):
            F[f"ev_{c}_{w}"] = roll(past[c].fillna(0), w, "sum", 1) / w
    for c in ["share_par_1", "share_par_2", "share_par_3p", "share_dim_0_60", "share_dim_61_150",
              "share_dim_151_305", "share_dim_305p"]:
        F[f"mix_{c}"] = past[c]
    F["mix_mean_dim_proxy"] = (past["share_dim_0_60"] * 30 + past["share_dim_61_150"] * 105
                               + past["share_dim_151_305"] * 228 + past["share_dim_305p"] * 360)
    for w in (7, 28, 91):
        F[f"wx_thi_{w}"] = roll(past["thi_mean"], w)
    F["wx_heat_hours_28"] = roll(past["hours_thi_above"].fillna(0), 28, "sum", 1)
    F["wx_rain_28"] = roll(past["rain_total_mm"].fillna(0), 28, "sum", 1)
    F["wx_rain_91"] = roll(past["rain_total_mm"].fillna(0), 91, "sum", 1)
    sess = roll(past["n_sessions"].fillna(0), 28, "sum", 1).replace(0, np.nan)
    F["hl_mastitis_91"] = roll(past["mastitis_episodes"].fillna(0), 91, "sum", 1)
    F["hl_blood_alarm_rate_28"] = roll(past["n_blood_alarms"].fillna(0), 28, "sum", 1) / sess
    F["hl_cond_alarm_rate_28"] = roll(past["n_conductivity_alarms"].fillna(0), 28, "sum", 1) / sess
    F["hl_sessions_per_cow_28"] = sess / (roll(past["milking"], 28) * 28)
    F["q_clean_cows_7"] = roll(past["cows_clean"], 7)
    F["q_recorded_share_28"] = roll(past["cows_clean"] / m, 28)
    F["q_removed_share_28"] = (roll(past["records_removed_gt18"], 28, "sum", 1)
                               / roll(past["milk_observed_records"].fillna(0), 28, "sum", 1).replace(0, np.nan))
    F["q_clean_day_share_28"] = roll(past["clean_day"].astype(float), 28, "mean", 1)
    return F


def own_features(s: pd.Series, kind: str) -> tuple[pd.DataFrame, pd.Series]:
    # history of one series before each date, and its level on the forecast date (the anchor)
    p = s.shift(1)
    F = pd.DataFrame(index=s.index)
    for w in (7, 14, 28, 91, 182, 365):
        F[f"own_mean_{w}"] = roll(p, w, mp=1 if kind == "event" else None)
    if kind == "milk":
        level = F["own_mean_7"].fillna(F["own_mean_28"])
    elif kind == "stock":
        level = p.ffill(limit=7)
    else:
        level = roll(p.fillna(0), 365, "mean", 1)                # trailing 365-day rate per day
    eps = 1.0 / 365 if kind == "event" else 0.0
    F["own_mom_7_28"] = lr(F["own_mean_7"] + eps, F["own_mean_28"] + eps)
    F["own_mom_28_91"] = lr(F["own_mean_28"] + eps, F["own_mean_91"] + eps)
    F["own_mom_91_365"] = lr(F["own_mean_91"] + eps, F["own_mean_365"] + eps)
    for w in (28, 91):
        F[f"own_spread_{w}"] = roll(p, w, "std") / (roll(p, w) + eps)
    F["own_min_28"] = lr(roll(p, 28, "min") + eps, level + eps)
    F["own_max_28"] = lr(roll(p, 28, "max") + eps, level + eps)
    for hl in (7, 28, 91):
        F[f"own_ewm_{hl}"] = lr(p.ewm(halflife=hl, ignore_na=True).mean() + eps, level + eps)
    if kind != "event":
        for k in (1, 7, 14, 28):
            F[f"own_lag_{k}"] = lr(s.shift(k), level)
    F["own_yoy_28"] = lr(F["own_mean_28"] + eps, F["own_mean_28"].shift(365) + eps)
    F["own_recorded_share_28"] = roll(p.notna().astype(float), 28, "mean", 1)
    return F, level


def build_all():
    global SHARED, SER
    SHARED = shared_features(panel)
    SER = {}
    for name, kind in SERIES.items():
        own, level = own_features(DAILY[name], kind)
        SER[name] = {"kind": kind, "own": own, "level": level}


build_all()
GH = [(g, L, h) for g, (L, hs, _) in GRAINS.items() for h in hs]
G_CODE = {g: i for i, g in enumerate(GRAINS)}


def expand(name: str, origins) -> pd.DataFrame:
    # forecast date x (grain, horizon) rows for one series; actual is NaN where not (yet) recorded
    S = SER[name]; kind = S["kind"]
    idx = panel.index; n = len(idx)
    v = DAILY[name].reindex(idx).to_numpy(float)
    CS = np.concatenate([[0.0], np.nancumsum(v)])
    CN = np.concatenate([[0], np.cumsum(~np.isnan(v))])
    CA = np.concatenate([[0.0], np.cumsum(panel["ais"].fillna(0).to_numpy(float))])
    pos = idx.get_indexer(pd.DatetimeIndex(origins))
    pos = pos[pos >= 0]
    k = len(GH)
    o_pos = np.repeat(pos, k)
    g = np.tile(np.array([G_CODE[x[0]] for x in GH]), len(pos))
    L = np.tile(np.array([x[1] for x in GH]), len(pos))
    h = np.tile(np.array([x[2] for x in GH]), len(pos))
    st = o_pos + L * (h - 1); en = st + L
    inside = en <= n
    stc, enc = np.minimum(st, n), np.minimum(en, n)
    tot, cnt = CS[enc] - CS[stc], CN[enc] - CN[stc]
    if kind == "milk":
        actual = np.where(inside & (cnt >= np.ceil(L * MIN_MILK_COVERAGE)), tot / np.maximum(cnt, 1), np.nan)
    elif kind == "stock":
        actual = np.where(inside & (cnt == L), tot / L, np.nan)
    else:
        actual = np.where(inside & (cnt == L), tot, np.nan)
    level = S["level"].to_numpy(float)[o_pos]
    base = level * L if kind == "event" else level
    # same period last year (all of it lies before the forecast date for horizons ≤ 6 months)
    lst, len_ = st - 365, en - 365
    okl = lst >= 0
    lst_c, len_c = np.clip(lst, 0, n), np.clip(len_, 0, n)
    ly_tot, ly_cnt = CS[len_c] - CS[lst_c], CN[len_c] - CN[lst_c]
    lvl_ly = np.where(o_pos >= 365, S["level"].to_numpy(float)[np.maximum(o_pos - 365, 0)], np.nan)
    if kind == "event":
        ly_feat = np.where(okl, ly_tot / L, np.nan)
        ly_rel = np.log((ly_feat + 1 / 365) / (lvl_ly + 1 / 365))
    else:
        ly_mean = np.where(okl & (ly_cnt >= L * 0.5), ly_tot / np.maximum(ly_cnt, 1), np.nan)
        ly_feat = np.log(ly_mean / lvl_ly)
        ly_rel = ly_feat
    # inseminations 270-290 days before the target period, recorded before the forecast date
    a0 = np.clip(st - 290, 0, n); a1 = np.clip(np.minimum(en - 270, o_pos), 0, n)
    ai_win = np.where(a1 > a0, CA[a1] - CA[a0], 0.0) / L
    ai_vis = np.clip((a1 - a0) / np.maximum((en - 270) - (st - 290), 1), 0, 1)
    pstart = idx[o_pos] + pd.to_timedelta(L * (h - 1), unit="D")
    mid = pstart + pd.to_timedelta(L / 2, unit="D")
    doy = mid.dayofyear.values
    rows = pd.DataFrame(np.hstack([S["own"].to_numpy(float)[o_pos], SHARED.to_numpy(float)[o_pos]]),
                        columns=list(S["own"].columns) + list(SHARED.columns))
    rows["per_grain"] = g; rows["per_horizon"] = h; rows["per_lead_days"] = L * (h - 1); rows["per_length"] = L
    for kk in (1, 2):
        rows[f"per_doy_sin{kk}"] = np.sin(2 * np.pi * kk * doy / 365.25)
        rows[f"per_doy_cos{kk}"] = np.cos(2 * np.pi * kk * doy / 365.25)
    rows["per_last_year"] = ly_feat
    rows["per_last_year_rel"] = ly_rel
    rows["per_ai_window"] = ai_win
    rows["per_ai_visible"] = ai_vis
    meta = pd.DataFrame({"series": name, "origin": idx[o_pos], "grain": np.array(list(GRAINS))[g], "horizon": h,
                         "L": L, "period_start": pstart, "period_end": pstart + pd.to_timedelta(L, unit="D"),
                         "actual": actual, "base": base})
    out = pd.concat([meta, rows.replace([np.inf, -np.inf], np.nan)], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["y"] = np.log(out["actual"] / out["base"]) if kind != "event" else out["actual"]
    return out


META = ("series", "origin", "grain", "horizon", "L", "period_start", "period_end", "actual", "base", "y")


def feats(df: pd.DataFrame) -> list[str]:
    # the feature columns of a row table (events have no lag features, so lists differ by series)
    return [c for c in df.columns if c not in META]


ROWS = {}
for name, kind in SERIES.items():
    lvl = SER[name]["level"]
    first = DAILY[name].first_valid_index() + pd.Timedelta(days=365 if kind != "milk" else 60)
    ok_dates = panel.index[(panel.index >= first) & lvl.notna().values & (lvl.values > 0 if kind != "event" else True)]
    origins = ok_dates[::ORIGIN_STEP[kind]]
    r = expand(name, origins)
    r = r[np.isfinite(r["y"]) & (r["base"] > 0)].reset_index(drop=True)
    ROWS[name] = r
    print(f"{name:15s} {kind:5s}: {r['origin'].nunique():5,} forecast dates, {len(r):8,} rows, {len(feats(r))} features "
          f"({r['origin'].min():%Y-%m-%d} .. {r['origin'].max():%Y-%m-%d})")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 4. Train / test split (80:20 per series, chronological)

For each series the first 80 % of its forecast dates train and the last 20 % test. Training
rows whose target period ends after the split date are removed (purge), so no training row has
seen a test-period value.
""")

code(r"""
SPLIT, TRAIN, TEST = {}, {}, {}
for name, r in ROWS.items():
    o = np.sort(r["origin"].unique())
    SPLIT[name] = pd.Timestamp(o[int(len(o) * (1 - TEST_SHARE))])
    TRAIN[name] = r[(r["origin"] < SPLIT[name]) & (r["period_end"] <= SPLIT[name])].reset_index(drop=True)
    TEST[name] = r[r["origin"] >= SPLIT[name]].reset_index(drop=True)
display(pd.DataFrame({"split_date": {k: f"{v:%Y-%m-%d}" for k, v in SPLIT.items()},
                      "train_rows": {k: len(v) for k, v in TRAIN.items()},
                      "test_rows": {k: len(v) for k, v in TEST.items()},
                      "test_from": {k: f"{v['origin'].min():%Y-%m-%d}" for k, v in TEST.items()},
                      "test_to": {k: f"{v['period_end'].max():%Y-%m-%d}" for k, v in TEST.items()}}))
""")

# --------------------------------------------------------------------------------------
md(r"""
## 5. Models, hyper-parameter tuning and training

| Model | What it is |
|---|---|
| `persistence` (milk, stocks) | the level on the forecast date carried forward |
| `rate_365` / `rate_91` (events) | trailing 365- / 91-day rate × period length |
| `ridge` (milk, stocks) | linear model, median impute + missing flags + scaling, α = 10 |
| `lgbm_14` | LightGBM with the pfoi-1.4 settings |
| `lgbm_tuned` | LightGBM with the settings chosen by the search below |

**Search.** `N_TRIALS` random settings from `SEARCH_SPACE`, plus the 1.4 settings, are scored by
`CV_FOLDS` purged expanding time-series folds inside the training 80 % (the first 40 % of
training dates always train). Loss: mean absolute log error for milk and stocks; mean Poisson
deviance for events. The setting with the lowest mean fold loss is refitted on the whole
training 80 %. Training rows are weighted by recency (half-life 730 days). Out-of-fold errors of
the chosen setting give the 80 % forecast range.
""")

code(r"""
def recency(dates: pd.Series, half_life: float = 730.0) -> np.ndarray:
    age = (dates.max() - dates).dt.days.clip(lower=0).to_numpy()
    return 0.5 ** (age / half_life)


def lgbm(kind: str, params: dict) -> lgb.LGBMRegressor:
    p = {k: v for k, v in params.items() if k != "loss"}
    obj = "poisson" if kind == "event" else {"l2": "regression", "l1": "regression_l1", "huber": "huber"}[params.get("loss", "l2")]
    return lgb.LGBMRegressor(objective=obj, random_state=SEED, verbose=-1, **p)


def fit(kind: str, params: dict, tr: pd.DataFrame) -> lgb.LGBMRegressor:
    m = lgbm(kind, params)
    kw = {"sample_weight": recency(tr["period_end"])}
    if kind == "event":
        kw["init_score"] = np.log(np.clip(tr["base"].to_numpy(), 1e-3, None))
    m.fit(tr[feats(tr)], tr["y"], **kw)
    return m


def predict(kind: str, m, df: pd.DataFrame) -> np.ndarray:
    # forecast on the original scale: litres / head per day (milk, stocks), count (events)
    X = df[feats(df)]
    raw = m.predict(X, raw_score=True) if kind == "event" else m.predict(X)
    if kind == "event":
        return np.exp(raw + np.log(np.clip(df["base"].to_numpy(), 1e-3, None)))
    return df["base"].to_numpy() * np.exp(raw)


def loss(kind: str, df: pd.DataFrame, pred: np.ndarray) -> float:
    a = df["actual"].to_numpy()
    if kind == "event":
        pred = np.clip(pred, 1e-9, None)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(a > 0, a * np.log(a / pred), 0.0)
        return float(np.mean(2 * (t - (a - pred))))
    return float(np.mean(np.abs(np.log(pred / a))))


def folds(tr: pd.DataFrame):
    o = np.sort(tr["origin"].unique())
    edges = np.linspace(0.4, 1.0, CV_FOLDS + 1)
    for k in range(CV_FOLDS):
        cut = pd.Timestamp(o[int(len(o) * edges[k])])
        end = pd.Timestamp(o[min(int(len(o) * edges[k + 1]), len(o) - 1)])
        a = tr[(tr["origin"] < cut) & (tr["period_end"] <= cut)]
        b = tr[(tr["origin"] >= cut) & (tr["origin"] < end)]
        if len(a) >= 500 and len(b) >= 100:
            yield a, b


def sample_params(kind: str) -> dict:
    p = {k: v[RNG.integers(len(v))] for k, v in SEARCH_SPACE.items()}
    p["subsample_freq"] = 1
    if kind == "event":
        p.pop("loss")
    return p


def make_ridge():
    # quantile scaling keeps a few extreme engineered values from dominating the linear fit
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                         QuantileTransformer(n_quantiles=200, output_distribution="normal", subsample=100_000,
                                             random_state=SEED), Ridge(alpha=10.0))


def tune(name: str, kind: str, tr: pd.DataFrame, n_trials: int):
    # random search scored by purged time-series CV inside tr; returns settings, trial table, out-of-fold errors
    base = dict(LGBM_14) | ({"loss": "l2"} if kind != "event" else {})
    fl = list(folds(tr))
    if not fl:
        print(f"{name}: not enough training rows for time-series CV; using the 1.4 settings")
        return base, pd.DataFrame(), None
    cands = [base] + [sample_params(kind) for _ in range(n_trials)]
    res, best_oof = [], None
    t0 = time.time()
    for i, prm in enumerate(cands):
        ls, oof = [], []
        for a, b in fl:
            pr = predict(kind, fit(kind, prm, a), b)
            ls.append(loss(kind, b, pr))
            oof.append(pd.DataFrame({"grain": b["grain"].values,
                                     "ratio": np.log(np.clip(b["actual"].values, 1e-9, None) / np.clip(pr, 1e-9, None))}))
        res.append({"trial": "1.4 default" if i == 0 else f"random {i}", "cv_loss": float(np.mean(ls)), "_i": i, **prm})
        if i == 0 or res[-1]["cv_loss"] < min(r_["cv_loss"] for r_ in res[:-1]):
            best_oof = pd.concat(oof)
    t = pd.DataFrame(res).sort_values("cv_loss").reset_index(drop=True)
    best = t.iloc[0]
    d14 = t.loc[t["trial"] == "1.4 default", "cv_loss"].iloc[0]
    print(f"{name:15s}: {len(cands)} settings x {len(fl)} folds in {time.time() - t0:5.0f} s; "
          f"best {best['trial']} cv_loss {best['cv_loss']:.4f} (1.4 default {d14:.4f})")
    return dict(cands[int(best["_i"])]), t.drop(columns="_i"), best_oof


def train_models(kind: str, params: dict, tr: pd.DataFrame) -> dict:
    m = {"lgbm_tuned": fit(kind, params, tr), "lgbm_14": fit(kind, dict(LGBM_14), tr)}
    if kind != "event":
        m["ridge"] = make_ridge().fit(tr[feats(tr)], tr["y"], ridge__sample_weight=recency(tr["period_end"]))
    return m


TUNED, TRIALS, OOF, MODELS = {}, {}, {}, {}
t_all = time.time()
for name, kind in SERIES.items():
    TUNED[name], TRIALS[name], OOF[name] = tune(name, kind, TRAIN[name], N_TRIALS)
    MODELS[name] = train_models(kind, TUNED[name], TRAIN[name])
print(f"tuning and training: {time.time() - t_all:.0f} s")
print("\nChosen settings per series:")
display(pd.DataFrame(TUNED).T)
""")

code(r"""
# the five best settings of each series (lower cv_loss = better; compare with '1.4 default')
for name, t in TRIALS.items():
    print(f"\n{name}"); display(t.head(5).round(4))
""")

# --------------------------------------------------------------------------------------
md(r"""
## 6. Testing and evaluation (held-out 20 %, scored horizons only)

* **Milk and stocks:** share within ±10 % (target ≥ 85 %), accuracy = 1 − WAPE, bias, and skill
  against persistence (1 − MAE / MAE of persistence; > 0 = better).
* **Events:** counts are small, so ±10 % is not meaningful; accuracy = 1 − WAPE, mean absolute
  error and skill against the trailing 365-day rate.
""")

code(r"""
def test_predictions(name: str, te: pd.DataFrame = None, models: dict = None) -> pd.DataFrame:
    kind = SERIES[name]
    te = TEST[name] if te is None else te
    models = MODELS[name] if models is None else models
    out = te[["origin", "grain", "horizon", "L", "period_start", "period_end", "actual", "base"]].copy()
    out["lgbm_tuned"] = predict(kind, models["lgbm_tuned"], te)
    out["lgbm_14"] = predict(kind, models["lgbm_14"], te)
    if kind == "event":
        out["rate_365"] = te["base"].values
        out["rate_91"] = te["own_mean_91"].values * te["L"].values
    else:
        out["persistence"] = te["base"].values
        out["ridge"] = te["base"].values * np.exp(models["ridge"].predict(te[feats(te)]))
    return out


def scores(name: str, df: pd.DataFrame) -> pd.DataFrame:
    kind = SERIES[name]
    base = "rate_365" if kind == "event" else "persistence"
    models = ([base, "rate_91"] if kind == "event" else [base, "ridge"]) + ["lgbm_14", "lgbm_tuned"]
    keep = [(g, h) for g, (_, _, hs) in GRAINS.items() for h in hs]
    rows = []
    for (g, h), d in df.groupby(["grain", "horizon"]):
        if (g, h) not in keep:
            continue
        a = d["actual"].to_numpy()
        bmae = np.mean(np.abs(d[base].to_numpy() - a))
        for m in models:
            e = d[m].to_numpy() - a
            rows.append({"series": name, "grain": g, "horizon": h, "model": m, "n": len(d),
                         "within_10pct": np.mean(np.abs(e / a) <= TOLERANCE) if kind != "event" else np.nan,
                         "accuracy_1_wape": 1 - np.abs(e).sum() / max(np.abs(a).sum(), 1e-9),
                         "mae": np.mean(np.abs(e)), "bias_pct": e.sum() / max(a.sum(), 1e-9),
                         "skill": 1 - np.mean(np.abs(e)) / bmae if bmae > 0 else np.nan})
    return pd.DataFrame(rows)


PRED = {n: test_predictions(n) for n in SERIES}
SC = pd.concat([scores(n, PRED[n]) for n in SERIES], ignore_index=True)
order = {g: i for i, g in enumerate(GRAINS)}
for name, kind in SERIES.items():
    s = SC[SC["series"] == name].copy()
    s["col"] = s["grain"].str[0] + s["horizon"].astype(str)
    s = s.sort_values(["grain", "horizon"], key=lambda c: c.map(order) if c.name == "grain" else c)
    cols = list(dict.fromkeys(s["col"]))
    metric = "within_10pct" if kind != "event" else "accuracy_1_wape"
    print(f"\n{name} ({kind}), test from {SPLIT[name]:%Y-%m-%d}: "
          + ("share within ±10 %, %" if kind != "event" else "accuracy 1 - WAPE, %") + " (d = day, w = week, m = month ahead)")
    display((s.pivot(index="model", columns="col", values=metric)[cols] * 100).round(1))
    print("skill against " + ("persistence" if kind != "event" else "the 365-day rate") + " (> 0 = better)")
    display(s.pivot(index="model", columns="col", values="skill")[cols].round(3))
""")

code(r"""
# what tuning added: lgbm_tuned minus lgbm_14, mean over the scored horizons of each grain
d = SC[SC["model"].isin(["lgbm_14", "lgbm_tuned"])].pivot_table(index=["series", "grain"], columns="model",
                                                                  values=["skill", "within_10pct"], aggfunc="mean")
gain = pd.DataFrame({"skill_14": d[("skill", "lgbm_14")], "skill_tuned": d[("skill", "lgbm_tuned")],
                     "within10_14": d[("within_10pct", "lgbm_14")], "within10_tuned": d[("within_10pct", "lgbm_tuned")]})
gain["skill_gain"] = gain["skill_tuned"] - gain["skill_14"]
display(gain.round(3))
""")

# --------------------------------------------------------------------------------------
md(r"""
### 6b. Forecasts on unseen test data vs what was recorded (page style)

One figure per test forecast date, like the PFOI compare charts: 30-day blocks, two years of
recorded history, the recorded outcome after the forecast date (dots, never seen by the model),
the tuned model (dashed) with its 80 % range, and the benchmark (grey dashed). The models are the
ones trained on the training 80 % only.
""")

code(r"""
PANELS = [("herd_milk", "Herd milk (L / 30 days)", 30), ("milking", "Milking cows (daily avg)", 1),
          ("n_herd", "Total herd (daily avg)", 1), ("calvings", "Calvings / 30 days", 1),
          ("real_abortions", "Abortions / 30 days", 1)]


def blocks_back(s: pd.Series, o: pd.Timestamp, n: int, how: str) -> pd.Series:
    vals, dates = [], []
    for k in range(n, 0, -1):
        a, b = o - pd.Timedelta(days=30 * k), o - pd.Timedelta(days=30 * (k - 1))
        part = s.loc[a: b - pd.Timedelta(days=1)]
        ok = part.notna().sum() >= (24 if how == "mean" else 30)
        vals.append((part.mean() if how == "mean" else part.sum()) if ok else np.nan)
        dates.append(a)
    return pd.Series(vals, index=pd.DatetimeIndex(dates))


def range_q(name: str, oof: dict = None) -> pd.Series:
    o = (OOF if oof is None else oof).get(name)
    if o is None or SERIES[name] == "event":
        return None
    return o[o["grain"] == "month"]["ratio"].quantile([0.10, 0.90])


def pick_dates(test: dict, wanted=None) -> list:
    if wanted:
        return list(pd.DatetimeIndex(wanted))
    common = set(test["milking"]["origin"]) & set(test["calvings"]["origin"])
    if len(test.get("herd_milk", [])):
        common &= set(test["herd_milk"]["origin"])
    cand = sorted(common) if common else sorted(test["milking"]["origin"].unique())
    ok = [d for d in cand if DAILY["herd_milk"].loc[d: d + pd.Timedelta(days=179)].notna().sum() >= 120]
    pool = ok or cand
    return [pool[i] for i in sorted({0, len(pool) // 2, len(pool) - 1})] if pool else []


def draw_page(o: pd.Timestamp, models: dict, oof: dict, tag: str, title_note: str) -> None:
    fig, axes = plt.subplots(len(PANELS), 1, figsize=(11, 2.6 * len(PANELS)), sharex=True)
    for ax, (name, title, scale) in zip(axes, PANELS):
        kind = SERIES[name]
        sc = scale if kind != "event" else 1
        hist = blocks_back(DAILY[name], o, 24, "sum" if kind == "event" else "mean") * sc
        ax.plot(hist.index, hist.values, color="#3b3b3b", lw=1.2, label="Recorded")
        fr = expand(name, [o])
        fr = fr[fr["grain"] == "month"].reset_index(drop=True)
        if name not in models or not len(fr) or not np.isfinite(fr["base"]).all() or (fr["base"] <= 0).all():
            ax.set_title(f"{title}: no forecast at this date", loc="left", fontsize=10)
            continue
        f = predict(kind, models[name]["lgbm_tuned"], fr) * sc
        x = pd.DatetimeIndex(fr["period_start"])
        if kind == "event":
            lo, hi = poisson.ppf(0.10, f), poisson.ppf(0.90, f)
        else:
            q = range_q(name, oof)
            lo, hi = (f * np.exp(q.iloc[0]), f * np.exp(q.iloc[1])) if q is not None else (None, None)
        if lo is not None:
            ax.fill_between(x, lo, hi, color="#9fb4c7", alpha=0.3, lw=0, label="80 % range")
        ax.plot(x, fr["base"].to_numpy() * sc, ls="--", color="#a0a0a0", lw=1.2, label="benchmark (persistence / 365-day rate)")
        ax.plot(x, f, ls="--", color="#b8572a", lw=1.7, label=f"{MODEL_VERSION} (tuned LightGBM)")
        ax.plot(x, fr["actual"].to_numpy() * sc, marker="o", mfc="white", color="#3b3b3b", lw=0.8, ms=4,
                label="Recorded outcome (not seen by the model)")
        ax.axvline(o, color="#4a6fa5", ls=":", lw=1)
        ax.set_title(title, loc="left", fontsize=10)
    axes[0].legend(fontsize=7, loc="upper left", ncol=2)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.suptitle(f"Forecast date {o:%Y-%m-%d}: {MODEL_VERSION} {title_note} (herd level; 80 % ranges)"
                 + ("  [SYNTHETIC DEMO]" if USE_SYNTHETIC else ""), fontsize=11)
    plt.tight_layout()
    fig.savefig(CHART_DIR / f"nb04_{tag}_{o:%Y%m%d}{'_demo' if USE_SYNTHETIC else ''}.png", dpi=130)
    plt.show()


dates_ = pick_dates(TEST, CHART_DATES)
for o in dates_:
    draw_page(o, MODELS, OOF, "test", "on unseen data")
print("chart dates:", ", ".join(f"{d:%Y-%m-%d}" for d in dates_), f"| saved to {CHART_DIR}")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 7. Explainability

TreeSHAP of each tuned model (`pred_contrib=True`), summed into feature groups: the parts add
up exactly to the model output (checked; for events, to the change from the 365-day rate on
the log scale). The table shows each group's share of the mean absolute contribution on the
test rows: what the model leans on for each series.
""")

code(r"""
def group_of(f: str) -> str:
    for pre, g in (("own_", "own history"), ("st_", "herd stocks"), ("pipe_", "pregnancy pipeline"),
                   ("per_ai", "pregnancy pipeline"), ("ev_", "event rates"), ("mix_", "lactation mix"),
                   ("wx_", "heat / weather"), ("hl_", "health / sensors"), ("q_", "record quality"),
                   ("per_last_year", "same period last year"), ("per_", "period / season")):
        if f.startswith(pre):
            return g
    return "other"


shap_rows = {}
for name, kind in SERIES.items():
    te = TEST[name]
    smp = te.sample(min(10000, len(te)), random_state=SEED)
    m = MODELS[name]["lgbm_tuned"]
    F_ = feats(smp)
    c = m.predict(smp[F_], pred_contrib=True)
    raw = m.predict(smp[F_], raw_score=True)
    assert np.allclose(c.sum(axis=1), raw, atol=1e-6), f"{name}: SHAP parts do not add up"
    a = pd.Series(np.abs(c[:, :-1]).mean(axis=0), index=F_)
    g = a.groupby(a.index.map(group_of)).sum()
    shap_rows[name] = g / g.sum()
SHAP = pd.DataFrame(shap_rows).fillna(0)
print("Additivity check passed for every series. Share of mean |SHAP| by feature group:")
display(SHAP.round(3))
fig, ax = plt.subplots(figsize=(12, 4.5))
im = ax.imshow(SHAP.values, aspect="auto", cmap="Blues")
ax.set_xticks(range(SHAP.shape[1])); ax.set_xticklabels(SHAP.columns, rotation=30, ha="right")
ax.set_yticks(range(SHAP.shape[0])); ax.set_yticklabels(SHAP.index)
for i in range(SHAP.shape[0]):
    for j in range(SHAP.shape[1]):
        ax.text(j, i, f"{SHAP.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
ax.set_title("What each tuned model leans on (share of mean |SHAP|)"); plt.colorbar(im); plt.tight_layout(); plt.show()
""")

# --------------------------------------------------------------------------------------
md(r"""
## 7b. Period tests: 2019–2021 and 2022–2026

Two fixed test windows (`PERIODS` in §0). For each window, every series is re-tuned and trained
**only on rows whose target period ended before the window starts**: up to 2018 for 2019–2021,
up to 2021 for 2022–2026. It is then scored on forecast dates inside the window whose targets
also end inside it. The §5 settings are not reused (that search saw these years). The row
counts show where a series has nothing to score: clean milk is missing for most of 2022–2025
(too few recorded cows), so milk in 2022–2026 is scored on the days that exist; herd and event
series cover every year.
""")

code(r"""
PRES = {}
for pname, (train_end, t_from, t_to) in PERIODS.items():
    P_END, P0, P1 = pd.Timestamp(train_end), pd.Timestamp(t_from), pd.Timestamp(t_to)
    res = {"models": {}, "oof": {}, "test": {}, "pred": {}, "counts": []}
    t0 = time.time()
    print(f"\n=== {pname}: train on targets ending by {P_END:%Y-%m-%d}, test {P0:%Y-%m-%d} .. {P1:%Y-%m-%d}")
    for name, kind in SERIES.items():
        r = ROWS[name]
        tr = r[(r["origin"] < P_END) & (r["period_end"] <= P_END)].reset_index(drop=True)
        te = r[(r["origin"] >= P0) & (r["origin"] < P1) & (r["period_end"] <= P1)].reset_index(drop=True)
        res["counts"].append({"series": name, "train_rows": len(tr), "test_rows": len(te),
                              "test_years": ", ".join(str(y) for y in sorted(te["origin"].dt.year.unique()))})
        if len(tr) < 2000 or not len(te):
            print(f"{name:15s}: skipped ({len(tr):,} training rows, {len(te):,} test rows)")
            continue
        params, _, res["oof"][name] = tune(name, kind, tr, N_TRIALS_PERIOD)
        res["models"][name] = train_models(kind, params, tr)
        res["test"][name] = te
        res["pred"][name] = test_predictions(name, te, res["models"][name])
    res["sc"] = pd.concat([scores(n, res["pred"][n]) for n in res["pred"]], ignore_index=True) if res["pred"] else pd.DataFrame()
    PRES[pname] = res
    print(f"{pname} trained in {time.time() - t0:.0f} s")
    display(pd.DataFrame(res["counts"]).set_index("series"))
""")

code(r"""
def period_summary(res: dict) -> pd.DataFrame:
    rows = []
    for name in res["pred"]:
        kind = SERIES[name]; base = "rate_365" if kind == "event" else "persistence"
        row = {"series": name, "test_rows": len(res["test"][name])}
        for g, (_, _, hs) in GRAINS.items():
            s_ = res["sc"][(res["sc"]["series"] == name) & (res["sc"]["grain"] == g) & res["sc"]["horizon"].isin(hs)]
            if kind == "event":
                row[f"{g}_acc"] = s_.loc[s_["model"] == "lgbm_tuned", "accuracy_1_wape"].mean()
            else:
                row[f"{g}_within10"] = s_.loc[s_["model"] == "lgbm_tuned", "within_10pct"].mean()
                row[f"{g}_within10_bench"] = s_.loc[s_["model"] == base, "within_10pct"].mean()
            row[f"{g}_skill"] = s_.loc[s_["model"] == "lgbm_tuned", "skill"].mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("series") if rows else pd.DataFrame()


for pname, res in PRES.items():
    print(f"\n{pname}: tuned LightGBM, mean over the scored horizons (milk and stocks: share within ±10 %; "
          "events: accuracy 1 - WAPE; skill > 0 = better than the benchmark)")
    display(period_summary(res).round(3))
    for name, kind in SERIES.items():
        if name not in res["pred"] or kind == "event":
            continue
        s_ = res["sc"][res["sc"]["series"] == name].copy()
        s_["col"] = s_["grain"].str[0] + s_["horizon"].astype(str)
        cols = [f"{g[0]}{h}" for g, (_, _, hs) in GRAINS.items() for h in hs if f"{g[0]}{h}" in set(s_["col"])]
        print(f"{name}: share within ±10 %, % ({pname})")
        display((s_.pivot(index="model", columns="col", values="within_10pct")[cols] * 100).round(1))
""")

code(r"""
# page-style charts per window: the model trained only on the years before the window
for pname, res in PRES.items():
    if not {"milking", "calvings"} <= set(res["test"]):
        print(f"{pname}: no charts (herd series missing)"); continue
    tests = dict(res["test"])
    tests.setdefault("herd_milk", tests["milking"].iloc[0:0])
    for o in pick_dates(tests, None):
        draw_page(o, res["models"], res["oof"], f"period_{pname}", f"trained before {pname}")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 8. Prediction from the latest data

Each tuned model is refitted on every row with a known outcome (train + test) and forecasts from
the day after the last day in the data: daily (1–30 days), weekly (1–13) and monthly (1–6).
Milk is withheld if there is no recent clean level. Exported in the `c1_output.outlook` row
shape to `logs/pfoi/notebook_ml/forecast_direct_<date>.json`.
""")

code(r"""
origin = panel.index.max() + pd.Timedelta(days=1)
panel = panel.reindex(pd.date_range(panel.index.min(), origin, freq="D"))
for k in list(DAILY):
    DAILY[k] = DAILY[k].reindex(panel.index)
build_all()
quality = lambda d: "high" if d <= 7 else ("moderate" if d <= 30 else "limited")
out_rows, latest = [], []
for name, kind in SERIES.items():
    fr = expand(name, [origin])
    if not np.isfinite(fr["base"]).all() or (fr["base"] <= 0).all():
        print(f"{name}: no recent level on {origin:%Y-%m-%d}; forecast withheld")
        continue
    m = fit(kind, TUNED[name], ROWS[name])
    f = predict(kind, m, fr)
    q = range_q(name)
    if kind == "event":
        lo, hi = poisson.ppf(0.10, f), poisson.ppf(0.90, f)
    else:
        lo, hi = (f * np.exp(q.iloc[0]), f * np.exp(q.iloc[1])) if q is not None else (f, f)
    for i in range(len(fr)):
        out_rows.append({"origin_date": f"{origin:%Y-%m-%d}", "target_period": f"{fr['period_start'].iloc[i]:%Y-%m-%d}",
                         "grain": fr["grain"].iloc[i], "horizon": int(fr["horizon"].iloc[i]), "series": name,
                         "forecast": round(float(f[i]), 2), "lower": round(float(lo[i]), 2), "upper": round(float(hi[i]), 2),
                         "quality_flag": quality(int(fr["per_lead_days"].iloc[i]) + int(fr["L"].iloc[i])),
                         "unit": ("count per period" if kind == "event" else "per day (period mean)"),
                         "model_version": MODEL_VERSION, "core_version": INPUT_SCHEMA})
    mo = fr["grain"] == "month"
    latest.append(pd.Series(f[mo.values], index=[f"month {h}" for h in fr.loc[mo, "horizon"]], name=name))
print(f"forecast date {origin:%Y-%m-%d} (source = {SOURCE}); monthly blocks: milk and stocks per day, events per 30 days")
display(pd.DataFrame(latest).round(2))
""")

# --------------------------------------------------------------------------------------
md(r"""
## 9. Summary against the targets

Printed from §6. Frontend readiness (fixed rule): for herd milk and litres per cow, the mean
share within ±10 % over the scored daily horizons (1, 7, 14, 30 days) **and** over weeks 1 and 4
must each be ≥ 85 %, with positive skill against persistence.
""")

code(r"""
def mean_of(name, model, grain, hs, col):
    s = SC[(SC["series"] == name) & (SC["model"] == model) & (SC["grain"] == grain) & SC["horizon"].isin(hs)]
    return s[col].mean() if len(s) else np.nan


lines = [f"{MODEL_VERSION} (tuned LightGBM per series) | source = {SOURCE}", ""]
ready = {}
for name, kind in SERIES.items():
    base = "rate_365" if kind == "event" else "persistence"
    parts = []
    for g, (_, _, hs) in GRAINS.items():
        sk = mean_of(name, "lgbm_tuned", g, hs, "skill")
        if kind == "event":
            parts.append(f"{g} acc {mean_of(name, 'lgbm_tuned', g, hs, 'accuracy_1_wape'):.1%} skill {sk:+.2f}")
        else:
            w = mean_of(name, "lgbm_tuned", g, hs, "within_10pct"); wb = mean_of(name, base, g, hs, "within_10pct")
            parts.append(f"{g} ±10 % {w:.1%} (bench {wb:.1%}) skill {sk:+.2f}")
    lines.append(f"{name:15s} test from {SPLIT[name]:%Y-%m-%d}: " + " | ".join(parts))
    if name in ("herd_milk", "milk_per_cow"):
        d = mean_of(name, "lgbm_tuned", "day", GRAINS["day"][2], "within_10pct")
        w = mean_of(name, "lgbm_tuned", "week", [1, 4], "within_10pct")
        sk = min(mean_of(name, "lgbm_tuned", "day", GRAINS["day"][2], "skill"), mean_of(name, "lgbm_tuned", "week", [1, 4], "skill"))
        ready[name] = bool(d >= TARGET_HIT and w >= TARGET_HIT and sk > 0)
lines.append("")
for name, ok in ready.items():
    lines.append(("✅ FRONTEND READY: " if ok else "❌ NOT FRONTEND READY: ") + name +
                 f" (daily 1-30 and weeks 1/4 need ≥ {TARGET_HIT:.0%} within ±10 % and positive skill)")
print("\n".join(lines))

payload = {"source": SOURCE, "model_version": MODEL_VERSION, "frontend_ready": ready,
           "basis": "direct LightGBM per series, tuned by time-series CV; no placeholder or shipped milk; "
                    "pregnancy counts without hindsight", "outlook": out_rows}
stamp = f"{origin:%Y%m%d}" + ("_demo" if USE_SYNTHETIC else "")
(OUT_DIR / f"forecast_direct_{stamp}.json").write_text(json.dumps(payload, indent=1))
SC.assign(source=SOURCE).to_csv(OUT_DIR / f"test_metrics_direct_{stamp}.csv", index=False)
pd.concat([t.assign(series=n) for n, t in TRIALS.items()]).to_csv(OUT_DIR / f"tuning_trials_direct_{stamp}.csv", index=False)
print("written:", *(p.name for p in sorted(OUT_DIR.glob(f"*direct_{stamp}*"))), sep="\n  ")
""")

md(r"""
**Reporting rules.** Quote the numbers as printed, including any ❌. The search space, folds and
thresholds in §0 were fixed before the run and stay fixed; the test 20 % was not used for
tuning. Persistence and trailing rates are benchmarks only and are never blended into the
forecast.
""")


def build(path: Path) -> None:
    nb = {
        "cells": [
            {"cell_type": t, "metadata": {}, "source": s.splitlines(keepends=True),
             **({"execution_count": None, "outputs": []} if t == "code" else {})}
            for t, s in CELLS
        ],
        "metadata": {"kernelspec": {"display_name": "PFOI (.venv)", "language": "python", "name": "pfoi-venv"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    out = HERE / "04_direct_ml_tuned.ipynb"
    build(out)
    print(f"wrote {out} ({len(CELLS)} cells)")
