# Layer 1: adaptive level (H4)

Code: `pfoi/adaptive.py`; tests: `tests/test_adaptive.py` (synthetic). Target: recover
after a break within 0–2 months (weekly herd milk 4 weeks ahead ≥ 90 %; pfoi-1.0.0:
67.2 %, see `targets.md`).

## Method

The structural forecast (herd engine or milk baseline) is kept and multiplied by
(1 + x). x is the current level of the model's relative error (actual ÷ forecast − 1),
estimated by a local-level Kalman filter over the errors whose target period had ended by
the origin. Nothing after the origin is used (tested).

* **Drift scaled by time.** Between two finished errors the level's variance grows by
  `q30` × (robust error variance) per 30 days. After a data gap the first new errors
  therefore move the level quickly.
* **Fading.** With `tau` (default 365 days) the level decays towards 0, so a correction
  learned before a long gap fades unless new errors confirm it.
* **Break response.** Two successive errors more than 3 standard deviations from the
  level reset its variance, so a regime change is followed within weeks.
* **Pooled or per horizon.** Pooled: one level per series and grain, fed by every
  horizon's errors with its own noise variance, so the newest short-horizon errors
  correct long horizons. Per horizon: one level per horizon.

It replaces the 2-year mean correction (`error_tools.bias_corrected`, the variant the
nested validation currently prefers) with one that reacts faster after breaks and
forgets after gaps. Explanation stays exact: the Shapley parts explain the structural
forecast and the adaptive level is reported as its own part, "recent error level".

## Commands (development block, on files already in logs/pfoi)

```bash
python -m components.predictive_farm_intelligence.pfoi.cli adapt --family both
python -m components.predictive_farm_intelligence.pfoi.cli nested-cv --family both
```

`adapt` writes, for each development backtest tag and each setting (pooled / per
horizon × `q30` 0.1 / 0.5, `tau` 365), files tagged `<tag>_ad<setting>` with model
`herd_engine_adaptive` / `milk_baseline_adaptive` plus the benchmarks, and prints accuracy
over all origins and 0–5 months after a break. `nested-cv` then chooses year by year
among raw, bias-corrected and adaptive candidates.

## Next

* Intervals from the filter's own variance plus quality band (H3), replacing the
  empirical quantiles that cover 34–83 %.
* Use the second milking-herd measure (cows giving milk, from 2026-04) as an extra
  observation of the level once the ETL fixes (E3) are in.
