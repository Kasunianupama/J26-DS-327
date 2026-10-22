# Layer 2: cow-level lactation model (experimental, synthetic only so far)

Status 2026-10-22. Code: `pfoi/cow_layer.py`. Tests: `tests/test_cow_layer.py` on the
SYNTHETIC herd in `tests/synthetic_cows.py`. Nothing has been run on Farm X data yet.

## Why

The daily milk record is a sample of the milking cows (about 20–80 of 1,000–1,900 before
2022, about 300 of 400 from June 2026). Litres per recorded cow mixes yield with *which*
cows were recorded, and any herd-level series model learns that noise. Layer 2 models one
cow-day and predicts every milking cow, recorded or not:

    ln litres = curve(parity, DIM) + pregnancy effect + cow effect + noise
    herd litres(day) = Σ over all milking cows of predicted litres

No lagged yield is used, so predictions cross the 2022–2026 recording gap.

## Two glass-box models, same inputs

| Model | Form | What you can read |
|---|---|---|
| `wood` | Linear mixed model in log space: `ln a_p + b_p ln DIM − c_p DIM − s·max(days pregnant − 150, 0) + u_cow` (statsmodels MixedLM, REML, random intercept per cow) | a, b, c, peak day, peak litres and 305-day litres per parity; pregnancy slope; cow and residual variance (`WoodMixed.summary()`) |
| `ebm` | Explainable Boosting Machine on ln litres (DIM, parity, days pregnant; optional extra columns) + empirical-Bayes shrunken cow effect | term importances and one shape curve per term (`EbmCow.importances()`, `.shape(term)`) |

Both use the same retransformation: known cow `exp(η + u) × smear_known`, cow never seen in
training `exp(η) × smear_marginal` (Duan smearing on training residuals).

Usable record: litres > 0 and ≤ 18 L, DIM 5–400, parity 1 / 2 / 3+, not in the excluded or
gap period. Placeholder herd totals are never cow records and are never used.

## Date split (from the user's monthly aggregates, 2026-10-22)

| Period | Dates | Use | Evidence (monthly aggregates) |
|---|---|---|---|
| excluded | before 2016-01-01 | none | herd still building (5 → 650 milking cows) |
| train | 2016-01-01 – 2020-12-31 | fit | 24–31 days a month with records, about 23–80 cows a day |
| validate | 2021-01-01 – 2022-04-30 | tune, compare models | thins from 2021-09 (about 20 cows a day); 2022-01..04 only 12–16 days a month. Herd-day scores use only days with ≥ 20 cows |
| gap | 2022-05-01 – 2026-03-31 | never fitted or scored | fragments at 5–8 L per cow (2022–24); 2025-04..2026-03 milk days are placeholder-only (≈ 0 cows recorded) |
| recalibrate | 2026-04-01 – 2026-05-31 | level factor only | about 20 then 50 cows a day |
| test | 2026-06-01 – latest | scored **once**, only with `score_test=True` | about 190–310 of about 400–440 milking cows a day; 38 near-full days |

The boundaries are in `CowSplit` (one place) and covered by a unit test.

**Known risk:** litres per recorded cow falls from about 12–13 L (2016–18) to about 9 L
(2021). A curve fitted on 2016–2020 will probably over-predict validation and test. The
recalibration level factor (Layer 5 seed) measures that; it is reported, not hidden.

## Synthetic results (fictional herd; shows the code works, not a Farm X result)

- Wood recovers the true synthetic b, c, peak day and pregnancy slope (b within 0.02, c
  within 0.0004 per day).
- With recording biased toward late lactation, "mean of recorded × milking" is off by
  13.5% on ordinary sample days (selection bias −10.7%); the summed cow model is off by 0.1%.
- Cow-day MAPE: train 7.9%, validate 9.0% (Wood); EBM 8.1% / 9.4%. The synthetic test cows are all
  new (no cow effect), so test MAPE is about 13%.

## Outputs (aggregates only)

`run_layer2(frame, split, models, score_test, ebm_kwargs)` returns cow-day scores by
period (cow-days, cows, MAE, bias, MAPE, share within ±10%), herd-day scores (MAPE of
the summed prediction for the recorded cows, selection bias), level factors and the
share of scored cow-days from cows seen in training. No cow-level rows are returned.

