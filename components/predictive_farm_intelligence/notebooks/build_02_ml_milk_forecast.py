"""Writes notebooks/02_ml_milk_forecast.ipynb (outputs empty).

The notebook is kept as plain cell strings here so it can be reviewed in a diff and
re-generated. Run:  .venv/bin/python components/predictive_farm_intelligence/notebooks/build_02_ml_milk_forecast.py
"""
from __future__ import annotations

import json
from pathlib import Path

CHART_HELPERS = r"""
# charts in the PFOI page style: weekly means, recorded history, recorded outcome after the
# forecast date (not seen by the model), the model's forecast (dashed) and its 80 % range
CHART_DIR = OUT_DIR / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)


def weekly_path(values: pd.Series, origin: pd.Timestamp) -> pd.DataFrame:
    # mean per 7-day block counted from the forecast date (negative blocks = history)
    s = values.dropna()
    k = (s.index - origin).days // 7
    g = s.groupby(k)
    out = pd.DataFrame({"mean": g.mean(), "n": g.count()})
    out.index = origin + pd.to_timedelta(out.index * 7, unit="D")
    return out


def forecast_panel(ax, title, history, outcome, fc, lo, hi, origin, label, color, unit):
    h = weekly_path(history, origin)
    h = h[h["n"] >= 4]
    ax.plot(h.index, h["mean"], color="#3b3b3b", lw=1.2, label="Recorded")
    f = weekly_path(fc, origin)
    if lo is not None:
        band = pd.DataFrame({"lo": weekly_path(lo, origin)["mean"], "hi": weekly_path(hi, origin)["mean"]})
        ax.fill_between(band.index, band["lo"], band["hi"], color="#9fb4c7", alpha=0.3, lw=0, label="80 % range")
    ax.plot(f.index, f["mean"], ls="--", color=color, lw=1.6, label=label)
    a = weekly_path(outcome, origin)
    a = a[a["n"] >= 4]
    ax.plot(a.index, a["mean"], marker="o", mfc="white", color="#3b3b3b", lw=0.8, ms=4,
            label="Recorded outcome (not seen by the model)")
    ax.axvline(origin, color="#4a6fa5", ls=":", lw=1)
    ax.set_title(f"{title} ({unit}, weekly mean)", loc="left", fontsize=10)


def chart_dates(origins, outcome_days: pd.Series, wanted=None, n=3, min_days=56):
    # forecast dates for the charts: the ones asked for, else first / middle / last test date
    # that still has ≥ min_days recorded days in its 90-day outcome window
    o = pd.DatetimeIndex(sorted(pd.unique(origins)))
    if wanted:
        return [d for d in pd.DatetimeIndex(wanted) if d in o]
    ok = [d for d in o if outcome_days.loc[d: d + pd.Timedelta(days=HORIZON_DAYS - 1)].notna().sum() >= min_days]
    if not ok:
        return list(o[[0, len(o) // 2, -1]]) if len(o) else []
    pick = sorted({0, len(ok) // 2, len(ok) - 1})
    return [ok[i] for i in pick][:n]
"""


CELLS: list[tuple[str, str]] = []


def md(s: str) -> None:
    CELLS.append(("markdown", s.strip("\n")))


def code(s: str) -> None:
    CELLS.append(("code", s.strip("\n")))


# --------------------------------------------------------------------------------------
md(r"""
# Farm X: machine-learning milk forecast, 1 to 3 months ahead, daily and weekly (PFOI experiment)

One notebook covers the whole processing chain, in this order:

| § | Step | What it answers |
|---|---|---|
| 0 | Settings | target, horizon, split and pass thresholds, fixed **before** looking at results |
| 1 | Import dataset | which `model_input2` tables and columns are read, and why |
| 2 | Description | coverage by year (where the data gets rich in 2025–2026), level, gaps, season |
| 3 | Feature engineering | what the model knows on the forecast date (no leakage) |
| 4 | Train / test split | chronological 80:20 by forecast date, with a purge gap |
| 5 | ML modelling and training | benchmarks, Ridge, Random Forest, LightGBM, ensemble; time-series CV picks the model |
| 6 | Testing and evaluation | within ±10 % share (target ≥ 85 %), AUC for milk drops (target ≥ 80 %), by month ahead and grain |
| 7 | Explainability | TreeSHAP by factor group; the parts add up to each forecast |
| 8 | Data-richness experiment | does training only on recent (richer) years help? |
| 9 | Prediction | daily and weekly forecast for the next 1–3 months from the latest data, with a range |
| 10 | Summary | pass / fail against the targets, printed from the numbers above |

**Experiment status.** This is a notebook experiment (`pfoi-nb-ml-0.1-dev`). It does not
replace the published model and writes nothing to the database. Results only count if the
thresholds in §0 are met on the held-out 20 %; they are never changed after a run.

**Privacy (AGENTS.md).** Every query aggregates in SQL to one row per day for the whole
herd (`model_input2.day_panel`, `model_input2.day_cell`), so the notebook never sees animal
keys or animal-level rows. The session is read-only. Settings come from the root `.env`
through `pfoi.config.DatabaseSettings`; nothing secret is printed. Exports go to
`logs/pfoi/notebook_ml/` (gitignored). **Clear all outputs before committing.**

`USE_SYNTHETIC = True` runs the whole notebook on fictional data (no database), labelled
`source = "demo"` everywhere.
""")

code(r"""
USE_SYNTHETIC = False        # True = fictional demo data, no database connection

# ---- fixed before any run (do not tune these on test results) ------------------------
INPUT_SCHEMA   = "model_input2"   # the rebuilt inputs (docs/sql/model_input2_from_core.sql)
TARGET         = "per_cow"        # "per_cow" = cleaned litres per recorded cow per day (default);
                                  # "herd_estimate" = clean litres per recorded cow x milking cows
                                  # (docs/model_input2.md §5). Placeholder and shipped milk are never used.
CLEAN_MAX_LITRES  = 18.0          # a day above 18 L per recorded cow is removed (model_input2 already drops records > 18 L)
MIN_RECORDED_COWS = 20            # a day counts only if ≥ 20 cows have a clean record
MODEL_FROM     = None             # e.g. "2026-04-01": model only forecast dates from here (80:20 inside it)
HORIZON_DAYS   = 90               # 1, 2 and 3 months ahead (30-day blocks)
TEST_SHARE     = 0.20             # last 20 % of forecast dates = test
ORIGIN_STEP    = 1                # a forecast date every day (few clean days, so use them all)
TOLERANCE      = 0.10             # "accurate" = within ±10 % of the recorded value
TARGET_HIT     = 0.85             # pass: ≥ 85 % of forecasts within ±10 %
TARGET_AUC     = 0.80             # pass: AUC ≥ 0.80 for the milk-drop warning
CHART_DATES    = None             # forecast dates for the test charts, e.g. ["2021-07-01", "2026-05-01"]; None = automatic
# period tests (§8b): name -> (training targets end before, test from, test to); trained only on earlier years
PERIODS        = {"2019-2021": ("2019-01-01", "2019-01-01", "2022-01-01"),
                  "2022-2026": ("2022-01-01", "2022-01-01", "2027-01-01")}
MONTH_MIN_COVERAGE = 0.80         # a 30-day block is scored if ≥ 80 % of its days are recorded
                                  # (forecast and record averaged over the same days); weeks need all 7
DROP_THRESHOLD = 0.05             # a "drop" = recorded value ≥ 5 % below the last-28-day level
CV_FOLDS       = 3                # time-series CV folds inside the training 80 %
SEED           = 17
MODEL_VERSION  = "pfoi-nb-ml-0.2-dev"
# training windows compared in §8 (all evaluated on the same test rows)
TRAIN_WINDOWS  = {"all history": None, "from 2021": "2021-01-01",
                  "from 2022": "2022-01-01", "from 2025": "2025-01-01"}
MIN_WINDOW_ROWS = 1000            # §8 skips a window with fewer training rows

import sys, json, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score
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
RNG = np.random.default_rng(SEED)

pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
plt.rcParams.update({"figure.figsize": (13, 4.5), "axes.grid": True, "grid.alpha": 0.3,
                     "axes.spines.top": False, "axes.spines.right": False})
COL = {"actual": "#3b3b3b", "persistence_7d": "#a0a0a0", "mean_28d": "#c9b79c",
       "seasonal_naive": "#d9a441", "ridge": "#2a6fdb", "random_forest": "#3aa66a",
       "lightgbm": "#b8572a", "ensemble": "#7b4fb3"}
if USE_SYNTHETIC:
    print("SYNTHETIC DEMO DATA: every number below is fictional (source = 'demo').")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 1. Import dataset

Two herd-level tables from `model_input2` (built from `core` only by
`docs/sql/model_input2_from_core.sql`):

**`day_panel`**: one row per calendar day from 2015-08-01.

| Group | Columns used | Meaning |
|---|---|---|
| target inputs | `milk_observed_cow_litres`, `observed_milking_cows`, `milk_per_recorded_cow`, `is_sparse_day` | identified-cow milk (records ≤ 18 L) and the number of recorded cows; the target is built from these in §1b |
| not used | `target_litres`, `herd_milk_measured`, `is_scoreable`, `data_gap`, `milk_shipped` | they contain placeholder milk or are shipments (AGENTS.md, docs/model_input2.md §5); not loaded |
| herd stocks | `n_herd`, `milking`, `calves`, `bulls` | head counts on the day |
| pregnancy stocks | `dry_open`, `dry_pregnant`, `heifers_open`, `heifers_pregnant` from **`day_cell_known`** | pregnant only once the pregnancy was knowable; `day_panel`'s own columns use hindsight (pregnant from conception) and are replaced |
| events | `calvings`, `dry_offs`, `ais`, `real_abortions`, `deaths`, `culls`, `sales`, `entries` | counts that day |
| record quality | `observed_milking_cows`, `lactating_unrecorded`, `milk_observed_records` | how complete the milk records are |
| placeholder (description only, §2c) | `milk_observed_placeholder_litres`, `milk_record_type`, `herd_milk_measured`, `milk_reassigned_to_unidentified`, `identified_share`, `is_implausible_volume`, `milk_observed_litres` | described in §2c; never a model input or target |
| weather | `thi_mean`, `rain_total_mm`, `weather_is_complete` | heat stress (THI) and rain |
| health / sensors | `mastitis_episodes`, `n_sessions`, `n_blood_alarms`, `n_conductivity_alarms` | recorded health and parlour sensor alarms |

**`day_cell`**: counts per `date × state × parity_group × dim_band`. Only milking cows are
read, aggregated to shares per day: parity mix (1 / 2 / 3+) and lactation stage
(days in milk 0–60 / 61–150 / 151–305 / 305+). Herd level, no animal rows.

### 1b. Data cleaning on the loaded `day_panel`

`model_input2` holds herd totals per day only, so the cleaning works on daily columns of the
dataframe; no other table is read. What `model_input2` already did when it was built:

* cow records above 18 L are dropped from cow milk (`milk_excluded_high_records` /
  `_litres`); on herd-total days that milk is moved to unidentified
  (`milk_reassigned_to_unidentified`);
* placeholder (unidentified, herd-total) milk is kept apart in
  `milk_observed_placeholder_litres`; it is a herd number, not a cow, so the 18 L rule does
  not apply to it;
* each day has a `milk_record_type`: `herd_total` (placeholder present and ≥ 5 L per milking
  cow → `herd_milk_measured`), `cow_sample` (no plausible herd total, ≥ 10 cows → herd milk
  **estimated**, `herd_milk_is_estimated`), `none` (no data);
* herd milk above 18 L per milking cow is `is_implausible_volume` and not scoreable.

What this notebook adds in pandas:

1. **cow milk per day** = `milk_observed_cow_litres` (records ≤ 18 L) on non-sparse days, and
   **recorded cows** = `observed_milking_cows`;
2. **litres per recorded cow** = cow milk / recorded cows, used only on days with ≥
   `MIN_RECORDED_COWS` cows;
3. a day whose litres per recorded cow is still above `CLEAN_MAX_LITRES` = 18 L is removed.
   `model_input2` caps single records, so this catches a cow whose several records of one day
   add up to more than 18 L;
4. placeholder milk is **not** in the per-cow target; §2c describes it.

Litres per recorded cow does not jump when the number of recorded cows changes, which is
what broke run 1. Herd milk for the outlook is derived as litres per cow × milking cows (§9).
""")

