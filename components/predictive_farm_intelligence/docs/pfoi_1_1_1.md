# pfoi-1.1.1: the 12-month outlook at every grain

Decided by the user on 2026-10-20, for PP1. Code: `outlook.reconcile`, `outlook.path_horizons`,
`path_backtest.py`, `freeze.V111_*`; tests: `tests/test_pfoi_1_1_1.py`.

## What changes and what does not

* **Unchanged from pfoi-1.1.0:** the engine (24-month recency-weighted rates, known
  conceptions), the milk model, the correction layer, and therefore **every monthly value**
  (tested to be identical).
* **New:** the outlook is published for the next 12 months at every grain: 365/366 days,
  every complete Monday week inside the 12 months (51 or 52), and 12 months. Days and weeks
  now carry every series (milk, the herd stocks, herd events, expected mastitis), not just
  milk for 14 days.

The engine always ran daily for 12 months (the monthly horizon needs it); earlier versions
only published 14 of those days and 13 weeks.

## Reconciliation: top-down from the corrected months ("option b")

1.1.0 corrects each grain and horizon separately, so corrected days would not add up to
corrected months. 1.1.1 uses one rule everywhere:

* for each of the 12 months and each output column,
  `factor = corrected month (1.1.0 layer) / structural month`;
* every day of that month = structural day × factor (if the structural month is zero and
  the correction is not, the difference is spread evenly over its days);
* weeks are sums (events, milk) or means (stocks) of those days.

Consequences, all unit-tested: days add up exactly to the 1.1.0 months; weeks add up
exactly to their days; the engine's day-to-day shape is kept within a month (one factor per
month); without a correction layer the path is the structural forecast. The per-grain daily
and weekly correction terms are **not** used.

Alternative (a), keeping per-day corrections for days 1–14, was rejected by the user: it
breaks the month total or forces a step at day 15, and it is harder to explain.

## Ranges for days and weeks: from the published forecast's own errors

The weekly-origin backtests score a different forecast (per-grain corrected, Monday
origins, days 1/7/14 and weeks 1/4/8/13 only). Borrowing their ranges for day 300 would be
too narrow. `backtest-path` therefore replays the 1.1.1 forecast itself at every monthly
forecast date:

1. frozen 1.1.0 engine and milk model, facts before the origin only;
2. correction layer from backtest errors whose period ended by the origin
   (`build_output_layer`, the same code as the published run);
3. reconcile, then score days 1/7/14/30/61/91/182/273/365 and weeks 1/4/8/13/26/39/51
   against the recorded herd panel and herd milk (week 52 uses the week-51 errors). A milk period
   is scored only when every day is scoreable and from one source.

Rows are written for `pfoi_reconciled` (published) and `pfoi_structural` (no layer), with
5 %/95 % ranges and coverage from each model's own past errors (period ended by the
origin, at least 12). The published daily and weekly ranges use the `pfoi_reconciled`
errors at the next scored horizon at or above the requested step. **A series with no such
errors gets no range and is flagged "limited"; ranges are never borrowed from another
forecast.** Monthly ranges are unchanged from 1.1.0. Expected mastitis keeps its
rate-based range (recent vs reference rate).

Leakage: tested by tripling every synthetic value after the first forecast date; that
date's forecasts do not move, only the recorded outcomes do.

## What the daily values mean (say this at PP1)

A day 200 days ahead is the model's **expected level** for that day: herd size ×
lactation stage × the month's correction. It is smooth by construction and does not
predict a particular day's swings (weather spikes, a missed shipment). The 5–95 % range,
learned from how far real days fell from this path at the same reach, is what to read far
ahead. Daily event counts (around 0.1–0.5 calvings a day) are expected values. Their
weekly and monthly sums are the useful view.

## Evidence status

* Development block (origins 2017-01 – 2023-12): `backtest-path --block development`.
* 2024-26: `--block posthoc`. 1.1.1 was decided after 2024-26 had been looked at, so these
  scores are **post-hoc**, like 1.1.0's. pfoi-1.0.0 keeps its run-once final test.
* Months published after 2026-08-20 are the prospective holdout.

## Runbook (run from the repository root; aggregates only)

The 1.1.0 backtest error files must already be in `logs/pfoi/` (tag
`w24_ck_kn_rk_lag90_hl6`), as used by `build-outlook --preset pfoi-1.1`.

```bash
python -m components.predictive_farm_intelligence.pfoi.cli backtest-path --block development
python -m components.predictive_farm_intelligence.pfoi.cli backtest-path --block posthoc
python -m components.predictive_farm_intelligence.pfoi.cli build-outlook --preset pfoi-1.1.1 --origin 2026-08-01
```

