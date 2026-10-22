# Linear regression baseline vs the current milk model

Question: how would a plain linear regression predict Farm X milk yield, compared with the
current structural model (`current_structural` = `milk_baseline_adaptive`, w12 candidate)?

Status labels (see `command_sheet.md` §0): monthly, weekly and daily development = **evaluated**
(user ran them, aggregates supplied). Monthly post-hoc = **not yet run** (first attempt failed, fixed).

## The candidate

`linear` in `pfoi/forecast_experiments.py`: ordinary least squares, no penalty, 7 inputs:
recent milk level, 7/28/84-day milk ratios, cows milking, month of year (sin/cos).
Target is the daily rate times period length. Refitted at every forecast origin on
completed outcomes only (up to 5 years, minimum 24 examples, same milk source). Same origins,
labels, periods and benchmarks as every other candidate, so the comparison is like for like.
`ridge` (426 raw inputs, alpha 100) is reported alongside as the regularised version.

## Monthly, development block (forecast dates 2019-2023), accuracy = 100 − WAPE %

Same target periods for all three models (`matched` table). n = periods scored.

| Horizon | Year | n | Linear | Persistence | Current model |
|---|---|---|---|---|---|
| 1 month | 2019 | 12 | 96.5 | 96.8 | 97.9 |
| | 2020 | 10 | 96.9 | 96.1 | 96.2 |
| | 2021 | 10 | 93.9 | 96.0 | 97.7 |
| | 2022 | 5 | 81.6 | 87.8 | 90.5 |
| 3 months | 2019 | 10 | 85.9 | 93.0 | 95.1 |
| | 2020 | 10 | 87.1 | 90.0 | 91.0 |
| | 2021 | 10 | 66.1 | 88.6 | 92.4 |
| | 2022 | 5 | 52.2 | 70.7 | 76.9 |
| 6 months | 2019 | 7 | 80.5 | 90.5 | 93.7 |
| | 2020 | 10 | 84.6 | 86.3 | 94.1 |
| | 2021 | 10 | 34.2 | 80.1 | 87.8 |
| | 2022 | 6 | below 0 (WAPE 104) | 51.9 | 71.0 |
| 12 months | 2020 | 10 | 79.6 | 90.0 | 90.8 |
| | 2021 | 10 | 35.9 | 57.8 | 74.7 |
| | 2022 | 6 | below 0 (WAPE 173) | 9.3 | 54.4 |
| | 2023 | 5 | below 0 (WAPE 209) | 5.3 | 18.4 |

Excluded: 12-month 2019 (n = 1). Cells with n < 12 are "not interpretable" by the project
rule; read them as indicative.

### Findings

1. **Short range, stable years:** at 1 month in 2019-2020 linear is within about 1 point of
   the current model and beats it in 2020 (96.9 vs 96.2). From 2021 it falls behind.
2. **Beyond a month:** the current model is 4-54 points more accurate at 3, 6 and 12 months,
   and on the matched monthly periods it is at least as accurate as persistence.
3. **Bias:** linear over-forecasts and the bias grows with horizon and over time (+5 % at
   1 month in 2021, +65 % at 6 months in 2021, +173 % at 12 months in 2022). It keeps
   projecting an old level after the herd has changed. The current model also over-forecasts
   in 2021-2023 but far less.
4. **Coverage:** linear (and ridge) produce no forecast for 2023 at 1-6 months and for some
   2022 months, because fewer than 24 completed same-source examples were available
   (`training_coverage`). The current model has no such gap.
5. **Ridge** is worse than plain linear everywhere (for example WAPE 36 % at 1 month in 2021,
   541 % at 12 months in 2023), so extra inputs without structure made it worse.
6. The current model is not good everywhere: 54 % at 12 months in 2022 and 18 % in 2023.

### Caveats

- Development block only; hindsight design choices were made here, so this is not a
  confirmation. Post-hoc (2024-2026) is reported, never confirmed.
- Small n per cell; no significance test has been run.
- Retrospective ETL revisions cannot be undone (replay, not as-published).
- "Accuracy at each point" is reported per horizon and year, not per forecast date, because
  per-date output would be row-level.

## Weekly, development block, accuracy = 100 − WAPE %