code(r"""
PANEL_COLS = ["n_herd", "milking", "dry_open", "dry_pregnant", "heifers_open", "heifers_pregnant",
              "calves", "bulls", "calvings", "dry_offs", "ais", "real_abortions", "deaths", "culls", "sales", "entries",
              "is_sparse_day", "identified_share",
              "observed_milking_cows", "lactating_unrecorded", "milk_observed_records",
              "thi_mean", "hours_thi_above", "rain_total_mm", "weather_is_complete",
              "mastitis_episodes", "n_sessions", "n_blood_alarms", "n_conductivity_alarms",
              # milk columns of model_input2 (herd totals per day)
              "milk_observed_litres", "milk_observed_cow_litres", "milk_observed_placeholder_litres",
              "milk_excluded_high_records", "milk_excluded_high_litres", "milk_reassigned_to_unidentified",
              "milk_record_type", "herd_milk_measured", "herd_milk_is_estimated", "milk_per_recorded_cow",
              "is_implausible_volume"]

PANEL_SQL = f'''
SELECT date, {", ".join(PANEL_COLS)}
FROM {{schema}}.day_panel ORDER BY date
'''

# pregnancy stocks WITHOUT hindsight: day_panel's dry_/heifers_pregnant/open come from day_cell,
# where a cow counts as pregnant from conception (known only later). day_cell_known counts her
# as pregnant only once the pregnancy was knowable, so these replace the day_panel columns.
KNOWN_SQL = '''
SELECT date,
       COALESCE(SUM(n_animals) FILTER (WHERE state = 'dry_pregnant'), 0)::float    AS dry_pregnant,
       COALESCE(SUM(n_animals) FILTER (WHERE state = 'dry_open'), 0)::float        AS dry_open,
       COALESCE(SUM(n_animals) FILTER (WHERE state = 'heifer_pregnant'), 0)::float AS heifers_pregnant,
       COALESCE(SUM(n_animals) FILTER (WHERE state = 'heifer_open'), 0)::float     AS heifers_open
FROM {schema}.day_cell_known
GROUP BY date ORDER BY date
'''
PREGNANCY_COLS = ["dry_pregnant", "dry_open", "heifers_pregnant", "heifers_open"]

# milking-cow composition per day: shares only (herd level)
CELL_SQL = '''
SELECT date,
       SUM(n_animals)::float                                                   AS cells_milking,
       SUM(n_animals) FILTER (WHERE parity_group = '1')::float                AS par_1,
       SUM(n_animals) FILTER (WHERE parity_group = '2')::float                AS par_2,
       SUM(n_animals) FILTER (WHERE parity_group = '3+')::float               AS par_3p,
       SUM(n_animals) FILTER (WHERE dim_band = '0-60')::float                 AS dim_0_60,
       SUM(n_animals) FILTER (WHERE dim_band = '61-150')::float               AS dim_61_150,
       SUM(n_animals) FILTER (WHERE dim_band = '151-305')::float              AS dim_151_305,
       SUM(n_animals) FILTER (WHERE dim_band = '305+')::float                 AS dim_305p
FROM {schema}.day_cell WHERE state = 'milking'
GROUP BY date ORDER BY date
'''

def synthetic_milk_columns(p: pd.DataFrame, dates: pd.DatetimeIndex, milking: np.ndarray,
                            per_cow: np.ndarray, r) -> None:
    # fictional model_input2 milk columns: cow samples 2020-22 and from 2026-04, herd totals 2025-09 .. 2026-06
    n = len(dates)
    rec_share = np.select([(dates >= "2020-01-01") & (dates < "2022-03-01"),
                           (dates >= "2022-03-01") & (dates < "2025-09-01"),
                           (dates >= "2025-09-01") & (dates < "2026-04-01"),
                           dates >= "2026-04-01"], [0.2, 0.01, 0.001, 0.6], 0.0)
    cows = np.round(milking * rec_share * r.uniform(0.7, 1.3, n))
    high = r.binomial(cows.astype(int), 0.03).astype(float)
    cow_l = cows * per_cow
    cow_l[r.random(n) < 0.01] *= 2.2                                       # days with doubled records
    ph = (dates >= "2025-09-01") & (dates < "2026-07-01")
    ph_l = np.where(ph, milking * per_cow * 0.95, np.nan)
    p["observed_milking_cows"] = cows
    p["milk_observed_cow_litres"] = np.where(cows > 0, cow_l, np.nan)
    p["milk_observed_placeholder_litres"] = ph_l
    p["milk_excluded_high_records"] = high
    p["milk_excluded_high_litres"] = high * 24.0
    p["milk_observed_litres"] = np.nansum([p["milk_observed_cow_litres"], ph_l, high * 24.0], axis=0)
    p["milk_observed_records"] = cows + high + ph
    herd_total = ph & (p["milk_observed_litres"] >= 5 * milking)
    sample = ~herd_total & (cows >= 10)
    p["milk_record_type"] = np.where(herd_total, "herd_total", np.where(sample, "cow_sample", "none"))
    p["herd_milk_measured"] = np.where(herd_total, p["milk_observed_litres"], np.nan)
    p["herd_milk_is_estimated"] = sample
    p["milk_per_recorded_cow"] = np.where(cows >= 10, cow_l / np.maximum(cows, 1), np.nan)
    p["milk_reassigned_to_unidentified"] = np.where(herd_total, high * 24.0, np.nan)
    p["identified_share"] = np.where(p["milk_observed_litres"] > 0,
                                     np.nan_to_num(p["milk_observed_cow_litres"]) / p["milk_observed_litres"], np.nan)
    p["target_litres"] = np.where(herd_total, p["herd_milk_measured"],
                                  np.where(sample, p["milk_per_recorded_cow"] * milking, np.nan))
    p["is_implausible_volume"] = p["target_litres"] / milking > 18
    p["is_scoreable"] = ~np.isnan(p["target_litres"]) & ~p["is_implausible_volume"]
    p["data_gap"] = np.isnan(p["target_litres"])


def synthetic_inputs(seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Fictional herd shaped like the real contract: DelPro milk from 2020-08, a thin
    # 2023-24 record period, rich sensor data in 2025-26. For testing the notebook only.
    r = np.random.default_rng(seed)
    dates = pd.date_range("2015-08-01", "2026-09-30", freq="D")
    n = len(dates)
    t = np.arange(n)
    doy = dates.dayofyear.values
    milking = np.clip(170 + np.cumsum(r.normal(0, 0.8, n)) * 0.6 + 20 * np.sin(2 * np.pi * t / 1500), 90, 260)
    per_cow = 8.5 - 0.8 * np.sin(2 * np.pi * (doy - 60) / 365) + r.normal(0, 0.35, n)
    per_cow[(dates >= "2021-06-01") & (dates < "2022-10-01")] -= 1.2       # a yield dip
    litres = milking * per_cow * np.where(dates.weekday == 6, 0.97, 1.0)
    p = pd.DataFrame({"date": dates.date})
    p["milking"] = milking.round()
    p["n_herd"] = (milking * 2.1 + r.normal(0, 5, n)).round()
    p["dry_open"] = (milking * 0.10).round(); p["dry_pregnant"] = (milking * 0.18 + 6 * np.sin(t / 60)).round()
    p["heifers_open"] = (milking * 0.25).round(); p["heifers_pregnant"] = (milking * 0.15).round()
    p["calves"] = (milking * 0.35).round()
    for c, lam in [("calvings", 0.5), ("dry_offs", 0.45), ("ais", 0.8), ("real_abortions", 0.03), ("deaths", 0.05),
                   ("culls", 0.08), ("sales", 0.04), ("entries", 0.4)]:
        p[c] = r.poisson(lam, n)
    has = dates >= "2020-08-01"
    thin = (dates >= "2023-01-01") & (dates < "2025-01-01")
    has = has & ~(thin & (r.random(n) < 0.55))
    has = has & ~((dates >= "2022-03-01") & (dates < "2022-04-15"))      # an outage
    p["target_litres"] = np.where(has, litres, np.nan)
    p["is_scoreable"] = has
    p["data_gap"] = ~has
    p["is_sparse_day"] = False
    p["identified_share"] = np.where(has, np.clip(0.85 + r.normal(0, 0.05, n), 0, 1), np.nan)
    p["observed_milking_cows"] = np.where(has, milking * np.where(thin, 0.5, 0.95), 0).round()
    p["lactating_unrecorded"] = (milking * np.where(thin, 0.4, 0.05)).round()
    p["milk_observed_records"] = p["observed_milking_cows"]
    thi = 74 + 3 * np.sin(2 * np.pi * (doy - 100) / 365) + r.normal(0, 1, n)
    p["thi_mean"] = thi; p["rain_total_mm"] = r.gamma(0.6, 8, n); p["weather_is_complete"] = True
    p["hours_thi_above"] = np.clip((thi - 72) * 3, 0, 24).round()
    p["bulls"] = (milking * 0.02).round()
    p["mastitis_episodes"] = np.where(dates < "2019-01-01", r.poisson(0.3, n), r.poisson(0.02, n))
    rich = dates >= "2025-01-01"
    p["n_sessions"] = np.where(rich, milking * 2, np.where(has, milking * 0.3, 0)).round()
    p["n_blood_alarms"] = np.where(rich, r.poisson(30, n), 0)
    p["n_conductivity_alarms"] = np.where(rich, r.poisson(20, n), 0)
    c = pd.DataFrame({"date": dates.date, "cells_milking": milking})
    share1 = 0.35 + 0.05 * np.sin(t / 400)
    c["par_1"] = milking * share1; c["par_2"] = milking * 0.3; c["par_3p"] = milking * (0.35 - 0.05 * np.sin(t / 400))
    fresh = 0.2 + 0.05 * np.sin(2 * np.pi * (doy - 30) / 365)
    c["dim_0_60"] = milking * fresh; c["dim_61_150"] = milking * 0.3
    c["dim_151_305"] = milking * (0.4 - fresh + 0.2); c["dim_305p"] = milking * 0.1
    synthetic_milk_columns(p, dates, milking, per_cow, r)
    return p, c


if USE_SYNTHETIC:
    panel_raw, cells_raw = synthetic_inputs()
    known_raw = panel_raw[["date"] + PREGNANCY_COLS].copy()
else:
    from sqlalchemy import create_engine, text
    from pfoi.config import DatabaseSettings
    settings = DatabaseSettings.from_env()
    engine = create_engine(settings.url, pool_pre_ping=True,
                           connect_args={"options": "-c default_transaction_read_only=on"})
    with engine.connect() as conn:
        panel_raw = pd.read_sql(text(PANEL_SQL.format(schema=INPUT_SCHEMA)), conn)
        cells_raw = pd.read_sql(text(CELL_SQL.format(schema=INPUT_SCHEMA)), conn)
        known_raw = pd.read_sql(text(KNOWN_SQL.format(schema=INPUT_SCHEMA)), conn)
    engine.dispose()

panel = panel_raw.copy()
panel["date"] = pd.to_datetime(panel["date"])
panel = panel.set_index("date").asfreq("D")            # one row per calendar day
cells = cells_raw.copy()
cells["date"] = pd.to_datetime(cells["date"])
cells = cells.set_index("date").reindex(panel.index)
for c in ["par_1", "par_2", "par_3p", "dim_0_60", "dim_61_150", "dim_151_305", "dim_305p"]:
    panel["share_" + c] = cells[c] / cells["cells_milking"].replace(0, np.nan)
known = known_raw.copy()
known["date"] = pd.to_datetime(known["date"])
known = known.set_index("date").reindex(panel.index)
for c in PREGNANCY_COLS:                               # replace the hindsight pregnancy stocks
    panel[c] = known[c]

# never used here: stored target (contains placeholder milk) and shipments
panel = panel.drop(columns=["target_litres", "is_scoreable", "data_gap", "milk_shipped"], errors="ignore")
for c in ("is_sparse_day", "is_implausible_volume", "herd_milk_is_estimated"):
    panel[c] = panel[c].fillna(False).astype(bool)

# §1b cleaning on the dataframe (daily herd totals)
ok = ~panel["is_sparse_day"]
panel["cows_clean"] = panel["observed_milking_cows"].where(ok, 0).fillna(0)
panel["litres_clean"] = panel["milk_observed_cow_litres"].where(ok)
panel["placeholder_litres"] = panel["milk_observed_placeholder_litres"]
panel["records_removed_gt18"] = panel["milk_excluded_high_records"].fillna(0)
panel["litres_removed_gt18"] = panel["milk_excluded_high_litres"].fillna(0)
panel["clean_per_cow"] = panel["litres_clean"] / panel["cows_clean"].replace(0, np.nan)
panel["enough_cows"] = panel["cows_clean"] >= MIN_RECORDED_COWS
panel["per_cow_over_cap"] = panel["enough_cows"] & (panel["clean_per_cow"] > CLEAN_MAX_LITRES)
panel["clean_day"] = panel["enough_cows"] & ~panel["per_cow_over_cap"]
# the series the model learns; every other day is missing (never 0)
if TARGET == "per_cow":
    panel["y"] = panel["clean_per_cow"].where(panel["clean_day"])
    panel["per_cow"] = panel["y"]
elif TARGET == "herd_estimate":
    panel["per_cow"] = panel["clean_per_cow"].where(panel["clean_day"])
    panel["y"] = panel["per_cow"] * panel["milking"].replace(0, np.nan)
else:
    raise ValueError('TARGET must be "per_cow" or "herd_estimate"')

print(f"day_panel: {len(panel):,} days, {panel.index.min():%Y-%m-%d} .. {panel.index.max():%Y-%m-%d}; "
      f"{panel['y'].notna().sum():,} days with a usable target ({TARGET}).")
print(f"cleaning: {panel['records_removed_gt18'].sum():,.0f} cow records > 18 L dropped by model_input2; "
      f"{panel['enough_cows'].sum():,} days with ≥ {MIN_RECORDED_COWS} recorded cows, of which "
      f"{panel['per_cow_over_cap'].sum():,} removed here (> {CLEAN_MAX_LITRES:g} L per recorded cow) "
      f"-> {panel['clean_day'].sum():,} clean days.")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 2. Dataset description

Aggregates only: per year, how many days carry a usable target, the mean level, milk per
milking cow, how complete the records are and how many sensor sessions and alarms exist.
This shows **where the data gets rich** (the recent DelPro sensor years) and where it is
thin, which matters more for the forecast than the choice of algorithm.
""")

