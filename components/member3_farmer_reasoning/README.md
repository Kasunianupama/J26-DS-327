# Farmer Reasoning

Current viva mode: fast local rules and factual templates; no chat-time Qwen inference.

Architecture for a dairy-scoped Digital Agronomist. The local chat reads validated aggregate evidence, supports English/Sinhala/Tamil text and optional local speech, and retains profile-scoped browser history. Older demo/evaluation modules remain separate from the local chat.


## C3 published-data readiness

The human operator runs this command from the application repository root:

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.data_readiness
```

It loads the local root `.env` only on an explicit CLI invocation. Configure
APP_DB_NAME=farmx_app, APP_DB_C3_USER=farmx_c3 and APP_DB_C3_PASSWORD privately;
APP_DB_HOST and APP_DB_PORT select the server (native Windows setup: port 5432).
It never substitutes the API or administrator login.

The command uses a read-only transaction and prints only aggregate herd/date
coverage, milk-gap counts, weather missingness/completeness, temperature range,
mean daily THI, the publish version and C3 output-schema permissions. No animal
records or credentials are printed, and nothing is sent to an external service.
Missing weather stays missing. Historical reanalysis is not a weather forecast.

This is a connectivity and coverage check, not a validated assistant or model.
The existing assistant endpoints continue using synthetic records. Connecting a
real aggregate context and documented teammate-output contracts is a separate
step; existing ETL herd-balance failures remain unresolved.

## Local historical aggregate briefing

After readiness succeeds, the human operator can run:

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.aggregate_brief
```

This local command reads aggregate queries from core only, under the C3 login and
one repeatable-read, read-only transaction. It reports reconstructed latest herd
counts, two seven-day milk summaries anchored to the last herd observation, weather
summaries, publication provenance and current monthly herd-balance failure counts.
The pregnant_nonmilking count covers pregnant heifers and dry pregnant cows only;
it is not a total pregnancy count for the herd.

DelPro and shipment totals stay separate. Partial totals include their observed-day
counts; missing shipment measurements remain null. Weekly changes are suppressed
unless both windows have seven source observations, no data_gap flags and a positive
baseline. No gaps are filled. DelPro days require a positive recorded total; zero
cannot be distinguished reliably from absent source milk in this derived table.
Historical weather and associations are not forecasts or causal explanations.

Output stays in the local terminal; do not upload it to an LLM or other service.
The web assistant still uses synthetic records. Connecting this bounded aggregate
context to API/UI and integrating teammates' published model contracts are later
steps. This command does not generate model predictions or write c3_output.

## Published briefing in the web interface

The Assistant page has an explicit Data source selector. Synthetic demo keeps the
existing conversation interface. Published data exposes a separate historical
briefing, fetched only when the operator clicks Load published briefing. The
GET /api/v1/agent/briefing endpoint loads C3's local settings and read-only aggregate
repository; configuration/connection failures return a generic HTTP 503 with no
secret diagnostics and no synthetic fallback. No external AI service is used.

The published view displays source/version/date, reconstructed herd categories,
source-separated milk summaries with coverage, historical weather and quality
warnings. It has no invented confidence percentage. C1 model selection remains
pending; C2/C4 predictions are unavailable. Published mode is English only for now.
The free-form chat remains a labelled synthetic demo; published question routing,
translation and teammate output adapters are later stages.

Human-run verification from the application repository:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, run `npm run dev` from frontend. Open the Assistant page,
select Published data, then click Load published briefing. Compare its dates,
counts, coverage and warnings with the operator-run aggregate_brief result. Test
an unavailable-backend case: the UI must display an error rather than demo values.
AI agents must not start this backend against the configured real database.

## Tool contracts and offline orchestration

C3's provisional contracts live in schemas/tool_contracts.py and its allowlisted
executor in orchestration/tool_router.py. This is an internal C3 boundary, not an
agreed replacement for shared producer contracts. No shared schemas were changed.
An LLM is not connected: the router consumes an explicit structured ToolCall and
executes one registered tool. It does not infer user intent, translate, execute SQL,
load model paths, import teammate internals or automatically chain model actions.

