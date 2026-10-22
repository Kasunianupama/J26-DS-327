# model_input2: C1 inputs rebuilt from the app's core (instructions for modelling)

Status 2026-10-22. Built by the user from `docs/sql/model_input2_from_core.sql` in `farmx_app`.
`model_input` (ETL-published) and the research ETL are unchanged. Aggregates below were
supplied by the user; nothing here was read from the database by an agent.

## 1. Rules for every modelling session

1. **Placeholder milk is excluded from all modelling for now** (user decision, 2026-10-22).
   No model, backtest, calibration, feature or chart may use placeholder litres. Load the
   placeholder-free series in section 5, not `target_litres` as stored.
   **Shipped milk is not used either** (user decision, 2026-10-22): `milk_shipped`,
   `milk_internal`, `milk_hand_milked_est` and the DelPro-history columns (`milk_delpro_*`) are
   information only; no model, feature, calibration or check may use them.
2. Point C1 at the schema with the environment only: `PFOI_MODEL_INPUT_SCHEMA=model_input2`.
   Write files to `--out logs/pfoi_mi2`. Never `--write` to `c1_output` without the user's OK,
   and take a backup first (`python scripts/export_component_outputs.py`).
3. Herd-level aggregates only; no database access by agents (root `CLAUDE.md`).
4. Measured and estimated values stay distinguishable in every output (section 5 flags).

## 2. How it is built

- Script: `docs/sql/model_input2_from_core.sql`. Run the whole file as the schema owner in
  DBeaver with Execute SQL Script (⌥X). Checks C0–C12 are at the end.
- Reads only `core` (animal, animal_daily, daily_milk, milk_session, event, entry, exit,
  lactation, dry_off, insemination, abortion, calf, health_episode, vaccination,
  weather_day, herd_day).
- Animal-level helper tables live in `model_input2_work` (not granted to anyone).
  `model_input2` is granted read-only to `farmx_model` and `farmx_api`.
- Tables: `day_cell`, `day_cell_known`, `day_cell_inferred` (= `day_cell`), `day_panel`,
  `period_panel`. Same columns and order as `model_input`, plus appended columns (section 4).

## 3. What changed compared with model_input

### Milk
| Topic | model_input | model_input2 |
|---|---|---|
| Source | shipments to Jul 2022, DelPro history total after | `core.animal_daily` where `is_yield_valid` (source of truth) |
| Summation | single precision | double precision (monthly totals exact) |
| Missing days | gap flag by range | no valid record = missing (`data_gap`), never zero |
| Sparse days | none | no placeholder and < 10 cows, or < 10 % of the mean cows on the 3 days before and after → data not available (`is_sparse_day`) |
| Cow records > 18 L | kept | implausible: dropped on cow-sample days, moved to unidentified on herd-total days (`milk_excluded_high_*`, `milk_reassigned_to_unidentified`) |
| Day record type | n/a | `herd_total` (placeholder present and day total ≥ 5 L per milking cow), `cow_sample` (enough cows recorded), `none` |
| Stored `target_litres` | shipment / DelPro litres | measured herd total (herd_total) or estimate = milk per recorded cow × milking (cow_sample). **Contains placeholder on herd_total days: do not use as is (rule 1)** |
| `target_source` | shipment / delpro | always `delpro` (AnimalDaily is a DelPro table; keeps C1 source logic unchanged) |
| `is_implausible_volume` | > 20 L per cow | target > 18 L per milking cow |
| Shipments / DelPro history | target | information columns only (`milk_shipped`, `milk_delpro_*`) |

### Herd
| Topic | model_input2 rule |
|---|---|
| Presence | entries / exits (recorded win), else birth (or first event) to `core.animal.exit_date`; open tails closed at max(last evidence + 365 d, birth + 913 d); no evidence ever = never present |
| Milking | in lactation by calving / dry-off records (never made dry without a dry-off), or a usable milk record that day. The daily milk record is a **sample** of the milking cows |
| Adults with no calving in core | lactation number ≥ 1 in entry / event / milk records → never heifers: dry after a dry-off, milking on milk-record days, else `unknown` (`adult_no_recorded_calving`) |
| Pregnancy | inseminations with outcome calved / aborted / conceived, ending at next calving, real abortion, exit or 310 d; `day_cell_known` uses the as-known date |
| `day_cell_inferred` | equal to `day_cell` (no milk-inferred lactations) |
| `milking_with_inferred` | redefined: cows in lactation by calving / dry-off records |
| Events | calvings, dry-offs, AIs, real abortions, deaths, culls, sales, exits, entries counted from their core tables |

## 4. Appended columns

`day_panel` (after the `model_input` columns, in this order):

| Column | Meaning |
|---|---|
| `milk_observed_records` | valid `core.animal_daily` records that day (all, incl. placeholder and > 18 L) |
| `milk_observed_cow_litres` | identified-cow litres, records ≤ 18 L only |
| `milk_observed_placeholder_litres` | **placeholder litres** (empty = none) |
| `observed_milking_cows` | identified cows with a record ≤ 18 L that day |
| `lactating_unrecorded` | milking cows without a usable record that day |
| `adult_no_recorded_calving` | adults with no calving in core and no record that day |
| `milk_observed_litres` | raw total of all valid records (= reconciliation with core) |
| `is_sparse_day` | sparse-day rule hit (placeholder days are exempt) |
| `milk_excluded_high_records` / `_litres` | cow records > 18 L (all days) |
| `milk_record_type` | `herd_total` / `cow_sample` / `none` |
| `herd_milk_measured` | herd_total days: cows ≤ 18 L + > 18 L + placeholder (**contains placeholder**) |
| `herd_milk_is_estimated` | TRUE on cow_sample days |
| `milk_per_recorded_cow` | identified-cow litres ÷ cows recorded, when ≥ 10 cows (no placeholder) |
| `milk_reassigned_to_unidentified` | > 18 L cow litres moved to unidentified on herd_total days |

