# PFOI (Component 1): instructions for AI coding agents

Herd-dynamics and milk-yield forecasting. These rules **add to** the repository-wide rules in
the root `AGENTS.md` (privacy, confidentiality, no database access); they never loosen them.
Design detail: `docs/forecast_design.md` in this folder. Start with: *"Read
components/predictive_farm_intelligence/CLAUDE.md and start Step 3."*

## 0. Who and when

- BSc Data Science final-year project J26-DS-327, Component 1: **Predictive Farm Outlook
  Intelligence (PFOI)**, herd-dynamics and milk-yield forecasting for one government dairy
  farm in Sri Lanka, called **"Farm X"** everywhere.
- Progress Presentation 1 (PP1) is **Fri 2026-10-23**. Work must be working, testable and
  explainable by then. Each student presents for exactly 2 minutes.
- Scope for PP1: herd counts, herd events, herd milk and mastitis (herd level). Finance,
  feed and resources are deferred until the Excel files arrive.

## 1. Hard rules (override everything else)

1. **No database access for Claude.** Never connect to any database (`farmx_app`,
   `farmx_research`, DelPro/SQL Server), never read `.env`, never ask for passwords.
   Write the code, SQL or command; the user runs it and sends back results.
2. **Aggregates only.** Any check the user runs must return counts, sums, means, min/max,
   percentages or distributions: never individual rows, animal keys or names. Never
   print row-level data to the console, logs, chat or files.
3. **Confidentiality.** Never write the real farm, place, herd, group, staff, vet or buyer
   names anywhere (code, comments, docs, fixtures, commits, logs, chat).
4. **No data in Git.** `.gitignore` must cover `.env`, `data/` (except `data/sample/`
   synthetic files), `logs/`, `*.csv`, `*.parquet`, `*.xlsx`. Check `git status` before
   every commit.
5. **Read-only inputs.** Models read `core` and `model_input` only, and write only to
   schema `c1_output`. They never read or write `raw`, `staging` or `secure` (those exist
   only in the ETL database).
6. You may run `pytest` (unit tests on synthetic data, no database). Unit tests must not
   open database connections.
7. Work one step at a time. After each step: run `pytest`, give the user the command and
   the aggregate check SQL, report changed files and results, then stop and wait.

## 2. The monorepo

- Layout: `frontend/` (React+Vite), `backend/` (FastAPI), `components/<member>/`,
  `shared/schemas/` (Pydantic contracts). Components talk only through `shared/schemas`.
- This component lives in `components/predictive_farm_intelligence/` (currently a demo
  service). Keep research logic out of route files and the UI.
