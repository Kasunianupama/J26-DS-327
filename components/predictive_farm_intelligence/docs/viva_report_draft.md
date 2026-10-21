# PFOI (Component 1) viva draft: template table and report sections 2–4

Draft from code and docs, 2026-10-21. Numbers are herd-level aggregates already recorded in
`docs/pp1_results.md` and `docs/pp1_plan.md`. Status words follow `docs/pp1_plan.md`
(implemented and tested / evaluated / post-hoc / not interpretable).

## A. Template table

| Area | Item | Content |
|---|---|---|
| Data Pipeline | Data Sources | DelPro herd and milk records for Farm X (SQL Server `DDM`, read-only); ERA5 hourly weather (`data/weather/`, ETL repo); milk shipment records 2015-08 – 2020-07 |
| | Data Preprocessing | ETL repo `research-etl-data-integration`: `extract-raw` → `build-staging` → `build-core` (HMAC pseudonym keys, `etl/pseudonymise.py`) → `load-weather` → `build-model-input` (`sql/model_input/01_day_panel.sql`, `01_known_day_cell.sql`) |
| | Data storage and versioning | PostgreSQL `farmx_research` (raw, staging, secure, core, model_input) → `farmx_app` (`core`, `model_input`, `c1_output`); core version tag e.g. `p20261018T125214Z`; snapshots `snapshot-core`; anonymised `share/vN/` |
| Model Development | Model Selection | Structural herd model: daily cohort herd engine (`pfoi/herd_engine.py`) + lactation-curve milk model (`milk_baseline.py`, Wood curve) + correction layers; benchmarks: persistence, seasonal naive, ETS, SARIMA |
| | Model Training | Rates from a trailing 24-month window with 6-month half-life, beta-binomial shrinkage (`rates.py`); curves fitted on past data only; design choices on development block 2017–2023 via nested and purged CV (`nested_cv.py`); config frozen by hash (`freeze.py`) |
| Model Integration | Tools used | Python (pandas, NumPy, SciPy, scikit-learn ridge), SQLAlchemy, FastAPI backend, React/TypeScript frontend (`frontend/src/pages/PredictiveIntelligence/`), pytest |
| Model Deployment | Testing Environments | Local machine; synthetic fixtures in `tests/`; rolling-origin backtests run by the owner |
| | Deployment Platform | Local PostgreSQL `farmx_app`; FastAPI + React prototype; no cloud |
| | Deployment Method | `cli build-outlook --write` publishes a run document to `c1_output`; frontend reads it; dev builds labelled `pfoi-1.2.0-dev` |
| Future Enhancements | Model Improvement | Validate exit-only candidate; matched interval coverage/width audit; evaluate `hybrid_runner` (1.3.0-dev); prospective confirmation after 2026-08-20; regime-change handling for total herd |

## 2. Data exploration

### 2.1 Data collection
Herd and milk records come from Farm X's DelPro system, copied read-only into PostgreSQL by
the ETL repo and pseudonymised (animals `A…`, bulls `B…`, groups `G…`). Weather is ERA5
hourly reanalysis, aggregated to daily THI. PFOI reads only `core` and `model_input`.

### 2.2 Dataset description

| Data source | Description | Resource | Size | Key attributes |
|---|---|---|---|---|
| Herd history | Calvings, inseminations, pregnancy checks, exits, entries | `farmx_app.core` | whole period (2015–2026), animal-level | lactation, parity, DIM, conception known date |
| Herd milk target | Daily herd milk, shipments to 2020-07, DelPro after | `model_input.day_panel` | daily, 2015-08 → 2026-08; gaps in 2022, 2024, 2024-09 – 2025-09 | target litres, `is_scoreable`, source |
| Per-cow milk | Reliable cow-days | `core.cow_day` | about 174k (2020), 75k (2021), 11k (2022), under 1k (2023–25) | litres, DIM, parity |
| Weather | ERA5 hourly → daily | `core.weather_day` | daily, whole period | `thi_mean`, `thi_max`, `hours_thi_above`, rain |
| Session sensors | Milking-session alarms | `core.milk_session` | from 2025-09 only | blood and conductivity alarms |
| Health | Diagnoses, treatments | `health_episode` | mostly 2015–18, almost none since 2023 | mastitis episodes |

