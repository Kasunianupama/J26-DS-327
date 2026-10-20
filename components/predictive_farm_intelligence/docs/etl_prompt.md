# Prompt for the ETL session (copy everything below the line)

---

You are working in the ETL repository that builds `farmx_research` and publishes `core` and
`model_input` to `farmx_app` for the dairy intelligence project (farm called "Farm X").
Read this repository's `AGENTS.md` / `CLAUDE.md` first and follow them. In particular:

- You never connect to any database, never read `.env`, never read row-level data, and
  never ask for passwords. When a check is needed, write SQL or a command that returns
  **aggregates only** (counts, sums, means, min/max, percentiles); I run it and send you
  the numbers.
- Never write real farm, place, herd, group, staff or other personal names, and never
  use or reconstruct source IDs. Animals are pseudonym keys only.
- Work one item at a time: change the code, add or update the ETL acceptance checks,
  run the unit tests on synthetic data, give me the commands and aggregate check SQL,
  then stop and wait for my numbers.
- Published tables are contracts for the forecasting component (PFOI). Do not change or
  remove existing columns. Add new columns or new tables, and list every addition in the
  publish notes with its definition.

## Background: what the forecasting side found (aggregates, 2026-10-19)

1. **Conception dates are chosen in hindsight.** Every `core.lactation.conception_date`
   (7,119 in 2017–2023) is exactly the insemination that led to the next calving. Median
   gestation 277 days (p5–p95 265–285), but the minimum is −546 and the maximum 414.
2. **`model_input.day_cell` pregnant heifers use hindsight.** On sample days the count
   of `heifer_pregnant` tracks the heifers that later calved, and 3–74 of them (up to 30 %)
   had been served under 35 days earlier, so their pregnancy could not have been known
   that day. `core.preg_check` (with `event_ts`) exists and is not used for this.
3. **Cows milked without a lactation.** In Jun–Aug 2026, with 86–90 % of DelPro milk
   identified, 477–514 cows give milk per day while `day_panel.milking` counts 398–422.
   Of the cows giving milk, about 359–367 a day have an open lactation, 54–59 have one
   that is closed (dry-off recorded) or starts later, and 76–95 have **never had any
   lactation**. Likely cause: calvings not recorded during the DelPro outage
   (Sep 2024 – Sep 2025) and dry-off or calving dates out of step with milk recording.
4. **Sales stop being recorded from Sep 2024** (0 in most months since; culls continue).
5. **Implausible milk Sep 2025 – Mar 2026.** Herd milk is 13.8–23.8 L per recorded
   milking cow-day while only 0–1.5 % is identified; in Oct–Nov 2025 about 270k L a
   month against about 125k in mid-2026. More than 20 L per cow per day is not realistic
   for this herd. In Feb–Mar 2026 one identified animal has 29–31 L a day.
6. **Identification decay.** The identified share of DelPro milk falls from 0.77
   (Jan 2023) to about 0 (2025) and recovers to 0.90 only by Aug 2026.
7. **No record-entry timestamps** in `core`, so late-entered records cannot be cut.
8. Dry-offs, culls and sales are recorded in batches (a few days a month); calvings are
   recorded daily. This is a fact to document, not a bug.

## Work items (in this order)

**E1. As-known pregnancy.** Using `core.preg_check` and `core.insemination`:
- Add to `core.lactation` (new columns): `conception_confirmed_date` = date of the first
  positive pregnancy check after the conception service (null if none),
  `conception_known_date` = `conception_confirmed_date`, else the next calving date,
  and `conception_known_source` ('preg_check' | 'calving').
- Do the same for heifers' first conceptions (wherever the ETL keeps them).
- Publish `model_input.day_cell_known`: same columns and grain as `day_cell`, but an
  animal is in a pregnant state on day d only if its conception is known on or before d
  (`conception_known_date <= d`); otherwise it stays in the open state.
- Acceptance checks: totals per day equal `day_cell`; pregnant counts in
  `day_cell_known` ≤ `day_cell`; aggregate report of the lag service → confirmation
  (count, median, p10/p90) by year, and the share of conceptions confirmed by a check.

**E2. Bad conception dates.** Flag (`is_bad_date` or a new flag) conceptions whose
gestation to the next calving is outside 240–310 days or negative. Report counts by year.

**E3. Missing and misaligned lactations.** For cows with milk yields (`core.cow_day`,
placeholder excluded) on days with no open lactation:
- if no lactation was ever recorded, or the yields start a new lactation after a
  dry-off, add an **inferred lactation** starting at the first yield day of the run
  (new column `is_inferred` = true, `inferred_reason`), with parity = previous + 1;