- Before changing anything: the checkout was on branch `component-2` (a teammate's) and
  `git status` showed the whole folder as untracked. Ask the user to create and switch to
  their own branch (e.g. `feature/member1-pfoi`) and to resolve the untracked state
  before any commit.
- `backend/app/database/connection.py` currently builds a SQL Server URL (DelPro). The
  backend must instead use PostgreSQL `farmx_app` (`postgresql+psycopg`) as role
  `farmx_api`, with settings read from environment variables. Confirm with the user
  before changing shared backend files, because teammates use them too.

## 3. Data access

- PostgreSQL 17, `localhost:5433`, database **`farmx_app`**. Separate from the ETL
  database; filled by the ETL's publish step.
- Schemas and roles:

  | Schema | Content | Read by | Written by |
  |---|---|---|---|
  | `core` | pseudonymised research tables (copy) | model, api | ETL publisher |
  | `model_input` | herd-level panel (copy) | model, api | ETL publisher |
  | `c1_output` | model outputs | api | `farmx_model` |
  | `app` | backend tables | api | `farmx_api` |

- Connection settings come from env vars (`PFOI_DATABASE_URL` or host/port/db/user/password),
  never hard-coded. Provide a `.env.example` with empty values.
- `core` is pseudonymised, **not anonymised** (real dates, keyed animal IDs `A…`).
  Treat it as restricted research data; outputs and charts are aggregate only.
- **Prerequisites still pending on the ETL side**, done in the ETL project:
  `build-model-input` has not been run yet, and the `publish-app-db` command is not
  written yet. Until data is published, build and unit-test everything on synthetic
  fixtures.

### model_input2 (rebuilt from the app's core, 2026-10-22)
- Read `docs/model_input2.md` before any modelling on it: every change versus `model_input`,
  the appended columns, the verified aggregates and the known limits.
- **Placeholder milk is excluded from all modelling for now** (user decision). Load the
  placeholder-free daily target described in `docs/model_input2.md` section 5; never use the
  stored `target_litres`, `herd_milk_measured` or `period_panel` milk sums as they are.
  Shipped milk (`milk_shipped`, `milk_internal`, `milk_hand_milked_est`) and DelPro-history
  totals (`milk_delpro_*`) are not used in any modelling either. `pfoi/data.py` applies the
  placeholder-free target automatically on model_input2 (`clean_target_frame`).
- Select it with `PFOI_MODEL_INPUT_SCHEMA=model_input2`; write files to `--out logs/pfoi_mi2`.

## 4. Data contract (inputs)

### `model_input.day_cell` (herd engine input)
One row per `date × state × parity_group × dim_band × generation_group` with `n_animals`.
- `state`: calf, heifer_open, heifer_pregnant, milking, dry_open, dry_pregnant, bull, unknown.
- `parity_group`: '0' (not calved), '1', '2', '3+', 'unknown'.
- `dim_band` (milking only, else 'na'): 0-60, 61-150, 151-305, 305+, unknown.
- `generation_group`: '0', '1', '2', '3+', 'unknown'.
- Sum over cells per state = `core.herd_day` state counts exactly (tested).

### `model_input.day_panel` (one row per day, 2015-08-01 onward)
- Stocks: n_herd, calves, heifers_open/pregnant, milking, dry_open/pregnant, bulls, unknown_state.
- Events: calvings, dry_offs, ais, real_abortions, deaths, culls, sales, exits, entries,
  births, external_entries.
- Milk: milk_shipped, milk_internal, milk_delpro_cows, milk_delpro_unidentified,
  milk_delpro_total, identified_share, data_gap.
- Target: `target_source` ('shipment' before 2020-08-01, 'delpro' from 2020-08-01,
  null when unavailable or in the gap), `target_litres`, `is_suspect_low` (below 50% of
  the past 28-day mean), `is_scoreable`.
- `time_block`: burn_in (< 2017-01-01), development (< 2024-01-01), test.
- Weather: weather_is_complete, temp_mean_c, temp_max_c, rh_mean_pct, rain_total_mm,
  thi_mean, thi_max, hours_thi_above.
- Health: mastitis_episodes, udder_teat_episodes, preventive_episodes,
  other_health_episodes, vaccinations, n_sessions, n_blood_alarms, n_conductivity_alarms.

### `model_input.period_panel`
Same measures summed to `grain` = 'week' (Monday start) or 'month'. Stocks are daily
averages (`avg_*`). `is_scoreable` only when every expected day is scoreable from one source.

### `core` tables used by the models
- `core.lactation` (calving_date, lactation_no, dry_off_date, end_date, cycle_end_date,
  conception_date, n_services, aborted, …)
- `core.cow_day` (milk_date, yield_litres, dim, lactation_no, is_reliable): lactation curves
- `core.animal` (birth_date, generation, exit_date, exit_type)
- `core.insemination`, `core.calf`, `core.health_episode` (health_group),
  `core.state_transition_month`, `core.herd_month`, `core.weather_day`

## 5. Design decisions (full detail in docs/forecast_design.md)

- Engine runs at **daily** resolution; weeks and months are sums of days (always consistent).
- Horizons: daily 1/7/14 days (milk); weekly 1/4/8/13 weeks; monthly 1/3/6/12 months.
- Rolling origin with a strict no-leakage rule: a forecast at origin *m* uses only facts
  dated before *m*. Only exception: calvings already scheduled by conceptions recorded
  before *m*.
- Blocks: burn-in 2015-08 – 2016-12; development origins 2017-01 – 2023-12; **final test
  2024-01 – 2026-08, run once on the frozen model**.
- Herd rates: trailing window (default 24 months; compare 12/36/expanding), small cells
  shrunk toward the herd rate (beta-binomial).
- Milk baseline: `k × Σ cells × curve(parity, days in milk)`; Wood curve per parity fitted
  on reliable cow-days only; `k` fitted per source on the 12 months before the origin.
- Curve leakage: no reliable per-cow data exists before 2020-08. For origins before
  2020-09, use a published Jersey curve shape (external knowledge). A sensitivity run
  using the 2020–22 shape everywhere is labelled and excluded from the H1 claim.
- Weather in forecasts: THI climatology from training years only; actual THI only
  explains the past.
- Intervals: 5%/95% quantiles of the model's own past errors per horizon (from 2018).
- Attribution: Shapley over {herd size, lactation-stage mix, parity mix, THI, mastitis,
  residual}; the parts must sum exactly to the change (unit test). Herd flows split into
  already determined vs rate-driven.
- Benchmarks: persistence, seasonal-naive, SARIMA if available. Metrics: MAE, RMSE,
  bias, coverage, by horizon and data-quality band.
- Novelty claim (keep it modest): every past and future point and every revision is
  explained by construction, and uncertainty reflects record quality. St-Pierre et al.
  2001 and Gong et al. 2025 are the foundation, not the contribution.

## 6. Findings so far (aggregates supplied by the user)

- Reliable cow-days by year: 2020 ≈ 174k, 2021 ≈ 75k, 2022 ≈ 11k, 2023–25 < 1k,
  2026 ≈ 7k. Curves are fitted mainly on Aug 2020 – early 2022.
- Lactation-level 305-day yields are truncated (only 75 lactations pass quality ≥ 0.8),
  so they are not used.
- Generation (= farm-born generations in the maternal line, not crossbreeding):
  within-period fertility reverses the pooled trend (Simpson's paradox). In 2023–26,
  services per conception are gen 0 = 3.76, gen 1 = 5.50, gen 2 = 5.87. Abortions jump
  for every generation in 2023–26 (gen 0: 3.3% → 11.2%), a persistent period shift.
  There is no consistent milk advantage by generation at matched parity × lactation
  stage. Generation is used for composition projection and is not a milk multiplier by
  default.
- Exotic fraction is unusable (69% unknown, no intermediate values), so it is dropped.
- Health: mastitis records are concentrated in 2015–18; "Heifer mastitis" is the farm's
  general mastitis label (1,074 of 1,657 uses are on cows). Almost no diagnoses since
  2023, while 2025–26 session sensors raise about 1,000 blood alarms a month. This is a
  recording gap. Individual detection belongs to Component 3.
- `core` acceptance: 14/15 pass. `05_herd_balance` fails in 90 months (a documented
  source entry/exit mismatch). Herd counts therefore come from presence intervals, never
  from summed events.

## 7. Steps to do

### Step 3: herd engine (Mon 19)
- Package `components/predictive_farm_intelligence/pfoi/`: `data.py` (read-only loaders,
  env-configured), `herd_engine.py`.
- Daily cell transitions with all flows (births, calf→heifer, conception, calving,
  dry-off, real abortion, death, cull, sale, entry), rates from the trailing window
  before the origin, scheduled calvings from known conceptions, generation of calf =
  dam generation + 1.
- Backtest: projected vs actual counts and events by horizon (weekly and monthly).
- Unit tests on a small synthetic herd (conservation of animals, no negative counts,
  leakage guard).
- User check: MAE by horizon for milking, total herd, calvings and abortions.

### Step 4: milk model (Tue 20)
- `lactation_curve.py` (Wood per parity; fallback mean table), `milk_baseline.py`
  (cells × curve × k), `benchmarks.py`, `backtest.py` (rolling origin, all grains,
  intervals).
- User check: the H1 table (MAE/RMSE/bias/coverage by model × grain × horizon,
  development block).

### Step 5: explanation (Wed 21)
- `attribution.py`: Shapley for milk; flow decomposition for herd; mastitis expected
  episodes = cows at risk × rate (labelled with the rate period).
- Generation profile: composition projection plus descriptive fertility by period.

### Step 6: outlook, contracts, charts, freeze (Thu 22)
- Write `c1_output.outlook(origin_date, target_period, grain, horizon, series, forecast,
  lower, upper, quality_flag, model_version, core_version)` and
  `c1_output.attribution(origin_date, target_period, grain, series, factor, contribution,
  model_version, core_version)`. Herd level only. `core_version` = the latest
  `publish.publish_log.version` used by the run. Teammates restore this schema from a
  dump (see docs/database/app_database_setup.md, section 10), so its columns are a contract:
  change them only with a version bump and a note in `shared/schemas`.
- Pydantic models in `shared/schemas/` for these outputs, and a FastAPI route that
  serves them (deterministic demo fallback if no data).
- Aggregate charts: milk past + future with interval and gap shading; herd flow; events;
  two waterfalls (one past month, one future month).
- Run the final test block once, then `pytest`, one clean end-to-end run, commit, and a
  recorded backup demo.

What to drop first if behind: mastitis forecast → THI layer → 12-month horizon.
Never drop the herd engine, milk baseline or attribution.
