# PFOI command sheet: build, evaluate, compare and publish a new model

Hand this file to a new chat. It is the method used for pfoi-1.0 → 1.1 → 1.2-dev → 1.3-dev.
Run everything from the **repository root**. The user runs real-data commands and sends
back the printed aggregate tables; the agent never touches the DB, `.env` or row-level data
(root `AGENTS.md` §0). Agents may run `pytest` (synthetic only).

```bash
# shorthand used below (set once per terminal)
PFOI="python -m components.predictive_farm_intelligence.pfoi"
```

---

## 0. The method in one paragraph (how accuracy is judged)

1. **Freeze the yardstick first** (`docs/targets.md`): accuracy = 1 − WAPE, skill vs best
   benchmark, bias, 80/90 % coverage, interval width, recovery after a break. Never loosen
   a target after seeing results.
2. **Three blocks of time, never mixed:**
   - *development* = forecast dates 2017-01 → 2023-12. Every design choice is made here.
   - *posthoc* = 2024-01 → 2026-08. Already inspected, so it is **reported, not confirmed**.
   - *prospective* = months after 2026-08-20. The only honest confirmation.
   - The old *test* block (pfoi-1.0.0) is frozen and runs once. **Never use `--block test`.**
3. **Rolling-origin backtest:** at each forecast date (monthly origins, weekly origins),
   forecast using only data known on that date, then score against what happened.
   Code enforces "no future data" and unit tests check it (`test_leakage_and_backtest.py`).
4. **Compare on identical periods** against persistence, seasonal naive, ETS, SARIMA, and
   against the previous model version. A model must beat the best benchmark (skill > 0),
   not just look accurate.
5. **Report by horizon** (monthly 1/3/6/12, weekly 1/4/13, daily 1/7/14), by origin year,
   and after breaks (outage/recovery bands). Small n (< 12 periods) = "not interpretable".
6. **Choose options without hindsight:** `nested-cv` picks settings year by year using
   only past periods. Hindsight-tagged runs are kept apart (`logs/pfoi_ref`).
7. **Label status honestly:** implemented-and-tested (synthetic) ≠ evaluated (user ran it
   and sent aggregates) ≠ post-test development ≠ confirmed (prospective only).

---

## 1. Check the code first (agent may run; synthetic only)

```bash
# all component unit tests (no DB)
.venv/bin/python -m pytest components/predictive_farm_intelligence/tests -q

# just the new model's tests
.venv/bin/python -m pytest components/predictive_farm_intelligence/tests/test_hybrid.py -q

# frontend type check + build
cd frontend && npm run build && cd ..
```

---

## 2. Generate backtests (the saved error files every comparison reads)

Output goes to `logs/pfoi/` (gitignored). `--jobs 0` = use all cores. Slow; run in background.

```bash
# herd engine: 24-month window, known-data cutoffs, recorded conceptions, 90-day lag
$PFOI.cli backtest-herd --grain both --preset pfoi-1.1 --jobs 0

# milk model on top of it (anchor_first = level from trusted recent days)
$PFOI.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --jobs 0

# same for the 2024-26 post-hoc block (report only, never tune on it)
$PFOI.cli backtest-herd --grain both --preset pfoi-1.1 --block posthoc --jobs 0
$PFOI.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --block posthoc --jobs 0

# variants: exit model, break reset, anchor gate, fast half-life
$PFOI.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --exit-model lactation --jobs 0
$PFOI.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --anchor-gate on --jobs 0
$PFOI.cli backtest-milk --grain both --preset pfoi-1.1 --k anchor_first --borrow-k off --jobs 0
$PFOI.cli backtest-herd --grain both --preset pfoi-1.1 --fast-half-life 3 --jobs 0

# errors by recording regime (shipment / DelPro 2022-24 / gap / from 2024-05) from saved CSVs,
# no database. Pass the monthly + weekly files of ONE run (one exact tag); a glob that matches
# several tags is refused. --model-b compares two models on the same periods.
python -m components.predictive_farm_intelligence.pfoi.regimes logs/pfoi/milk_backtest_errors_{monthly,weekly}_<tag>.csv --model milk_baseline_adaptive

# REJECTED (user, 2026-10-21): persistence blend (M10/T1) is not used for PP1; commands kept for the record.
# persistence blend of an adaptive development run (daily + weekly rows; writes <tag>_bl files)
$PFOI.cli blend --tag herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3

# M10 preview BEFORE any database write (files only, real built documents): derive <version>-blend from the
# built pfoi-1.2.0-dev documents, then draw 1.0.0 vs 1.2.0-dev vs the blend with the recorded outcome
$PFOI.cli blend-outlook
$PFOI.cli compare-runs --origins 2019-06-01 2020-08-01 2023-11-01 2024-01-01 2024-07-01 2026-08-01 \
    --base pfoi-1.0.0 --candidate pfoi-1.2.0-dev --also pfoi-1.2.0-dev-blend --grain week
$PFOI.cli compare-runs --origins 2019-06-01 2020-08-01 2023-11-01 2024-01-01 2024-07-01 2026-08-01 \
    --base pfoi-1.0.0 --candidate pfoi-1.2.0-dev --also pfoi-1.2.0-dev-blend --grain day

# M10 charts, tables and robustness check from the saved error files (dev + offline post-hoc replay):
# forecast-date panels in the page style, ratio and regime bars, weekly timeline; writes docs/figures/m10_*.png
# and docs/data/m10_blend_*.csv. --origins picks the forecast dates (nearest scored Monday is used).
python components/predictive_farm_intelligence/docs/make_blend_figures.py
python components/predictive_farm_intelligence/docs/make_blend_figures.py --only-panels --origins 2020-08-03 2022-11-28 2024-07-01

# daily/weekly path (reconciled to months)
$PFOI.cli backtest-path --block development
$PFOI.cli backtest-path --block posthoc

# quick smoke test: every 6th origin instead of all
$PFOI.cli backtest-herd --grain monthly --preset pfoi-1.1 --every 6 --jobs 0
```