Tools:
- core_summary: herd or weather aggregate evidence with an observation date.
- c1_forecast: a selected series/grain/target, reference date and optional exact
  forecast origin. The selected model is pfoi-1.2.0-dev. A future adapter must choose
  the latest available origin on/before the reference date when origin is omitted;
  the router independently rejects future or mismatched output. Source publication
  version and quality flags remain visible. Local-data compatibility is not assumed.
- c2_simulation: legacy intervention/change-percent/horizon fixture, retained only
  for the synthetic exercise. Its 730-day cap does not describe C2 model support.
  This registry has no live C2 adapter. The actual chat uses C2's documented 1.1
  API with absolute THI/milking inputs and a fixed one-day horizon (see below).

Empty/unknown tools, extra arguments, invalid inputs and nonfinite numeric results
are rejected. Missing fields produce needs_input without invoking a model. Tool
failures return sanitized messages with no synthetic fallback. Results must match
requested model/scenario/dates and declared synthetic-vs-published provenance.
Missing forecast bounds stay null; reversed bounds are rejected; points outside
bounds retain the original numbers plus a producer-review warning.

Human-run offline exercise from the application root (no settings or DB required):

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.orchestration.synthetic_tools
```

The fixture registry is opt-in and used only by that exercise/tests. Its simulator
returns fixed fictional values to test plumbing, not research predictions. The
five exercise outputs demonstrate core evidence, C1 evidence, missing C2 inputs,
synthetic C2 evidence and an unavailable adapter in that fixture registry. The
web chat does not use fictional adapters: its local readers and C2 API bridge are
documented in the later sections.

## Gemini synthetic-only evaluation (not a production provider integration)

orchestration/hosted_eval.py evaluates six fixed fictional cases: three short
English/Sinhala/Tamil explanations and three structured tool-selection cases.
It imports no farm repositories, reads no dumps, and never starts the backend.
No arbitrary prompts, files, endpoints or local records are accepted. The only
network destination is Google's generateContent API. Tool schemas describe C3's
provisional internal contracts; this is structured JSON tool-selection testing,
not a native provider function-calling benchmark or a deployed agent.

Preview the case list offline (no .env loading and zero requests):

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.orchestration.hosted_eval
```

Human operator only: obtain a Gemini API key through Google AI Studio, and add
GEMINI_API_KEY privately to the application's root .env or shell environment.
Never paste it into chat, screenshots, source code or a command argument. No SDK
installation is needed beyond existing httpx/python-dotenv dependencies. Choose
an exact model available to your account; there is no automatic model fallback.
Current Google quickstart uses gemini-3.8-flash; account access/charges may vary.

Start with one request:

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.orchestration.hosted_eval --live --model gemini-3.8-flash --case explain_en
```

Then, if successful, run all six cases by omitting --case. --live is the explicit
network opt-in. Each case makes one request with a 60-second timeout and no retry;
the run stops on provider failure. No real farm-data transmission is authorized.
AI agents must not load the key or execute this live branch.

The report prints only synthetic answers, elapsed seconds, available token counts,
script/digit sanity checks, and synthetic-router validation. Script matching does
not establish language quality; native-speaker review must check fluency, factual
meaning, missingness and refusal to invent values. No test score proves a model
is suitable for voice or production. Latency includes network/provider processing;
this evaluates text only, not speech recognition, TTS or end-to-end voice latency.
No answers are persisted and production chat remains unchanged.

Sources: https://ai.google.dev/api/generate-content and
https://ai.google.dev/gemini-api/docs/structured-output and
https://ai.google.dev/gemini-api/docs/get-started

The Gemini evaluation now supplies an explicit JSON response schema, beyond JSON
MIME mode. It requires the exact tool/arguments envelope and rejects extra fields.
Argument fields remain optional at the generation boundary so incomplete scenarios
can reach C3's needs_input path; per-tool Pydantic validation is still authoritative.
Invalid envelopes are not silently repaired. Format failures report sanitized error
categories without printing raw provider content. These are schema-constrained JSON
selection tests; native provider function calling is not wired into the web chat.

## Local C4 historical research adapter

services/c4_repository.py maps the restored c4_output.farm_risk_assessment_v1
columns supplied by the operator into C3-owned RiskEvidence. This field mapping is
provisional contract 1.1.0 support, not a claim of C4 model validation or a replacement
for a producer-approved shared contract. No C4 internal code is imported or modified.

The c4_risk tool accepts a required reference_date and a historical_explanation
purpose. It selects the latest assessment_date on/before that date with a bound
SQL parameter and read-only transaction. Only aggregate queries execute; IDs,
farm labels, risk-category text and unrestricted JSON payload never enter evidence.
Exactly one assessment record/group and one nonnull farm reference must be present
at the chosen date; duplicates or competing versions are rejected, not averaged.
No independent score range, threshold or risk category is invented.

Contract version, score basis, scoring version, model status, research_only,
live_warning_allowed, assessment date, cutoff and generation timestamps stay in
the evidence. source_core_version stays null because this export has no confirmed
source version column. An assessment date does not prove the result was known then:
backfilled generation timestamps remain visible. Historical explanation is always
research-only in this adapter; live_warning requests are refused before any read.
The current export's research-only and not-live-validated limitations are retained.

The local registry is services.c4_repository.local_c4_router(). It is not connected
to web chat, local Qwen or Gemini yet. The six-case hosted evaluation remains pinned
to its original synthetic tools, so adding C4 does not authorize cloud processing.

Human-run connectivity check from the application root (aggregates only):

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.c4_repository
```