## Input check 1 (user's yearly aggregates, 2026-10-22)

| Year | Valid cow records ≤ 18 L | % in a lactation | % DIM 5–400 | Parity 1 / 2 / 3+ | Mean DIM | Mean litres |
|---|---|---|---|---|---|---|
| 2016 | 21,767 | 96.4 | 96.2 | 20,899 / 85 / 0 | 181 | 12.16 |
| 2017 | 14,441 | 97.1 | 70.9 | 7,406 / 6,570 / 49 | 249 | 10.70 |
| 2018 | 16,690 | 98.6 | 88.9 | 2,444 / 10,380 / 3,632 | 207 | 11.03 |
| 2019 | 18,875 | 98.5 | 89.2 | 4,021 / 3,107 / 11,464 | 193 | 11.00 |
| 2020 | 15,851 | 96.9 | 86.1 | 3,898 / 2,118 / 9,342 | 218 | 10.76 |
| 2021 | 12,474 | 94.1 | 81.4 | 3,901 / 2,011 / 5,821 | 215 | 9.23 |
| 2022–25 | 8,256 | 87–98 | 73–90 | small | 155–211 | 6.5–11.9 |
| 2026 | 77,132 | 91.6 | 40.8 | 43,242 / 7,689 / 19,758 | 385 | 6.41 |

What it shows:

1. **2016–2021 has about 100k cow records, 94–99% inside a lactation.** Training on
   2016–2020 is possible; Layer 2 does not depend on `core.cow_day.is_reliable` (from 2020-08).
2. ~~Parity is the on-farm lactation count~~ **Corrected by check 2:** the 2016 parity-1
   cows were real heifers (mean age at calving 2.2 years, 0% older than 3.5 years). The
   herd was built from young stock and moved through parities together, so parity is usable.
3. **Cow-level litres fall from 12.2 (2016) to 9.2 (2021)** at a similar mean DIM, so the
   drop is not explained by lactation stage. Expect over-prediction in validation unless a
   cohort / age term or the level factor absorbs it.
4. **The 2026 row is wrong because of the query.** The join accepted every lactation with no
   dry-off or end date, so a record can match several lactations (rows duplicated, DIM
   counted from an old calving). That explains 77k records, mean DIM 385 and only 40.8% in
   DIM 5–400. Check 2 picks only the latest calving on or before each record.
5. Conception is known for 24–44% of records. Days pregnant is only partly observed, so
   the pregnancy term must treat "unknown" separately from "open".

## Input check 2 (latest calving per record; user's aggregates, 2026-10-22)

| Year | Records | Duplicate cow-days | % with calving | % after dry-off | % DIM 5–400 | % DIM > 400 | Median DIM | Age at calving (y) | % parity 1 older than 3.5 y | % pregnancy known | Mean litres |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016 | 21,767 | 0 | 96.5 | 0.1 | 96.3 | 0.4 | 182 | 2.2 | 0.0 | 26.3 | 12.16 |
| 2017 | 14,441 | 0 | 98.8 | 1.8 | 70.0 | 22.5 | 259 | 2.8 | 0.3 | 47.0 | 10.70 |
| 2018 | 16,674 | 0 | 99.5 | 1.0 | 88.2 | 5.9 | 213 | 3.7 | 0.7 | 35.4 | 11.03 |
| 2019 | 18,849 | 2 | 99.7 | 1.3 | 88.4 | 7.0 | 188 | 4.3 | 0.3 | 33.4 | 11.00 |
| 2020 | 15,812 | 1 | 99.3 | 2.6 | 84.4 | 11.3 | 215 | 4.6 | 0.1 | 30.0 | 10.76 |
| 2021 | 12,360 | 6 | 99.0 | 5.5 | 77.7 | 17.6 | 196 | 4.6 | 0.2 | 31.2 | 9.23 |
| 2022–25 | 7,374 | 13 | 99.6–100 | 2.9–29.5 | 54–89 | 4–44 | 123–395 | 5.2–8.5 | 0–4.3 | 22–39 | 6.5–9.0 |
| 2026 | 24,346 | 1,518 | 84.0 | 62.8 | 79.9 | 18.2 | 199 | 5.3 | 16.1 | 98.7 | 8.87 |

