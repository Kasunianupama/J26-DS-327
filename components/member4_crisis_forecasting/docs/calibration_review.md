# Scoring review and calibration proposal — no numerical changes approved

## What the code establishes

`farm_risk/dairy_risk_score.py::score_domain` assigns a stored indicator value a
configured linear score bounded to 0–100. Higher-is-riskier rules map values at or
below their lower bound to 0 and at or above their upper bound to 100; the reverse
direction reverses those endpoints. A complete domain takes the MAXIMUM configured
indicator score, not an episode/alarm sum. Missing required indicators withhold
the domain and combined score. Complete domains enter a fixed weighted sum.
The output contract revalidates this same calculation and category boundaries.

For Biological Risk, recorded zero counts can consequently yield zero scores.
Counts below a nonzero configured lower bound can also score zero. This means
zero recorded burden under those rules, NOT verified absence of disease. Sparse
recording, unknown episode definitions, omitted health categories, missing events
encoded upstream as zeros or incomplete surveillance remain possible explanations,
not established facts. The descriptive 1.1.0 contract explicitly retains unknown
recording quality. Computational completeness is not surveillance completeness.
Simply raising biological scores would not repair these measurement limitations.

For Operational Risk, the user identifies an alarm-count upper bound of 12. If
the selected stored higher-is-riskier rule actually has that upper bound, any
eligible count >=12 saturates at 100. Because the domain takes MAX, one such
indicator suffices. This follows mechanically from the formula, not evidence of
equipment failure or a crisis. The scoring engine itself does NOT hardcode 12;
actual stored rules remain authoritative. Private research configurations and farm
records were not inspected. We cannot verify how often saturation occurred or
whether 12 matches recorded alarm distributions from available evidence.

## September 2025: unresolved measurement-change hypothesis

The apparent September rise is user-reported. Existing component documentation
(`research_outputs_local.md`, `output_contract_v1.md`, `scoring_verification.md`)
documents unknown quality/availability and raw-count comparability limitations,
but provides no verified before/after operational coverage or distribution figures.
No verified numerical coverage change around September 2025 was found. Do not
assert an actual crisis or a proven recording change from the plotted score.

Possible explanations to test separately: increased session/device coverage,
alarm recording activated or redefined, duplicate event aggregation, increased
herd/session volume, zero-versus-missing encoding, a source/version/rule change,
or a genuine change in recorded burden. A transition into saturated raw counts
can raise a fixed-weight combined score without demonstrating worsening true risk.
Scoring-version separation alone does not prove measurement comparability.

## Owner-run aggregate evidence needed (no individual rows)

Using existing authorized access only, obtain monthly aggregate counts for 2025
and 2026: total calendar days, observed days, missing days, zero-count days and
positive-count days for each session/alarm/health field separately. Compare the
period before September 2025 with September onward. Include positive alarms with
zero sessions, positive sessions with missing alarms, and recording/source/ETL
change summaries if known. Do not infer completeness from production is_scoreable.

For each separate indicator, ask for min/median/p75/p90/p95/p99/max and the fraction
of observed days at or above its actual stored upper bound, split by comparable
recording regime. Inspect score distributions and configured versions in aggregate
without counting repeated publications as independent farm-days. Check contributions
and category shifts by month and version. Report aggregates only, never payloads,
dates linked to individual records, farm keys or row-level predictions.

Confirm episode initiation vs ongoing-case counts, category overlap, recording
coverage and surveillance process. Confirm alarm events vs flagged sessions,
multiple alarms per session, matching day/timezone/animal population and numerator/
denominator completeness before considering rates. No rates are introduced now.

## Separately versioned future calibration, conditional on evidence

If definitions and coverage are defensible, fit candidate empirical percentile
bounds only within a documented PRIOR reference period of one compatible recording
regime. Choose the period, minimum support, percentile candidates, treatment of
zeros/ties and eligibility before evaluating later dates. Do not use future days
to calibrate historical scores. Percentiles describe unusual recorded burden;
they are not clinical thresholds and cannot establish disease or equipment failure.
Zero-inflated or sparse health data may require withholding a score or better
recording indicators rather than percentile scaling. Degenerate equal bounds must
remain unavailable, not be adjusted with invented offsets.

Review sensitivity, saturation, stability, missingness and practical false alarms
on later compatible data before accepting a new research configuration. Keep
MAX aggregation and weights unchanged unless separately justified and approved.
Assign any accepted configuration a NEW explicit version, reference period,
provenance, coverage policy and rationale. Do not overwrite or reinterpret the
existing 597 assessments or 85 predictions. New publication/recalculation needs
separate approval and compatibility review with Member 3 XAI. No new numeric bounds,
weights, clinical bands or database changes are implemented by this review.

## Implemented presentation improvements

Dashboard wording is now derived locally from stored indicator values/scores and
matching rules. It distinguishes recorded zero, unavailable, partial and positive
contributions; explains saturation against the selected rule; and does not alter
stored payloads. Simple View uses friendly indicator labels and supported units.
Detailed View retains original calculation text/rules/rationales. History defaults
to 30 days with 7/30/90/all options, one scoring version, unmerged duplicate dates
withheld and explicit calendar gaps. Scores are not recomputed or averaged.

Synthetic tests (not executed by agent):

```powershell
node --test frontend/src/pages/DairyCrisisForecasting/dashboardInsights.test.mjs
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests/test_scoring_output.py -q
npm.cmd --prefix frontend run build
```

The presentation tests use Node's built-in test runner without added dependencies;
the .d.mts file supplies the existing TypeScript dashboard's module declarations.
No backend, authentication, model, scoring logic, data or published output changed.