### 2.3 Suitability analysis (relevance to the research objectives, 1 = low, 4 = high)

| Data source | Herd milk forecast | Herd events (calvings, dry-offs, herd size) | Explanation (Shapley) | Heat effect |
|---|---|---|---|---|
| Herd history | 4 | 4 | 4 | 1 |
| Herd milk target | 4 | 2 | 3 | 3 |
| Per-cow milk | 3 | 1 | 3 | 1 |
| Weather | 2 | 1 | 1 | 3 |
| Sensors | 1 | 1 | 1 | 1 |
| Health | 1 | 1 | 1 | 1 |

These scores are my judgement from the coverage figures above, not a measured result; adjust
them before submission. Dataset size is sufficient for the herd engine, but sparse for per-cow
curves after 2021 and for sensors (about 5 months of overlap).

## 3. Methodology

### 3.1 Data preprocessing (by objective)

| Objective | Technique |
|---|---|
| Herd events | Data integration (joins in `core`), date/time transformation, pseudonym mapping, rates by parity × DIM band, shrinkage for small groups, exits calibrated to daily herd totals |
| Herd milk | Missing-data handling (gaps never scored, never zero), outlier gate (litres per cow, identified-share, `trusted_days` in `milk_baseline.py`), source separation (shipment vs DelPro), data aggregation (daily → week → month) |
| Heat and sensors | 6-day availability lag for ERA5, lagged and 7-day THI, herd-relative knots (P75/P90), standardisation inside each training window |

Leakage control: `day_cell_known` and `conception_known="recorded"`; unit tests in
`tests/test_leakage_and_backtest.py`.

### 3.2 Data sufficiency (the template's missing 3.2)
Rolling-origin periods with fewer than 12 scored periods are "not interpretable"
(`docs/targets.md`). Post-2022 monthly milk fails this (n 1–5).

### 3.3 Feature extraction
Per origin, the engine builds cows by parity × DIM × pregnancy state. The milk model uses the
projected cell counts and the Wood curve. The correction layers use the history of past
errors. The driver layer uses lagged THI features (shadow or dropped). Hybrid 1.3.0-dev adds
recent mean, trend, variability, recording coverage and calendar features (`pfoi/hybrid.py`,
`milk_context`).

## 4. Modelling and results

### 4.1 Key insights

- **Development (2017–2023), ratio to persistence (below 1 is better):** monthly milk 0.62 /
  0.63 / 0.61 / 0.75 at 1/3/6/12 months; calvings 0.23 and 0.16 at 3 and 6 months.
- **Final test, pfoi-1.0.0 (2024 – Aug 2026):** calvings 0.87 / 0.48 / 0.89 at 3/6/12 and
  dry-offs 0.62–0.77 hold up. Monthly milk is not interpretable (5 / 3 / 2 / 1 periods).
- **Post-hoc, 1.2.0-dev vs 1.1.0:** total herd is worse at all 7 scored origins; milk is
  mixed; July 2024 milking improves (MAE 98.3 → 36.2 cows). Individual origins, not averages.
- **Dropped by their keep rules:** anchor gate (M3), THI drivers (M5), conception shape (M7),
  fast half-life combination.
- **Status:** 1.2.0-dev is a development experiment, not a validated replacement for 1.1.0.

*Add charts here: ratio-by-horizon bars (development vs post-hoc), the 2026-08 outlook with
ranges, and total herd forecast vs actual at 2023-11 and 2024-01.*

### 4.2 Challenges faced

- An 11-month milk gap left no clean months to calibrate k (fixed for dates by anchor-first).
- Regime change: the herd contracted in 2023, then recovered; the 12/24-month rates lagged,
  and the correction layer sometimes amplified the miss.
- Intervals under-covered (34–83%); the ACI bands for events are visibly too wide.
- Diagnoses stopped being recorded, so mastitis cannot be forecast or used as a label.
- Missing calvings since the outage push the starting milking herd down (ETL issue); milking
  cow-days from lactations are 8.6% above the daily herd in 2025–26.
- Backtest runtime (hours) limits how many variants can be tested.
