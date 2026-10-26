# PP1 viva script: Component 1, Predictive Farm Outlook Intelligence (PFOI)

Ordered to follow the PP1 mark sheet. Each section: what to **say** (short), what to **show**
on the prototype, and likely **questions**. Numbers are herd-level aggregates already in
`pp1_results.md` and `pp1_plan.md`. Check every number against those files before speaking.

## 0. The 2-minute talk (then sections 1–13 are for Q&A)

1. **(15 s) Problem:** Farm X can't see its herd milk and herd events 1–12 months ahead, or
   why. Records also stop for months.
2. **(30 s) Method, on the Farm Outlook screen:** ETL builds pseudonymised herd cells →
   daily herd engine (St-Pierre Markov) → Wood lactation curves × k → Shapley explanation
   and ranges from past errors.
3. **(30 s) Proof, on Model evaluation:** milk about 37–39 % better than persistence at 3–6
   months; calvings 4–6× better; the final test confirmed calvings and dry-offs and was
   honest about milk after the gap.
4. **(25 s) Trust and integration:** record banner, withheld milk, outage recovery; C3 and
   C4 read `c1_output.outlook` through the shared contract.
5. **(20 s) Next:** yield-level accuracy at long horizons, cow-level model.

---

## 1. Problem definition (LO1, 30 % of 10 %)

**Say (30 s):**
"Farm X records its herd in DelPro, but the records only describe the past. The manager
can't see what herd milk, milking cows, calvings and dry-offs will be over the next 1 to 12
months, or why. Generic time-series tools such as persistence, ETS or SARIMA forecast the
milk line but can't explain it, and they break when records stop. Farm X had an 11-month
milk-record gap (Oct 2024 – Aug 2025). The gap is that no tool gives a herd-level forecast
that explains itself, says how far to trust it, and still works when records go stale."

**Research question:** can a structural herd model (biology plus lactation curves) forecast
herd milk and herd events better than simple benchmarks, while explaining every number?

**Hypotheses:** H1 beats persistence/seasonal naive; H2 a learned deviation layer adds heat,
health and events; H3 intervals reflect record quality; H4 updating after errors handles
regime change and gaps.

**Show:** Farm Outlook workspace, top metric deck (next-month milk, milking cows, calvings).

---

## 2. Proof of concept (LO1, 70 % of 10 %): what to have ready

1. **Live prototype, model data, not demo.** Backend running with C1 output enabled, page
   showing the run chip "Model output" (not the amber "Demo data" banner). Pick a past
   forecast date so forecast and recorded values sit on the same chart (`realised`).
2. **End-to-end chain in one sentence:** DelPro → ETL (pseudonymised `core`) →
   `model_input` → `pfoi cli build-outlook --write` → `c1_output.run_document` →
   FastAPI `GET /predictive/pfoi/run?origin=` → React page.
3. **Backtest evidence (development 2017–2023, ratio = model MAE ÷ persistence MAE):**
   monthly milk 0.62 / 0.63 / 0.61 / 0.75 at 1/3/6/12 months (about 37–39 % better at 3–6
   months); calvings 0.23 / 0.16 at 3/6 months (4–6× better). Month-1 MAPE 5.2 %.
4. **Honest final test (2024 – Aug 2026, frozen `pfoi-1.0.0`, run once):** calvings 0.87 /
   0.48 / 0.89 and dry-offs 0.62–0.77 confirmed. Monthly milk not interpretable (1–5 scored
   months after the gap). Total herd under-forecast (regime change after 2023).
5. **Diagnosis since then (1.2.x-dev):** error split shows yield per cow causes 85–93 % of
   milk error; the herd count is right. That points the next work at yield level, not
   herd structure.
6. **Unit tests** on synthetic fixtures (`components/predictive_farm_intelligence/tests/`,
   `backend/tests/test_pfoi_outlook.py`); leakage tests prove no input is dated after the
   forecast date.
7. **Backup:** screen recording of the page, in case the database or backend fails on the day.

---

## 3. Data, ETL and inputs