Same target periods for all three models. Weekly forecasts are scored at 1, 4, 8 and 13 weeks.

| Horizon | Year | n | Linear | Persistence | Current model |
|---|---|---|---|---|---|
| 1 week | 2019 | 52 | 97.4 | 98.4 | 98.3 |
| | 2020 | 50 | 97.4 | 97.9 | 97.6 |
| | 2021 | 50 | 97.3 | 97.8 | 97.8 |
| | 2022 | 27 | 91.1 | 94.3 | 94.3 |
| | 2023 | 26 | 90.7 | 90.8 | 90.0 |
| 4 weeks | 2019 | 49 | 93.0 | 96.9 | 96.8 |
| | 2020 | 50 | 93.7 | 95.5 | 94.4 |
| | 2021 | 50 | 91.2 | 95.8 | 96.9 |
| | 2022 | 28 | 82.8 | 87.6 | 91.5 |
| | 2023 | 20 | 79.3 | 81.1 | 70.5 |
| 8 weeks | 2019 | 45 | 88.7 | 95.4 | 95.3 |
| | 2020 | 50 | 88.8 | 92.5 | 91.4 |
| | 2021 | 50 | 80.0 | 92.6 | 95.1 |
| | 2022 | 28 | 72.1 | 82.2 | 86.1 |
| | 2023 | 13 | 82.7 | 66.4 | 33.5 |
| 13 weeks | 2019 | 40 | 83.8 | 93.5 | 94.6 |
| | 2020 | 50 | 83.9 | 90.1 | 89.8 |
| | 2021 | 50 | 63.1 | 88.9 | 93.3 |
| | 2022 | 28 | 54.5 | 75.0 | 77.8 |
| | 2023 | 6 | 68.1 | 69.8 | 62.0 |

### Weekly findings

1. 1 week: linear is within 1 point of the current model in 2019-2021 and level with it in 2023.
2. 4 to 13 weeks: the current model beats linear by 1-30 points in 2019-2022, with the gap growing
   from 2021 as the herd changed. Linear over-forecasts (+20 % at 8 weeks in 2021, +37 % at
   13 weeks in 2021).
3. **2023 reverses at 4 and 8 weeks.** Linear (79.3 and 82.7) beats the current model (70.5 and 33.5)
   on the periods linear could be fitted for (n = 20 and 13). The current model's 2023 weekly
   error is large (WAPE 66 % at 8 weeks, bias +16 %), so it is a real weakness, not only small n.
   Linear only produced forecasts where it had at least 24 completed same-source examples
   (`training_coverage`: 19-28 of ~45 origins skipped in 2023), so this is a favourable subset.
4. Persistence beats or ties the current model at 1 week in most years, and at 4 weeks in 2020
   and 2023.

## Daily, development block, accuracy = 100 − WAPE %

Daily forecasts for 1, 7 and 14 days ahead, issued weekly.

| Horizon | Year | n | Linear | Persistence | Current model |
|---|---|---|---|---|---|
| 1 day | 2019 | 52 | 97.5 | 98.0 | 97.8 |
| | 2020 | 51 | 97.1 | 97.8 | 97.5 |
| | 2021 | 51 | 97.4 | 97.7 | 97.3 |
| | 2022 | 31 | 93.6 | 96.0 | 95.5 |
| | 2023 | 34 | 89.8 | 92.0 | 90.6 |
| 7 days | 2019 | 51 | 96.1 | 97.2 | 97.2 |
| | 2020 | 52 | 96.7 | 97.6 | 97.3 |
| | 2021 | 52 | 96.0 | 96.9 | 97.0 |
| | 2022 | 30 | 90.2 | 93.6 | 94.0 |
| | 2023 | 34 | 87.5 | 89.2 | 88.2 |
| 14 days | 2019 | 50 | 94.9 | 97.0 | 97.1 |
| | 2020 | 52 | 95.7 | 96.9 | 96.1 |
| | 2021 | 52 | 94.6 | 96.7 | 96.8 |
| | 2022 | 31 | 87.2 | 91.3 | 91.6 |
| | 2023 | 32 | 83.3 | 87.7 | 83.1 |

### Daily findings