Expected from the operator's prior checks: 597 assessments, 2025-01-01 through
2026-08-20, all 597 research-only, zero live-warning permissions and no missing
combined scores. AI agents must not execute this database check or load .env.
The optional --reference-date YYYY-MM-DD exercises the local historical tool and
prints its aggregate evidence with warnings; neither command calls a hosted model.

## Local C4 historical question answering

POST /api/v1/agent/local-query calls services/local_risk_chat.py and the validated
local C4 router. It has no LLM/provider call, cloud fallback or synthetic fallback.
English questions mentioning C4/risk/assessment are supported. Provide one explicit
ISO reference date in the question or date picker. Missing, conflicting or invalid
dates are clarified without reading the DB. Requests for current/live warnings are
refused before retrieval. Latest-on/before selection is explicit in the answer.
Only one-date questions are supported; arbitrary comparisons, multilingual routing,
core/C1 question answering and Qwen phrasing are not connected in this view yet.

The Assistant Data source selector now includes Local C4 chat. It displays a factual
template answer with assessment and generation dates, with technical provenance and
limitations in an expandable panel. It does not label an unverified score high/low,
claim a cause, invent a missing score or silently present retrospective results as
current. The date picker persists within the view for clarification; no server-side
conversation memory or cross-user state is stored. No voice/cloud browser service
is used by this local view. Questions and evidence stay in the local application.

Human operator: start/restart the local backend and frontend as above, choose Local
C4 chat, and ask "Show C4's historical assessment for 2026-08-20". Compare with the
already verified CLI result. Also test a missing date and a live-warning request.
Never ask an AI agent to run the configured backend or read real rows.


## Unified local chat — first integration step

Assistant now mounts one real-data chat, styled with Predictive Intelligence tokens.
POST `/agent/chat` routes bounded English, Sinhala and Tamil requests to recorded core summaries, a new
C3-owned C1 aggregate reader, or the existing C4 reader. Missing dates are clarified
in conversation; optional Add dates controls provide reference/target/grain.
C1 is pinned to pfoi-1.2.0-dev, selects the latest eligible origin on/before the
reference date and requires one stored forecast for the exact target/grain/series.
Weekly/monthly period dates must match the stored contract; no nearest-period guess.
No producer internals are imported, and compatibility with local core is unverified.
Core summaries currently cover only the latest recorded snapshot and the two
latest seven-day periods. Other requested core dates fail visibly.
C2 has an explicit local API adapter (see below). Local Qwen interpretation and multilingual text are described below; the evidence readers and their limits remain unchanged.
This implementation uses local factual templates in the selected language, no hosted API, cloud browser
speech, fabricated confidence or synthetic fallback. Local history and voice are described below.
Conversation history and follow-up parameters use the local browser storage described below.
The previous Assistant demo UI is no longer mounted. Other dashboards are unchanged.

Human checks: ask the herd/milk/weather suggestions, a C4 historical assessment
with reference 2026-08-20, and a daily milk forecast with reference 2026-08-01 and
target 2026-08-14. Check source dates/version, incomplete milk coverage and research
flags. Test missing dates, unavailable dates and simulator questions. Report only
aggregate results/statuses; do not share identifying records or secrets.