**ETL (separate repo, read-only on DelPro):**
`extract-raw` → `build-staging` → `build-core` (HMAC pseudonym keys: animals `A…`, bulls
`B…`, groups `G…`) → `load-weather` (ERA5 hourly → daily THI) → `build-model-input`.
Database `farmx_research` (raw, staging, secure) → published to `farmx_app` (`core`,
`model_input`). Each build has a core version tag, so every forecast says which data it
used. C1 never touches DelPro or the restricted schemas.

**What C1 reads (all read-only, `pfoi/data.py`, aggregate-only):**

| Table | Grain | Key columns | Used for |
|---|---|---|---|
| `model_input.day_cell` / `day_cell_known` | date × `state` × `parity_group` × `dim_band` × `generation_group` | `n_animals`; states calf, heifer_open/pregnant, milking, dry_open/pregnant; DIM bands 0-60, 61-150, 151-305, 305+; `_known` uses the date a pregnancy was *recorded* | starting herd for the herd engine; leakage control |
| `model_input.day_panel` | day | `target_litres`, `target_source`, `is_scoreable`, `is_implausible_volume`, milking count, event counts | milk target, k anchor, scoring |
| `model_input.period_panel` | week / month | same, aggregated | weekly and monthly scoring |
| `core.cow_day` / `animal_daily` | cow-day (keys only) | litres, DIM, parity | Wood curve fitting (aggregated per curve) |
| `core.weather_day` | day | `thi_mean`, `thi_max`, `hours_thi_above`, rain | heat panel, THI driver test |
| `core` events | event | calvings, inseminations, pregnancy checks, dry-offs, exits, entries | transition rates |

**`model_input2` (2026-10-22):** C1 inputs rebuilt from the app `core`, milk from
`animal_daily.is_yield_valid`. Missing days are gaps, never zero; sparse days (< 10 cows)
are "not available"; cow records > 18 L are flagged implausible. Placeholder and shipped
milk are excluded from all modelling. Selected only by environment variable, so the ETL
schema stays unchanged.

---

## 4. Methodology and feature engineering

**Say (60 s):** "Three layers, each explainable."

1. **Herd engine** (`pfoi/herd_engine.py`): a daily cohort Markov model. It starts from the
   recorded herd on the day before the forecast date and moves animals through
   calf → heifer → pregnant → calving → milking → dry, with abortions, deaths, culls, sales
   and entries. Rates come from a trailing window (recency-weighted, 6-month half-life from
   1.1.0), by parity × DIM band. Small groups are shrunk to the herd rate with
   beta-binomial shrinkage (`rates.py`). Exits are calibrated to daily herd totals.
2. **Milk model** (`milk_baseline.py`): herd milk = k × Σ (cows per parity × DIM ×
   pregnancy cell × Wood-curve yield). Wood curves per parity are fitted on Farm X's own
   reliable cow-days. Before Sep 2020 the shape is fitted to herd totals; a published
   Jersey-crossbred curve is kept as the sensitivity run. k (the level) is anchored on
   the last 14 trusted days.
3. **Correction and trust layers:** adaptive/bias correction from past errors (1.1–1.2),
   intervals from the model's own past errors with adaptive conformal inference (ACI),
   widened by record staleness; milk is **withheld** when there are no trusted recent days.

**Feature engineering (what to name):**
- **Herd-state features:** cohort counts by parity, DIM band (stage of lactation) and
  pregnancy state, built per forecast date.
- **Known-date features:** conception counted only from the day it was recorded
  (`conception_known="recorded"`). That's why calvings already *determined* differ from
  *rate-driven* calvings.
- **Rates:** recency-weighted, shrunk transition probabilities.
- **Lactation-curve features:** Wood parameters (a, b, c) per parity; DIM.
- **Record-quality features:** freshness (days since last trusted milk day), completeness,
  plausibility (litres per cow), source agreement → `quality_flag` and the record banner.
- **Heat:** daily THI from ERA5, 6-day availability lag, 1–2 day lags, 7-day mean,
  herd-relative thresholds (P75/P90), standardised inside each training window.
- **Explanation features:** Shapley split of each month-to-month milk change into herd
  size, parity mix, stage mix, pregnancy mix and yield level. It adds up exactly; a
  residual is shown for past months.

**Evaluation design:** rolling-origin backtests (Hyndman, fpp3), design choices on
2017–2023 only, nested and purged CV, config frozen by hash (`freeze.py`), final test run
once. Benchmarks: persistence, seasonal naive, ETS, SARIMA.