code(r"""
yr = panel.groupby(panel.index.year)
coverage = pd.DataFrame({
    "days": yr.size(),
    "days_with_target": yr["y"].count(),
    "target_share": yr["y"].count() / yr.size(),
    "mean_target_per_day": yr["y"].mean(),
    "mean_milking_cows": yr["milking"].mean(),
    "litres_per_milking_cow": yr["per_cow"].mean(),
    "clean_cows_per_day": yr["cows_clean"].mean(),
    "clean_cows_share_of_milking": (yr["cows_clean"].sum() / yr["milking"].sum().replace(0, np.nan)),
    "clean_litres_per_recorded_cow": (yr["litres_clean"].sum() / yr["cows_clean"].sum().replace(0, np.nan)),
    "sessions_per_day": yr["n_sessions"].mean(),
    "blood_alarms_per_month": yr["n_blood_alarms"].sum() / (yr.size() / 30.4),
    "mastitis_episodes": yr["mastitis_episodes"].sum(),
    "thi_mean": yr["thi_mean"].mean(),
})
coverage.index.name = "year"
display(coverage)

rich = coverage[coverage["target_share"] >= 0.9]
print("Years with a scoreable target on ≥ 90 % of days:", list(rich.index))
print("Year with the most parlour sensor sessions per day:", int(coverage["sessions_per_day"].idxmax()))
first_y = panel["y"].first_valid_index()
print(f"First day with a scoreable target: {first_y:%Y-%m-%d}")
""")

md(r"""
### 2b. Cleaning report

Monthly totals only, from the loaded `day_panel`. `records_removed_gt18` = cow records above
18 L that `model_input2` dropped from cow milk; `days_over_cap` = days with enough recorded
cows whose litres per recorded cow was still above 18 L (removed in §1b).
""")

code(r"""
mo = panel.groupby(panel.index.to_period("M"))
cleaning = pd.DataFrame({
    "valid_records": mo["milk_observed_records"].sum(),
    "records_removed_gt18": mo["records_removed_gt18"].sum(),
    "litres_removed_share": mo["litres_removed_gt18"].sum() / mo["milk_observed_litres"].sum().replace(0, np.nan),
    "recorded_cows_per_day": mo["cows_clean"].mean(),
    "days_with_enough_cows": mo["enough_cows"].sum(),
    "days_over_cap": mo["per_cow_over_cap"].sum(),
    "days_used": mo["clean_day"].sum(),
    "clean_litres_per_cow": mo["litres_clean"].sum() / (panel["cows_clean"].where(panel["litres_clean"].notna())
                                                         .groupby(panel.index.to_period("M")).sum().replace(0, np.nan)),
})
cleaning["removed_share"] = cleaning["records_removed_gt18"] / cleaning["valid_records"].replace(0, np.nan)
cleaning = cleaning[cleaning["valid_records"] > 0]
cleaning.index.name = "month"
display(cleaning.round(3))
tot = cleaning[["valid_records", "records_removed_gt18", "days_over_cap", "days_used"]].sum()
print(f"Total: {tot['records_removed_gt18']:,.0f} of {tot['valid_records']:,.0f} valid records above 18 L "
      f"({tot['records_removed_gt18'] / tot['valid_records']:.2%}); {tot['days_over_cap']:,.0f} days removed for "
      f"> {CLEAN_MAX_LITRES:g} L per recorded cow; {tot['days_used']:,.0f} days used.")
""")

md(r"""
### 2c. Placeholder (unidentified, herd-total) milk

All placeholder milk in the dataset, by year and by month, from the loaded `day_panel`. A
placeholder day becomes measured herd milk only when `milk_record_type = 'herd_total'`
(day total ≥ 5 L per milking cow); otherwise the day falls back to a cow sample (estimated) or
no data. Placeholder milk is described here and is never part of the per-cow target.
""")

code(r"""
def placeholder_table(key) -> pd.DataFrame:
    g = panel.groupby(key)
    has = panel["placeholder_litres"].fillna(0) > 0
    rt = panel["milk_record_type"]
    t = pd.DataFrame({
        "days": g.size(),
        "days_with_placeholder": has.groupby(key).sum(),
        "placeholder_litres": g["placeholder_litres"].sum(),
        "all_recorded_litres": g["milk_observed_litres"].sum(),
        "placeholder_used_as_herd_total": (has & rt.eq("herd_total")).groupby(key).sum(),
        "placeholder_fell_back_to_estimate": (has & rt.eq("cow_sample")).groupby(key).sum(),
        "placeholder_no_data": (has & ~rt.isin(["herd_total", "cow_sample"])).groupby(key).sum(),
        "herd_total_days": rt.eq("herd_total").groupby(key).sum(),
        "estimated_days": panel["herd_milk_is_estimated"].groupby(key).sum(),
        "no_data_days": (~rt.isin(["herd_total", "cow_sample"])).groupby(key).sum(),
        "measured_litres": g["herd_milk_measured"].sum(),
        "reassigned_gt18_litres": g["milk_reassigned_to_unidentified"].sum(),
        "mean_identified_share": g["identified_share"].mean(),
        "herd_total_days_over_18l_per_cow": (rt.eq("herd_total") & panel["is_implausible_volume"]).groupby(key).sum(),
    })
    t["placeholder_share_of_litres"] = t["placeholder_litres"] / t["all_recorded_litres"].replace(0, np.nan)
    t["placeholder_per_milking_cow"] = (panel["placeholder_litres"].where(has) / panel["milking"].replace(0, np.nan)).groupby(key).mean()
    return t


ph_year = placeholder_table(panel.index.year)
ph_year.index.name = "year"
display(ph_year.round(3))
ph_month = placeholder_table(panel.index.to_period("M"))
ph_month.index.name = "month"
ph_month = ph_month[(ph_month["days_with_placeholder"] > 0) | (ph_month["herd_total_days"] > 0)]
display(ph_month.round(3))
any_ph = panel.index[panel["placeholder_litres"].fillna(0) > 0]
if len(any_ph):
    print(f"Placeholder milk on {len(any_ph):,} days, first {any_ph.min():%Y-%m-%d}, last {any_ph.max():%Y-%m-%d}; "
          f"{panel['placeholder_litres'].sum():,.0f} L = {panel['placeholder_litres'].sum() / panel['milk_observed_litres'].sum():.1%} "
          f"of all recorded milk; used as measured herd milk on {int(ph_year['placeholder_used_as_herd_total'].sum()):,} days.")
""")

