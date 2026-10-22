# V3 biological input review: interpretation change only

User-reported V2 result: Biological Risk is zero on 231 of 232 assessment dates.
Earlier user-verified published aggregates reported zero mastitis-positive dates,
zero udder/teat-positive dates and one other-health-positive date among 597 V1
assessments. These describe different cohorts: they support investigating sparse
recorded health input but do not independently establish the exact V2 day-level
cause. No private records or configuration were inspected to reconcile them.

## What reviewed code establishes

- `data_access/local_training_loader.py` reads `mastitis_episodes`,
  `udder_teat_episodes`, `other_health_episodes` directly from the approved
  model_input.day_panel columns, with no health-category joins or zero filling.
- `schemas/historical_dataset.py::ApprovedAggregate` requires each column and
  accepts only strict nonnegative integer or None. Missing columns fail validation;
  missing values are not silently corrected. `aggregate_mapper.py` copies the
  names directly into biological inputs; unknown quality remains unknown.
- `biological_risk/biological_assessment.py` withholds missing or insufficiently
  verified quality inputs. Zero counts are recorded values, not disease absence.
- `services/retrospective_scoring.py` separately computes DESCRIPTIVE indices
  from the exact counts with explicitly unknown completeness, rather than forging
  quality declarations. `farm_risk/dairy_risk_score.py` maps counts under explicit
  rules and uses domain MAX. Zero counts can score zero; positive counts below a
  configured lower bound can also score zero. Required missing configured inputs
  yield unavailable scores, not zeros. Threshold changes cannot fix absent evidence.
- V2 config compatibility checks retain V1 Biological/Climate rules; V3 preview
  retains stored V2 Biological/Climate scores. No newly trained health model exists.

Thus the likely immediate explanation is sparse recorded eligible health burden
under the existing rules, not a new UI scoring bug. We cannot conclude that 231
days were disease-free, nor rule out upstream missing-to-zero conversion or
incomplete episode coverage. The producer's ETL category mapping, aggregation date,
missing-value policy and surveillance definitions are not verified by this review.

## Additional indicators and decision

The existing authorized 14-column input boundary supplies only the three separate
health categories. Udder/teat episodes are available, but they are not independently
verified real-time udder-health alerts. Blood/conductivity alarms already belong to
Operational Risk; their health significance, event overlap and recording completeness
remain unverified. Reclassifying them as disease indicators would introduce an
unsupported interpretation and possible double-counting. Milking animal counts
do not establish compatible episode incidence denominators. No rates or additional
health categories are introduced. Current V2 payloads expose only configured
indicators, not necessarily every approved raw input field.

A numerical V3 Biological improvement is therefore NOT justified from the available
code and aggregate evidence. Retain the stored score and explicitly mark its health
interpretation unverified. When configured health inputs are missing/ineligible,
mark the interpretation unavailable instead. When raw counts are positive but scores
zero, say recorded episodes scored zero under the rules, not 'no episodes'.

## Implemented frontend-only interpretation

`biologicalEvidence()` in v3Preview.mjs reports unverified/unavailable interpretation
without changing scores, thresholds, metadata, events or combined-score weights.
V3 displays a compact health-evidence notice. Detailed Model Information explains
the approved field boundary and why alarms are not reused as health diagnoses.
No alarm averages or Climate logic changed. V1/V2 rendering and stored data remain
unchanged; the preview is still Experimental Preview — Not Published.

Before numerical change, obtain owner-verified aggregate reconciliation of health
episode categories into daily counts for the SAME V2 period, event-date definition,
NULL-to-zero handling and independently supported recording completeness. Aggregate
evidence alone cannot identify absent disease or justify invented positive events.
No new SQL/data access, ETL modification or publication is part of this task.

Synthetic checks added, NOT executed:

```powershell
node --test frontend/src/pages/DairyCrisisForecasting/v3Preview.test.mjs frontend/src/pages/DairyCrisisForecasting/dashboardInsights.test.mjs
npm.cmd --prefix frontend run build
```

Review V3 preview at `/risk-management`: recorded zero remains 0, missing remains
unavailable, and the notice states interpretation limitations. Do not publish V3
based on this interpretation-only update.
