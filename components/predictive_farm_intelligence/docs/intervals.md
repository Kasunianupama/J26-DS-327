# Honest intervals (H3, step B)

Code: `pfoi/intervals.py`; tests: `tests/test_intervals.py` (synthetic). Agreed rule
(`targets.md`): an interval is **calibrated** when 80 % ranges cover 75–85 % and 90 %
ranges cover 85–95 % of outcomes. pfoi-1.0.0's 90 % ranges covered 34–83 % in
development, and far less in 2024–26.

## Method (`--intervals aci`)

Per series × grain × horizon × model, only from errors whose target period had ended
before the origin:

1. Residuals are log(actual ÷ forecast), so the range is multiplicative and never
   negative.
2. **Recency weights** 0.5^(age ÷ 365 days): the spread follows the current regime, so
   ranges widen soon after a break.
3. **Record quality.** Each origin gets the band of the 28 days before it (normal,
   degraded, unverified, gap), known at the time. Residuals are divided by their band's
   spread factor (band spread ÷ normal spread from finished errors, at least 1; defaults
   1.5 / 2 / 2 while a band has fewer than 12 errors), and the new range is multiplied by
   the factor of the current band. Poor records give honestly wider ranges.
4. **Adaptive conformal inference** (Gibbs & Candès 2021). When a forecast finishes,
   a miss lowers the miscoverage level used for the next interval (wider) and a hit
   raises it a little (step 0.02), so coverage stays at the target over time even when
   errors change.

Tests show: no outcome after the origin changes its interval; coverage within a few
points of 80 % / 90 % on stable errors; after the noise triples, 90 % coverage stays
above 80 % and beats the old quantiles by more than 10 points; ranges are more than
twice as wide in an unverified band with three times the spread.

## Commands

```bash
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block development --conception-cut known --intervals aci
python -m components.predictive_farm_intelligence.pfoi.cli scorecard --block development --conception-cut known
```

The first writes `scorecard_..._aci.csv`. Compare the `coverage80`, `coverage90`,
`width90` and `calibrated` columns of the two. With `--quality off` the bands are not
used and every origin counts as normal.

## Next

* Use the ACI ranges in the outlook (`c1_output.outlook.lower/upper`) from pfoi-1.1.
* The adaptive level's own variance (Layer 1) is a candidate extra scale; add it only if
  the scorecard shows the ranges are too wide or too narrow by horizon.