- if a recorded dry-off is followed by more yields, report it (do not change the date).
- Rebuild `day_cell` / `day_panel.milking` with inferred lactations and add a column or
  table version note. Acceptance check: from 2026-04, mean cows a day giving identified
  milk vs `milking` (target: within 5 % when identified share ≥ 0.8). Report the counts
  of inferred lactations by month.

**E4. Sales after Sep 2024.** Check how exit types are mapped from the source after the
outage (new codes, sales recorded as culls, or not recorded). Report exits by type and
month for 2023–2026 (counts only) and fix the mapping if codes changed.

**E5. Milk volume Sep 2025 – Mar 2026.** Check for double counting between session-level
and daily milk after the new system started (sessions per cow, `milk_session` vs
`daily_milk`, `modification_code`), unit changes, and flush or test volumes in
unidentified milk. Add a daily flag `is_implausible_volume` when litres per recorded
milking cow-day exceed 20, and set `is_scoreable` false on those days. Flag cow-days
above 40 L as `is_spike`. Report monthly totals before and after.

**E6. Definitions.** Document in the publish notes, in one line each: how `is_reliable`
and `is_spike` in `core.cow_day` are computed (past-only or centred windows), how
`identified_share` is computed, and how `data_gap` is set. If a centred window is used,
add a past-only variant.

**E7. Entry dates.** If any DelPro source table has a record-creation or modification
time, carry it into `core` as `entered_ts`. If none exists, say so in the notes.

After each item: run the ETL unit tests, give me the publish command and the aggregate
acceptance SQL, list files changed, and wait for my numbers before the next item.

---

# Round 2 (after the retest of 2026-10-19), copy everything below this line

Same rules as before: no database access for the AI, aggregates only, no names or source
IDs, add columns or tables rather than change existing ones, one item at a time with
acceptance SQL, then wait for my numbers.

Retest results (aggregates): E1 and E7 are done and correct (`day_cell_known` totals
match `day_cell` every day, pregnant ≤ `day_cell`; `entered_ts` exists in 13 tables).
Still open:

**R-E2. Flag impossible gestations.** 105 conceptions have a gestation to the next
calving outside 240–310 days (some negative) and none is flagged. Set `is_bad_date`
(or a new `is_bad_conception`) on them, keep `day_cell_known` and the known dates
consistent with the flag, and report counts by year before and after.

**R-E3. Count inferred lactations in the milking herd.** `core.lactation.is_inferred`
exists, but `day_panel.milking` and `cells_milking` are unchanged: in Jun–Aug 2026,
477–514 cows give identified milk per day while milking = 398–421 (ratio 0.78–0.88).
Rebuild `day_cell`, `day_cell_known` and `day_panel` stocks with the inferred lactations
(milking from the inferred start; dry from the next recorded dry-off or the end of the
milk run). Acceptance: from 2026-06, milking ÷ cows giving identified milk within
0.95–1.05 when the identified share is ≥ 0.8; inferred lactations by month and reason;
daily totals of `day_cell` still equal the herd count.

**R-E4. Sales.** Sales are about 0 from Sep 2024 while culls continue (6–64 a month).
Check whether the source still has a sale exit type after the outage (codes, mapping,
or sales now recorded as culls with a reason). Report exits by source exit code and
month for 2024–2026 (counts only). If sales are really recorded as culls, add
`exit_type_harmonised` with the mapping documented; otherwise state that sales stopped.

**R-E5. Do not score implausible milk.** `is_implausible_volume` exists, but Oct–Nov 2025
(23.8 L per recorded milking cow-day) still have 14 and 5 scoreable days. Set
`is_scoreable = false` on implausible days and on days whose milk per recorded milking
cow exceeds 20 L, and rebuild `period_panel.is_scoreable`. Fill or document
`milk_hand_milked_est` (currently empty). Acceptance: no scoreable month above 20 L per
recorded milking cow-day; implausible-and-scoreable days = 0.

**R-E6. Definitions.** One line each in the publish notes: `is_reliable`, `is_spike`
(past-only or centred windows), `identified_share`, `data_gap`, `is_suspect_high`,
`is_implausible_volume`, `inferred_exits`, `cells_milking`, `milk_hand_milked_est`,
`conception_known_source`.

After each item: unit tests on synthetic data, the publish command, the aggregate
acceptance SQL, files changed; then wait for my numbers.
