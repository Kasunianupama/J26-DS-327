# PFOI frontend prototype plan for PP1 (Fri 2026-10-23)

Written 2026-10-20, companion to `pp1_plan.md` (modelling milestones M1–M8). Plan only;
nothing here is implemented yet. Like the modelling plan, **all of it is done before PP1**.

Goal: a farm manager or examiner can see, in plain language and in under two minutes,
what the herd and milk will do, why, how sure the model is, and what it does when
records stop or come back.

## 1. Starting point (existing page, verified 2026-10-20)

`frontend/src/pages/PredictiveIntelligence/` already has a working PFOI page (React 18,
Recharts, no extra libraries):

| Existing | File | Reuse for |
|---|---|---|
| Three workspaces: Farm Outlook, Herd & Production (milk, herd movement, events, generations), Forecast Confidence | `index.tsx` | keep the structure; add panels, not pages |
| Run status chip: "Demo data" vs "Model output", origin, versions | `RunStatus.tsx` | extend with the record-status banner (F1) |
| Timeline with gap shading, waterfalls, contribution chart | `panels/MasterTimeline.tsx`, `Waterfall.tsx`, `ContributionChart.tsx` | withheld periods, staleness-widened ranges, THI layer |
| Reproduction pipeline (calvings already determined vs rate-driven) | `workspaces/Reproduction.tsx` | reproductive timing (F5) |
| Generations | `workspaces/HerdGenetics.tsx` | separate outcomes (F6) |
| Backtest vs benchmarks, quality bands, forecast replay | `workspaces/Evidence.tsx` | evidence ladder (F7) |
| Model evaluation placeholder | `workspaces/ModelEvaluation.tsx` | outage simulation and ablation results (F7) |
| Findings inbox | `panels/Findings.tsx` | new findings: records stale, heat ahead, forecast withheld |
| Data contract and labelled synthetic demo run | `data/pfoi/contract.ts`, `demo.ts`, `view.ts` | new optional keys + demo values |

## 2. Rules

* **Edit only the PFOI page and `frontend/src/data/pfoi/`.** Shared layout (`App.tsx`,
  `components/layout/`), the backend and `shared/schemas` stay untouched unless the user
  agrees (teammates depend on them).
* **No contract-breaking change.** New data travels as **new optional keys in the run
  document** (`c1_output.run_document.document`, JSON), as was done for `realised`. No
  table column changes. Each new key gets one line in
  `shared/schemas/PFOI_OUTLOOK_CHANGES.md`, a shared file, so **ask the user first**.
  Older documents lack the keys and the page shows "not available for this run".
* **Demo data stays labelled.** Every new panel works on the synthetic demo run, and the
  demo values are visibly marked "Demo data, not Farm X". No real number is typed into
  `demo.ts`; real numbers come only from a model run document.
* **Herd level only.** No animal keys, names or per-animal values anywhere in the UI.
* **Honest status on screen.** Each result card carries one badge: *Evaluated*,
  *Post-test development*, *Not interpretable (n < 12)*, *Implemented, not yet evaluated*,
  or *Cannot be validated with current data*. The badge comes from the run document, not
  from frontend code.
* Plain language first, numbers second: every card opens with one sentence a farm manager
  understands ("Milk records have been missing for 23 days, so the range is wider").

## 3. Features (one per modelling milestone)

| # | Panel (where) | What the user sees | Needs from the model (run-document key) | Milestone |
|---|---|---|---|---|
| **F1** | **Record status banner** (header, next to the run chip) | Traffic light: *Records current* / *Milk records N days old* / *Milk forecast withheld*, with the reason in words ("no trusted milk days in the last 28 days"). Click opens a drawer with completeness, freshness, plausibility and source agreement as four small gauges | `record_status: {last_trusted_day, staleness_days, checks[], milk_withheld, reason}` | M1, M3 |
| **F2** | **Withheld and widened periods on the timeline** (MasterTimeline) | Withheld milk periods drawn as a hatched band with "forecast withheld" instead of a line; ranges visibly wider when records are stale; herd counts still shown (biology continues) | outlook rows with `quality_flag`; `withheld_periods[]` | M1, M4 |
| **F3** | **"What happens when records stop"** (Forecast Confidence, new card) | Simple chart: forecast error against days without milk records, one line per days-of-records-back (0 / 3 / 7 / 14). Sentence: "After a 90-day gap, one week of new records brings the error back to …" (filled from the run, never typed) | `outage_simulation[]: {gap_days, resumed_days, horizon, mae_pct, n, withheld_share}` | M2 |
| **F4** | **Heat outlook** (Farm Outlook card + THI layer in Milk supply) | Recent THI vs this time of year (climatology band), days of high heat in a row, and the heat part of the milk explanation. Badge "Operational" vs "Oracle (uses actual future weather, analysis only)". If THI did not help: "No detectable heat effect on herd milk" | `thi_recent[]`, `thi_climatology[]`, `driver_contributions[]`, `thi_ablation{operational, oracle, n}` | M5 |
| **F5** | **Reproduction timeline** (Herd & Production → Herd count & movement) | Funnel / step chart: calving → first service → known conception → pregnancy kept → next calving, with median days and the share still open (censored, labelled "still open, not failed"); link to how many future calvings are already fixed | `repro_timing[]: {step, median_days, p25, p75, n, open_share, period}` | M7 |
| **F6** | **Herd outcomes by generation** (Generations tab) | Small multiples for separate outcomes (yield vs expected, days to conception, pregnancy kept, alarm persistence, productive days), split by calving period; banner "associations, not genetic effects" | `generation_outcomes[]` | M8 |
| **F7** | **Evidence ladder** (Forecast Confidence + ModelEvaluation) | One chart: persistence → current model → + recent records → + heat → + sensors → combined, error ratio to persistence by horizon, n on every bar, status badge per bar; normal / heat / outage / recovery tabs; interval coverage vs target (85–95 %) | `ablation[]: {rung, grain, horizon, band, mae, ratio, n, status}`, `coverage[]` | M2–M6 |
| **F8** | **Sensor signals (shadow mode)** (Forecast Confidence, small card) | Which sensor signals the model is watching and their status (shadow / probation / active) with counts; sentence "too few months of sensor records to use them yet" when that is the case | `feature_registry[]: {feature, status, n_rows}` | M6 |
| **F9** | **New findings** (Findings inbox) | "Milk records stale", "Milk forecast withheld", "Hot spell expected (scenario)", "Recovery after gap: range back to normal" | derived in `view.ts` from F1–F4 keys | all |

