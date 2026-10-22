# Explicit loopback-only dashboard development mode

This replaces interactive local startup: no username/password setup, no dashboard
login form, no session cookie required in this mode. Normal server startup remains
authenticated/denied by default. No authentication or business logic of other
components changes.

From repository root, backend terminal:

```powershell
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.start_local_api --enable-local-read-only
```

The flag is REQUIRED. It sets process-only C4_LOCAL_READ_ONLY=on, APP_ENV=development,
C4_RESEARCH_DB=on and APP_DB_API_USER=farmx_api; it defaults APP_DB_PORT to 5432 unless
already explicitly configured. It rejects an explicitly non-development APP_ENV
or different APP_DB_API_USER. Database host/name/password still use the existing
owner-configured backend settings; none are printed, entered into the frontend or
replaced. An existing backend port setting overrides this default: correct it
manually to 5432 if necessary. No .env file was inspected or edited by the agent.

Frontend terminal:

```powershell
$env:VITE_C4_RESEARCH_API_ENABLED = 'true'; $env:VITE_API_BASE_URL = 'http://localhost:8000/api/v1'; npm.cmd --prefix frontend run dev -- --host localhost --port 5173 --strictPort
```

Open http://localhost:5173/risk-management directly. The existing Axios client,
payload validation, scoring and unavailable states remain unchanged.

## Security boundary and limitations

**While explicitly enabled, other local processes/users able to contact loopback
can read these research outputs without login.** This is not production auth.
Do not use shared/untrusted machines, tunnels, proxies, LAN or public deployment.
The launcher binds only 127.0.0.1:8000, disables proxy-header trust, and uses no
reload or multiple workers. Development access is restricted to GET on exactly
the two FARM_X research endpoints and requires loopback peer, exact expected Host
(localhost:8000, 127.0.0.1:8000 or [::1]:8000), and either no Origin (local CLI)
or http://localhost:5173 / http://127.0.0.1:5173. Unexpected hosts/origins, remote
peers, cross-site fetches and forwarded headers are rejected. Origin checks are a
browser restriction, not authentication against a local process capable of forging
headers. No bypass is offered to session, demo, C1 or other endpoints.

Stopping the launcher stops access. Standard uvicorn startup without the opt-in
retains trusted-auth/session requirements. Never carry C4_LOCAL_READ_ONLY=on into
production; the guard also rejects APP_ENV other than development. For non-local
deployment use team-managed verified authentication and TLS. The legacy opt-in
local session adapter remains for compatibility but the launcher disables it;
the unused frontend login component has been removed. No global auth was disabled.

Queries are unchanged: parameterized FARM_X selection from only
c4_output.farm_risk_assessment_v1 and c4_output.milk_decline_prediction_v1 in
read-only repeatable-read transactions. farmx_api must already have CONNECT on
farmx_app, schema USAGE and SELECT on these two tables. No permissions are granted
by this launcher. Missing configuration/permission/table or invalid payload remains
503 unavailable; authentication removal cannot repair database access.

Optional USER-RUN aggregate API count verification, no records printed:

```powershell
$c4Assessments = Invoke-RestMethod 'http://localhost:8000/api/v1/risks/research/farms/FARM_X/assessments'
$c4Predictions = Invoke-RestMethod 'http://localhost:8000/api/v1/risks/research/farms/FARM_X/milk-decline-predictions'
[pscustomobject]@{Assessments=@($c4Assessments.items).Count; Predictions=@($c4Predictions.items).Count}
Remove-Variable c4Assessments,c4Predictions
```

Manual synthetic checks (not executed by agent):

```powershell
backend/venv/Scripts/python.exe -m pytest backend/tests/test_member4_local_read.py backend/tests/test_member4_research_api.py backend/tests/test_member4_session.py -q
```

No database access, tests, services, publishing, credential reads or data changes
were performed by the agent. Existing 597/85 records are not recalculated.