## Local chat history

C3 conversations, displayed evidence, follow-up context and date controls are
automatically saved under the versioned `farmx.c3.chat-history.v1` localStorage key.
History is scoped to this browser profile and origin, not to the UI role selector
or an authenticated account. Different browsers/ports do not share it; clearing
site data removes it. No server/database history or cloud sync is introduced.
The sidebar reopens conversations. New conversation preserves previous chats;
individual deletion and Clear saved chats require the user's confirmation.
Storage/quota failures are visible and keep the conversation in memory. Invalid
saved history is not overwritten automatically. Cross-tab storage changes block
autosaving until reload to prevent overwriting another tab's history.
Interrupted requests resume with an explicit resend message. Saved answers remain
snapshots, not refreshed live results; restored context supports the same bounded
follow-ups as before, without adding LLM memory. No automatic history pruning.

Human UI check: ask a question, refresh, reopen it and inspect its saved evidence;
start another conversation and switch back; verify its follow-up dates persist.
Delete one chat and cancel/confirm Clear saved chats to check the controls.


## Local profiles, role separation and offline backups

Chat profiles now organise separate histories for each existing UI role. They are
local labels (Profile 1, Profile 2, ...) rather than authenticated users or access
controls. The existing role selector is reused without changing the shared layout.
Each profile/role has its own storage key; switching remounts the chat so in-flight
answers cannot appear in another profile. Role selection itself remains the app's
existing session-only preference. Profiles and selected chat profile persist locally.
Earlier unscoped history is preserved under its old key and copied only when the
operator explicitly chooses Import earlier unassigned chats for a destination.

Back up this role exports only the current profile/role. Back up whole profile
includes its saved role histories, excluding other profiles. Backup files contain
conversations, evidence, dates and context; keep them on a trusted local device.
They are unencrypted local JSON, not anonymised exports for external sharing.
Nothing is uploaded and no cloud provider or database is called for backup/restore.
Restore validates the format, role allowlist and all history records before showing
a confirmation identifying the destination. It can recreate a profile on another
browser. Existing conversation IDs are kept unchanged; the result reports skipped
IDs. Other profiles and roles are preserved. Storage writes are staged and rolled
back on failure where browser storage remains writable. Original backup files are
never modified. Corrupt histories are not silently omitted from whole-profile backups.


## Local voice input and answer playback