code(r"""
fig, ax = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
ax[0].plot(panel.index, panel["y"], lw=0.5, color=COL["actual"])
ax[0].plot(panel.index, panel["y"].rolling(28, min_periods=7).mean(), lw=1.5, color=COL["lightgbm"], label="28-day mean")
gap = panel["y"].isna()
ax[0].fill_between(panel.index, 0, 1, where=gap, transform=ax[0].get_xaxis_transform(), color="#cccccc", alpha=0.4, lw=0, label="no scoreable record")
ax[0].set_title(f"{TARGET}: recorded per day (grey = missing)"); ax[0].legend(loc="upper left")
ax[1].plot(panel.index, panel["milking"], lw=1, color="#2a6fdb", label="milking cows")
ax[1].plot(panel.index, panel["cows_clean"], lw=0.6, color="#3aa66a", label="cows with a clean milk record")
ax[1].axhline(MIN_RECORDED_COWS, color="#c00", lw=0.8, ls="--", label=f"minimum {MIN_RECORDED_COWS} cows")
ax[1].legend(loc="upper left"); ax[1].set_title("Herd size vs cows actually recorded")
ax[2].plot(panel.index, panel["clean_per_cow"].rolling(28, min_periods=7).mean(), color="#b8572a", label="clean litres per recorded cow")
ax[2].axhline(CLEAN_MAX_LITRES, color="#c00", lw=0.8, ls="--")
ax[2].set_title("Litres per cow (28-day mean)"); ax[2].legend(loc="upper left")
ax[2].xaxis.set_major_locator(mdates.YearLocator())
plt.tight_layout(); plt.show()

# season: mean by calendar month relative to each year's mean (only years with ≥ 30 % coverage)
ok_years = coverage.index[coverage["target_share"] >= 0.3]
s = panel.loc[panel.index.year.isin(ok_years), "y"]
seasonal = (s.groupby([s.index.year, s.index.month]).mean().unstack()
              .div(s.groupby(s.index.year).mean(), axis=0))
fig, ax = plt.subplots(figsize=(13, 3.5))
for y_, row in seasonal.iterrows():
    ax.plot(range(1, 13), row.values, marker="o", lw=1, label=str(y_))
ax.axhline(1, color="#888", lw=0.8); ax.set_xticks(range(1, 13))
ax.set_title("Season: month mean / year mean"); ax.legend(ncol=8, fontsize=8)
plt.show()
""")

md(r"""
**What to read here (write the interpretation after the run, from the table above):**
which years have a target on most days; whether 2023–2024 are thin (few cows recorded,
`observed_cows_share` low); whether 2025–2026 have many more sensor sessions; whether
litres per cow moves in steps (regime changes) rather than smoothly. These patterns set the
ceiling for any model: a forecast cannot learn a level change it has never seen.
""")

# --------------------------------------------------------------------------------------
md(r"""
## 3. Feature engineering

**Direct multi-horizon design.** For each forecast date *o* (the origin) and each lead
*h* = 1 … 90 the model predicts day *o + h − 1*. Every feature uses only days **before**
*o* (the series is shifted by one day before any window), so nothing from the forecast
period leaks in. One model covers all 90 leads; `lead` is a feature.

**Target.** `log(actual / level_7d)`: the change from the mean of the last 7 recorded days.
The forecast in litres is `level_7d × exp(prediction)`. Predicting a ratio instead of litres
keeps the model valid when the herd size moves to a level it never saw in training.

| Group | Features |
|---|---|
| recent level | 7/28/91/365-day means; log ratios 7/28, 28/91, 91/365 (momentum) |
| yield per cow | with `TARGET = "per_cow"` the recent-level features *are* yield per cow (no duplicates); with the herd target: litres per milking cow over 7 / 28 days and change vs 91 days |
| herd stocks | milking, total herd, dry (pregnant / open), pregnant heifers, calves on the day before; 28- and 91-day change |
| pipeline | pregnant dry cows and heifers per milking cow (cows about to calve = future fresh cows) |
| events | calvings, dry-offs, exits (deaths + culls + sales), entries over 30 and 91 days |
| lactation mix | parity shares (1 / 2 / 3+) and days-in-milk shares of milking cows |
| weather | THI mean over 7 and 28 days, rain over 28 days (past only, no weather forecast) |
| health / sensors | mastitis episodes 91 days, blood and conductivity alarms per session 28 days |
| record quality | share of usable days in 28 days, days since the last gap, clean recorded cows (count and share of milking), share of cow-days removed by the 18 L rule |
| season | target day of year (sin / cos), target weekday, lead; last year's change over the same window |
""")

code(r"""
def roll_mean(s, w):
    return s.rolling(w, min_periods=max(2, w // 4)).mean()


def roll_sum(s, w):
    return s.rolling(w, min_periods=1).sum()


def safe_log_ratio(a, b):
    return np.log(a / b).replace([np.inf, -np.inf], np.nan)


def origin_features(p: pd.DataFrame) -> pd.DataFrame:
    # One row per origin date o; every column uses days < o only.
    past = p.shift(1)                     # value on o-1 sits on row o
    y = past["y"]
    F = pd.DataFrame(index=p.index)
    for w in (7, 28, 91, 365):
        F[f"lvl_{w}"] = roll_mean(y, w)
    F["level_7d"] = F["lvl_7"].fillna(F["lvl_28"])            # the anchor
    F["mom_7_28"] = safe_log_ratio(F["lvl_7"], F["lvl_28"])
    F["mom_28_91"] = safe_log_ratio(F["lvl_28"], F["lvl_91"])
    F["mom_91_365"] = safe_log_ratio(F["lvl_91"], F["lvl_365"])
    F["cv_28"] = y.rolling(28, min_periods=7).std() / F["lvl_28"]
    if TARGET != "per_cow":               # with the per-cow target these equal the level features
        pc = past["per_cow"]
        F["per_cow_7"] = roll_mean(pc, 7)
        F["per_cow_28"] = roll_mean(pc, 28)
        F["per_cow_chg_91"] = safe_log_ratio(F["per_cow_28"], F["per_cow_28"].shift(91))
    for c in ["milking", "n_herd", "dry_pregnant", "dry_open", "heifers_pregnant", "calves"]:
        F[c] = past[c]
        F[f"{c}_chg_28"] = safe_log_ratio(past[c] + 1, past[c].shift(28) + 1)
        F[f"{c}_chg_91"] = safe_log_ratio(past[c] + 1, past[c].shift(91) + 1)
    m = past["milking"].replace(0, np.nan)
    F["pipe_dry_preg_per_milking"] = past["dry_pregnant"] / m
    F["pipe_heifer_preg_per_milking"] = past["heifers_pregnant"] / m
    exits = past["deaths"] + past["culls"] + past["sales"]
    for name, s in [("calvings", past["calvings"]), ("dry_offs", past["dry_offs"]),
                    ("exits", exits), ("entries", past["entries"]), ("abortions", past["real_abortions"])]:
        F[f"{name}_30"] = roll_sum(s, 30)
        F[f"{name}_91"] = roll_sum(s, 91)
    for c in ["share_par_1", "share_par_2", "share_par_3p",
              "share_dim_0_60", "share_dim_61_150", "share_dim_151_305", "share_dim_305p"]:
        F[c] = past[c]
    F["thi_7"] = roll_mean(past["thi_mean"], 7)
    F["thi_28"] = roll_mean(past["thi_mean"], 28)
    F["rain_28"] = roll_sum(past["rain_total_mm"].fillna(0), 28)
    F["mastitis_91"] = roll_sum(past["mastitis_episodes"].fillna(0), 91)
    sess = roll_sum(past["n_sessions"].fillna(0), 28).replace(0, np.nan)
    F["blood_alarm_rate_28"] = roll_sum(past["n_blood_alarms"].fillna(0), 28) / sess
    F["cond_alarm_rate_28"] = roll_sum(past["n_conductivity_alarms"].fillna(0), 28) / sess
    F["sessions_per_cow_28"] = sess / (roll_mean(past["milking"], 28) * 28)
    F["scoreable_share_28"] = y.notna().astype(float).rolling(28, min_periods=1).mean()
    ok = y.notna()
    last_ok = pd.Series(np.where(ok, np.arange(len(ok)), np.nan), index=p.index).ffill()
    F["days_since_gap"] = (pd.Series(np.arange(len(ok)), index=p.index)
                           - pd.Series(np.where(~ok, np.arange(len(ok)), np.nan), index=p.index).ffill())
    F["days_since_record"] = np.arange(len(ok)) - last_ok
    F["recorded_cows_share_28"] = roll_mean(past["cows_clean"] / m, 28)
    F["clean_cows_7"] = roll_mean(past["cows_clean"], 7)
    F["removed_share_28"] = (roll_sum(past["records_removed_gt18"], 28)
                             / roll_sum(past["milk_observed_records"].fillna(0), 28).replace(0, np.nan))
    return F


FEAT = origin_features(panel)
# centred 7-day mean of the series, used for "last year's change over the same window"
Y_C7 = panel["y"].rolling(7, center=True, min_periods=3).mean()
print(f"{FEAT.shape[1]} origin features built for {len(FEAT):,} days.")
""")