**Tested and dropped by pre-set keep rules (show this as rigour):** anchor gate, THI drivers,
conception shape, persistence blend, GRU, Chronos-2 zero-shot, damped-trend correction,
hybrid 1.3. "A rule was written before each run; if the rule failed, the change stayed off."

---

## 5. Research referred to (LO2)

| Source | What we took |
|---|---|
| St-Pierre et al. 2001, J. Dairy Sci. | Markov herd model: animals in states moving by transition rates → herd engine |
| Wood 1967 (lactation curve) | y = a·tᵇ·e^(−ct) per parity → milk per cow by DIM |
| Mandal et al. 2026 | published Jersey-crossbred curve → sensitivity run for early years |
| Gong et al. 2025 | lactation-curve calibration to herd totals → k anchor idea |
| Murphy et al. 2014; Zhang et al. 2016 | herd milk model comparisons → benchmark set, horizons |
| Shapley (game theory, used as in SHAP) | exact additive attribution of each change |
| Gibbs & Candès 2021 | adaptive conformal inference → intervals that adapt after misses |
| Hyndman & Athanasopoulos, fpp3 | rolling-origin evaluation, persistence/seasonal naive/ETS benchmarks |
| Bohmanova et al. 2007; West 2003 | THI formula choice; heat effect lags 1–2 days |
| Michael 2023, Niyonzima 2022, Mbuthia 2021, Ekine-Dzivenu 2020 | tropical THI thresholds 66–79 → herd-relative knots instead of a fixed threshold |

**Novelty (say "to our knowledge"):** a structural herd–milk forecaster that separates
reproduction (herd records) from production level (trusted recent milk), measures how
accuracy decays when records stop, withholds milk when evidence is too thin, and explains
every number by construction.

---

## 6. Technologies (LO2, 70 %)

- **Data:** PostgreSQL (`farmx_app`, schemas `core`, `model_input`, `c1_output`), SQL ETL,
  ERA5 reanalysis, SQLAlchemy read-only role.
- **Modelling:** Python, pandas, NumPy, SciPy (curve fitting), scikit-learn (ridge, logistic
  gate), statsmodels (ETS/SARIMA benchmarks), LightGBM/EBM for the cow-level experiments.
- **Backend:** FastAPI (`backend/app/api/routes/predictive.py`), Pydantic contract
  `shared/schemas/pfoi_outlook.py` (CONTRACT_VERSION 1.0).
- **Frontend:** React 18 + TypeScript + Vite, Recharts; Excel export (`simple/xlsx.ts`),
  Sinhala text (`simple/si.ts`).
- **Quality:** pytest with synthetic fixtures, `npm run build` type check, git branches per member.

Be ready to explain *why* each one: e.g. "Pydantic contract so teammates read C1 without
importing my code"; "Recharts because it handles ranges as area bands".

---

## 7. Front end: the prototype, panel by panel (LO3, design + completion)

**Data path:** `source.tsx` calls `GET /predictive/pfoi/runs` (published forecast dates),
then `GET /predictive/pfoi/run?origin=`. The backend's `outlook_service.py` reads
`SELECT document FROM c1_output.run_document`. One JSON document (`PfoiRun`,
`frontend/src/data/pfoi/contract.ts`) drives every chart. If the API is offline, labelled
synthetic demo runs are used and an amber "Demo data" banner says so.

**Two views by role** (`UserContext`): farm manager/worker → **Simple view**; vet/board →
**Detailed view**.

### Detailed view