Install the optional CPU runtime and public multilingual base weights once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r components/member3_farmer_reasoning/requirements-voice.txt
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.local_voice --download-model
```

Setup never reads `.env`, farm records or databases. Default weights are cached
outside the repo at `~/.cache/farmx-c3-speech/base`; runtime accepts a private shell
C3_VOICE_MODEL_PATH override. Inference uses CPU/int8 and local_files_only=True,
without network download or fallback. GET /agent/voice/status checks readiness;
POST /agent/voice/transcribe accepts bounded raw audio, not multipart or model paths.
Thirty-second / 6 MB limits apply and concurrent inference is bounded to one clip
per backend process. Audio is decoded in memory and is not written to files, logs,
chat history or backups. Only the reviewed submitted question enters chat history.

Choose English, Sinhala or Tamil and click Speak question. Audio is sent only to
a loopback backend. All three languages are transcribed into a draft in the selected
input language by the local model. Recognition can be wrong,
especially for low-resource speech: review numbers/dates/text before pressing Send.
Answers use factual templates in the selected chat language.
No automatic submission, retry or browser cloud SpeechRecognition is used.
Read aloud uses only matching-language speechSynthesis voices with localService=true;
if no matching local voice is installed, it is unavailable. No remote voice fallback is used.
Profile/conversation changes stop recording and playback; an obsolete transcript
cannot be inserted into another conversation. First CPU use may be slow.

Operator check: restart backend after setup, allow microphone only after clicking
Speak question, record a short non-sensitive test phrase, review the draft, and test
Stop, denied permission, an unavailable model and Read aloud. Evaluate each language
manually; synthetic unit tests do not establish real speech accuracy or latency.


## Multilingual local text chat

Select English, සිංහල or தமிழ் in Digital Agronomist. This controls the chat labels,
suggested questions, date prompts, evidence labels and new replies. Typed questions
can use any of these three scripts regardless of the selected answer language.
The conversation saves its selection in the existing profile/role browser history
and backups. Existing replies remain in their original language. Technical model
versions, ISO dates, source identifiers and raw evidence values are not translated.

`POST /agent/chat` accepts optional `language` (`en`, `si`, `ta`; default `en`).
Common native wording uses local rules. Unrecognised Sinhala/Tamil wording can use
the already installed `qwen3:4b-instruct` at the fixed loopback Ollama endpoint as a
schema-constrained intent classifier. Only the question is passed to this local
classifier, never the evidence. It cannot execute tools, choose SQL or supply dates.
Unknown, invalid or unavailable interpretation asks the user to rephrase.
The local classifier has a bounded 25-second request timeout; common suggested
questions bypass model inference. CPU classification may time out on this machine. There is
no Gemini/cloud fallback. English routing retains the existing bounded rules.

Validated readers still control facts. Hand-authored Sinhala/Tamil templates retain
numbers, dates, missing bounds and coverage, C1 development status and C4 research
limitations. Warnings with no reviewed translation retain their original text so a
limitation is never hidden. Native-language fluency and terminology need speaker
review; successful routing/script tests are not a language-quality certification.
Transliteration (Sinhala/Tamil written in Latin letters) and unrestricted questions
are not guaranteed. C2 uses the documented 1.1 local API contract described below.

Restart the backend after these Python changes and refresh the frontend. Existing
voice controls now transcribe native scripts; playback additionally requires an
installed local voice matching the answer language. Verify using ordinary typed
questions first, then review speech drafts before sending.


## Automatic conversational C2 orchestration (producer contract 1.1)

Users ask ordinary what-if questions in Digital Agronomist. C3 identifies the
simulation intent, extracts explicitly supplied values, and runs C2 internally.
There is no separate simulator form, tool selector or Run what-if button in C3.
Voice transcripts follow the same chat path after the user reviews and sends them.

The current C2 contract supports one approved cow, an absolute THI, milkings/day,
or both together, and a fixed one-day horizon. If all required inputs are clear in
the question, the same request calls C2. Otherwise C3 asks a conversational follow-up
for the missing cow or target and keeps the supplied details in bounded context.
Answering the final required detail automatically runs the model; no extra launch
or confirmation step is required. Cow selection and values are never invented.

`POST /agent/chat` normally receives only `query`, `language` and `context`.
`context.scenario` holds proposed `animal_ref`, `thi_mean`, `milkings_per_day` and
`mode`; these are input parameters, not observed farm facts. The optional structured
root `simulation` field remains for compatible API clients but is not required by
the chat interface. Source cow references are approved pseudonyms only.

The local parser handles common English/Sinhala/Tamil question patterns, explicit
absolute values, small number words for milking frequency, and unambiguous from/to
changes. Missing or ambiguous values ask for clarification. Relative percentages,
feed scenarios, whole-herd simulation and unsupported horizons do not run C2.
Cancellation clears the pending scenario. Unrelated questions never execute a
pending tool; a new topic resets its parameters. A new named feature does not
silently retain an old combined scenario, and unrecognised cow references cannot
fall back to a preceding cow. Native wording still requires speaker review.

Local chat history and role/profile backup preserve partial scenario context, so
the user can continue after reopening a chat. Older history remains readable;
historical messages that mention the former manual form are retained as history.
Start a new conversation to use the new flow without those earlier instructions.

C3 uses `services/c2_dialogue.py`, `services/c2_chat.py` and `services/c2_gateway.py`.
It calls C2's existing HTTP boundary, without importing or changing C2's internals,
training scripts, model or dashboard. The legacy provisional `change_percent` /
`horizon_days` synthetic registry is not the live C2 contract.

The fixed endpoint is
`http://127.0.0.1:8000/api/v1/interventions/simulate-counterfactual`. For another
local backend port, set shell variable `C3_C2_API_PORT` before starting the backend.
Only the port is configurable: the loopback host and API path remain fixed. Proxy
settings, redirects and automatic retries are disabled. Responses are bounded to
1 MiB and one active C3-to-C2 request per process. No farm context goes to Gemini.