code(r"""
LEADS = np.arange(1, HORIZON_DAYS + 1)
ORIGIN_COLS = [c for c in FEAT.columns if c not in ("level_7d",)]


def expand_rows(origins: pd.DatetimeIndex, with_target: bool = True) -> pd.DataFrame:
    # origin x lead rows. Target day = origin + lead - 1.
    idx = panel.index
    pos = idx.get_indexer(origins)
    o_pos = np.repeat(pos, len(LEADS))
    lead = np.tile(LEADS, len(pos))
    t_pos = o_pos + lead - 1
    t_dates = idx[pos].repeat(len(LEADS)) + pd.to_timedelta(lead - 1, unit="D")
    rows = pd.DataFrame(FEAT.iloc[o_pos].values, columns=FEAT.columns)
    rows["origin"] = idx[o_pos]
    rows["target_date"] = t_dates
    rows["lead"] = lead
    rows["month_ahead"] = (lead - 1) // 30 + 1
    doy = t_dates.dayofyear.values
    rows["tgt_doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    rows["tgt_doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    rows["tgt_weekday"] = t_dates.weekday.values
    # last year: centred mean at (target - 365) over the 28-day level at (origin - 365), both < origin
    ly_t = Y_C7.reindex(t_dates - pd.Timedelta(days=365)).values
    ly_o = FEAT["lvl_28"].reindex(idx[o_pos] - pd.Timedelta(days=365)).values
    with np.errstate(divide="ignore", invalid="ignore"):
        rows["last_year_change"] = np.log(ly_t / ly_o)
    rows.loc[~np.isfinite(rows["last_year_change"]), "last_year_change"] = np.nan
    if with_target:
        actual = np.full(len(rows), np.nan)
        inside = t_pos < len(idx)
        actual[inside] = panel["y"].values[t_pos[inside]]
        rows["actual"] = actual
        with np.errstate(divide="ignore", invalid="ignore"):
            rows["y_ratio"] = np.log(rows["actual"] / rows["level_7d"])
    return rows


MODEL_FEATURES = ORIGIN_COLS + ["lead", "tgt_doy_sin", "tgt_doy_cos", "tgt_weekday", "last_year_change"]

# usable origins: a level exists (≥ 2 recorded days in the last 7, else 28)
first = panel["y"].first_valid_index() + pd.Timedelta(days=60)
if MODEL_FROM is not None:
    first = max(first, pd.Timestamp(MODEL_FROM))
all_origins = FEAT.index[(FEAT.index >= first) & FEAT["level_7d"].notna()][::ORIGIN_STEP]
rows = expand_rows(all_origins)
rows = rows[rows["y_ratio"].notna()].reset_index(drop=True)
print(f"{len(all_origins):,} forecast dates x {HORIZON_DAYS} leads -> {len(rows):,} rows with a recorded target; "
      f"{len(MODEL_FEATURES)} features.")
display(rows[MODEL_FEATURES].describe().T[["count", "mean", "min", "max"]].head(12))
""")

# --------------------------------------------------------------------------------------
md(r"""
## 4. Train / test split (80:20, chronological)

A random 80:20 split would put tomorrow's milk in training and yesterday's in test, which
leaks the answer through neighbouring days. Here the split is **by forecast date**: the
first 80 % of forecast dates train, the last 20 % test. Training rows whose *target day*
falls on or after the first test date are removed (purge), so no training row has seen a
test-period value.
""")

code(r"""
origins_sorted = np.sort(rows["origin"].unique())
split_date = pd.Timestamp(origins_sorted[int(len(origins_sorted) * (1 - TEST_SHARE))])
train_mask = (rows["origin"] < split_date) & (rows["target_date"] < split_date)
test_mask = rows["origin"] >= split_date
train, test = rows[train_mask].reset_index(drop=True), rows[test_mask].reset_index(drop=True)
purged = int(((rows["origin"] < split_date) & (rows["target_date"] >= split_date)).sum())

print(f"split date (first test forecast date): {split_date:%Y-%m-%d}")
print(f"train: {train['origin'].nunique():,} forecast dates, {len(train):,} rows "
      f"({train['origin'].min():%Y-%m-%d} .. {train['target_date'].max():%Y-%m-%d})")
print(f"test : {test['origin'].nunique():,} forecast dates, {len(test):,} rows "
      f"({test['origin'].min():%Y-%m-%d} .. {test['target_date'].max():%Y-%m-%d})")
print(f"purged {purged:,} training rows whose target day is in the test period")
print(f"forecast-date share: train {train['origin'].nunique() / len(origins_sorted):.0%}, "
      f"test {test['origin'].nunique() / len(origins_sorted):.0%}")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 5. ML modelling and training

| Model | Type | Role |
|---|---|---|
| `persistence_7d` | last-7-day mean carried forward | benchmark (an ML model must beat it) |
| `mean_28d` | last-28-day mean | benchmark |
| `seasonal_naive` | 7-day level × last year's change over the same window | benchmark with season |
| `ridge` | linear, median impute + missing flags + scaling, α = 10 | simple ML |
| `random_forest` | 200 trees, depth ≤ 14, ≥ 30 rows per leaf | non-linear ML |
| `lightgbm` | gradient-boosted trees, 2 settings tried in CV | non-linear ML |
| `ensemble` | mean of Random Forest and LightGBM log-ratios | combination |

All ML models predict the log ratio to the 7-day level. Rows are weighted by recency
(half-life 730 days) so recent regimes count more.

**Model selection by time-series cross-validation inside the training 80 %.** The training
forecast dates are cut into `CV_FOLDS` expanding windows; each fold trains on the earlier
part (purged the same way) and scores the next part. The model with the highest mean
share within ±10 % in CV is selected. The test 20 % is used **once**, after selection.
""")

code(r"""
def recency_weight(dates: pd.Series, ref: pd.Timestamp, half_life: float = 730.0) -> np.ndarray:
    age = (ref - dates).dt.days.clip(lower=0).values
    return 0.5 ** (age / half_life)


def make_ridge():
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), Ridge(alpha=10.0))


def make_rf():
    return make_pipeline(SimpleImputer(strategy="median"),
                         RandomForestRegressor(n_estimators=200, max_depth=14, min_samples_leaf=30,
                                               max_features=0.5, n_jobs=-1, random_state=SEED))


LGBM_SETTINGS = {
    "lightgbm_a": dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=40,
                       subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0),
    "lightgbm_b": dict(n_estimators=800, learning_rate=0.02, num_leaves=31, min_child_samples=80,
                       subsample=0.8, subsample_freq=1, colsample_bytree=0.6, reg_lambda=5.0),
}


def make_lgbm(name="lightgbm_a", **extra):
    return lgb.LGBMRegressor(random_state=SEED, verbose=-1, **{**LGBM_SETTINGS[name], **extra})


ML_FACTORIES = {"ridge": make_ridge, "random_forest": make_rf,
                "lightgbm_a": lambda: make_lgbm("lightgbm_a"), "lightgbm_b": lambda: make_lgbm("lightgbm_b")}


def fit(factory, tr: pd.DataFrame):
    model = factory()
    w = recency_weight(tr["target_date"], tr["target_date"].max())
    X = tr[MODEL_FEATURES]
    if hasattr(model, "steps"):
        model.fit(X, tr["y_ratio"], **{f"{model.steps[-1][0]}__sample_weight": w})
    else:
        model.fit(X, tr["y_ratio"], sample_weight=w)
    return model


def benchmark_ratio(df: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "persistence_7d": np.zeros(len(df)),
        "mean_28d": np.log(df["lvl_28"] / df["level_7d"]).fillna(0).values,
        "seasonal_naive": df["last_year_change"].fillna(0).clip(-0.7, 0.7).values,
    }


def hit_share(pred_ratio, df) -> float:
    pred = df["level_7d"].values * np.exp(pred_ratio)
    return float(np.mean(np.abs(pred / df["actual"].values - 1) <= TOLERANCE))
""")

code(r"""
# time-series CV inside the training forecast dates
tr_origins = np.sort(train["origin"].unique())
edges = np.linspace(0.4, 1.0, CV_FOLDS + 1)          # first 40 % always trains
cv_rows, cv_resid = [], []        # out-of-fold errors also give the forecast range (§5 final cell)
t0 = time.time()
for k in range(CV_FOLDS):
    cut = pd.Timestamp(tr_origins[int(len(tr_origins) * edges[k])])
    end = pd.Timestamp(tr_origins[min(int(len(tr_origins) * edges[k + 1]), len(tr_origins) - 1)])
    f_tr = train[(train["origin"] < cut) & (train["target_date"] < cut)]
    f_va = train[(train["origin"] >= cut) & (train["origin"] < end)]
    if len(f_tr) < 500 or len(f_va) < 100:
        print(f"fold {k + 1} skipped: {len(f_tr)} train / {len(f_va)} validation rows")
        continue
    scores = {name: hit_share(r, f_va) for name, r in benchmark_ratio(f_va).items()}
    preds = {}
    for name, factory in ML_FACTORIES.items():
        preds[name] = fit(factory, f_tr).predict(f_va[MODEL_FEATURES])
        scores[name] = hit_share(preds[name], f_va)
    best_lgbm = max(LGBM_SETTINGS, key=lambda n: scores[n])
    preds["ensemble"] = (preds["random_forest"] + preds[best_lgbm]) / 2
    scores["ensemble"] = hit_share(preds["ensemble"], f_va)
    for name, pr in preds.items():
        cv_resid.append(pd.DataFrame({"model": name, "month_ahead": f_va["month_ahead"].values,
                                      "resid": f_va["y_ratio"].values - pr}))
    cv_rows.append({"fold": k + 1, "validate_from": cut.date(), "validate_to": end.date(),
                    "train_rows": len(f_tr), "validate_rows": len(f_va), **scores})

cv = pd.DataFrame(cv_rows)
if cv.empty:
    raise RuntimeError("No CV fold had enough rows: lower MIN_RECORDED_COWS or check §2 coverage.")
print(f"time-series CV ({len(cv)} folds, {time.time() - t0:.0f} s): share within ±{TOLERANCE:.0%}, all leads 1-{HORIZON_DAYS}")
display(cv)
model_cols = [c for c in cv.columns if c not in ("fold", "validate_from", "validate_to", "train_rows", "validate_rows")]
cv_mean = cv[model_cols].mean().sort_values(ascending=False)
display(cv_mean.to_frame("mean CV share within ±10 %"))

LGBM_CHOICE = max(LGBM_SETTINGS, key=lambda n: cv_mean[n])
ml_only = cv_mean.drop(["persistence_7d", "mean_28d", "seasonal_naive"])
SELECTED = ml_only.idxmax()
print(f"LightGBM setting kept: {LGBM_CHOICE}; selected ML model by CV: {SELECTED}")
""")