## 4. Files

| File | Change |
|---|---|
| `frontend/src/data/pfoi/contract.ts` | optional types for the new keys |
| `frontend/src/data/pfoi/demo.ts` | labelled synthetic values for every new key |
| `frontend/src/data/pfoi/view.ts` | helpers: staleness text, withheld periods, ladder rows, new findings |
| `pages/PredictiveIntelligence/RunStatus.tsx` + new `panels/RecordStatus.tsx` | F1 |
| `panels/MasterTimeline.tsx` | F2 |
| new `panels/OutageRecovery.tsx`, `panels/EvidenceLadder.tsx`, `panels/SensorRegistry.tsx` | F3, F7, F8 |
| new `panels/HeatOutlook.tsx`; `workspaces/MilkSupply.tsx` | F4 |
| new `panels/ReproTimeline.tsx`; `workspaces/Reproduction.tsx` | F5 |
| `workspaces/HerdGenetics.tsx` | F6 |
| `workspaces/Evidence.tsx`, `workspaces/ModelEvaluation.tsx` | F7, F8 |
| `components/predictive_farm_intelligence/pfoi/outlook.py` (`run_document`) | write the new keys (after the pfoi-1.1.1 edits are committed) |
| `shared/schemas/PFOI_OUTLOOK_CHANGES.md` | one line per new key (**ask first**) |

## 5. Checks

* `npm run build` (type check) after every feature.
* Browser preview of the page on the demo run: every new panel renders, nothing overflows
  at phone width, the "Demo data" label is visible, a document without the new keys
  shows "not available for this run".
* Python unit test that the run document's new keys contain no animal keys and only
  aggregate fields.
* One end-to-end run with a real run document, done by the user on their machine
  (`build-outlook ... --write`, backend with `PFOI_OUTLOOK_DB=on`); the user sends a
  screenshot of the page, which must show only herd-level aggregates.

## 6. Schedule (runs alongside `pp1_plan.md`)

| When | Frontend | Depends on |
|---|---|---|
| **Wed 21, morning** | contract types, demo values, F1 banner + drawer, F2 timeline | M1 reason codes fixed (Tue evening) |
| **Wed 21, afternoon** | F3 outage chart, F7 evidence ladder (demo shape) | M2 output shape |
| **Wed 21, evening** | F4 heat outlook, F5 reproduction timeline | M5, M7 output shapes |
| **Thu 22, morning** | F6, F8, F9; `run_document` writes the new keys; real-data screenshot from the user | M4, M6, M8; user's runs |
| **Thu 22, 14:00** | **freeze** with the model code; build, preview, backup screen recording | — |

Priority if behind: F1 → F2 → F7 → F3 → F4 → F5 → F9 → F8 → F6. Panels whose model
milestone is unfinished still ship on demo data with the badge "Implemented, not yet
evaluated".

## 7. Two-minute demo path

1. **Farm Outlook (20 s):** milk and herd for the next months, with ranges; record banner green.
2. **Switch to a forecast date after the outage (30 s):** banner amber or red, milk withheld
   or widened, herd still projected; one sentence why.
3. **What happens when records stop (25 s):** error vs days without records, recovery after
   records return.
4. **Heat and reproduction (25 s):** heat outlook with operational vs oracle badge;
   reproduction timeline feeding future calvings.
5. **Evidence ladder (20 s):** which additions helped, with n and status badges; what is
   still unconfirmed.