C2 selects its latest usable recorded cow-day and predicts the next calendar day;
that date is not necessarily tomorrow or a current farm observation. Custom
historical reference/target dates are unsupported. C3 matches the cow, target
values, units, horizon, response contract and model version, checks prediction
arithmetic and requires PASSED training support before explaining success. Missing,
out-of-range or unchecked estimates remain unavailable. Observed milk, predicted
baseline and predicted what-if milk are separate. Combined input changes use C2's
combined prediction, not a sum of individual changes.

Producer warnings and assumptions stay visible. No causal benefit, management
recommendation, source-core compatibility or uncertainty interval is invented.
Raw cow state and producer rankings are not copied into C3 evidence or history.

The actual trained artifact and compatible runtime are still required. At review
of dev commit `6cdec2e`, the producer README specifies scikit-learn 1.6.1 and the
Git-ignored file
`components/member1_didt/prediction/artifacts/farmx_milk_yield.joblib`, overridable
by the producer's `DIDT_MODEL_PATH`. Git does not supply that file. Do not blindly
downgrade the shared app environment: agree on a compatible artifact/runtime with
the owner. C3 does not train or install a replacement model, and missing models
never produce demo estimates.

Agent verification uses fictional inputs, mocked repositories and an in-process
test API; it never opens a real database, model artifact or `.env`. Once the model
is installed, the user can restart the backend, refresh the frontend, start a new
conversation, and ask a supported what-if question. A metadata-only readiness check:

```powershell
$support = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/interventions/model-support'
$support | Select-Object status, model_version
```

Do not paste individual cow records, reference lists or real simulation output into
an agent chat. The trained artifact remains an outstanding local dependency until
provided by the owner or trained locally by the user using the owner's procedure.


## Experimental Ollama/Qwen diagnostics (not used by viva chat)

The current `/agent/chat` path uses fast rules and templates only. Unrecognised
wording returns an immediate supported-topic clarification without calling Qwen.
The standalone diagnostic below still evaluates `qwen3:4b-instruct`; an explicit
planner can also be injected in isolated tests, not through HTTP requests.
Qwen does not generate farm facts or extract simulation values. Validated local
readers, the existing C2 parser/API and factual answer templates remain responsible
for evidence and answers. Real questions never go to Gemini, and no provider
switch or hosted fallback is introduced.

The model sees only the current question, without evidence or full conversation
history. Only complete explicit follow-ups inherit bounded client context; inferred
dates, values and model-suggested tool arguments are never accepted. Rules bypass
inference where possible. Qwen thinking is disabled, output/context sizes are
limited, and the model is kept resident for five minutes after a request using
Ollama's documented `keep_alive` field. CPU latency still depends on local load.

The local transport has a 20-second read timeout, a 2-second connect timeout,
a response-size limit, elapsed-time checks while receiving chunks, and one active
C3 inference per backend process. It never queues another C3 inference, retries,
follows redirects, uses environment proxies or accepts a remote runtime URL.
Timeout, busy, missing-model and invalid/unavailable responses produce a localized
message without running a data tool; existing follow-up context remains intact.
These limits bound C3 waiting and do not guarantee immediate cancellation inside
the Ollama server. Separate backend processes can each have an active request.