| Panel | What it shows | Comes from (run document key → columns) | Model source |
|---|---|---|---|
| Run status chip | model vs demo, model version, core version, forecast date, data through | `source`, `model_version`, `core_version`, `origin_date`, `data_through` | `outlook.py` run metadata |
| **Farm Outlook**: metric deck, outcome bar, timeline | milk, milking cows, herd, calvings with 5–95 % range | `outlook[]`: `target_period`, `grain`, `horizon`, `series`, `forecast`, `lower`, `upper`, `quality_flag`; recorded line from `actuals[]` (`value`, `source`, `scoreable`) | herd engine + milk model + intervals |
| Signal band / Findings | "milk records stale", "forecast withheld", "hot spell" | derived in `view.ts` from `record_status`, `withheld`, `heat` | — |
| Point drawer (click a period) | why that period moves | `attribution[]`: `factor`, `contribution` (L/day) | Shapley split |
| **Herd & Production → Milk supply** | milk forecast vs recorded, waterfall of the change | `outlook` (milk_litres), `actuals`, `attribution` (herd size, parity mix, stage mix, pregnancy mix, yield level, residual) | milk model |
| → Herd count & movement | milking / dry / heifers / calves; flows between groups; calvings *determined* vs *rate-driven* | `outlook` (milking, dry, heifers, calves, total_herd), `moves[]` (`from`, `to`, `value`), attribution factors `determined` / `rate_driven`, `repro_timing[]` (median days per step, open share) | herd engine |
| → Herd events | calvings, dry-offs, abortions, deaths, culls/sales, entries, expected mastitis | `outlook` series of the same names; `mastitis_rate_period` | rates × herd cells |
| → Generations | herd share by generation, services per conception, abortion % | `generations[]` (`share`, `projected`), `fertility[]`, `generation_outcomes[]` | descriptive (associations, not genetic effects) |
| **Model evaluation** | backtest vs benchmarks, error by quality band, evidence ladder, outage recovery, record checks, sensor registry | `backtest[]` (`block`, `model`, `mae`, `rmse`, `bias`, `coverage`, `n_origins`), `qualityBands[]` (`mae_pct`, `coverage`, `n_periods`), `evidence_ladder[]`, `outage_simulation[]` (`gap_days`, `resumed_days`, `ratio_to_persistence`), `record_status` (4 checks), `feature_registry[]`, `coverage[]` | backtest / outage_sim / record_status modules |
| Forecast replay | past forecasts against what happened | `replay[]`, `realised[]`, `revisions[]` | rolling-origin runs |
| Heat outlook | recent THI vs this time of year (P10/P50/P90), forecast THI | `heat` (thi_recent, climatology, predictions) | `thi_forecast.py` |
| Scenario bands | "what if a hot spell / outage" | `scenarios[]` (`forecast`, `scenario`, `low`, `high`, `sentence`) | `scenarios.py` |

### Simple view (`ManagerView.tsx`): plain-language tabs
What to watch · Why milk changes · One date · Herd movement · Herd events · Heat ·
Breeding · How far to trust · Model tests. Same run document, fewer controls, Excel
export, Sinhala option.

**Design points to say:** every card starts with one plain sentence; ranges shown, not just
a line; status badge per result (*Evaluated / Post-test development / Not interpretable
(n < 12) / Not yet evaluated*); measured, derived and assumed values are tagged; herd level
only, no animal shown.

**Teammate contract vs page document:** the page reads the rich `run_document` JSON;
teammates read the fixed tables `c1_output.outlook`, `attribution`, `history` through
`shared/schemas/pfoi_outlook.py`. Series names there: `herd_milk`, `n_herd`, `milking`,
`calvings`, `dry_offs`, `real_abortions`.

---

## 8. How C1 feeds the other components

- **Component 4 (crisis forecasting / early warning):** reads `c1_output.outlook` daily
  `herd_milk` forecasts with `lower`/`upper` through the shared contract
  (`member4_crisis_forecasting/data_access/c1_forecast_loader.py`). It uses them as
  research context next to its own risk scores. It uses only rows with
  `quality_flag = ok` and an exact model and core version, and never imports C1 code.
- **Component 3 (farmer reasoning / digital agronomist):** `services/c1_repository.py`
  reads one forecast (with range and quality flags) through aggregate-only SQL, so the
  assistant can answer "how much milk next month?" with C1's number and its uncertainty.
- **Component 2 (behavioural intelligence):** herd context (milking cows, stage mix,
  expected calvings) is available through the same contract; individual-cow health
  detection belongs to C3/C2, not C1.
- **Exchange:** outputs are shared as `c1_output` schema dumps between authorised members
  (`scripts/export_component_outputs.py`), never as raw data.

---

## 9. Standards and best practices (LO3, 20 %)