code(r"""
# final training on the whole training 80 %, then predict the test 20 % once
t0 = time.time()
models = {"ridge": fit(make_ridge, train), "random_forest": fit(make_rf, train),
          "lightgbm": fit(lambda: make_lgbm(LGBM_CHOICE), train)}
print(f"trained in {time.time() - t0:.0f} s")

ratio = benchmark_ratio(test)
for name, m in models.items():
    ratio[name] = m.predict(test[MODEL_FEATURES])
ratio["ensemble"] = (ratio["random_forest"] + ratio["lightgbm"]) / 2
SELECTED_KEY = "lightgbm" if SELECTED.startswith("lightgbm") else SELECTED

pred = pd.DataFrame({"origin": test["origin"], "target_date": test["target_date"], "lead": test["lead"],
                     "month_ahead": test["month_ahead"], "level_7d": test["level_7d"],
                     "level_28d": test["lvl_28"].fillna(test["level_7d"]), "actual": test["actual"]})
for name, r in ratio.items():
    pred[name] = test["level_7d"].values * np.exp(r)
# 80 % range = 10th / 90th percentile of the selected model's own out-of-fold CV errors, per month ahead
resid = pd.concat(cv_resid)
resid = resid[resid["model"] == (LGBM_CHOICE if SELECTED_KEY == "lightgbm" else SELECTED_KEY)]
RANGE_Q = resid.groupby("month_ahead")["resid"].quantile([0.10, 0.90]).unstack()
RANGE_Q = RANGE_Q.reindex(range(1, HORIZON_DAYS // 30 + 2)).ffill().bfill()
print("80 % range from CV errors (log ratio), by month ahead:"); display(RANGE_Q.round(3))
lo_q = RANGE_Q[0.10].reindex(test["month_ahead"]).values
hi_q = RANGE_Q[0.90].reindex(test["month_ahead"]).values
pred["lower_80"] = test["level_7d"].values * np.exp(ratio[SELECTED_KEY] + lo_q)
pred["upper_80"] = test["level_7d"].values * np.exp(ratio[SELECTED_KEY] + hi_q)
MODELS = list(ratio)
print("models scored on test:", MODELS, "| selected:", SELECTED_KEY)
""")

# --------------------------------------------------------------------------------------
md(r"""
## 6. Testing and evaluation (held-out 20 %)

**Accuracy (project target ≥ 85 %).** Share of forecasts within ±10 % of the recorded value.
Also shown: accuracy = 1 − WAPE, MAE, bias and skill against persistence
(`1 − MAE_model / MAE_persistence`, > 0 means better than carrying the last week forward).

**Grains.** *Daily* = each day. *Weekly* = mean of 7 consecutive forecast days (weeks 1–12
after the forecast date); a week is scored only when all 7 days are recorded. *Monthly* =
mean of 30-day blocks (months 1, 2, 3), scored when at least `MONTH_MIN_COVERAGE` (80 %) of
its days are recorded; forecast and record are averaged over the same recorded days.

**AUC (project target ≥ 0.80).** Forecasting litres is regression, so AUC needs a yes/no
question. The one used here is an early warning: *will milk on the target day be at least
5 % below the last-28-day level?* The 28-day level is used (not 7 days) so ordinary
day-to-day noise is not counted as a drop. The score is the forecast relative to that level
(lower = more likely a drop). AUC = how well that score ranks real drops above non-drops
(0.5 = coin flip). It is reported by month ahead.
""")

code(r"""
def blocks(df: pd.DataFrame, size: int, n_blocks: int, cols: list[str], min_cov: float = 1.0) -> pd.DataFrame:
    # mean per day over the recorded days of each block; a block counts if ≥ min_cov of its days are recorded
    d = df[df["lead"] <= size * n_blocks].copy()
    d["block"] = (d["lead"] - 1) // size + 1
    g = d.groupby(["origin", "block"])
    out = g[cols + ["actual"]].mean()
    out["n_days"] = g.size()
    out = out[out["n_days"] >= int(np.ceil(size * min_cov))].reset_index()
    return out


def score(df: pd.DataFrame, by: str) -> pd.DataFrame:
    out = []
    for key, g in df.groupby(by):
        a = g["actual"].values
        base_mae = np.mean(np.abs(g["persistence_7d"].values - a))
        for m in MODELS:
            f = g[m].values
            err = f - a
            out.append({by: key, "model": m, "n": len(g),
                        "within_10pct": np.mean(np.abs(err / a) <= TOLERANCE),
                        "accuracy_1_wape": 1 - np.abs(err).sum() / np.abs(a).sum(),
                        "mae": np.mean(np.abs(err)), "bias_pct": err.sum() / a.sum(),
                        "skill_vs_persistence": 1 - np.mean(np.abs(err)) / base_mae if base_mae > 0 else np.nan})
    # same columns when a grain has no complete period in the test window (empty table)
    return pd.DataFrame(out, columns=[by, "model", "n", "within_10pct", "accuracy_1_wape", "mae",
                                      "bias_pct", "skill_vs_persistence"])


def show(s: pd.DataFrame, values, scale: float = 1.0) -> None:
    if s.empty:
        print("  (no complete period in the test window: every day of a block needs a recorded value)")
        return
    display((s.pivot(index="model", columns="month_ahead", values=values).loc[MODELS] * scale).round(3 if scale == 1 else 1))


daily_score = score(pred, "month_ahead")
weekly = blocks(pred, 7, 12, MODELS)
weekly["month_ahead"] = (weekly["block"] - 1) // 4 + 1         # weeks 1-4 = month 1, ...
weekly_score = score(weekly, "month_ahead")
monthly = blocks(pred, 30, HORIZON_DAYS // 30, MODELS, min_cov=MONTH_MIN_COVERAGE)
monthly_score = score(monthly.rename(columns={"block": "month_ahead"}), "month_ahead")

print(f"scored test periods: {len(weekly):,} complete weeks, {len(monthly):,} 30-day blocks "
      f"with ≥ {MONTH_MIN_COVERAGE:.0%} of days recorded")
for title, s in [("DAILY", daily_score), ("WEEKLY (7-day means)", weekly_score),
                 (f"MONTHLY (30-day means, ≥ {MONTH_MIN_COVERAGE:.0%} of days recorded)", monthly_score)]:
    print(f"\n{title}: share within ±{TOLERANCE:.0%} by month ahead, % (target ≥ {TARGET_HIT:.0%})")
    show(s, "within_10pct", 100)
print("\nDAILY: skill against persistence (> 0 = better than carrying the last week forward)")
show(daily_score, "skill_vs_persistence")
print("\nDAILY: accuracy = 1 - WAPE and bias")
show(daily_score, ["accuracy_1_wape", "bias_pct"])
""")

code(r"""
# AUC: early warning of a drop of at least DROP_THRESHOLD below the 28-day level
pred["is_drop"] = pred["actual"] < (1 - DROP_THRESHOLD) * pred["level_28d"]
auc_rows = []
for mo, g in pred.groupby("month_ahead"):
    row = {"month_ahead": mo, "drop_rate": g["is_drop"].mean(), "n": len(g)}
    for m in MODELS:
        if g["is_drop"].nunique() < 2:
            row[m] = np.nan
            continue
        row[m] = roc_auc_score(g["is_drop"], -(g[m] / g["level_28d"]))
    auc_rows.append(row)
auc = pd.DataFrame(auc_rows).set_index("month_ahead")
print(f"AUC for 'milk ≥ {DROP_THRESHOLD:.0%} below the last-28-day level' (target ≥ {TARGET_AUC:.2f})")
display(auc)

# coverage of the selected model's 80 % range (from its CV errors)
cov = ((pred["actual"] >= pred["lower_80"]) & (pred["actual"] <= pred["upper_80"])).groupby(pred["month_ahead"]).mean()
print("Share of recorded days inside the 80 % range (nominal 0.80):")
display(cov.to_frame("coverage"))
""")

code(r"""
# how far ahead does the selected model stay ≥ 85 % within ±10 %? (by lead day / week)
def hits(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({m: (np.abs(df[m] / df["actual"] - 1) <= TOLERANCE).astype(float) for m in MODELS})


by_lead = hits(pred).groupby(pred["lead"]).mean()
by_week = hits(weekly).groupby(weekly["block"]).mean()

def reach(series: pd.Series) -> int:
    if series.empty:
        return 0
    ok = series.rolling(7, min_periods=1, center=True).mean() >= TARGET_HIT if len(series) > 20 else series >= TARGET_HIT
    if not ok.iloc[0]:
        return 0
    return int(ok.index[(~ok).values.argmax() - 1]) if (~ok).any() else int(ok.index[-1])

print(f"Longest horizon at ≥ {TARGET_HIT:.0%} within ±{TOLERANCE:.0%} (selected = {SELECTED_KEY}):")
print(f"  daily : {reach(by_lead[SELECTED_KEY])} days   (persistence: {reach(by_lead['persistence_7d'])} days)")
print(f"  weekly: {reach(by_week[SELECTED_KEY])} weeks  (persistence: {reach(by_week['persistence_7d'])} weeks)")

fig, ax = plt.subplots(1, 2, figsize=(14, 4))
for m in ["persistence_7d", "seasonal_naive", "ridge", "random_forest", "lightgbm", "ensemble"]:
    ax[0].plot(by_lead.index, by_lead[m].rolling(7, min_periods=1, center=True).mean(), label=m, color=COL[m],
               lw=2.2 if m == SELECTED_KEY else 1.2)
    ax[1].plot(by_week.index, by_week[m], marker="o", label=m, color=COL[m], lw=2.2 if m == SELECTED_KEY else 1.2)
for a, xl in [(ax[0], "days ahead"), (ax[1], "weeks ahead")]:
    a.axhline(TARGET_HIT, color="#c00", ls="--", lw=1); a.set_ylim(0, 1); a.set_xlabel(xl)
    a.set_ylabel(f"share within ±{TOLERANCE:.0%}")
ax[0].set_title("Daily (7-day smoothed)"); ax[1].set_title("Weekly means"); ax[1].legend(fontsize=8)
plt.tight_layout(); plt.show()

# hit rate by test year: does accuracy improve where the data is richer?
pred["year"] = pred["target_date"].dt.year
by_year = hits(pred)[["persistence_7d", SELECTED_KEY]].groupby(pred["year"]).mean()
by_year["n"] = pred.groupby("year").size()
display(by_year)
""")

