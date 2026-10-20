# Runbook: real-data runs before freezing pfoi-1.1 (step E)

Run from the repository root. Development block only; never `--block test`. Every
command prints herd-level aggregates and writes files under `logs/` (gitignored).

**Before you start**

* Finish ETL round 2 first (R-E2, R-E3, R-E5 change milking counts and scoreable days);
  otherwise these runs must be repeated.
* Check that the final-test markers are in `logs/pfoi/final_test/` (copied back after the
  move).

**Names used below**

* Honest herd tag: `w<window>_ck_kn_rk_lag90` (conception cut, `day_cell_known`, recorded
  conceptions, 90-day rate window).
* Honest milk tag: `herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90` (default milk options).
* The pfoi-1.0.0 reference goes to a separate folder, `logs/pfoi_ref`, so `nested-cv` never
  picks a configuration that uses hindsight.

## 1. Reference: pfoi-1.0.0 rules on the new data (separate folder)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --jobs 0 --out logs/pfoi_ref
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --jobs 0 --out logs/pfoi_ref
```

## 2. Honest herd candidates (four windows)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 12 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 24 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window 36 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-herd --grain both --window expanding --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
```

## 3. Honest milk candidates (two windows)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --window 12 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both --window 36 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --jobs 0
```

## 4. Layer 1 (adaptive level) on every honest tag

```bash
python -m components.predictive_farm_intelligence.pfoi.cli adapt --family both
```

## 5. Layer 2 (drivers) on the raw and the adaptive milk forecast

```bash
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90
python -m components.predictive_farm_intelligence.pfoi.cli drivers --tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adpq0.1t365z3 --base milk_baseline_adaptive
```

## 6. Choose year by year (nested, purged)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli nested-cv --family both
```

## 7. Scorecards: reference vs honest, old vs new intervals

```bash
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block development --out logs/pfoi_ref
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block development --window 12 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block development --window 12 --conception-cut known --cell-table day_cell_known --conception-known recorded --pregnancy-lag 90 --intervals aci
```

## 8. Scenarios on the current outlook

The outlook is built by the frozen model, so it reads the reference folder. Do not add
`--write`.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli build-outlook --origin 2026-08-01 --out logs/pfoi_ref
python -m components.predictive_farm_intelligence.pfoi.cli scenarios --tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90 --outlook logs/pfoi_ref/outlook/outlook_202608.csv
```

## What to send back (printed tables only)

| From | Tables |
|---|---|
| 1–3 | "MAE by horizon" of each run (or nothing, if they ran cleanly) |
| 4 `adapt` | "development accuracy, all origins and 0–5 months after a break" |
| 5 `drivers` | feature registry, last coefficients, "development accuracy, herd milk" (both runs) |
| 6 `nested-cv` | both tables, herd and milk |
| 7 `scorecard` | the three "development block: targets" tables, plus the band and recovery tables of the last one |
| 8 `scenarios` | episode library, response table, the sentences, monthly scenario table |

With these, step E chooses the pfoi-1.1 configuration (from the nested results),
freezes it, reports 2024–26 as post-hoc and sets up the prospective holdout.