From the application root, the following checks never read `.env` or a database:

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.local_ollama
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.local_ollama --check en
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.local_ollama --check si
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.local_ollama --check ta
```

The default command checks metadata only. Each `--check` sends one fixed generic
phrase directly to Qwen, reports classification/latency and exits unsuccessfully
on failure or mismatch. It tests interpretation, not answer quality, speech or
real C2 estimates. Restart the backend to load code changes. If classification is
slow, recognised/suggested questions still use local rules. No additional model
download is performed. Native wording and speech still need speaker review.

API references: https://docs.ollama.com/api/chat and https://docs.ollama.com/api/tags.


## Farmer-facing forecast dates and evidence

Chat now asks only which date/period the farmer wants a forecast for. With no
explicit historical cutoff, C3 internally selects the latest unique stored
forecast covering that target, using a cutoff no later than today or the target
period. The existing exact-model/grain/series/target aggregate query and validation
remain unchanged. No value, run or missing interval is invented. Automatic cutoffs
are not saved into follow-up context; each new target is resolved independently.
An explicit historical cutoff is still available under Review older records.
C4 asks which past day to review; it does not offer live alerts.

Essential cautions remain visible in ordinary language. Producer warnings, quality
flags, publication/model versions and C4 research/live-warning flags remain intact
in saved evidence and collapsed Technical notes / Technical source details.
These are presentation changes, not changes to C4 validation or permissions, and
they do not enable or disable the separate C2 simulation bridge.

Forecast date selection uses the stored origin date; it is not proof a backfilled
forecast was published or available on that day. Answers say forecast dated, and
model/source versions remain in the original evidence. No publication timestamp
is inferred from the origin.


## Practical explanation of historical C4 results

C3's English/Sinhala/Tamil risk explanation now leads with what the result can
support, then separates general record-review suggestions from supplied scores
and date/availability limits. Suggested checks are C3 guidance to inspect records,
not C4-prescribed interventions or evidence of a cause. Only present component
scores prompt the corresponding record checks; missing and zero scores stay
distinct. No score scale, probability, category, ranking or decision threshold is
invented. Original values, research/live flags and producer warnings remain intact.
Validated management action mappings still require the producer's documented
definitions and validation. C3 does not change C4 models, scores or dashboards.

The UI renders plain-text section headings and review lists as readable cards,
without accepting HTML. The same plain answer is retained for local history,
backups and read-aloud. Previously saved replies remain unchanged snapshots.


## Milk summary chart and Excel snapshot

The latest milk question now uses daily herd-level aggregates for the fourteen
calendar days ending on the last published herd date. The reader fetches the
existing weekly summaries and the added date-grouped totals in the same read-only,
repeatable-read transaction. No animal rows, source IDs or raw data are retrieved.
DelPro keeps the established positive-total observation rule; a DelPro zero cannot
establish a recorded day. Shipment zero stays a valid observed zero. Dates absent
from the source become calendar gaps with null measurements, never invented zeros.

`services/milk_report.py` validates consecutive dates, duplicate source counts,
finite values, separate source sums and coverage. Daily aggregates must reconcile
with the existing weekly figures. Changes require full observation coverage, clear
gap flags and a positive previous total; unknown gap status suppresses comparison.
No source merging, causal explanation or missing-value filling is introduced.

The same `evidence.milk_report` snapshot supplies the localized narrative, neutral
source cards, accessible daily chart/table and Excel download. Native SVG paths
break at missing points. Earlier saved answers without daily evidence remain
readable and receive no fabricated chart. Ask again to obtain a new snapshot.

The explicit Download Excel click posts that displayed snapshot to
`POST /api/v1/agent/reports/milk.xlsx`, which revalidates its internal arithmetic
and creates an XLSX entirely in memory with Python's standard library. It never
rereads the database, reruns a model, writes farm data to server files or calls a
hosted service. The workbook has a summary, selected-language explanation, source
notes and fourteen daily records. Numeric values, percentages and dates are typed;
missing daily cells are blank. Strings are literal cells, never executable formulas
or external links. This is a saved report snapshot, not a signed/authenticated
database extract. C3's local profile/history behavior is unchanged.

Agent checks use fictional aggregates and mocked readers only. The operator can
restart the backend, refresh Digital Agronomist, ask a new milk-summary question,
inspect missing days and download Excel. Compare the displayed source totals with
this aggregate-only SQL in DBeaver (do not send individual records to an agent):

```sql
WITH bounds AS (SELECT max(date) AS last_day FROM core.herd_day)
SELECT min(h.date) AS first_day, max(h.date) AS last_day,
       count(*) AS recorded_days,
       count(*) FILTER (WHERE h.data_gap IS DISTINCT FROM FALSE) AS flagged_or_unknown_days,
       count(*) FILTER (WHERE h.milk_delpro_cows + h.milk_delpro_unidentified > 0) AS delpro_days,
       sum(h.milk_delpro_cows + h.milk_delpro_unidentified)
           FILTER (WHERE h.milk_delpro_cows + h.milk_delpro_unidentified > 0) AS delpro_litres,
       count(h.milk_shipped) AS shipment_days, sum(h.milk_shipped) AS shipment_litres