code(CHART_HELPERS + r"""


def predict_selected(X: pd.DataFrame) -> np.ndarray:
    # the selected model as trained on the training 80 % (it has not seen the test period)
    if SELECTED_KEY == "ensemble":
        return (models["random_forest"].predict(X) + models["lightgbm"].predict(X)) / 2
    return {"persistence_7d": lambda X_: np.zeros(len(X_))}.get(SELECTED_KEY, models.get(SELECTED_KEY, models["lightgbm"]).predict)(X)


UNIT = "litres per recorded cow per day" if TARGET == "per_cow" else "litres per day"
dates_ = chart_dates(pred["origin"], panel["y"], CHART_DATES)
fig, axes = plt.subplots(len(dates_), 1, figsize=(12, 3.3 * len(dates_)), squeeze=False)
for ax_, o in zip(axes[:, 0], dates_):
    fr = expand_rows(pd.DatetimeIndex([o]), with_target=False)
    r_ = predict_selected(fr[MODEL_FEATURES])
    td = pd.DatetimeIndex(fr["target_date"])
    fc = pd.Series(fr["level_7d"].values * np.exp(r_), index=td)
    lo = fc * np.exp(RANGE_Q[0.10].reindex(fr["month_ahead"]).values)
    hi = fc * np.exp(RANGE_Q[0.90].reindex(fr["month_ahead"]).values)
    forecast_panel(ax_, f"Forecast date {o:%Y-%m-%d}: {SELECTED_KEY}",
                   panel["y"].loc[o - pd.Timedelta(days=364): o - pd.Timedelta(days=1)],
                   panel["y"].loc[o: td.max()], fc, lo, hi, o, SELECTED_KEY, COL.get(SELECTED_KEY, "#b8572a"), UNIT)
axes[0, 0].legend(fontsize=8, loc="upper left", ncol=2)
fig.suptitle(f"{MODEL_VERSION}: forecasts on unseen test data vs what was recorded" +
             ("  [SYNTHETIC DEMO]" if USE_SYNTHETIC else ""), fontsize=11)
plt.tight_layout(); fig.savefig(CHART_DIR / f"nb02_test_forecasts{'_demo' if USE_SYNTHETIC else ''}.png", dpi=130)
plt.show()
print("chart dates:", ", ".join(f"{d:%Y-%m-%d}" for d in dates_), f"| saved to {CHART_DIR}")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 7. Explainability

LightGBM's built-in TreeSHAP (`pred_contrib=True`, no extra package) splits each forecast's
log ratio into one contribution per feature plus a base value; the parts add up exactly to
the model output (checked below). Features are summed into the factor groups of §3, so the
chart says *which kind of information* moves the forecast, per month ahead.
""")

code(r"""
GROUPS = {
    "recent level / momentum": ["lvl_", "mom_", "cv_28"],
    "yield per cow": ["per_cow"],
    "herd stocks": ["milking", "n_herd", "dry_open", "calves"],
    "pregnancy pipeline": ["pipe_", "dry_pregnant", "heifers_pregnant"],
    "events": ["calvings_", "dry_offs_", "exits_", "entries_", "abortions_"],
    "lactation mix": ["share_par", "share_dim"],
    "weather": ["thi_", "rain_"],
    "health / sensors": ["mastitis", "alarm", "sessions_per_cow"],
    "record quality": ["scoreable", "days_since", "identified", "recorded_cows", "clean_cows", "removed_share"],
    "season / lead": ["tgt_", "lead", "last_year"],
}


def group_of(f: str) -> str:
    for g, keys in GROUPS.items():
        if any(f.startswith(k) or k in f for k in keys):
            return g
    return "other"


if SELECTED_KEY != "lightgbm":
    print(f"Note: the selected model is {SELECTED_KEY}; TreeSHAP below explains the LightGBM model, "
          f"trained on the same rows (test share within ±10 % for both is in §6).")
sample = test.sample(min(20000, len(test)), random_state=SEED)
contrib = models["lightgbm"].predict(sample[MODEL_FEATURES], pred_contrib=True)
raw = models["lightgbm"].predict(sample[MODEL_FEATURES])
assert np.allclose(contrib.sum(axis=1), raw, atol=1e-6), "SHAP parts do not add up to the forecast"
print("Additivity check passed: base + feature contributions = forecast for every row.")

shap_df = pd.DataFrame(contrib[:, :-1], columns=MODEL_FEATURES)
grouped = shap_df.T.groupby(shap_df.columns.map(group_of)).sum().T.abs()
grouped["month_ahead"] = sample["month_ahead"].values
imp = grouped.groupby("month_ahead").mean().T
imp = imp.div(imp.sum(axis=0), axis=1).sort_values(imp.columns[0])
ax = imp.plot.barh(figsize=(10, 5), color=["#b8572a", "#d9a441", "#7b4fb3"][: imp.shape[1]])
ax.set_xlabel("share of mean |SHAP| (log-ratio units)"); ax.set_title("What drives the LightGBM forecast, by month ahead")
plt.tight_layout(); plt.show()

top = shap_df.abs().mean().sort_values(ascending=False).head(15)
display(top.to_frame("mean |SHAP|"))
""")

# --------------------------------------------------------------------------------------
md(r"""
## 8. Data-richness experiment: train on recent years only?

Same model type and settings as the selected model, trained on different start dates, all
scored on the **same** test rows. If the recent, richer records (2025–2026) carry a
different regime, training only on them can beat training on all history, but with fewer
rows. Windows with fewer than `MIN_WINDOW_ROWS` training rows are skipped.
""")

code(r"""
factory = {"ridge": make_ridge, "random_forest": make_rf, "ensemble": None}.get(SELECTED_KEY, lambda: make_lgbm(LGBM_CHOICE))
win_rows = []
for label, start in TRAIN_WINDOWS.items():
    tr = train if start is None else train[train["origin"] >= pd.Timestamp(start)]
    if len(tr) < MIN_WINDOW_ROWS:
        win_rows.append({"window": label, "train_rows": len(tr), "note": "skipped: too few rows"})
        continue
    if factory is None:     # ensemble = mean of RF and LightGBM
        r_ = (fit(make_rf, tr).predict(test[MODEL_FEATURES]) + fit(lambda: make_lgbm(LGBM_CHOICE), tr).predict(test[MODEL_FEATURES])) / 2
    else:
        r_ = fit(factory, tr).predict(test[MODEL_FEATURES])
    f_ = test["level_7d"].values * np.exp(r_)
    hit = np.abs(f_ / test["actual"].values - 1) <= TOLERANCE
    row = {"window": label, "train_rows": len(tr), "note": ""}
    for mo in sorted(test["month_ahead"].unique()):
        row[f"month {mo}"] = hit[test["month_ahead"].values == mo].mean()
    win_rows.append(row)
windows = pd.DataFrame(win_rows).set_index("window")
print(f"{SELECTED_KEY}: share within ±{TOLERANCE:.0%} on the same test rows, by training start")
display(windows)
""")

# --------------------------------------------------------------------------------------
md(r"""
## 8b. Period tests: 2019–2021 and 2022–2026

Two fixed test windows (`PERIODS` in §0). For each, every model is trained **only on rows whose
target day is before the window starts** (up to 2018, or up to 2021) and scored on forecast
dates inside the window whose targets also fall inside it. Nothing is selected on these years:
all models are shown, and LightGBM uses the fixed setting `lightgbm_a`; the ensemble = mean of
Random Forest and that LightGBM. Few or no rows in a window mean there is no clean milk to
score there (most of 2022–2025 has too few recorded cows).
""")

code(CHART_HELPERS + r"""


PERIOD_SCORES = {}
for pname, (train_end, t_from, t_to) in PERIODS.items():
    E, P0, P1 = pd.Timestamp(train_end), pd.Timestamp(t_from), pd.Timestamp(t_to)
    tr = rows[(rows["origin"] < E) & (rows["target_date"] < E)]
    te = rows[(rows["origin"] >= P0) & (rows["origin"] < P1) & (rows["target_date"] < P1)].reset_index(drop=True)
    yrs = ", ".join(str(y) for y in sorted(te["target_date"].dt.year.unique()))
    print(f"\n=== {pname}: train {len(tr):,} rows (targets before {E:%Y-%m-%d}), test {len(te):,} rows (target years: {yrs or 'none'})")
    if len(tr) < 2000 or not len(te):
        print("  skipped: not enough rows")
        continue
    pm = {"ridge": fit(make_ridge, tr), "random_forest": fit(make_rf, tr),
          "lightgbm": fit(lambda: make_lgbm("lightgbm_a"), tr)}
    rr = benchmark_ratio(te)
    for k_, m_ in pm.items():
        rr[k_] = m_.predict(te[MODEL_FEATURES])
    rr["ensemble"] = (rr["random_forest"] + rr["lightgbm"]) / 2
    pf = pd.DataFrame({"origin": te["origin"], "target_date": te["target_date"], "lead": te["lead"],
                       "month_ahead": te["month_ahead"], "level_7d": te["level_7d"], "actual": te["actual"]})
    for k_, r_ in rr.items():
        pf[k_] = te["level_7d"].values * np.exp(r_)
    wk = blocks(pf, 7, 12, MODELS); wk["month_ahead"] = (wk["block"] - 1) // 4 + 1
    mo = blocks(pf, 30, HORIZON_DAYS // 30, MODELS, min_cov=MONTH_MIN_COVERAGE).rename(columns={"block": "month_ahead"})
    PERIOD_SCORES[pname] = {"daily": score(pf, "month_ahead"), "weekly": score(wk, "month_ahead"), "monthly": score(mo, "month_ahead")}
    for g_, s_ in PERIOD_SCORES[pname].items():
        print(f"{pname}, {g_}: share within ±{TOLERANCE:.0%} by month ahead, %")
        show(s_, "within_10pct", 100)
    print(f"{pname}, daily: skill against persistence")
    show(PERIOD_SCORES[pname]["daily"], "skill_vs_persistence")
    # charts: the period ensemble at up to three forecast dates in the window
    UNIT = "litres per recorded cow per day" if TARGET == "per_cow" else "litres per day"
    dts = chart_dates(te["origin"], panel["y"], None)
    if dts:
        fig, axes = plt.subplots(len(dts), 1, figsize=(12, 3.3 * len(dts)), squeeze=False)
        for ax_, o in zip(axes[:, 0], dts):
            fr = expand_rows(pd.DatetimeIndex([o]), with_target=False)
            r_ = (pm["random_forest"].predict(fr[MODEL_FEATURES]) + pm["lightgbm"].predict(fr[MODEL_FEATURES])) / 2
            td = pd.DatetimeIndex(fr["target_date"])
            fc = pd.Series(fr["level_7d"].values * np.exp(r_), index=td)
            forecast_panel(ax_, f"Forecast date {o:%Y-%m-%d}: ensemble trained before {E:%Y}",
                           panel["y"].loc[o - pd.Timedelta(days=364): o - pd.Timedelta(days=1)],
                           panel["y"].loc[o: td.max()], fc, None, None, o, "ensemble", COL["ensemble"], UNIT)
        axes[0, 0].legend(fontsize=8, loc="upper left", ncol=2)
        fig.suptitle(f"{MODEL_VERSION}, period test {pname}" + ("  [SYNTHETIC DEMO]" if USE_SYNTHETIC else ""), fontsize=11)
        plt.tight_layout(); fig.savefig(CHART_DIR / f"nb02_period_{pname}{'_demo' if USE_SYNTHETIC else ''}.png", dpi=130)
        plt.show()
""")