`period_panel` appended (week and month): `milk_observed_records`, `n_observed_days`,
`avg_observed_milking_cows`, `distinct_observed_cows`, `avg_lactating_unrecorded`,
`avg_adult_no_recorded_calving`, `milk_observed_litres`, `n_sparse_days`,
`milk_excluded_high_records`, `milk_excluded_high_litres`, `herd_milk_measured`,
`herd_milk_estimated`, `n_herd_total_days`, `n_cow_sample_days`,
`milk_reassigned_to_unidentified`. Its `target_litres`, `identified_share` and
`herd_milk_measured` include placeholder milk: rebuild period values from the clean daily
series (section 5), never use them directly.

## 5. Loading day_panel without placeholders (required)

Placeholder milk appears only in: `milk_observed_placeholder_litres`, `herd_milk_measured`,
`milk_reassigned_to_unidentified`, `milk_observed_litres`, `target_litres`,
`target_litres_per_cow`, `identified_share`, `is_suspect_low/high`, `is_implausible_volume`,
`is_scoreable`, `data_gap` and the period sums of these. Everything below avoids them.

Clean daily milk target (identified cows only, scaled to the milking herd; always an estimate):

```sql
SELECT date,
       'delpro' AS target_source,
       CASE WHEN milk_per_recorded_cow IS NOT NULL AND observed_milking_cows >= 10
                 AND milk_per_recorded_cow > 0 AND milk_per_recorded_cow <= 18
                 AND (milk_record_type <> 'none')
            THEN milk_per_recorded_cow * milking END        AS target_litres,
       milk_per_recorded_cow                                AS target_litres_per_cow,
       TRUE                                                 AS target_is_estimated,
       milk_observed_cow_litres, observed_milking_cows, milking
FROM model_input2.day_panel
ORDER BY date;
```

Then, in code:
- defensively remove a day before constructing the target if
  `milk_per_recorded_cow` is outside `(0, 18]`; individual records above 18 L were already
  excluded when `milk_per_recorded_cow` was built;
- `data_gap = target_litres IS NULL`; recompute `is_suspect_low/high` past-only on the clean
  series (28-day window, as in the SQL) and `is_scoreable = target present and not suspect`.
- Per-cow work (curves, yield) uses `milk_observed_cow_litres` / `observed_milking_cows`
  (records ≤ 18 L, no placeholder).
- Weekly / monthly values: sum the clean daily series; a period is scoreable only if every
  expected day is.
- Herd series (`n_herd`, states, events, `day_cell*`) contain no placeholder and are used as
  stored.

Effect: herd-total months with too few identified cows (most of Sep 2025 – Mar 2026, and
Apr – Sep 2025) become missing. Placeholder-on days with ≥ 10 identified cows keep a clean
estimate. Note the relative-drop part of the sparse rule is not applied on placeholder days;
the `observed_milking_cows >= 10` condition is the guard there.

**Implemented in C1 (2026-10-22):** `SqlHerdSource.placeholder_free()` detects model_input2
(its `day_panel` has `milk_per_recorded_cow`). Then `target_daily` loads only
`date, milk_per_recorded_cow, observed_milking_cows, milking, milk_record_type` (28 extra days
for the past-only flags) and builds the target with `pfoi/data.py::clean_target_frame`;
`driver_daily` takes its `target_litres`, `is_scoreable` and `identified_share` from it; and
`delpro_daily` (the `--target delpro` option) raises, because DelPro-history totals include
unidentified milk. On the old `model_input` nothing changes. Tests:
`tests/test_clean_target.py` (synthetic, no database).

## 6. Verified (user-supplied aggregates)

- Milk: monthly litres, record counts and days equal the core reconciliation query in all
  119 months (C2 = 0 / 0). Distinct cows with valid milk 4,204 + 1 placeholder = 4,205 (C5).
- Herd: no duplicate days, states sum to the herd every day (C3); calvings, dry-offs, AIs,
  real abortions, deaths, culls, sales, exits, entries match core in every year (C6 = 0).
  Herd balance residual −91 … +17 per year (C7).
- Milking (C8, daily mean): 2016 1,656 milking, 75 with a record; 2019 1,458 / 65;
  2022 1,036 / 6; 2026 447 / 101.
- Opening herd (C9): 2,202 animals entered before 2016, all as heifers (lactation 0), mostly
  12–24 months old.
- Milk per recorded cow ≈ 9–12 L/day 2015–2021, 6.6–7.9 in 2022–2024 (C12).

## 7. Known limits

- 2016–2021 herd milk is an estimate from a small daily sample (~60–75 recorded cows of
  ~1,500 milking); recorded cow-days may favour event days.
- 2022–2024 mostly no usable milk; Oct 2024 – Aug 2025 records gap.
- 2025–26 herd totals exist only through the placeholder (excluded by rule 1). Their
  litres per milking cow are 16–24 L (60 / 34 implausible days), so either the totals or the
  milking count after the gap are off.
- Forecast dates 2022-09 … 2026-04 have no milk forecast (no trusted recent days).

## 8. Charts (no model)

`docs/make_herd_milk_overview.py` (needs `PFOI_MODEL_INPUT_SCHEMA=model_input2`):
`herd_milk_overview.png`, `milk_yield_per_cow.png`, `milk_composition.png` in
`logs/pfoi_mi2/charts/`. Model vs persistence: `build-outlook` → `neural-outlook` →
`compare-runs` with `--out logs/pfoi_mi2` (see `command_sheet.md`).
