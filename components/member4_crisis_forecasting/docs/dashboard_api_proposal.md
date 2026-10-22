# Member 4 dashboard API proposal — team approval required

The frontend preserves the DairyIQ shell and replaces synthetic Farm Dashboard
values. National navigation is removed and legacy routes redirect to Farm Dashboard.
No shared backend code was changed. Existing `/risks/farms/{farm_id}` and national
routes return demo data and MUST NOT be used as published research evidence.

## Missing read-only endpoints

Relative to the existing Axios `/api/v1` base, propose:

- GET `/risks/research/farms/FARM_X/assessments`: validated full stored payloads
  from `c4_output.farm_risk_assessment_v1`, including rules, contributions,
  explanations and provenance. Assessment contracts 1.0.0 and 1.1.0 supported.
- GET `/risks/research/farms/FARM_X/milk-decline-predictions`: validated full
  payloads from `c4_output.milk_decline_prediction_v1`. Never join predictions
  onto assessment dates; the current experimental period is 2022, independently
  selected in Detailed View, while assessments cover 2025–2026.

Both require an envelope `{ "source": "published", "contract_version": "1.0.0",
"items": [...] }`. `items` contains complete output-contract objects, not SQL
rows wrapping a `payload` field. Return all authorized records for this small
historical dashboard, chronologically ordered. Do not silently truncate/paginate;
if pagination becomes necessary, agree a new client contract first. Empty results
remain empty. Never fall back to demo data. Authenticate/authorize according to
team policy, enforce FARM_X scope, validate stored contracts server-side and use
the backend's existing least-privilege read role. No credentials belong in browser
configuration. Proposed access changes need separate approval, never this UI.

Member 4 requests are DISABLED by default. Only after team approval and endpoint
implementation, enable the non-secret Vite build setting
`VITE_C4_RESEARCH_API_ENABLED=true`. Existing VITE_API_BASE_URL behavior is reused.
No .env file was read or edited. Missing endpoint, malformed response, rejected
research flags, synthetic provenance and network errors display unavailable state.
No hardcoded assessment count, score, category, threshold or prediction is rendered.
Actual record counts may differ from user-reported 597/85 and are never fabricated.

## Existing C1 boundary

GET `/predictive/pfoi/outlook?grain=daily&series=herd_milk` is available in source.
The client accepts only `source=model`, shared contract `1.0`, model version
`pfoi-1.2.0-dev`, nonempty matching core provenance, quality exactly `ok`, finite
nonnegative forecasts and matching daily horizon/date pairs (horizon 1=origin).
Its independent forecast origin is visible. Other versions/demo/quality issues
withhold context. No C1 internal imports or page edits are needed. C1 availability,
publication vintage and historical completeness remain unverified by this API.
This UI does not generate early warnings or feed C1 forecasts into risk scores.

## Display and calibration

Simple View exposes four provisional scores, independent assessment selection,
short explanations and score history. Detailed View adds domain/indicator values,
stored thresholds/rationales/weights/contributions, longer history and separate
2022 RF experimental output. Null means unavailable; zero is rendered as zero.
Biological 0 and Operational 100 explicitly require calibration review. No medical
or equipment-failure claims are made. Technical limitations are expandable.
Charts use only one scoring version, preserve null gaps and withhold ambiguous
duplicate dates rather than average publications. No recomputation of scores.

## Local verification

No backend startup or real API/database verification was performed by the agent.
A frontend-only build does not start a database connection:

```powershell
npm --prefix frontend run build
```

After authorized backend preparation, run the existing local frontend with
`npm --prefix frontend run dev` and review `/risk-management/farm`. Check loading,
empty, 404, malformed and unavailable states; Simple/Detailed toggles; mobile
layout and keyboard controls; 2025–2026 vs 2022 date separation; null vs zero;
provisional calibration notices and C1 origin/version. Confirm national routes
redirect and other members' navigation/pages are unchanged. The agent must not
inspect private API responses. Share only aggregate verification outcomes.
