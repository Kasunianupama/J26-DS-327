# Local aggregate diagnostic and isolated operational calibration

This USER-RUN workflow reuses the approved 14-column loader, validators and existing
descriptive scoring engine. The agent never runs it against a database. No new
permissions, queries to other tables, ETL, output records, thresholds or publication
code are introduced. Real records remain in local memory; stdout is aggregates.

## Interpretation and scope

User-verified findings: 597 published assessments, zero mastitis-positive days,
zero udder/teat-positive days and one other-health-positive day; in 2026, 229 of
232 assessed days reached at least 12 blood alarms (about 98.7%). The current
12-alarm rule consequently has little discriminatory range in that cohort. This
does not prove alarms indicate failures, that they are incorrectly recorded, or
that any replacement numeric limit is scientifically validated.

The diagnostic reports each health field separately: observed, missing, recorded
zero and positive counts, distributions and missing calendar days. Interpretation
is explicitly unverified: zero recorded episodes are not absence of health problems.
Approved columns cannot distinguish true zeros from missing events converted to
zeros upstream. No disease events are added and no old score is corrected.

Monthly diagnostics expose possible recording-regime differences around 2025,
without declaring a proven change or crisis. Compare coverage and distributions
before treating different periods as comparable. Sessions are reported separately,
along with paired observed days, alarms with zero sessions and alarms greater than
session counts. The latter can be legitimate multiple events, not automatically
an error. Nonmissing positive sessions alone do not establish denominator
compatibility. No alarm rates are calculated: event units, same population/day
and complete numerator/denominator recording remain unknown.

## Candidate calibration and chronology

Supply your EXISTING reviewed RetrospectiveResearchConfig JSON privately. Also
predeclare a prior reference interval, separate later comparison interval, upper
percentile, minimum observed days, new version and a recording-regime assumption
note. No percentile, minimum support or numeric replacement threshold is silently
chosen for you. These are experimental design choices, not clinically validated
cutoffs. Both intervals must be within 2025–2026; the comparison must precede the
execution date. A short synthetic fixture is not a recommendation for real support.

Only configured raw blood/conductivity alarm rules with higher-is-riskier direction
are eligible for fitting. Upper bounds use linear empirical percentiles of the
reference counts, including observed zeros. Existing lower bounds, domain MAX,
weights, health/climate rules and provisional category boundaries are retained.
All reference calendar days and each calibrated alarm value must be present, meet
the explicitly requested minimum support, have variation and yield upper>lower.
Positive alarms with zero sessions withhold the proposal. Missing sessions remain
unknown; raw-count calibration does NOT assert rate compatibility or completeness.
Unknown quality and historical availability remain unknown even for nonmissing data.
Unsupported ratio rules, degenerate ranges or insufficient reference data withhold
the entire proposed configuration; diagnostics and old-score summaries still work.

The comparison period never fits the candidate. No candidate search or automatic
selection based on comparison results occurs. Repeatedly trying percentiles after
viewing comparison results would turn this period into development data, requiring
a separate later evaluation. Reference-period choice and regime comparability
remain your research assumptions; the approved columns cannot verify them.

Old vs proposed distributions use the SAME later snapshot rows and unchanged
scoring engine. Summaries include counts, missing/zero/100 scores, percentiles,
means, categories and paired operational-score differences. Old results are
RECOMPUTATIONS using the old supplied configuration, not a verified reconstruction
of the 597 stored assessments: corrections or different snapshots may differ.
No published records are read or replaced. The 597/85 outputs and Member 3 XAI stay
unchanged. No model training, backend/auth or frontend changes occur.

## One local PowerShell command (repository root)

Before execution, choose and document the reference regime, percentile and minimum
support. The prompts below supply explicit experimental choices; they do not ask
another member for confirmation or permission. The password is prompted hidden by
the program using existing authorized farmx_c4 read access.

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.diagnose_calibration_local `
  --config (Read-Host 'Existing reviewed research configuration JSON path') `
  --reference-start (Read-Host 'Prior reference start YYYY-MM-DD') `
  --reference-end (Read-Host 'Prior reference end YYYY-MM-DD') `
  --comparison-start (Read-Host 'Later comparison start YYYY-MM-DD') `
  --comparison-end (Read-Host 'Later comparison end YYYY-MM-DD') `
  --upper-percentile (Read-Host 'Predeclared experimental upper percentile, greater than 0 and less than 100') `
  --minimum-days (Read-Host 'Predeclared minimum reference days, at least 2') `
  --new-version (Read-Host 'New provisional scoring version') `
  --recording-regime-note (Read-Host 'Reference regime assumptions and unresolved coverage limitations') `
  --candidate-config (Read-Host 'NEW configuration-only JSON path outside repository, existing parent directory')
```

The optional candidate-config flag writes only a new standalone research
configuration, not records or reports; exclusive creation forbids overwrite. It
must be outside the repository in an existing private directory. When evidence
is insufficient, no candidate file is written. Omit the flag to keep everything
in memory. Existing config is never edited. Loader defaults: localhost:5432,
farmx_app/farmx_c4, fixed 14 columns, read-only snapshot. It never reads .env.
Any local connection errors are sanitized without exposing records/credentials.

Treat the candidate file as a research proposal only. Do not feed it to publication
commands or overwrite old configurations; accepting new outputs is a separate
task. Reduced saturation is not proof of better health/operational risk assessment.

Synthetic tests (added but NOT executed):

```powershell
backend/venv/Scripts/python.exe -m pytest components/member4_crisis_forecasting/tests/test_aggregate_calibration.py -q
```