Window options: `--window 12|24|36|expanding`. Use a **new `--out <folder>`** for any
experiment you do not want to mix with the main results.

---

## 3. Correction layers (optional add-ons on top of the backtests)

```bash
# Layer 1: adaptive level (bias/level correction from past errors)
$PFOI.cli adapt --family both

# Layer 2: drivers (heat/THI, rain, health, sensors, quality)
$PFOI.cli drivers --tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90

# Does an added piece help? same periods, one rung at a time
$PFOI.cli evidence-ladder --grain weekly --rung "current=<TAG>:milk_baseline_adaptive" \
    --rung "+ heat=<TAG_WITH_HEAT>:milk_baseline_adaptive_drivers"

# outage simulation (how bad after missing milk days)
python -m components.predictive_farm_intelligence.pfoi.outage_sim --preset pfoi-1.1 --anchor-gate on --every 2 --jobs 0

# break reset check
$PFOI.cli break-reset --preset pfoi-1.1
```

---

## 4. Score it against the agreed targets

```bash
# development block scorecard (accuracy, skill, bias, coverage, width, recovery)
$PFOI.cli scorecard --block development --preset pfoi-1.1 --k anchor_first

# with adaptive conformal intervals (ACI)
$PFOI.cli scorecard --block development --preset pfoi-1.1 --k anchor_first --intervals aci

# 2024-26 post-hoc (report only)
$PFOI.cli scorecard --block posthoc --preset pfoi-1.1 --k anchor_first --intervals aci

# choose options year by year, past data only
$PFOI.cli nested-cv --family both

# H1 / report tables from finished backtests
$PFOI.cli milk-report
$PFOI.cli herd-report --preset pfoi-1.1

# where does the error come from? (by issue year, target year, break)
$PFOI.error_diagnostics --tag <MILK_TAG> --model milk_baseline_adaptive \
    --herd-tag <HERD_TAG> --quality on --out logs/pfoi_1_1_clean
```

**What to send back to the chat:** the printed tables only (MAE by horizon, scorecard
"targets" tables, band and recovery tables, nested-cv tables). Never files or rows.

---

## 5. Run a brand-new model (example: PFOI 1.3 hybrid)

A new model = new module + new tests + a runner that writes to a **new output folder**.

```bash
# 5a. needs the base errors from section 2 first (tags named in docs/hybrid_1_3.md):
#     herd  w24_ck_kn_rk_lag90_hl6
#     milk  herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6

# 5b. development replay 2017-2023
$PFOI.hybrid_runner --block development --start 2017-01-01 --end 2024-01-01 \
    --backtests logs/pfoi --out logs/pfoi_hybrid_1_3_dev_v1

# 5c. post-hoc replay 2024-26 (report only)
$PFOI.hybrid_runner --block posthoc --start 2024-01-01 --end 2026-08-21 \
    --backtests logs/pfoi --out logs/pfoi_hybrid_1_3_posthoc_v1

# 5d. variants: ALWAYS a new --out folder (runner refuses to overwrite)
$PFOI.hybrid_runner --block development --start 2017-01-01 --end 2024-01-01 \
    --exit-model lactation --break-reset --backtests logs/pfoi --out logs/pfoi_hybrid_1_3_dev_v2
```

Then open `<out>/manifest.json` (config + hashes) and send back the printed **metrics,
matched, decisions, recovery, by_origin_year** tables. `hybrid_runner` makes **no DB write**.

Template for the next model: copy the `hybrid.py` / `hybrid_runner.py` / `test_hybrid.py`
pattern, add a doc `docs/<model>.md` (what it is, base identity, evaluation commands,
acceptance, limits), keep it **unfrozen** and **unpublished** until evaluated.

---

## 6. Dates: forecast dates (origins) and the data window

