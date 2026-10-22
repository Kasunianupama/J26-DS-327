# Local Member 4 authenticated dashboard

Superseded for the direct local-development dashboard workflow by
[explicit loopback read-only mode](local_read_only_dashboard.md). The startup
module no longer creates or prompts for login credentials; use its REQUIRED
`--enable-local-read-only` flag. The session details below describe the retained
legacy optional adapter, not the current launcher or removed frontend login UI.

This opt-in single-owner local research login fills the missing backend session
boundary without changing shared authentication or Member 1. The user-run launcher
prompts for a NEW dashboard username/password, derives a salted PBKDF2-SHA256 hash
(600,000 iterations) and creates a random signing key in process memory. It never
prints them or writes a configuration file. They are not database credentials.
Restarting invalidates all sessions and requires choosing credentials again.

The server verifies the password and issues a signed, HttpOnly, SameSite=Strict,
one-hour cookie scoped to the Member 4 research path. Five login attempts per minute
are allowed process-wide. Only localhost:5173 Origin and loopback clients/Host are
accepted. The launcher disables proxy headers, binds 127.0.0.1 and uses one worker,
without reload. Do not expose this local mode through a tunnel, proxy or LAN. HTTP
cookies intentionally have Secure=false for this loopback-only workflow; any
network deployment requires team-managed TLS, Secure cookies and shared auth.
Trusted Starlette sessions with member4:read remain supported. UI roles and arbitrary
headers do not grant access. The cookie grants only existing FARM_X read endpoints.

## Start locally (user executes, repository root)

Backend terminal, with existing owner-configured APP_DB_* credentials untouched:

```powershell
$env:C4_RESEARCH_DB = 'on'
$env:APP_DB_PORT = '5432'
$env:FRONTEND_URL = 'http://localhost:5173'
backend/venv/Scripts/python.exe -m components.member4_crisis_forecasting.services.start_local_api
```

Choose a new password of at least 16 characters when prompted. No password is
embedded in command history. Existing backend settings still load their authorized
configuration when YOU start the server; the agent has not read it. APP_DB_NAME
must be farmx_app, APP_DB_API_USER must be the authorized backend role (normally
farmx_api), and APP_DB_HOST/APP_DB_API_PASSWORD must already be configured locally.
Do not substitute the ETL account or component publishing credentials.

Frontend terminal:

```powershell
$env:VITE_C4_RESEARCH_API_ENABLED = 'true'
$env:VITE_API_BASE_URL = 'http://localhost:8000/api/v1'
npm.cmd --prefix frontend run dev -- --host localhost --port 5173 --strictPort
```

Open http://localhost:5173/risk-management. Expand Local research access and enter
the DASHBOARD credentials chosen above. Successful login refreshes assessments
and predictions; it never changes scoring or C1. Use localhost consistently,
not a mixture of localhost and 127.0.0.1, for browser cookie same-site behavior.
Closing the backend revokes its sessions. Clear the browser cookie to sign out
locally; use short sessions and do not share the browser profile.

## Database access: owner action only

No permissions or database contents have been checked or changed by the agent.
The existing backend login normally farmx_api needs CONNECT on farmx_app, USAGE
on c4_output and SELECT on precisely these two tables. Its ordinary LOGIN and
network authentication must already work. Component farmx_c4 privileges do not
grant backend access. A database owner can manually check aggregate booleans:

```sql
SELECT has_database_privilege('farmx_api', 'farmx_app', 'CONNECT') AS can_connect,
       has_schema_privilege('farmx_api', 'c4_output', 'USAGE') AS can_use_schema,
       has_table_privilege('farmx_api', 'c4_output.farm_risk_assessment_v1', 'SELECT') AS can_read_assessments,
       has_table_privilege('farmx_api', 'c4_output.milk_decline_prediction_v1', 'SELECT') AS can_read_predictions;
```

If access is missing, these are the EXACT owner-reviewed permissions needed.
They are instructions for manual approval, not executed migration code:

```sql
GRANT CONNECT ON DATABASE farmx_app TO farmx_api;
GRANT USAGE ON SCHEMA c4_output TO farmx_api;
GRANT SELECT ON TABLE c4_output.farm_risk_assessment_v1,
    c4_output.milk_decline_prediction_v1 TO farmx_api;
```

Do not grant writes, ownership, ALL TABLES privileges or change ETL/schema/data.
If your configured backend role differs, the owner must review that role rather
than blindly substituting it. Existing SQL transactions remain read-only.

## Verify API counts without displaying records

In a third PowerShell terminal, use the same dashboard credentials. Responses
remain in local variables only; output below contains counts and status only.

```powershell
$localLogin = Get-Credential -Message 'Local Member 4 DASHBOARD login (not database login)'
$loginBody = @{username=$localLogin.UserName; password=$localLogin.GetNetworkCredential().Password} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/risks/research/session' -ContentType 'application/json' -Headers @{Origin='http://localhost:5173'} -Body $loginBody -SessionVariable c4Session | Out-Null
Remove-Variable loginBody,localLogin
$assessmentResponse = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/risks/research/farms/FARM_X/assessments' -WebSession $c4Session
$predictionResponse = Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/risks/research/farms/FARM_X/milk-decline-predictions' -WebSession $c4Session
[pscustomobject]@{Source=$assessmentResponse.source; AssessmentCount=@($assessmentResponse.items).Count; ExperimentalPredictionCount=@($predictionResponse.items).Count}
Remove-Variable assessmentResponse,predictionResponse,c4Session
```

Expected user-reported counts: 597 assessments and 85 predictions; neither count
has been verified by the agent. Never print response items or send them back.
403 means no valid authorized session, 401 rejected login, 429 retry after one
minute, 503 means missing config/DB permission or stored contract mismatch.

## Synthetic verification only (not run by agent)

```powershell
backend/venv/Scripts/python.exe -m pytest backend/tests/test_member4_session.py backend/tests/test_member4_research_api.py -q
npm.cmd --prefix frontend run build
```

Session tests use fictional passwords and in-memory requests/fake services; no
backend settings/main import, actual database connection or private data access.