FROM core.herd_day h CROSS JOIN bounds b
WHERE h.date BETWEEN b.last_day - 6 AND b.last_day;
```


## Experimental local Qwen milk wording (not used by viva chat)

The standalone experimental milk-wording service can make one
bounded local Ollama call to qwen3:4b-instruct for source-specific wording. Only
masked latest/previous aggregate-fact placeholders and total-availability flags
are included. Python inserts the actual source totals and recorded-day coverage
after generation. No measurements, dates, animal records, daily rows, source text,
credentials, conversation history or original question is included. Requests stay on the existing fixed
loopback transport: no proxies, redirects, retries, hosted fallback or downloads.
The interpretation and explanation calls share the existing nonqueueing lock and
use twenty seconds for interpretation and thirty seconds for wording. Slow CPU
generation can still add latency; the frontend allows sixty seconds for the full chat request.

The model writes bounded English/Sinhala/Tamil source paragraphs with exact fact
placeholders. Python inserts source-local numbers, units and coverage; it retains
the authoritative dates, comparison availability/percentage and next-record-check
sections. Raw generated numerals, unsupported slots, wrong scripts, reasoning,
markup and selected causal/trend claims are rejected. Missing values stay missing,
sources stay separate and no generated advice or calculation is accepted.
These checks constrain generation but cannot prove every sentence's meaning or
native-language fluency. Speaker review remains necessary. Qwen does not freely
answer arbitrary questions or establish why a recorded change happened.

Successful wording is labeled provider local_qwen, answer_generation
grounded_milk_v1 and generation_status success. A busy/missing/unavailable model,
timeout or invalid response returns the original selected-language template with
provider local_template and a public generation_status category. Generated text
and exceptions are not logged by this service. No replacement data is produced.
Both response types survive profile/role history and backup/restore. Older saved
answers remain unchanged. Charts and Excel continue using the exact validated
milk-report snapshot; Excel's explanation stays deterministic rather than copying
model prose. Other tools retain their current deterministic explanations, including
C4's research-only and no-live-warning limitations. C4 files are not changed.

An operator can test local generation with a fixed fictional aggregate fixture:

```powershell
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.grounded_milk --language en
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.grounded_milk --language si
.\.venv\Scripts\python.exe -m components.member3_farmer_reasoning.services.grounded_milk --language ta
```

Each command makes one local inference, reads no .env/database and prints only
fictional results, provider, generation status and elapsed seconds. Exit zero
means wording passed structural checks; exit one means the template fallback was
used. Neither is proof of translation quality. Restart the backend, refresh the
frontend and ask a new milk-summary question for the new behavior. Do not share
real animal records for troubleshooting.


The wording validator also requires explicit latest/previous period anchors and
separate sentences. This rejects ambiguous period relationships even if fact slots
are present. Fictional CPU smoke tests showed variable latency and Sinhala timeout;
native wording needs speaker review and may use the deterministic fallback. Runtime
diagnostics expose a public status only; they never imply structural acceptance is
proof of linguistic correctness. No real database check was run by the agent.


## Current viva mode: fast factual chat and general what-if guidance

Chat-time Qwen classification and milk wording are disabled. Recognised English,
Sinhala and Tamil questions use local rules; unsupported wording receives a short
clarification without an LLM call. Evidence readers, charts, Excel, local voice,
history and profile/role backups continue working. Database reads and an explicitly
requested C2 simulation still take their own time; no inference latency is claimed.
Installed models and standalone Qwen diagnostics are retained for later evaluation.

General C2 questions without an individual animal receive a localized explanation
of the comparison and its scope. They no longer start an animal-reference prompt.
No model is run, animal selected, or whole-herd effect inferred for that explanation.
Only an explicit individual request asks for the missing reference. A complete
approved reference and supported inputs still invoke the real local C2 API.
The simulator's one-cow, next-recorded-day contract is unchanged; this is C3 UX,
not a new farm-wide intervention model. Feed/causal/horizon restrictions remain.

A complete copied dropdown label is recognized only within an existing simulation
conversation. Its display date is stripped before parsing, not used as a requested
forecast date. Invalid dates, extra instructions and multiple references are not
accepted as list labels. Source/model validation, missing-data checks and C4's
research-only/no-live-warning flags are unchanged. C2 files and dashboards are not
modified. Existing saved messages retain their wording; start a new conversation
after restarting the backend to test the current flow. The synthetic unit suite
blocks .env loading, database connections, model-artifact loading and live network.