Findings:

1. **Train and validate (2016–2021) are clean:** 96–99.7% with a calving, ≤ 5.5% after a
   dry-off, almost no duplicates, birth date known for all.
2. **2017 and 2021 have many long lactations** (22.5% and 17.6% beyond DIM 400). They are
   outside DIM 5–400 and not fitted; the Wood curve is not extrapolated past 400.
3. **The cow-level yield decline (12.2 → 9.2 L) happens while the herd ages** (age at
   calving 2.2 → 4.6 years) and parity moves to 3+. Older cows usually give more, so the
   decline is a herd or management effect, not composition. Expect the 2016–2020 curve to
   over-predict 2021; the validation bias will measure it.
4. ~~2026 calving records are not usable~~ **Corrected by check 3.** Check 2 used
   `AVG(boolean)` and PostgreSQL skips NULLs, so "% after dry-off" (62.8%) and "% pregnancy
   known" (98.7%) were shares of records *with* a dry-off / conception date, not of all
   records. See check 3.

## Input check 3 (2025–26; user's aggregates, 2026-10-22)

| Query | Result |
|---|---|
| 3a duplicated cow-days (all valid records from 2025) | 57 cow-days, up to 41 rows each, 0% identical values, mean spread 347 L, mean largest 350 L, mean sum 499 L |
| 3b 2026 records after the recorded dry-off (≤ 18 L) | 2,694 records (11% of 24,346), 86 cows, median 434 days after the dry-off, calving overdue (conception + 300 d passed) for 69.5%, no conception 11.3%; dry-offs from 2023-05-15 to 2026-08-07 |
| 3c calvings / dry-offs per year | 2019 1,655 / 1,384 · 2020 1,406 / 1,454 · 2021 1,246 / 1,262 · 2022 1,323 / 1,014 · 2023 1,000 / 934 · 2024 436 / 643 · 2025 534 / 444 · 2026 (to Aug) 287 / 298 |

Findings:

1. **The duplicates are not cows.** Hundreds of litres per "cow-day" and up to 41 rows per
   day are herd-total placeholder records. Real cows have no duplicate cow-days. The loader
   drops placeholder animals (`core.animal.is_placeholder`); `prepare_cowdays` also drops an
   `is_placeholder` column if one is passed.
2. **About 86 cows (about 20% of the 2026 milking herd) have a missing calving.** They are
   milking a median 434 days after their recorded dry-off, and most are overdue to calve.
   Their DIM is unknown, so they are not fitted or scored. In the herd sum they get that
   day's mean prediction for the cows with a known DIM, and `herd_daily.dim_unknown` counts
   them so the estimated share stays visible.
3. **Calvings are not broadly under-recorded.** Calvings per year follow the herd size
   (about 1,300–1,650 with about 1,500 milking cows; about 430 a year in 2025–26 with about
   400). The gap is specific cows, not a whole period.
4. **The test period is usable:** about 24k cow records in 2026, about 11% after a dry-off and
   about 16% without a calving, excluded. Test scores cover cows with a known DIM only;
   say so when reporting.

## How to run on Farm X (the user runs it; aggregates only)

Loader: `pfoi/cow_data.py`. One row per milking cow-day from `core.lactation` (calving to
the day before dry-off / end / exit / next calving), joined to the cow's valid
`core.animal_daily` record. Records outside every milking interval are kept as milking
cow-days with unknown DIM (`after_dry_off`, or parity `unknown` with no calving).
Placeholder animals and bad dates are excluded; a cow with more than one record on a
day gets no litres that day.

**Exception to `data.py`'s aggregate-only rule (approved by the user, 2026-10-22):** a cow-level model has to
fit on cow-days. The query swaps `animal_key` for a per-run integer (`DENSE_RANK`), so keys
never reach Python. Rows exist only in memory and are never printed or written, and every
output file is checked for cow columns before it is written.

