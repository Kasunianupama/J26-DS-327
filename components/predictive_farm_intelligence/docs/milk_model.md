# Milk model (Step 4)

Herd milk = k × Σ over the projected herd (Step 3 engine) of cows × expected yield per
cow-day (lactation curve). Code: `pfoi/lactation_curve.py`, `milk_baseline.py`,
`benchmarks.py`, `error_tools.py`, `backtest_milk.py`. Tests: `tests/test_milk.py`
(synthetic, no database).

## Lactation curve (shape)

| Origin | Shape | Leakage |
|---|---|---|
| from 2020-09 | Wood curve per parity (1, 2, 3+) fitted on reliable cow-days before the origin month (`core.cow_day.is_reliable`, no spikes or missing yields, DIM 5–400), weighted least squares on log yield | none |
| before 2020-09, `--curve published` (default) | Mandal et al. 2026, Jersey crossbred: b = 0.340, c = 0.108 per fortnight → 0.108/14 per day (time unit **assumed** until the full paper is checked); same shape for all parities | none (external knowledge) |
| before 2020-09, `--curve herd_fitted` | one Wood shape (b, c) fitted to the farm's past monthly herd milk, given milking cow-days by DIM per month (grid search, least-squares level, peak day 20–120) on the 24 months before the calibration window, single source | none |
| `--curve fitted_everywhere` | 2020-08 – 2022-12 fitted curve at every origin | **uses later information**: sensitivity only, flagged, excluded from H1 |

Factors (fitted with the curve, from 2020-09 only):

* pregnancy: yield multiplier for cows ≥ 150 and ≥ 200 days pregnant, relative to open
  and early-pregnant cows (`--pregnancy-factor on`, default);
* generation: multiplier per generation (`--generation-factor off` by default; earlier
  aggregates showed no consistent generation difference at matched parity × stage).
  A factor is kept only if the backtest improves.

## Level (k)

k per source (shipments before 2020-08, DelPro from 2020-08) = Σ target litres ÷
Σ (curve litres × scoreable share), over 12 complete months ending two months before the
origin month (so all conceptions in the window had passed the 35-day check before the
origin). Curve litres for past months come from milking cow-days rebuilt from
`core.lactation` (within ~1 % of `day_cell`, check 3). The current source's k is used;
if it has fewer than 3 usable months the other source's k is used and the run is
flagged `source_switch`. Days that are not scoreable are never used or imputed.

## Benchmarks

Persistence (last complete period), seasonal naive (same period last year), ETS (damped
additive trend; additive seasonality with ≥ 2 years of monthly data), SARIMA
(1,0,0)(0,1,1)12 on ≥ 36 unbroken months (monthly only). ETS and SARIMA are also run on
monthly herd counts (n_herd, milking, calvings) in the Step 3 backtest.

## Backtest and intervals

Monthly origins 2017-01 – 2023-12 score months 1/3/6/12; weekly origins (Mondays) score
weeks 1/4/8/13 and days 1/7/14. A period is scored only if every day is scoreable and
from one source. Also reported: `milk_baseline_corrected` (own mean past error removed)
and, for every model, a 90 % interval from the 5 %/95 % quantiles of its own past
relative errors (≥ 12 finished past errors; coverage scored from 2018).

## Commands

```bash
python -m components.predictive_farm_intelligence.pfoi.cli milk-curve --origin 2021-06-01
python -m components.predictive_farm_intelligence.pfoi.cli backtest-milk --grain both
python -m components.predictive_farm_intelligence.pfoi.cli milk-report
```

Same options for all three: `--curve`, `--pregnancy-factor`, `--generation-factor`,
`--window`. Output: herd-level aggregates in `logs/pfoi/` (gitignored).
