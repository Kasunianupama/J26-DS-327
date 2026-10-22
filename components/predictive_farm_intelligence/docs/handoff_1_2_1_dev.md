# Handoff prompt: pfoi-1.2.1-dev, damped-trend yield correction (2026-10-22)

Paste everything below the line into a new chat started in the repository root.

---

Read `components/predictive_farm_intelligence/CLAUDE.md` (and the root `CLAUDE.md` / `AGENTS.md` it
pulls in) and follow it exactly: no database access, never read `.env`, aggregates only, "Farm X"
naming, work one step at a time and stop after each step. Do not open anything under `logs/`, except
`.png` charts in `logs/pfoi/compare/` (and its subfolders) if I ask you to look at them. Those are
herd-level charts and I have given permission for that folder only. I run every real-data command
myself and paste back herd-level tables.

## Where things stand (PFOI, Component 1, branch `tiyani_Component_1`, uncommitted work)

- The current model is **pfoi-1.2.0-dev** (milk = herd engine cows x lactation curve x level k, plus
  the adaptive correction `milk_baseline_adaptive`, `pfoi/adaptive.py`). Its development error files
  are `logs/pfoi/milk_backtest_errors_{monthly,weekly}_herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6_adhq0.1t365z3.csv`
  (raw, without correction: same tag without `_adhq0.1t365z3`). Herd files:
  `herd_backtest_errors_{monthly,weekly}_w24_ck_kn_rk_lag90_hl6.csv`.
- Rejected, keep code off, do not re-propose: persistence blend (M10/T1), the 1.3 hybrid, the anchor
  trust gate (M3), THI heat (M5), the neural GRU model (`pfoi/neural.py`, tested 2026-10-21: flat,
  biased high, worse than 1.2.0-dev). Never mix persistence into the forecast; it is a benchmark only.
- New measurement tools (built and tested, synthetic tests pass):
  - `hit-rate` (`pfoi/hit_rate.py`): share of milk forecasts within ±5 % / ±10 %, trusted record
    periods vs unverified/gap (quality bands from `pfoi/episodes.py`).
  - `milk-error-split` (`pfoi/error_split.py`): milk log error = cow-count part + yield-per-cow
    part, with hindsight ceilings, and yield error by calendar month and by forecast year.
- **My target for 1.2.1-dev:** 85 % of milk forecasts within ±10 % at every horizon, including
  week 13 and months 6–12. Do not change the tolerance or the definition.
- Baseline and findings are recorded at the end of `components/predictive_farm_intelligence/docs/pp1_plan.md`
  (sections "pfoi-1.2.1-dev: target and baseline" and "Error split result"). In short (development
  2017–2023, trusted periods, within ±10 %): day 1/7/14 0.92/0.89/0.83; week 1/4/8/13
  0.93/0.78/0.66/0.55; month 1/3/6/12 0.90/0.67/0.53/0.43.
  - Yield per cow is 85–93 % of the squared milk error; cow-count error is small (1–8 %).
  - If yield were exact: week 4 0.99, week 13 0.81, month 3 0.86, month 6 0.72, month 12 0.71.
    So months 6–12 need both parts improved; yield first.
  - Yield error by forecast year: 2018–2019 small (about −9 % to +1 %); 2017 +13–16 % (herd expansion);
    2020 month 12 +17 % (source switch Aug 2020); 2021–2022 month 12 +37 % to +48 % (yield per cow
    fell steadily for about two years while the correction held it flat); 2023 −21 % at week 13 /
    month 3 (rebound). Seasonality is weak and confounded with years (about 5 periods per cell).

## Task: first 1.2.1-dev change, a damped trend in the yield correction

1. Read `pfoi/adaptive.py`, `pfoi/nested_cv.py`, the `adapt` command in `pfoi/cli.py`, and
   `docs/layer1_adaptive.md`. The adaptive correction runs offline on the backtest error files, so
   variants need no engine reruns.
2. Add a **damped local-linear-trend** option to the adaptive level (two extra parameters: trend
   noise and damping phi; phi = 1 is not allowed, phi = 0 or the option off must reproduce today's
   `milk_baseline_adaptive` exactly). It may use only errors whose period had ended by each forecast
   date. Give it its own model name and tag; do not change the pfoi-1.0.0 / 1.1.0 frozen hashes.
3. Choose the trend settings **year by year on earlier years only** (`nested_cv.py`), not on the
   years being scored.
4. Add **hit rate by forecast year** to the `hit-rate` output, so stable years and regime changes
   are reported separately.
5. **Keep rule (fixed before any real run):** keep the trend only if, on development origins
   2017–2023 with trusted periods, the share within ±10 % rises at week 13 and months 3, 6 and 12,
   does not fall at week 1 or month 1, and no single forecast year gets worse by more than 5
   percentage points. Otherwise record it as tested and dropped in `pp1_plan.md` (code kept, off).
6. Unit tests on synthetic data only (`pytest -p components.predictive_farm_intelligence.tests.no_database`).
   They must show that the off setting reproduces the current correction exactly, that no future
   error is used, and that a synthetic steady decline in yield is followed while a flat series is not
   disturbed.
7. Then give me the exact commands (adapt variant, then `hit-rate --models milk_baseline_adaptive
   <new model> persistence`, then `milk-error-split --milk-model <new model>`) and stop. I will run
   them and paste the tables.

Context on timing: PP1 is Fri 2026-10-23. If the trend fails its keep rule, the PP1 finding is the
diagnosis above (the model is accurate in stable years; misses come from regime changes, measured by
the error split), which stands on its own.