1. At daily range the three models are close: linear trails the current model by 0.2-2.5 points
   in most cells, and is level or slightly ahead at 14 days in 2023 (83.3 vs 83.1).
2. **Persistence is the best or joint best model at 1 and 7 days in most years.** The current model
   does not beat it at 1 day in 2019-2020 or 2022-2023. The structural model's advantage starts
   at 14 days and beyond, and mainly from 2021.
3. Linear's bias is small at daily range (under +5 %), so its weakness is variance, not drift.
4. Ridge is far worse than all of them again (WAPE 11-13 % at 1 day in 2019-2021, 52 % in 2022).

## Figures and data

Source data: [data/linear_baseline_wape.csv](data/linear_baseline_wape.csv) (herd-level aggregates copied
from the `matched` tables; no animal-level rows). Rebuild with
`python components/predictive_farm_intelligence/docs/make_linear_figures.py`.

| Figure | What it shows |
|---|---|
| [fig1_accuracy_by_horizon.png](figures/fig1_accuracy_by_horizon.png) | Accuracy by horizon, one panel per year and grain, three models. Values below 0 % are drawn at 0 and labelled with the true value |
| [fig2_current_minus_linear.png](figures/fig2_current_minus_linear.png) | Current model minus linear, accuracy points, by horizon and year |
| [fig3_current_minus_persistence.png](figures/fig3_current_minus_persistence.png) | Current model minus persistence, same layout. Shows where persistence is as good (short range) |

Heatmap colour is capped at ±20 points so the large monthly gaps do not wash out the rest; the printed
numbers are the true gaps. `*` marks cells with n < 12. Palette checked with the dataviz validator
(light mode, all checks pass; markers differ by model as secondary encoding).

## Overall picture, development block

| Range | Linear vs current model | Linear vs persistence |
|---|---|---|
| 1 day to 1 week | within about 1-3 points | slightly worse |
| 4 weeks to 1 month | 2-10 points worse, growing from 2021 | worse |
| 3 to 12 months | 10-45 points worse, over-forecasts badly | much worse |
| 2023 weekly 4-8 weeks | better (small, favourable subset) | similar |

Points for the write-up:
- The structural model earns its keep from about 4 weeks ahead, and most clearly when the herd is
  changing (2021-2022). Below that, persistence is as good or better, so the value claim should
  be stated for horizons of 4 weeks and longer.
- A plain regression is a reasonable short-range tool but drifts upward at longer horizons.
- The current model has a genuine 2023 weakness at 4-13 weeks that should be investigated
  (the `milk_baseline_adaptive` level correction and the 2023 break recovery) before PP1 claims.

## Post-hoc run: first attempt failed, fixed

```
ValueError: source uses conception_known='lag' but the configuration asks for 'recorded'
```

Cause: `--generate-structural` replays the fixed w12 candidate (known cut, recorded conceptions,
`day_cell_known`), but `main()` built the data source with the default settings, and the
leakage guard in `load_origin_inputs` refused the mismatch. No results were produced, so nothing
was affected. Fix: when `--generate-structural` is set, the source is now built with
`cell_table="day_cell_known"` and `conception_known="recorded"`. The change is in
`pfoi/forecast_experiments.py` (`main`).

## Commands

`-W ignore` hides the repeated NumPy timedelta deprecation warnings. Use a new `--out` folder
each time (the runner refuses to overwrite; the failed run created no folder).

```bash
# monthly, post-hoc 2024-2026 (report only; regenerates structural forecasts, can take hours)
python -W ignore -m components.predictive_farm_intelligence.pfoi.forecast_experiments \
  --block posthoc --start 2024-01-01 --end 2027-01-01 \
  --grain monthly --models linear ridge \
  --structural-tag herd_fitted_p1_g0_ka_w12_ck_kn_rk_lag90_adhq0.1t365z3 \
  --generate-structural \
  --saved logs/pfoi_1_1_clean --out logs/pfoi_experiments/posthoc_monthly_linear
```

## Run status

| Run | Status |
|---|---|
| monthly, development | done (tables above) |
| weekly, development | done (tables above) |
| daily, development | done (tables above) |
| monthly, post-hoc | not run: first attempt failed, fixed, rerun needed |