```bash
# forecast dates are first-of-month, several at once:
$PFOI.cli build-outlook --origin 2025-09-01 2026-04-01 2026-08-01 ...

# the 12 dates the page's date picker offers (publish ALL of them for every version):
#   2017-01-01 2019-06-01 2020-08-01 2022-09-01 2023-11-01 2024-01-01
#   2024-07-01 2025-09-01 2025-12-01 2026-04-01 2026-07-01 2026-08-01 (latest)
# compare-runs cannot pair 2025-09, 2025-12, 2026-04 (no clean milk to anchor k),
# so leave those three out of compare-runs only.

# data window constants (pfoi/freeze.py, pfoi/data.py)
#   DATA_START = 2015-08-01    TEST_START = 2024-01-01    DATA_END = 2026-08-21 (exclusive)
# runner window flags: --start YYYY-MM-DD --end YYYY-MM-DD (end exclusive)
# some origins cannot be built (no clean milk to anchor k): use --k anchor_first
```

New data arrives → update `DATA_END` in `pfoi/freeze.py` only after discussing with the
user (it is a frozen-contract constant), then re-run backtests.

---

## 7. Build the outlook (CSV + page document), compare, then write to the DB

```bash
# 7a. BUILD, no DB write. Files land in logs/pfoi/outlook/<version>/
$PFOI.cli build-outlook --origin 2017-01-01 2019-06-01 2020-08-01 2022-09-01 2023-11-01 \
    2024-01-01 2024-07-01 2025-09-01 2025-12-01 2026-04-01 2026-07-01 2026-08-01 \
    --preset pfoi-1.1 --k anchor_first --fast-half-life 3 --exit-model lactation \
    --break-reset on --intervals aci \
    --staleness logs/pfoi/outage_sim/outage_staleness_pfoi-1.1_herd_fitted_p1_g0_kfg_weekly_every2.csv

# 7b. COMPARE two versions at the same forecast dates (needs both builds from 7a)
$PFOI.cli compare-runs --origins 2017-01-01 2019-06-01 2020-08-01 2022-09-01 2023-11-01 \
    2024-01-01 2024-07-01 2026-07-01 2026-08-01 --base pfoi-1.1.0 --candidate pfoi-1.2.0-dev
# other grains:  --grain week   or   --grain day      (charts in logs/pfoi/compare/)

# 7c. frozen versions + hashes
$PFOI.cli freeze-info

# 7d. WRITE to the DB only after the numbers are checked. Same command + --write
#     (replaces that origin's rows in c1_output.outlook/.attribution/.history/.run_document)
$PFOI.cli build-outlook --origin <same dates> <same flags> --write

# 7e. heat/THI forecast refresh only (does not rebuild milk/herd)
$PFOI.refresh_heat                 # preview, counts only
$PFOI.refresh_heat --write         # persist heat fields
$PFOI.refresh_heat --origin 2026-08-01 --until 2026-08-21
```

DB facts: PostgreSQL `farmx_app`, schema `c1_output`, DDL in `docs/sql/c1_output_tables.sql`,
connection from env vars (`PFOI_DATABASE_URL`), never hard-coded. Each build is keyed by
**forecast date + model version**; the page shows the newest version per date, so publish
the **same set of dates** for a version. Dev builds are labelled `pfoi-1.2.0-dev`, never
under a frozen name. **Not yet wired for DB write:** the 1.3 hybrid (needs its own
publisher plus a shared-contract change; ask the user before touching `shared/schemas`).

---

## 8. Show it on the page

```bash
# backend with DB-backed outlook
PFOI_OUTLOOK_DB=on  <start backend as usual>
# endpoints: GET /api/v1/predictive/pfoi/run | /pfoi/outlook | /pfoi/attribution
# without that flag the page shows a labelled DEMO run

cd frontend && npm run dev
```

---

## 9. Order of work for every new model (checklist)

1. Write the idea + acceptance targets in `docs/<model>.md` **before** any result.
2. Implement in its own module; no research logic in routes or UI.
3. Synthetic unit tests, including a leakage test (future data cannot change the output).
4. Section 1 → full `pytest`.
5. User runs section 2 (base errors) and section 5 (new model) on **development**.
6. Compare on identical periods vs benchmarks, vs previous version, and by ablation
   (does each added piece earn its place? section 3 `evidence-ladder`).
7. Check scorecard targets, calibration, recovery, withheld frequency (section 4).
8. Only then post-hoc 2024-26, labelled "post-test development".
9. Build + compare outlooks (7a, 7b); user decides; then `--write` (7d).
10. Record the result and limits in the doc; update `docs/pp1_plan.md` status.
11. Final confirmation only on the prospective months. Commit on your own branch
    (`git status` first; never commit `logs/`, data, dumps, `.env`).

---

## 10. Rules that never change

- Farm is **"Farm X"**; no real names. Keys `A…`, `B…`, `G…` only.
- Aggregates only in chat, logs and files.
- Demo/synthetic output must be labelled (`"source": "demo"`).
- A failing test or missed target is reported as is, never loosened.
- Ask before: schema/role creation, shared files (`backend/app/core`, `shared/schemas`),
  deleting or renaming anything you did not create, changing frozen constants.