```bash
.venv/bin/python -m components.predictive_farm_intelligence.pfoi.cli layer2-cow
```

Expect several minutes: about 4–5 million milking cow-days are predicted. Options:
`--models wood` (skip the EBM), `--ebm-bags 8`, `--ebm-interactions 3`, `--end YYYY-MM-DD`,
`--score-test` (scores 2026-04 onward; **run once, only after train and validate are
reviewed**). Output in `logs/pfoi_mi2/layer2/`:

| File | Content |
|---|---|
| `input_summary.csv` | per year: milking cow-days, mean milking cows, records, usable records, % DIM unknown, usable cows, parity mix, mean litres |
| `cow_scores.csv` | per model × period: cow-days, cows, MAE, bias, MAPE, share within ±10% |
| `herd_scores.csv` | per model × period: days with ≥ 20 recorded cows, MAPE / bias of the summed prediction for the recorded cows, selection bias |
| `herd_daily_<model>.csv` | per day: milking, recorded, actual and predicted recorded litres, predicted herd litres, naive herd estimate, selection bias, DIM-unknown cows (train / validate days only unless `--score-test`) |
| `wood_parameters.csv`, `wood_variance.csv` | a, b, c, peak day, peak and 305-day litres per parity; pregnancy slope, cow and residual variance |
| `ebm_importances.csv`, `ebm_shape_<term>.csv` | EBM term importance and shape curves |
| `level_factors.csv`, `known_cow_share.csv` | recalibration factor; share of scored cow-days from cows seen in training |

Send back the printed tables (they are all aggregates). Questions they answer: does the
cow model beat the naive herd estimate on validation, how large is the selection bias, how
far the 2016–2020 curve over-predicts 2021, and whether Wood and EBM agree on the curve.

## First Farm X run (train / validate; user's printed aggregates, 2026-10-22)

| | Wood | EBM |
|---|---|---|
| cow-day MAPE train / validate | 29.3% / 50.7% | 29.7% / 50.5% |
| cow-day bias validate (L) | +2.24 | +2.18 |
| herd-day MAPE train (1,139 days) | 5.5%, 85% within ±10% | 5.5%, 87% within ±10% |
| herd-day MAPE validate (153 days) | 24.7%, bias +24.7% | 23.8%, bias +23.8% |
| selection bias train / validate | −0.3% / +12.8% | −0.6% / +7.3% |
| level factor 2026-04..05 (actual / predicted) | 0.791 | 0.812 |

Wood (typical cow): peak day 51–53 for every parity; peak 15.2 / 15.7 / 14.1 L and
305-day 3,883 / 3,852 / 3,613 L for parity 1 / 2 / 3+; 74k train cow-days, 3,093 cows.
EBM importance: DIM 0.147, days pregnant 0.019, parity 0.018, interactions ≤ 0.015.

Reading:

1. **Shape and herd summation work.** With the right level, the summed prediction for
   recorded cows is within 5.5% on training days.
2. **The level is the failure, and it is one consistent shift.** Validation over-predicts
   by about 25%, and 2026 needs a factor of about 0.8 (also about 25%). Mean cow litres
   go from 11.6 (train) to 9.7 (validate). Composition does not explain it (check 2: the
   herd got older).
3. **Parity is confounded with calendar time.** Parity 1 is mostly 2016 (the high year) and
   3+ mostly 2019–20, so parity 1 ≥ 3+ here. The curve needs a time-level term during
   fitting before parity effects mean anything.
4. **Selection bias is real in 2021** (+7 to +13%: the recorded cows were at higher-yield
   stages than the herd), almost zero in 2016–20.
5. Single cow-days are noisy (MAPE about 29% even in training); the herd sum averages it out.
6. statsmodels warned "random effects covariance is singular" during optimisation; check
   `sigma2_cow` in `wood_variance.csv`.

## Next step

1. Proposed: fit a calendar level (half-year effect) next to the curve, so shape and parity
   are separated from the drift, and score validation with a trailing level factor from
   the previous 8 weeks of recorded cows (Layer 5 seed, no leakage).
2. Only then: one `--score-test` run on 2026-04 onward.
