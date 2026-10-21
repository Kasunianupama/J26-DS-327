# PFOI 1.3.0-dev: connected specialists with past-error selection

New research candidate, 2026-10-21. Implementation: `pfoi/hybrid.py` and
`pfoi/hybrid_runner.py`. No accuracy result, objective confirmation, causal result,
or interval-calibration claim follows from implementation or synthetic tests.

## Base identity

The existing CLI gives several option combinations the name `pfoi-1.2.0-dev` and
configuration string `dev`. Code alone cannot identify which combination was last
published. This replay therefore records an explicit **1.2 code reference**, using
the current `V11_ENGINE`, `V11_ADAPTIVE`, corrected-herd list, and `V11_MILK` with
`k_mode=anchor_first`: 24-month window, six-month rate half-life, known-data cutoffs,
recorded conceptions, 90-day pregnancy lag, no rejected fast rates or conception shape.
The exit model defaults to the code's `state`; `--exit-model lactation` explicitly
selects the exit-only candidate. `--break-reset` selects the existing origin-known
break reset. Neither is inferred from whichever saved file happens to be newest.

The manifest contains all base and hybrid parameters, configuration hash, core version,
and SHA-256 of every named base-error input. Base correction histories must match the
chosen engine/milk tag. The new version does not overwrite any old build, alter the
frozen test contract, publish to the database, or change frontend/shared contracts.

## Models and connection

1. **Persistence:** latest trusted same-source daily milk value, multiplied by target
   period days. This deliberately implements the user's last-observation benchmark;
   it differs from the existing CLI's last-complete-period mean benchmark. Record this
   difference when comparing existing reports.
2. **History-change model:** recency-weighted ridge predicts relative change from that
   level using recent mean, trend, variability, recording coverage, apparent litres per
   recorded cow, target calendar and lead. Missing trend has an explicit mask.
3. **Pipeline-change model:** adds projected milk level, milking population change,
   calvings and dry-offs from the origin-issued engine. Coefficients and standardization
   are fitted using completed same-source labels only, separately for each target month.
   Initial settings: minimum 24 examples, ridge 10, half-life 180 days. These are
   experimental settings, not measured optima.
4. **Abortion specialist:** discounted recent recorded event counts with a Gamma prior
   shrunk towards older counts. This is a count-intensity model, not a pregnancy-risk
   estimate: complete historical pregnant exposure is not supplied by the daily panel.
   At least 60 usable days in the last 90 and a recent observation are required.
   Missing counts never become zero. A zero recorded count cannot establish recording
   completeness. Gamma-Poisson (negative-binomial) predictive ranges are available for
   the standalone specialist; they assume a stable intensity, not arbitrary outbreak
   dynamics. They are never reused as calibrated ranges for the hybrid.
5. **Connection:** map the abortion specialist's daily intensity onto the known pregnant
   starting population. Select a blend of this hazard and the engine hazard using past
   issued first-month abortion forecasts, then rerun the engine. Pregnancies, calvings,
   milking populations and milk all respond through the same transition equations.
   This count-to-hazard mapping is an explicit assumption. No pregnancy exposure means
   the base hazard is retained. No abortions are pasted onto an incompatible herd path.
6. **Milk combination:** a coarse convex-weight grid compares persistence, coupled
   engine milk, history-change and pipeline-change using identical completed past
   forecast periods. Minimum 12 matched forecasts and a 2% loss improvement over
   persistence are required to depart from persistence. Weights use recency-weighted
   MAE, not the outcome being predicted. Early forecasts without sufficient comparison
   history retain persistence. Raw specialists remain in reports for ablation: a good
   mixture alone does not establish the incremental value of herd structure.
7. **One path:** selected monthly milk totals rescale the coupled engine's daily milk
   shape; weekly/monthly values are aggregated from that daily path. The correction is
   an effective-yield adjustment, not an invented biological change. Herd stocks and
   events remain on the engine's cohort-consistent path. Legacy independent additive
   stock biases are intentionally omitted from the hybrid, while the base reference
   retains its correction layer; assess the resulting accuracy tradeoff explicitly.

Starting-state reconciliation is **not automatically applied**: the current interface
does not provide an independently verified milking-population measurement that can
safely replace state membership. A statistical milk correction does not repair missing
lactations. This remains a data-validation limitation, not a solved modelling result.

## Weak evidence and intervals

Milk features/labels require scoreable records from one source; low-identification or
implausible DelPro days cannot train the specialists. Source changes isolate training
and interval histories. At least 14 trusted days in the last 28 are required and the
latest must be at most seven days old. Otherwise milk is withheld; herd output stays.
The base's milk-withholding decision is also respected.

80%/90% ranges use the hybrid's **own issued** completed forecast errors at that series,
grain, horizon and source (minimum 19). Milk errors are normalized by the origin-known
last-value scale; counts use additive errors. Neither divides by near-zero forecasts
nor exponentiates count residuals. Sparse cases get missing ranges, not zero-width
certainty. Time dependence, overlapping targets and changing models mean these are
empirical ranges requiring coverage/width evaluation, not guaranteed conditional
coverage. Prediction-interval endpoints are not temporally reconciled.

## User-run evaluation

AI agents must not execute these commands on real data. Run from the repository root
in the PFOI Python environment. They read local data, print only aggregate tables, save
only aggregate reports plus configuration, and make no output-database writes. Dependencies
are the component requirements (including SciPy); no neural-network dependency is needed.