- **Privacy by design:** pseudonymised keys (HMAC), "Farm X" naming, herd-level outputs
  only, no animal keys in any output; least-privilege DB roles (`farmx_api`), secrets only in
  `.env`; no farm data sent to external services.
- **Data zones:** DelPro → ETL restricted → `core` (read-only) → component input/output
  schemas; each component writes only its own output schema.
- **Forecast-evaluation standards:** rolling origin, no look-ahead (as-known dates,
  leakage tests), common periods for every model, benchmarks, development/test split, final
  test run once, config frozen by hash, semantic model versions (`pfoi-1.0.0`, `1.1.x`,
  `1.2.x-dev`).
- **Contracts:** Pydantic schema with a version number and a change log
  (`PFOI_OUTLOOK_CHANGES.md`); new page data only as optional keys.
- **Reproducibility:** CLI commands, run IDs, core version on every row, SHA-256 of runs.
- **Research integrity:** demo data labelled `source: "demo"`; failed tests and dropped
  models reported; keep rules fixed before runs.

---

## 10. User / functional requirements (LO3, 20 %)

**Users:** farm manager, farm worker, vet, board member.
**Functional:** forecast herd milk (daily/weekly/monthly, 1–12 months) with ranges; forecast
herd counts and events; explain every change; show trust (record status, error by
quality band); withhold when records are insufficient; replay past forecasts; export to
Excel; simple vs detailed view by role.
**Non-functional:** herd level only, pseudonymised, runs locally, works offline on demo
data, readable at phone width, response from one stored document (fast).

---

## 11. Risks and mitigation (LO3, 10 %)

| Risk | Mitigation (done / in progress) |
|---|---|
| Milk-record gaps (11 months) | anchor-first k with fallback; quality flags; widened ranges; explicit withholding; outage simulation measures recovery |
| Regime change (2023 herd contraction and recovery; 2022 yield drop) | recency-weighted rates; correction layer; stability gate (AUC 0.776, GO) + specialist under test; error split pointed to yield level |
| Intervals too narrow (42–77 % coverage) | ACI, staleness widening, coverage reported per run |
| Data quality (missing calvings, placeholder milk, diagnoses stopped after 2023) | `model_input2` with explicit gap/sparse/implausible flags; placeholder excluded; mastitis labelled "recording gap", not "no mastitis" |
| Overfitting / look-ahead | development-only design, nested CV, frozen hash, final test once |
| Privacy leak | data zones, no DB access for agents, aggregate-only checks, `.gitignore` rules |
| Integration break for teammates | versioned Pydantic contract, dumps with version, demo fallback |
| Demo-day failure | demo fallback labelled, screen recording backup |

---

## 12. Completion and next steps (≈ 50 % target)

**Done:** ETL inputs, herd engine, milk model, Shapley explanation, intervals, record
status, outage simulation, heat panel, reproduction timeline, generation outcomes,
evidence ladder, FastAPI + React prototype with simple and detailed views, contract for
teammates (M1–M8 of the PP1 plan).
**Next:** yield-level work for long horizons (target 85 % within ±10 %), cow-level
Layer 2 model (Wood + EBM, level drift being fixed), gate-driven confidence flag,
prospective confirmation on new 2026 records.

---

## 13. Commercial potential (LO5)

Any DelPro / herd-software farm can use it without new sensors; the model reads existing
records. Value: plan feed, labour and milk contracts 3–6 months ahead; spot recording
failures early; an explanation the manager can trust. Path: per-farm subscription or an
add-on to herd software; Sri Lankan dairy cooperatives as a first market.

---

## Likely questions (one-line answers)

- **Why not just deep learning?** Tested (GRU, Chronos-2, ML direct): below the structural
  model at long horizons on ~50 monthly points; the structure also gives the explanation.
- **Why is total herd bad in the final test?** Regime change: the herd recovered after the
  2023 fertility drop faster than the trailing rates learned. Reported, not hidden.
- **How do you know there's no leakage?** Inputs filtered to before the forecast date,
  pregnancies by recorded date, unit-tested.
- **Is mastitis predicted?** Only the expected count; diagnoses stopped being recorded, so
  it can't be validated. The page says so.
- **What is k?** The level factor between curve-based milk and recorded milk, anchored on
  the last 14 trusted days.
