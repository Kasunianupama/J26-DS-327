# PFOI outlook contract (c1_output) — change log

| Contract | Model | Date | Change |
|---|---|---|---|
| 1.0 | pfoi-1.0.0 | 2026-10-19 | First version: `c1_output.outlook`, `c1_output.attribution`, `c1_output.history` (DDL in `components/predictive_farm_intelligence/docs/sql/c1_output_tables.sql`). |
| 1.0 (unchanged) | pfoi-1.0.0 | 2026-10-19 | Page document only (`c1_output.run_document.document`, JSON; no table columns change): adds `realised` (recorded outcomes of the forecast periods, same row shape as `actuals`, only periods complete before the last data day; display and scoring only, read after every forecast is built) and `realised_through` (last data day, or null). Older documents lack both keys; readers treat a missing key as "no realised outcomes". |