The required base development errors are monthly and weekly files for herd
`w24_ck_kn_rk_lag90_hl6` and milk `herd_fitted_p1_g0_kf_w24_ck_kn_rk_lag90_hl6`.
For `--exit-model lactation`, both tags end `_xl`. Missing files stop execution before
opening a connection; different tags are never silently substituted. Existing
`cli backtest-herd` / `backtest-milk` with `--preset pfoi-1.1`, the same exit flag,
and milk `--k anchor_first` generate these files if needed. This can be expensive.

```bash
python -m components.predictive_farm_intelligence.pfoi.hybrid_runner \
  --block development --start 2017-01-01 --end 2024-01-01 \
  --backtests logs/pfoi --out logs/pfoi_hybrid_1_3_dev_v1
```

Review `manifest.json`, then return the printed **metrics, matched, decisions, recovery,
and by_origin_year** tables. Do not send source files or individual records.

For the exit-only or reset comparison, use `--exit-model lactation` and/or
`--break-reset`, a matching base-error directory, and a **new** output directory.
This is a separately identified experiment; do not choose by posthoc results.

```bash
python -m components.predictive_farm_intelligence.pfoi.hybrid_runner \
  --block posthoc --start 2024-01-01 --end 2026-08-21 \
  --backtests logs/pfoi --out logs/pfoi_hybrid_1_3_posthoc_v1
```

Posthoc requires the matching `_posthoc` base files too. Development is replayed first
to initialize the specialists and selection, but printed score and decision tables
are restricted to the requested window. Later completed outcomes can update future
forecasts chronologically. All 2024–26 scores remain post-test development. Warm-up
and replay can be slow: each monthly origin runs the structural engine, with additional
projections for the abortion specialist. No real-data runtime has been measured.

The runner issues monthly origins and scores selected daily/weekly/monthly steps of
that path. It does not reproduce the older weekly-origin backtest schedule. Pairing
with the base uses this same issuance schedule. Incomplete future targets, unverified
milk, missing counts, withheld predictions and missing ranges are counted separately.
Paired skill is computed on the exact same periods; small n is explicitly marked.

## Acceptance and objectives

Keep the existing `targets.md` accuracy, skill, bias, coverage and width targets.
Inspect both issue frequency and error; issuing fewer forecasts is not an accuracy win.
Monthly intervals must also satisfy the existing width limit where applicable. Review
matched MAE and count deviance for abortions, plus downstream calving/milking/milk
errors; an abortion-only improvement cannot justify a harmful connection. Report the
coarse gate's development tuning as exploratory, not an independent confirmation.

* **Patterns:** history-change must demonstrate added skill; planted synthetic recovery
  proves testability only. This version does not establish individual-cow learning.
* **Changing relationships:** pipeline ablation and recovery comparisons must demonstrate
  incremental value over history alone and the base. Associations are not causes.
* **Connected outcomes:** daily/monthly consistency and engine propagation are tested;
  predictive usefulness still needs measured skill. Finance/products remain unsupported
  without the relevant inputs.
* **Weak evidence:** report withheld frequency, coverage and width together. Missing
  intervals are explicit; no claim that widened ranges alone prove confidence.

A prospective evaluation is required before claiming general reliability. The code
does not relabel an unsupported objective as proven and does not auto-promote itself.

## Development result (2026-10-21): not adopted

Status: **tested on the development block (2017-2023), did not beat the 1.2 code
reference, not adopted. `pfoi-1.2.0-dev` remains the model.** Nothing from 1.3 was written to
the database or to `c1_output`; the runner has no database write path. Figures below are read
from the aggregate charts and are approximate; the exact tables are in
`logs/pfoi_hybrid_1_3_dev_v1/` (`matched.csv`, `metrics.csv`). Development block only; the
2024-26 post-hoc replay was not run, and no prospective confirmation exists.

* **Against the 1.2 reference (paired skill, herd milk):** worse at every monthly horizon,
  roughly -7 %, -25 %, -23 % and -54 % at horizons 1, 3, 6 and 12. Better only at weekly
  horizon 4 (about +6 %); worse at weekly horizons 1, 8 and 13 and at daily horizon 1.
* **Against persistence:** about even at monthly horizon 1, modest gains (about +6 % to
  +11 %) at monthly horizons 3-12 and weekly horizons 4-13, but clearly worse at daily
  horizon 1 (about -58 %) and weekly horizon 1.
* **Why:** the history-change and pipeline-change specialists were far worse than
  persistence at monthly horizon 12 (WAPE about 46 % and 37 % against about 27 %), and the
  past-error selection still gave them weight, so the blend sat above the coupled/1.2 engine
  (about 25 % against about 16 % WAPE at monthly horizon 12).
* **Intervals:** coverage was near or above nominal except the 80 % range at monthly
  horizon 12 (about 61 %). Widths were not assessed.
* **Selected forecast dates (2017-01, 2019-06, 2020-08, 2022-09, 2023-11):** milk MAE was
  lower than 1.2-dev at four of five dates, higher at 2020-08; herd counts and calvings were
  mixed to worse. With 2-4 periods per date this is illustrative only (n < 12) and does
  not change the full-block result.

Limits: monthly-origin issuance differs from the weekly-origin backtests; one development
configuration was run (`state` exit model, no break reset); no tuning followed the results.
