# V3 Preview — Average Operational Scoring

Select the explicitly labelled V3 Preview option in the existing scoring selector.
It reads only the already authenticated/loopback-restricted V2 API data. V2 remains
the default published generation; V3 is never automatically activated. There is
no V3 API, database table, publication path, export, configuration-file access or
model training. No agent accessed actual V2 data or ran tests.

## Exact contract compatibility

Stored Python FarmRiskOutput/DescriptiveRiskOutput contracts require domain MAX
aggregation and validate it. An averaged score cannot truthfully be serialized
as a published V2 output. `v3Preview.mjs` therefore builds an isolated browser view
model with explicit preview metadata and source ID/version references. It is NOT
a new valid published contract, output identifier or calibration configuration.
The dashboard never sends it back to an API or persists it. Deep cloning keeps
all source values and nested rules/metadata unchanged.

Preview requires exactly these two separate operational indicators AND rules:
`n_blood_alarms` and `n_conductivity_alarms`. Source Operational Risk must be
available and agree with V2 MAX aggregation. Each recorded count must be a finite
nonnegative integer, its score finite in 0–100, and its rule well formed with
valid direction/lower/upper. Scores must match the stored calibrated rule's
clipped linear mapping within the Python contract's 1e-8 tolerance. This check
does not refit or replace thresholds: the proposed mean uses stored scores.

Missing/ineligible/duplicate indicators, unavailable source domain, missing rules,
extra configured features or incompatible source scores withhold Operational Risk.
Additional session/rate rules are NOT silently dropped to force a preview. If
the actual published V2 configuration has more than these two rules, review the
proposed method explicitly before extending eligibility. Incomplete counts never
become zero. True recorded zeros remain zero, not verified absence of problems.

For eligible dates:

`preview_operational = (stored_blood_indicator_score + stored_conductivity_indicator_score) / 2`

Climate and Biological scores remain their stored values. Combined preview is
the three-domain weighted sum using the SAME V2 weights and inclusive medium/high
boundaries. Weights must be finite positive values summing to one; missing domains
withhold combined score without renormalization. All views keep research-only and
live-warning-disabled metadata. Clinical validity or improved warnings are not
inferred from a less saturated average.

## Dashboard comparison and scope

Preview banner/card labels/chart caption explicitly state Experimental Preview —
Not Published. Main score, factor cards, categories, contributions and historical
trend use derived preview values only while V3 is selected. Source IDs stay internal
to date selection; source scoring version remains available in Model Information.
History still filters by source scoring version and selected time window with
null calendar gaps and duplicate dates withheld. Stored V1/V2 selections use only
the original fetched records. Early Warning Outlook and the 2022 RF section are
unchanged and independent of the preview.

The comparison panel shows mean Operational Risk and counts of scores exactly 100
for stored V2 vs preview V3 on the SAME paired eligible dates across all available
V2 data. It explicitly reports excluded dates and missing previews, preventing a
misleading denominator comparison. Dates with duplicate publications are withheld.
It also shows stored vs preview Operational/Combined scores for the selected date.
No empirical results or eligible counts have been fabricated or assumed.

## Local synthetic verification (not executed)

```powershell
node --test frontend/src/pages/DairyCrisisForecasting/v3Preview.test.mjs frontend/src/pages/DairyCrisisForecasting/dashboardInsights.test.mjs
npm.cmd --prefix frontend run build
```

Start your existing authorized local backend/frontend using their current commands,
then select V3 Preview at `/risk-management`. If V2 is unavailable, the preview
also remains unavailable; it never substitutes V1, demo or synthetic scores. Review
paired eligible counts, selected dates, unavailable reasons and source configuration
before drawing conclusions. Future V3 contract/publication design requires separate
approval after this preview is reviewed. Existing Member 3 XAI inputs are untouched.