# --------------------------------------------------------------------------------------
md(r"""
## 9. Prediction from the latest data

The selected model is refitted on every row whose target is already recorded (train + test),
then forecasts the next `HORIZON_DAYS` days from the day after the last recorded day.
Daily values, weekly means (Monday weeks) and 30-day block means are exported with the
10–90 % range in the same shape as `c1_output.outlook` rows, so the frontend can read them
later. The range is the 10th–90th percentile of the selected model's own out-of-fold CV
errors per month ahead; its test coverage is in §6.

With `TARGET = "per_cow"` the model forecasts litres per recorded cow. Herd milk is then
**derived**: litres per cow × milking cows, with milking cows held at the last known count
(an assumption, labelled in the export). Only the per-cow forecast is tested in §6.
""")

code(r"""
full = rows                                      # every row with a recorded target
final = {"ridge": make_ridge, "random_forest": make_rf}.get(SELECTED_KEY)
if SELECTED_KEY == "ensemble":
    m_rf, m_lg = fit(make_rf, full), fit(lambda: make_lgbm(LGBM_CHOICE), full)
    predict_ratio = lambda X: (m_rf.predict(X) + m_lg.predict(X)) / 2
elif final is not None:
    m_sel = fit(final, full); predict_ratio = m_sel.predict
else:
    m_sel = fit(lambda: make_lgbm(LGBM_CHOICE), full); predict_ratio = m_sel.predict

last_recorded = panel["y"].last_valid_index()
origin = last_recorded + pd.Timedelta(days=1)
if origin not in panel.index:                   # extend the calendar so the origin row exists
    panel = panel.reindex(pd.date_range(panel.index.min(), origin, freq="D"))
    FEAT = origin_features(panel)
    Y_C7 = panel["y"].rolling(7, center=True, min_periods=3).mean()
fut = expand_rows(pd.DatetimeIndex([origin]), with_target=False)
r_mid = predict_ratio(fut[MODEL_FEATURES])
fut["forecast"] = fut["level_7d"] * np.exp(r_mid)
fut["lower"] = fut["level_7d"] * np.exp(r_mid + RANGE_Q[0.10].reindex(fut["month_ahead"]).values)
fut["upper"] = fut["level_7d"] * np.exp(r_mid + RANGE_Q[0.90].reindex(fut["month_ahead"]).values)
fut["persistence"] = fut["level_7d"]
LAST_MILKING = float(panel["milking"].loc[:origin - pd.Timedelta(days=1)].dropna().iloc[-1])
if TARGET == "per_cow":
    for c in ("forecast", "lower", "upper"):
        fut[f"herd_{c}"] = fut[c] * LAST_MILKING
    print(f"herd milk derived with {LAST_MILKING:,.0f} milking cows (last known count, held constant)")

print(f"forecast date {origin:%Y-%m-%d} (last recorded day {last_recorded:%Y-%m-%d}); "
      f"model {SELECTED_KEY} ({MODEL_VERSION}), source = {SOURCE}")
fut["week_start"] = fut["target_date"] - pd.to_timedelta(fut["target_date"].dt.weekday, unit="D")
agg = {c: (c, "mean") for c in fut.columns if c in ("forecast", "lower", "upper", "herd_forecast", "herd_lower", "herd_upper")}
weekly_fc = fut.groupby("week_start").agg(days=("forecast", "size"), **agg)
monthly_fc = fut.groupby("month_ahead").agg(**agg)
print("Forecast by month ahead (mean per day):"); display(monthly_fc)
print("Weekly forecast (mean per day; first / last week may be partial):"); display(weekly_fc)

hist = panel.loc[origin - pd.Timedelta(days=120): origin, "y"]
fig, ax = plt.subplots(figsize=(13, 4.5))
ax.plot(hist.index, hist.values, color=COL["actual"], lw=0.9, label="recorded")
ax.fill_between(fut["target_date"], fut["lower"], fut["upper"], color=COL[SELECTED_KEY], alpha=0.18, lw=0, label="80 % range")
ax.plot(fut["target_date"], fut["forecast"], color=COL[SELECTED_KEY], lw=1.8, label=f"{SELECTED_KEY} daily")
ax.step(weekly_fc.index, weekly_fc["forecast"], where="post", color="#333", lw=1, ls=":", label="weekly mean")
ax.axvline(origin, color="#888", lw=0.8)
for k in (30, 60):
    ax.axvline(origin + pd.Timedelta(days=k), color="#ccc", lw=0.8)
ax.set_title(f"{TARGET}: {HORIZON_DAYS}-day forecast from {origin:%Y-%m-%d}" + ("  [SYNTHETIC DEMO]" if USE_SYNTHETIC else ""))
ax.legend(loc="upper left"); plt.tight_layout(); plt.show()
""")

code(r"""
# export: outlook-shaped rows (herd level), plus the test metrics, to logs/ (gitignored)
quality = lambda h: "high" if h <= 7 else ("moderate" if h <= 30 else "limited")
# (series id, column prefix, how the value was obtained)
SERIES_OUT = ([("milk_per_cow", "", "forecast (tested in §6)"),
               ("milk_litres", "herd_", "derived: per-cow forecast x milking cows held at last count (not tested)")]
              if TARGET == "per_cow" else [("milk_litres", "", "forecast of clean herd estimate (tested in §6)")])
out_rows = []
for series, pre, basis in SERIES_OUT:
    for grain, frame in (("day", fut.set_index("target_date")), ("week", weekly_fc)):
        for i, (period, r) in enumerate(frame.iterrows(), start=1):
            h = int(r["lead"]) if grain == "day" else i
            out_rows.append({"origin_date": f"{origin:%Y-%m-%d}", "target_period": f"{period:%Y-%m-%d}",
                             "grain": grain, "horizon": h, "series": series,
                             "forecast": round(float(r[pre + "forecast"]), 2), "lower": round(float(r[pre + "lower"]), 2),
                             "upper": round(float(r[pre + "upper"]), 2), "quality_flag": quality(h if grain == "day" else 7 * h),
                             "basis": basis, "model_version": MODEL_VERSION, "core_version": INPUT_SCHEMA})
# frontend readiness (fixed rule): month 1 daily AND weekly ≥ TARGET_HIT within ±10 % and better than persistence
def _m1_ok(s_) -> bool:
    r = s_[(s_["model"] == SELECTED_KEY) & (s_["month_ahead"] == 1)]
    return bool(len(r)) and r["within_10pct"].iloc[0] >= TARGET_HIT and r["skill_vs_persistence"].iloc[0] > 0
READY = all(_m1_ok(s_) for s_ in (daily_score, weekly_score))   # no complete periods = not ready
payload = {"source": SOURCE, "model_version": MODEL_VERSION, "selected_model": SELECTED_KEY, "target": TARGET,
           "frontend_ready": bool(READY),
           "cleaning": {"input": f"{INPUT_SCHEMA}.day_panel", "max_litres_per_recorded_cow": CLEAN_MAX_LITRES,
                        "min_recorded_cows": MIN_RECORDED_COWS},
           "unit": "litres per day (weekly rows = mean per day)", "outlook": out_rows}
stamp = f"{origin:%Y%m%d}" + ("_demo" if USE_SYNTHETIC else "")
(OUT_DIR / f"forecast_{stamp}.json").write_text(json.dumps(payload, indent=1))
metrics = pd.concat([daily_score.assign(grain="day"), weekly_score.assign(grain="week"), monthly_score.assign(grain="month")])
metrics.assign(source=SOURCE).to_csv(OUT_DIR / f"test_metrics_{stamp}.csv", index=False)
auc.assign(source=SOURCE).to_csv(OUT_DIR / f"test_auc_{stamp}.csv")
print("written:", *(p.name for p in sorted(OUT_DIR.glob(f"*{stamp}*"))), sep="\n  ")
""")

# --------------------------------------------------------------------------------------
md(r"""
## 10. Summary against the targets

Printed from the tables above, nothing typed by hand. ✅ = target met on the held-out 20 %.
""")

code(r"""
sel = SELECTED_KEY
lines = [f"Selected model (time-series CV): {sel}   |   test forecast dates from {split_date:%Y-%m-%d}   |   source = {SOURCE}", ""]
for title, s in [("daily", daily_score), ("weekly", weekly_score), ("monthly", monthly_score)]:
    t = s[s["model"] == sel].set_index("month_ahead")
    p = s[s["model"] == "persistence_7d"].set_index("month_ahead")
    if t.empty:
        lines.append(f"⚪ {title:7s}: no complete period in the test window")
    for mo, r in t.iterrows():
        ok = "✅" if r["within_10pct"] >= TARGET_HIT else "❌"
        lines.append(f"{ok} {title:7s} month {mo}: within ±10 % = {r['within_10pct']:.1%} "
                     f"(persistence {p.loc[mo, 'within_10pct']:.1%}), accuracy 1-WAPE {r['accuracy_1_wape']:.1%}, "
                     f"skill {r['skill_vs_persistence']:+.2f}, n = {int(r['n'])}")
lines.append("")
for mo, v in auc[sel].items():
    if np.isnan(v):
        lines.append(f"⚪ AUC (drop ≥ {DROP_THRESHOLD:.0%}) month {mo}: n/a (test has only drops or only non-drops)")
    else:
        lines.append(f"{'✅' if v >= TARGET_AUC else '❌'} AUC (drop ≥ {DROP_THRESHOLD:.0%}) month {mo}: {v:.3f}")
lines.append("")
lines.append(f"Longest horizon at ≥ {TARGET_HIT:.0%}: daily {reach(by_lead[sel])} days, weekly {reach(by_week[sel])} weeks")
lines.append("")
lines.append(("✅ FRONTEND READY" if READY else "❌ NOT FRONTEND READY") +
             f": month-1 daily and weekly need ≥ {TARGET_HIT:.0%} within ±10 % and positive skill vs persistence")
print("\n".join(lines))
""")

md(r"""
**Reporting rules.** Quote the numbers printed above as they are, including any ❌. If a
target is missed, the thresholds stay as set in §0; record the result and the reason
(e.g. which years were thin in §2, which factor groups dominate in §7, whether recent-only
training helped in §8). Persistence is a benchmark only and is never blended into the
forecast.
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
    out = Path(__file__).with_name("02_ml_milk_forecast.ipynb")
    build(out)
    print(f"wrote {out} ({len(CELLS)} cells)")