Each `backtest-path` run prints, for milk, milking cows, total herd and calvings: n, MAE,
MAPE %, bias and 90 % coverage % by grain × horizon × model. The files
(`logs/pfoi/path_backtest_errors_w24_ck_kn_rk_lag90_hl6[_posthoc].csv`) stay local and
gitignored. Send back the printed tables. After checking the `build-outlook` numbers, add
`--write` to publish 1.1.1 next to the earlier versions. The page shows the newest build
for each forecast date.

Optional: run `build-outlook --preset pfoi-1.1.1` for each earlier forecast date the page
offers (for example `--origin 2024-07-01`), so the "Forecast as of" picker also shows
realised daily outcomes.

Check on the published tables (aggregates only):

```sql
-- rows per grain and series for the 1.1.1 outlook (expect 365/366 daily, 51-52 weekly, 12 monthly)
SELECT grain, series, COUNT(*) AS n, MIN(horizon) AS h_min, MAX(horizon) AS h_max,
       SUM((lower IS NULL)::int) AS no_range
FROM c1_output.outlook
WHERE model_version = 'pfoi-1.1.1' AND origin_date = DATE '2026-08-01'
GROUP BY grain, series ORDER BY grain, series;

-- days add up to months (expect max_abs_diff close to 0 for herd milk)
WITH d AS (
  SELECT date_trunc('month', target_period)::date AS m, SUM(forecast) AS daily_sum
  FROM c1_output.outlook
  WHERE model_version = 'pfoi-1.1.1' AND origin_date = DATE '2026-08-01'
    AND grain = 'daily' AND series = 'herd_milk'
  GROUP BY 1)
SELECT COUNT(*) AS months, MAX(ABS(d.daily_sum - o.forecast)) AS max_abs_diff
FROM d JOIN c1_output.outlook o
  ON o.target_period = d.m AND o.grain = 'monthly' AND o.series = 'herd_milk'
 AND o.model_version = 'pfoi-1.1.1' AND o.origin_date = DATE '2026-08-01';
```

## Results (aggregates supplied by the user, 2026-10-20)

`backtest-path`, 84 development forecast dates (2017-01 – 2023-12); 32 post-hoc dates
(2024-01 – 2026-08, of which 16–17 had a forecast and few milk periods were scoreable).
MAE in L/period for milk, head for stocks, events for calvings; coverage of the 90 % range.

Development, reconciled (published) vs structural:

| Series | Step | Reconciled MAE (MAPE) | Structural MAE (MAPE) | Reconciled coverage |
|---|---|---|---|---|
| Milk | day 1 | 496 L (4.3 %) | 438 L (3.4 %) | 82 % |
| Milk | day 91 | 1,519 L (14.4 %) | 1,915 L (18.9 %) | 77 % |
| Milk | day 182 | 2,495 L (23.4 %) | 3,168 L (32.4 %) | 71 % |
| Milk | day 365 | 2,705 L (31.0 %) | 2,901 L (38.4 %) | 52 % |
| Milk | week 13 | 10,550 L (13.9 %) | 13,611 L (18.5 %) | 75 % |
| Milk | week 51 | 18,376 L (28.2 %) | 20,001 L (35.6 %) | 49 % |
| Milking cows | day 1 | 15.6 (1.2 %) | 6.3 (0.5 %) | 88 % |
| Milking cows | day 182 | 107.6 (9.0 %) | 116.7 (9.9 %) | 69 % |
| Total herd | day 1 | 18.6 (0.6 %) | 4.9 (0.2 %) | 96 % |
| Total herd | day 91 | 103.0 (3.4 %) | 81.0 (2.7 %) | 97 % |
| Calvings | week 1 | 4.8 (19 %) | 5.9 (25 %) | 89 % |
| Calvings | week 39 | 10.4 (40 %) | 8.1 (32 %) | 76 % |

Reading:

* **Milk:** reconciliation reduces error and bias from day 61 and week 4 onward (for example
  MAPE 23 % vs 32 % at day 182). It is slightly worse in the first week (4.3 % vs 3.4 % at
  day 1), because a whole-month factor also moves the first days.
* **Herd stocks:** worse at days 1–7 (milking cows 1.2 % vs 0.5 %, total herd 0.6 % vs 0.2 %).
  The month's head-count correction is applied from day 1, although the starting herd is
  almost known. Small in percentage terms. Mixed at longer steps, with lower bias and
  higher coverage.
* **Coverage** is below the 90 % target at long steps (milk 49–52 % at a year ahead), so the
  far daily and weekly ranges are too narrow. Read them as a lower bound of the uncertainty.
* **Post-hoc 2024-26** (n 1–17, most months in the recording gap): the total herd drifts in
  both models (coverage 6 % at a year ahead). This is not evidence for or against
  reconciliation.

`build-outlook --preset pfoi-1.1.1 --origin 2026-08-01`: 2,568 outlook rows, 5,992 page
forecasts; realised outcomes on 260 days (259 scoreable) and 26 weeks.
