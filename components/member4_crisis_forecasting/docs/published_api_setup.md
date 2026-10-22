# Published Member 4 API: local setup and blockers

Update: an opt-in server-verified loopback session is now available. Follow
[local dashboard session setup](local_dashboard_session.md) for the current
launcher, login, manual permissions and aggregate count verification. The
authentication blocker described below remains applicable to non-local deployment
and to servers started without either trusted team authentication or local setup.

Implemented in the existing FastAPI risk router:

- GET `/api/v1/risks/research/farms/FARM_X/assessments`
- GET `/api/v1/risks/research/farms/FARM_X/milk-decline-predictions`

Responses: `{ "source": "published", "contract_version": "1.0.0", "items": [...] }`.
Items are full validated payloads; JSONB is not wrapped again. Empty tables return
200 and empty items. Access denied returns 403, other farm scopes 404, disabled or
unavailable reads 503, and invalid payloads 503 with
`member4_stored_contract_mismatch`. No rows, credentials or exceptions are logged.
All-or-nothing validation prevents silently showing a partial valid subset.

The component service uses the existing backend `create_app_database_engine`
factory and its existing credential configuration, lazily at request time. It
reads only the two fixed C4 tables using bound FARM_X parameters inside a read-only
repeatable-read transaction. No dynamic table selection, grants, migrations,
mutations, fallback values, private model loads or new server are introduced.
All selected denormalized columns are compared to their full Python-validated
payloads, including scoring and threshold consistency. Existing Python contract
defaults remain authoritative; no provenance is generated or repaired. Assessment
years 2025–2026 and experimental prediction year 2022 are separately enforced,
matching the current frontend. IDs and chronological ordering are preserved.

## Authentication blocker — intentionally fail closed

`backend/app/core/security.py` explicitly states authentication is not implemented.
There are no authenticated backend sessions to reuse. Browser UserContext role
selection is NOT authentication. The endpoints therefore require a trusted
Starlette authenticated `scope['user']` plus `scope['auth']` containing
`member4:read`. A team-approved authentication middleware/session integration
must populate these server-side after verification. No browser-provided role,
header or token string grants permission on its own. Do not remove the dependency
or copy the synthetic test authentication middleware into production.

Without that integration the UI will correctly remain unavailable (403), even
if the two flags below are enabled. Backend authentication implementation is a
separate shared security decision; it was not silently introduced here. Once
trusted auth exists, the C4 client supports its authenticated cookies with
withCredentials=true. Cookie/CORS/security policy must match the team's deployment.
C1 API requests and other members' API clients remain unchanged.

## Manual non-secret setup

Do not overwrite any .env file. Existing authorized backend credentials remain
configured by their owner. These commands contain no credentials. Run from repo
root in separate terminals after the authentication blocker is resolved.

Backend terminal (existing app only):

```powershell
$env:C4_RESEARCH_DB = 'on'
$env:APP_DB_PORT = '5432'
backend/venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Frontend terminal:

```powershell
$env:VITE_C4_RESEARCH_API_ENABLED = 'true'
npm.cmd --prefix frontend run dev
```

These process environment variables are supported by existing settings/Vite and
take effect for the locally launched process. Restart Vite after enabling them.
For a production build, set the same Vite flag before running the build. No flag
is authentication and none changes database permissions. APP_DB_PORT explicitly
overrides the shared default of 5433 without editing other members' settings.

The backend account must already have authorized SELECT on both C4 output tables.
`farmx_c4` loader access does not prove `farmx_api` has permission. Missing table,
driver, connection configuration or SELECT permissions returns unavailable. Ask
the team/database owner to resolve authorization separately; no GRANT command is
provided or executed by this task. The agent did not verify real access, counts,
payloads or schema. User-reported counts 597/85 are not hardcoded.

## Manual synthetic verification

Focused tests construct a standalone FastAPI app, fake authentication and fake
SQLAlchemy engine; they do not import backend main/settings or open a connection.
Fixtures are fictional and contain no farm records or private artifacts.

```powershell
backend/venv/Scripts/python.exe -m pytest backend/tests/test_member4_research_api.py -q
```

Frontend build (same terminal with the Vite flag if enabling for build):

```powershell
npm.cmd --prefix frontend run build
```

No tests, services, build, database queries or private data reads were executed by
the agent. Real integration is not verified. Report only aggregate counts/status
codes from local verification; do not send response items or credentials.
