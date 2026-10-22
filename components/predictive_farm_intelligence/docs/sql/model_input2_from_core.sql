-- Builds schema model_input2 in farmx_app from the app's core schema only.
-- Same tables and columns as model_input (day_cell, day_cell_known, day_cell_inferred,
-- day_panel, period_panel), plus appended columns at the end. model_input is not touched.
--
-- Milk: core.animal_daily WHERE is_yield_valid is the source of truth for observed milk.
--   target_litres = SUM(yield_litres) of every valid record that day (cows + placeholder),
--   so monthly sums equal the reconciliation query exactly. No valid record = missing
--   (target NULL, data_gap TRUE), never zero. Shipments and DelPro history totals are kept
--   as information columns only and are not the target. target_source = 'delpro' on every
--   day with a valid record (AnimalDaily is a DelPro table), so C1 code runs unchanged.
-- Herd: animal presence and states rebuilt from core.animal, core.entry, core.exit,
--   core.lactation, core.dry_off, core.insemination, core.abortion and evidence in
--   core.event / core.animal_daily / core.daily_milk / core.milk_session.
--   'milking' = in lactation by calving/dry-off records (never made dry without a dry-off),
--   or a valid milk record that day. The daily record is a sample of the milking cows:
--   day_panel.observed_milking_cows = cows with a record, lactating_unrecorded = milking cows
--   without one that day.
--   day_panel.milking_with_inferred = cows in lactation by calving/dry-off records (comparison).
--   Adults with no calving in core (e.g. cows brought in during 2015) are never heifers: they
--   are dry after a recorded dry-off, milking on milk-record days, otherwise 'unknown'
--   (counted in day_panel.adult_no_recorded_calving).
--   Days with no valid milk record are missing: target_litres NULL, data_gap TRUE.
--   Sparse days (section 6: < 10 cows or a sudden drop, no placeholder herd total) are missing too.
--   Cow daily records above 18 L are eliminated (not in usable milk, cow counts or milking evidence);
--   they stay in the raw milk_observed_litres total for reconciliation and are counted in
--   milk_excluded_high_records / _litres. Placeholder herd-total records are exempt.
--   Day record types (section 9): herd_total (placeholder present AND the day total is at least
--   5 L per milking cow: cows + >18 L records moved to unidentified + placeholder = all milk, MEASURED), cow_sample (no placeholder: a sample of cows;
--   herd milk ESTIMATED = milk per recorded cow x milking herd, herd_milk_is_estimated = TRUE;
--   >18 L records dropped), none (missing). target_litres = measured or estimated herd milk.
--   Herd milk above 18 L per milking cow is flagged is_implausible_volume (not scoreable).
--
-- Run as the schema owner (not farmx_model / farmx_api): DBeaver Execute script (Alt+X).
-- Helper tables live in model_input2_work, so a statement can also be re-run on its own.
-- Takes several minutes.
-- Then point C1 at it: in the root .env set PFOI_MODEL_INPUT_SCHEMA=model_input2
-- (remove the line to go back to model_input). Re-run the C1 page run to refill c1_output.

-- 0. Preflight: every core table used must exist. Expect missing = 0.
SELECT COUNT(*) FILTER (WHERE to_regclass(t) IS NULL) AS missing,
       string_agg(t, ', ') FILTER (WHERE to_regclass(t) IS NULL) AS missing_tables
FROM unnest(ARRAY['core.animal','core.animal_daily','core.daily_milk','core.milk_session',
  'core.event','core.entry','core.exit','core.lactation','core.dry_off','core.insemination',
  'core.abortion','core.health_episode','core.vaccination','core.weather_day',
  'core.herd_day']) AS t;

CREATE SCHEMA IF NOT EXISTS model_input2;
-- Working tables (animal-level helpers, pseudonymised keys like core). Not granted to anyone;
-- kept so every statement and check also works when run on its own or in another session.
CREATE SCHEMA IF NOT EXISTS model_input2_work;

-- 1. Calendar: the same days as core.herd_day (2015-08-01 .. last core day).
DROP TABLE IF EXISTS model_input2_work.cal;
CREATE UNLOGGED TABLE model_input2_work.cal AS
SELECT MIN(date) AS start_date, MAX(date) AS last_date FROM core.herd_day;

-- 2. Presence evidence: last date each animal was demonstrably on the farm.
--    Health events in same-day batches of 50+ animals are not evidence (campaigns).
DROP TABLE IF EXISTS model_input2_work.evidence;
CREATE UNLOGGED TABLE model_input2_work.evidence AS
WITH ev AS (
  SELECT animal_key, event_date AS d,
         event_type IN ('DiagnosisTreatmentEvent','HealthCheckEvent','VetVisitEvent') AS is_health
  FROM core.event
  WHERE NOT is_bad_date AND animal_key IS NOT NULL
    AND event_type IN ('EventInsemination','EventHeat','EventPregCheck','EventCalving',
      'EventDryOff','EventAbortion','EventEntry','DiagnosisTreatmentEvent',
      'HealthCheckEvent','VetVisitEvent')
), batched AS (
  SELECT *, COUNT(*) OVER (PARTITION BY is_health, d) AS n_same_day FROM ev
), all_ev AS (
  SELECT animal_key, d FROM batched WHERE NOT (is_health AND n_same_day >= 50)
  UNION ALL SELECT animal_key, milk_date FROM core.animal_daily
   WHERE is_yield_valid AND NOT is_bad_date AND yield_litres > 0 AND animal_key IS NOT NULL
  UNION ALL SELECT animal_key, milk_date FROM core.daily_milk
   WHERE NOT is_bad_date AND NOT is_placeholder AND yield_litres > 0 AND animal_key IS NOT NULL
  UNION ALL SELECT animal_key, milk_date FROM core.milk_session
   WHERE NOT is_bad_date AND NOT is_placeholder AND yield_litres > 0 AND animal_key IS NOT NULL
)
SELECT e.animal_key, MAX(e.d) AS last_evidence_date
FROM all_ev e JOIN core.animal a ON a.animal_key = e.animal_key
WHERE NOT COALESCE(a.is_placeholder, false)
  AND e.d BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'
GROUP BY e.animal_key;
CREATE UNIQUE INDEX ON model_input2_work.evidence (animal_key);

-- 3. Presence intervals [start_date, end_date). Recorded entries/exits win; an animal with
--    no entry starts at birth (else first event); with no exit it uses core.animal.exit_date;
--    an open tail is closed at greatest(last evidence + 365 d, birth + 913 d).
--    Animals with no evidence at all are never present.
DROP TABLE IF EXISTS model_input2_work.presence;
CREATE UNLOGGED TABLE model_input2_work.presence AS
WITH markers AS (
  SELECT animal_key, event_date AS d, 1 AS priority, 'present'::text AS state
  FROM core.entry WHERE NOT is_bad_date AND animal_key IS NOT NULL
  UNION ALL
  SELECT animal_key, event_date, 2, 'absent' FROM core.exit
  WHERE NOT is_bad_date AND animal_key IS NOT NULL
  UNION ALL
  SELECT a.animal_key, COALESCE(a.birth_date, f.first_date), 0, 'present'
  FROM core.animal a
  LEFT JOIN LATERAL (SELECT MIN(event_date) AS first_date FROM core.event e
                     WHERE e.animal_key = a.animal_key AND NOT e.is_bad_date) f ON true
  WHERE NOT COALESCE(a.is_placeholder, false)
    AND NOT EXISTS (SELECT 1 FROM core.entry x WHERE x.animal_key = a.animal_key AND NOT x.is_bad_date)
  UNION ALL
  SELECT a.animal_key, a.exit_date, 3, 'absent' FROM core.animal a
  WHERE a.exit_date IS NOT NULL AND NOT COALESCE(a.is_placeholder, false)
    AND NOT EXISTS (SELECT 1 FROM core.exit x WHERE x.animal_key = a.animal_key AND NOT x.is_bad_date)
), daily AS (
  SELECT DISTINCT ON (animal_key, d) * FROM markers
  WHERE d BETWEEN DATE '2000-01-01' AND DATE '2100-12-31'
  ORDER BY animal_key, d, priority DESC
), periods AS (
  SELECT *, LEAD(d) OVER (PARTITION BY animal_key ORDER BY d) AS next_d FROM daily
), closed AS (
  SELECT p.*, c.last_date,
         CASE WHEN p.next_d IS NULL THEN GREATEST(ev.last_evidence_date + 365, a.birth_date + 913) END AS inferred_close
  FROM periods p
  JOIN core.animal a ON a.animal_key = p.animal_key
  JOIN model_input2_work.evidence ev ON ev.animal_key = p.animal_key
  CROSS JOIN model_input2_work.cal c
  WHERE p.state = 'present' AND p.d <= c.last_date
)
SELECT animal_key, d AS start_date,
       LEAST(COALESCE(next_d, last_date + 1), last_date + 1, COALESCE(inferred_close, last_date + 1)) AS end_date,
       CASE WHEN next_d IS NOT NULL THEN 'recorded'
            WHEN inferred_close <= last_date THEN 'inferred_no_evidence' ELSE 'open' END AS end_reason
FROM closed
WHERE LEAST(COALESCE(next_d, last_date + 1), last_date + 1, COALESCE(inferred_close, last_date + 1)) > d;
CREATE INDEX ON model_input2_work.presence (animal_key, start_date, end_date);

-- 4. Pregnancies from services with a pregnancy outcome. Ends at the next calving, the next
--    real abortion, exit, or 310 days. known_from = when the pregnancy was knowable.
DROP TABLE IF EXISTS model_input2_work.pregnancy;
CREATE UNLOGGED TABLE model_input2_work.pregnancy AS
SELECT i.animal_key, i.insemination_date AS conception_date,
       COALESCE(i.conception_known_date, i.insemination_date) AS known_from,
       LEAST(
         (SELECT MIN(l.calving_date) FROM core.lactation l
          WHERE l.animal_key = i.animal_key AND NOT l.is_bad_date AND l.calving_date > i.insemination_date),
         (SELECT MIN(b.event_date) FROM core.abortion b
          WHERE b.animal_key = i.animal_key AND NOT b.is_bad_date AND b.is_auto_generated IS FALSE
            AND b.event_date > i.insemination_date),
         a.exit_date,
         i.insemination_date + 310) AS end_date
FROM core.insemination i
JOIN core.animal a ON a.animal_key = i.animal_key
WHERE NOT i.is_bad_date AND i.outcome IN ('calved', 'aborted', 'conceived');
CREATE INDEX ON model_input2_work.pregnancy (animal_key, conception_date, end_date);

-- 4b. Adult (parous) animals: first date any core record gives lactation number >= 1.
--     Covers cows brought in as adults (2015 restocking) whose earlier calvings are not in core.
DROP TABLE IF EXISTS model_input2_work.parous;
CREATE UNLOGGED TABLE model_input2_work.parous AS
SELECT animal_key, MIN(d) AS parous_from FROM (
  SELECT animal_key, event_date AS d FROM core.entry
  WHERE NOT is_bad_date AND lactation_no >= 1 AND animal_key IS NOT NULL
  UNION ALL SELECT animal_key, event_date FROM core.event
  WHERE NOT is_bad_date AND lactation_no >= 1 AND animal_key IS NOT NULL
  UNION ALL SELECT animal_key, milk_date FROM core.animal_daily
  WHERE is_yield_valid AND NOT is_bad_date AND lactation_no >= 1 AND animal_key IS NOT NULL
) x GROUP BY animal_key;
CREATE UNIQUE INDEX ON model_input2_work.parous (animal_key);

-- 5. State intervals: cut presence at every date where the state can change.
--    state (hindsight pregnancy, = day_cell) and state_known (pregnant only once known,
--    = day_cell_known).
DROP TABLE IF EXISTS model_input2_work.state_interval;
CREATE UNLOGGED TABLE model_input2_work.state_interval AS
WITH boundaries AS (
  SELECT animal_key, start_date AS d FROM model_input2_work.presence
  UNION SELECT animal_key, end_date FROM model_input2_work.presence
  UNION SELECT animal_key, birth_date + 271 FROM core.animal WHERE birth_date IS NOT NULL
  UNION SELECT animal_key, calving_date FROM core.lactation WHERE NOT is_bad_date
  UNION SELECT animal_key, event_date FROM core.dry_off WHERE NOT is_bad_date AND animal_key IS NOT NULL
  UNION SELECT animal_key, conception_date + 1 FROM model_input2_work.pregnancy
  UNION SELECT animal_key, known_from + 1 FROM model_input2_work.pregnancy
  UNION SELECT animal_key, end_date FROM model_input2_work.pregnancy
  UNION SELECT animal_key, parous_from FROM model_input2_work.parous
), periods AS (
  SELECT animal_key, d, LEAD(d) OVER (PARTITION BY animal_key ORDER BY d) AS next_d FROM boundaries
), active AS (
  SELECT p.* FROM periods p
  JOIN model_input2_work.presence r ON r.animal_key = p.animal_key AND p.d >= r.start_date AND p.d < r.end_date
  WHERE p.next_d > p.d
)
SELECT t.animal_key, t.d AS start_date, t.next_d AS end_date,
       CASE WHEN a.birth_date IS NULL OR a.sex IS NULL OR t.d < a.birth_date THEN 'unknown'
            WHEN c.calving_date IS NULL AND t.d - a.birth_date <= 270 THEN 'calf'
            WHEN a.sex = 'male' THEN 'bull'
            -- Adult with no calving in core: dry if a dry-off is recorded, else adult_no_calving
            -- (milking only with a milk record that day, otherwise unknown; never a heifer).
            WHEN c.calving_date IS NULL AND pa.parous_from <= t.d THEN
              CASE WHEN dr.event_date IS NULL THEN 'adult_no_calving'
                   WHEN pr.hindsight THEN 'dry_pregnant' ELSE 'dry_open' END
            WHEN c.calving_date IS NULL THEN CASE WHEN pr.hindsight THEN 'heifer_pregnant' ELSE 'heifer_open' END
            WHEN dr.event_date IS NULL OR dr.event_date < c.calving_date THEN 'milking'
            ELSE CASE WHEN pr.hindsight THEN 'dry_pregnant' ELSE 'dry_open' END END AS state,
       CASE WHEN a.birth_date IS NULL OR a.sex IS NULL OR t.d < a.birth_date THEN 'unknown'
            WHEN c.calving_date IS NULL AND t.d - a.birth_date <= 270 THEN 'calf'
            WHEN a.sex = 'male' THEN 'bull'
            WHEN c.calving_date IS NULL AND pa.parous_from <= t.d THEN
              CASE WHEN dr.event_date IS NULL THEN 'adult_no_calving'
                   WHEN pr.known THEN 'dry_pregnant' ELSE 'dry_open' END
            WHEN c.calving_date IS NULL THEN CASE WHEN pr.known THEN 'heifer_pregnant' ELSE 'heifer_open' END
            WHEN dr.event_date IS NULL OR dr.event_date < c.calving_date THEN 'milking'
            ELSE CASE WHEN pr.known THEN 'dry_pregnant' ELSE 'dry_open' END END AS state_known
FROM active t
JOIN core.animal a ON a.animal_key = t.animal_key
LEFT JOIN model_input2_work.parous pa ON pa.animal_key = t.animal_key
LEFT JOIN LATERAL (SELECT MAX(l.calving_date) AS calving_date FROM core.lactation l
                   WHERE l.animal_key = t.animal_key AND NOT l.is_bad_date AND l.calving_date <= t.d) c ON true
LEFT JOIN LATERAL (SELECT MAX(x.event_date) AS event_date FROM core.dry_off x
                   WHERE x.animal_key = t.animal_key AND NOT x.is_bad_date AND x.event_date <= t.d) dr ON true
CROSS JOIN LATERAL (
  SELECT EXISTS (SELECT 1 FROM model_input2_work.pregnancy p WHERE p.animal_key = t.animal_key
                 AND p.conception_date < t.d AND p.end_date > t.d) AS hindsight,
         EXISTS (SELECT 1 FROM model_input2_work.pregnancy p WHERE p.animal_key = t.animal_key
                 AND p.known_from < t.d AND p.end_date > t.d) AS known) pr;
CREATE INDEX ON model_input2_work.state_interval (animal_key, start_date);

-- 6. Observed milk per day (every valid core.animal_daily record) and the sparse-day rule.
--    A day is SPARSE = "data not available" (milk not taken, cows not counted milking) when it
--    has no placeholder herd-total record and its milk comes from fewer than 10 cows, or from
--    fewer than 10% of the average cows on the 3 days before and 3 days after
--    (e.g. ~200, 2, ~200 or 0, 5, 0). Raw totals stay in milk_observed_* for reconciliation.
DROP TABLE IF EXISTS model_input2_work.obs_day;
CREATE UNLOGGED TABLE model_input2_work.obs_day AS
WITH o AS (
  SELECT d.milk_date AS date,
         COUNT(*) AS records,
         -- yield_litres is single precision: sum in double so monthly totals are exact.
         SUM(d.yield_litres::double precision) AS litres,
         -- Cow records above 18 L/day are implausible and eliminated (placeholder herd totals exempt).
         SUM(d.yield_litres::double precision) FILTER (WHERE d.animal_key IS NOT NULL AND NOT COALESCE(a.is_placeholder, false)
                                                       AND d.yield_litres <= 18) AS cow_litres,
         SUM(d.yield_litres::double precision) FILTER (WHERE a.is_placeholder) AS placeholder_litres,
         COUNT(DISTINCT d.animal_key) FILTER (WHERE NOT COALESCE(a.is_placeholder, false)
                                              AND d.yield_litres > 0 AND d.yield_litres <= 18) AS cows,
         COUNT(*) FILTER (WHERE NOT COALESCE(a.is_placeholder, false) AND d.yield_litres > 18) AS high_records,
         SUM(d.yield_litres::double precision) FILTER (WHERE NOT COALESCE(a.is_placeholder, false)
                                                       AND d.yield_litres > 18) AS high_litres
  FROM core.animal_daily d
  LEFT JOIN core.animal a ON a.animal_key = d.animal_key
  WHERE d.is_yield_valid
  GROUP BY d.milk_date
), w AS (
  SELECT g::date AS date, o.records, o.litres, o.cow_litres, o.placeholder_litres, o.cows,
         o.high_records, o.high_litres,
         AVG(NULLIF(o.cows, 0)) OVER (ORDER BY g::date ROWS BETWEEN 3 PRECEDING AND 3 FOLLOWING
                                      EXCLUDE CURRENT ROW) AS neighbour_cows
  FROM model_input2_work.cal c CROSS JOIN generate_series(c.start_date, c.last_date, interval '1 day') g
  LEFT JOIN o ON o.date = g::date
)
SELECT x.*,
       -- herd_total: a placeholder record exists, so cows + placeholder = all milk collected that day.
       -- cow_sample: no placeholder; the records are a sample of cows (total unknown).
       -- none: no placeholder and too few cows (sparse).
       CASE WHEN COALESCE(x.placeholder_litres, 0) > 0 THEN 'herd_total'
            WHEN NOT x.is_sparse THEN 'cow_sample' ELSE 'none' END AS record_type
FROM (
  SELECT date, records, litres, cow_litres, placeholder_litres, cows, high_records, high_litres, neighbour_cows,
         (COALESCE(placeholder_litres, 0) <= 0
          AND (COALESCE(cows, 0) < 10 OR cows < 0.1 * neighbour_cows)) AS is_sparse,
         (COALESCE(cows, 0) < 10 OR cows < 0.1 * neighbour_cows) AS is_sparse_cows
  FROM w WHERE records > 0
) x;
CREATE UNIQUE INDEX ON model_input2_work.obs_day (date);

-- Milk evidence per cow-day: a valid record (cow, not placeholder) on a day that is not sparse.
DROP TABLE IF EXISTS model_input2_work.milk_evidence;
CREATE UNLOGGED TABLE model_input2_work.milk_evidence AS
SELECT DISTINCT d.animal_key, d.milk_date AS date
FROM core.animal_daily d
JOIN core.animal a ON a.animal_key = d.animal_key
JOIN model_input2_work.obs_day o ON o.date = d.milk_date AND NOT o.is_sparse
WHERE d.is_yield_valid AND NOT COALESCE(a.is_placeholder, false)
  AND d.yield_litres > 0 AND d.yield_litres <= 18;
CREATE UNIQUE INDEX ON model_input2_work.milk_evidence (animal_key, date);

-- 7. Animal-days with parity and days since calving (one lactation per animal-day).
--    Milking = in lactation by calving/dry-off records; the daily milk record is a sample:
--      valid milk record                       -> 'milking' (whatever the event state says)
--      calved, not dried off, no record that day -> 'milking' (also counted in lactating_unrecorded)
--      adult with no calving in core, no record -> 'unknown' (counted in adult_no_recorded_calving)
--      everything else keeps its event state (calf, heifer, dry, bull, unknown).
--    record_state keeps the calving/dry-off state for comparison (milking_with_inferred).
DROP TABLE IF EXISTS model_input2_work.animal_day;
CREATE UNLOGGED TABLE model_input2_work.animal_day AS
WITH state_raw AS (
  SELECT s.animal_key, g::date AS date, s.state AS record_state, s.state_known AS record_state_known
  FROM model_input2_work.state_interval s CROSS JOIN model_input2_work.cal c
  CROSS JOIN LATERAL generate_series(GREATEST(s.start_date, c.start_date),
                                     LEAST(s.end_date - 1, c.last_date), interval '1 day') g
  WHERE s.end_date > s.start_date
), state_day AS (
  SELECT r.animal_key, r.date, r.record_state, (m.animal_key IS NOT NULL) AS has_milk,
         -- In lactation (calved, not dried off) = milking, recorded that day or not: the daily
         -- record is a sample of the milking cows. A milk record also makes a cow milking.
         CASE WHEN m.animal_key IS NOT NULL THEN 'milking'
              WHEN r.record_state = 'adult_no_calving' THEN 'unknown' ELSE r.record_state END AS state,
         CASE WHEN m.animal_key IS NOT NULL THEN 'milking'
              WHEN r.record_state_known = 'adult_no_calving' THEN 'unknown'
              ELSE r.record_state_known END AS state_known
  FROM state_raw r
  LEFT JOIN model_input2_work.milk_evidence m ON m.animal_key = r.animal_key AND m.date = r.date
), lactation_day AS (
  SELECT DISTINCT ON (l.animal_key, g::date) l.animal_key, g::date AS date, l.lactation_no,
         g::date - l.calving_date AS days_since_calving
  FROM core.lactation l
  CROSS JOIN LATERAL generate_series(l.calving_date, l.cycle_end_date - 1, interval '1 day') g
  WHERE NOT l.is_bad_date AND l.cycle_end_date > l.calving_date
  ORDER BY l.animal_key, g::date, l.calving_date DESC
)
SELECT s.date, s.state, s.state_known, s.record_state, s.has_milk, l.lactation_no, l.days_since_calving,
       CASE WHEN a.generation IS NULL THEN 'unknown' WHEN a.generation >= 3 THEN '3+'
            ELSE a.generation::text END AS generation_group
FROM state_day s
JOIN core.animal a ON a.animal_key = s.animal_key
LEFT JOIN lactation_day l ON l.animal_key = s.animal_key AND l.date = s.date;

-- 8. day_cell / day_cell_known (same columns as model_input).
DROP TABLE IF EXISTS model_input2.day_cell;
CREATE TABLE model_input2.day_cell AS
SELECT date, state,
       CASE WHEN state NOT IN ('milking','dry_open','dry_pregnant') THEN '0'
            WHEN lactation_no IS NULL THEN 'unknown' WHEN lactation_no = 1 THEN '1'
            WHEN lactation_no = 2 THEN '2' ELSE '3+' END AS parity_group,
       CASE WHEN state <> 'milking' THEN 'na' WHEN days_since_calving IS NULL THEN 'unknown'
            WHEN days_since_calving <= 60 THEN '0-60' WHEN days_since_calving <= 150 THEN '61-150'
            WHEN days_since_calving <= 305 THEN '151-305' ELSE '305+' END AS dim_band,
       generation_group, COUNT(*)::integer AS n_animals
FROM model_input2_work.animal_day GROUP BY 1, 2, 3, 4, 5;
CREATE INDEX ON model_input2.day_cell (date, state);

DROP TABLE IF EXISTS model_input2.day_cell_known;
CREATE TABLE model_input2.day_cell_known AS
SELECT date, state_known AS state,
       CASE WHEN state_known NOT IN ('milking','dry_open','dry_pregnant') THEN '0'
            WHEN lactation_no IS NULL THEN 'unknown' WHEN lactation_no = 1 THEN '1'
            WHEN lactation_no = 2 THEN '2' ELSE '3+' END AS parity_group,
       CASE WHEN state_known <> 'milking' THEN 'na' WHEN days_since_calving IS NULL THEN 'unknown'
            WHEN days_since_calving <= 60 THEN '0-60' WHEN days_since_calving <= 150 THEN '61-150'
            WHEN days_since_calving <= 305 THEN '151-305' ELSE '305+' END AS dim_band,
       generation_group, COUNT(*)::integer AS n_animals
FROM model_input2_work.animal_day GROUP BY 1, 2, 3, 4, 5;
CREATE INDEX ON model_input2.day_cell_known (date, state);

-- day_cell_inferred: no inferred lactations are added (milk is no longer used to invent
-- milking spells), so it equals day_cell. Kept for the contract.
DROP TABLE IF EXISTS model_input2.day_cell_inferred;
CREATE TABLE model_input2.day_cell_inferred AS SELECT * FROM model_input2.day_cell;
CREATE INDEX ON model_input2.day_cell_inferred (date, state);

-- 9. day_panel: same columns and order as model_input.day_panel, then 5 appended columns.
DROP TABLE IF EXISTS model_input2.day_panel;
CREATE TABLE model_input2.day_panel AS
WITH days AS (
  SELECT g::date AS date FROM model_input2_work.cal c, generate_series(c.start_date, c.last_date, interval '1 day') g
), stocks AS (
  SELECT date, SUM(n_animals) AS n_herd,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'calf'), 0) AS calves,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'heifer_open'), 0) AS heifers_open,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'heifer_pregnant'), 0) AS heifers_pregnant,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'milking'), 0) AS milking,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'dry_open'), 0) AS dry_open,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'dry_pregnant'), 0) AS dry_pregnant,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'bull'), 0) AS bulls,
         COALESCE(SUM(n_animals) FILTER (WHERE state = 'unknown'), 0) AS unknown_state
  FROM model_input2.day_cell GROUP BY date
), lact AS (
  -- Lactating per calving/dry-off records, and those of them with no milk record that day.
  SELECT date, COUNT(*) FILTER (WHERE record_state = 'milking') AS lactating_recorded,
         COUNT(*) FILTER (WHERE record_state = 'milking' AND NOT has_milk) AS lactating_unrecorded,
         COUNT(*) FILTER (WHERE record_state = 'adult_no_calving' AND NOT has_milk) AS adult_no_recorded_calving
  FROM model_input2_work.animal_day GROUP BY date
), calvings AS (
  SELECT calving_date AS date, COUNT(*) AS calvings FROM core.lactation WHERE NOT is_bad_date GROUP BY 1
), dry_offs AS (
  SELECT event_date AS date, COUNT(*) AS dry_offs FROM core.dry_off WHERE NOT is_bad_date GROUP BY 1
), ais AS (
  SELECT insemination_date AS date, COUNT(*) AS ais FROM core.insemination WHERE NOT is_bad_date GROUP BY 1
), abortions AS (
  SELECT event_date AS date, COUNT(*) AS real_abortions FROM core.abortion
  WHERE NOT is_bad_date AND is_auto_generated IS FALSE GROUP BY 1
), exits AS (
  SELECT event_date AS date, COUNT(*) AS exits,
         COUNT(*) FILTER (WHERE exit_type = 'died') AS deaths,
         COUNT(*) FILTER (WHERE exit_type = 'culled') AS culls,
         COUNT(*) FILTER (WHERE exit_type = 'sold') AS sales
  FROM core.exit WHERE NOT is_bad_date GROUP BY 1
), inferred AS (
  SELECT end_date AS date, COUNT(*) AS inferred_exits FROM model_input2_work.presence
  WHERE end_reason = 'inferred_no_evidence' GROUP BY 1
), entries AS (
  SELECT event_date AS date, COUNT(*) AS entries,
         COUNT(*) FILTER (WHERE entry_type = 'born_on_farm') AS births,
         COUNT(*) FILTER (WHERE entry_type IS DISTINCT FROM 'born_on_farm') AS external_entries
  FROM core.entry WHERE NOT is_bad_date GROUP BY 1
), obs AS (
  SELECT date, records, litres, cow_litres, placeholder_litres, cows, high_records, high_litres, is_sparse,
         is_sparse_cows, record_type
  FROM model_input2_work.obs_day
), health AS (
  SELECT start_date AS date,
         COUNT(*) FILTER (WHERE health_group = 'mastitis') AS mastitis_episodes,
         COUNT(*) FILTER (WHERE health_group = 'udder_teat_condition') AS udder_teat_episodes,
         COUNT(*) FILTER (WHERE health_group = 'preventive') AS preventive_episodes,
         COUNT(*) FILTER (WHERE health_group NOT IN ('mastitis','udder_teat_condition','preventive')) AS other_health_episodes
  FROM core.health_episode GROUP BY 1
), vaccination AS (
  SELECT event_date AS date, COUNT(*) AS vaccinations FROM core.vaccination WHERE NOT is_bad_date GROUP BY 1
), session AS (
  SELECT milk_date AS date, COUNT(*) AS n_sessions,
         COUNT(*) FILTER (WHERE blood_alarm) AS n_blood_alarms,
         COUNT(*) FILTER (WHERE conductivity_alarm) AS n_conductivity_alarms
  FROM core.milk_session WHERE NOT is_bad_date GROUP BY 1
), base_raw AS (
  SELECT d.date, s.n_herd, s.calves, s.heifers_open, s.heifers_pregnant, s.milking, s.dry_open,
         s.dry_pregnant, s.bulls, s.unknown_state, o.records, o.litres, o.cow_litres, o.placeholder_litres, o.cows,
         o.high_records, o.high_litres,
         COALESCE(o.is_sparse, false) AS is_sparse,
         COALESCE(o.is_sparse_cows, true) AS is_sparse_cows,
         o.record_type AS candidate_type,
         COALESCE(o.cow_litres, 0) + COALESCE(o.high_litres, 0) + COALESCE(o.placeholder_litres, 0) AS day_total,
         -- Milk per recorded cow (records <= 18 L), when at least 10 cows were recorded.
         CASE WHEN o.cows >= 10 THEN o.cow_litres / o.cows END AS per_recorded_cow
  FROM days d
  LEFT JOIN stocks s USING (date)
  LEFT JOIN obs o USING (date)
), typed AS (
  -- A placeholder day is a herd total only when it is plausible for the whole herd: at least
  -- 5 L per milking cow (before 2025 the placeholder record is only a small slice of the day).
  -- Otherwise it falls back to a cow sample (enough cows recorded) or to no data.
  SELECT r.*,
         CASE WHEN r.candidate_type = 'herd_total' AND r.day_total >= 5 * NULLIF(r.milking, 0) THEN 'herd_total'
              WHEN r.records > 0 AND NOT r.is_sparse_cows THEN 'cow_sample'
              ELSE 'none' END AS record_type
  FROM base_raw r
), base0 AS (
  SELECT t0.*,
         -- Measured herd milk (herd_total days): cows <= 18 L + cow records > 18 L moved to
         -- unidentified + placeholder.
         CASE WHEN t0.record_type = 'herd_total' THEN t0.day_total END AS herd_measured,
         CASE WHEN t0.record_type = 'herd_total' THEN t0.high_litres END AS reassigned_litres
  FROM typed t0
), herd AS (
  -- Target = measured herd milk (herd_total) or, on cow_sample days, the ESTIMATE
  -- milk per recorded cow x milking herd (flagged herd_milk_is_estimated).
  SELECT b0.*,
         CASE WHEN b0.record_type = 'herd_total' THEN b0.herd_measured
              WHEN b0.record_type = 'cow_sample' THEN b0.per_recorded_cow * NULLIF(b0.milking, 0)
         END AS use_litres
  FROM base0 b0
), base AS (
  SELECT h.*, h.use_litres / NULLIF(h.milking, 0) AS per_cow FROM herd h
), flagged AS (
  -- Past-only 28-day means flag implausibly low totals and high litres per observed cow.
  SELECT b.*,
         AVG(NULLIF(b.use_litres, 0)) OVER w AS litres_prev28,
         AVG(NULLIF(b.per_cow, 0)) OVER w AS per_cow_prev28
  FROM base b WINDOW w AS (ORDER BY b.date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING)
), target AS (
  SELECT f.*,
         -- Labelled 'delpro' (AnimalDaily is a DelPro table) so C1's source logic runs unchanged.
         CASE WHEN f.use_litres IS NOT NULL THEN 'delpro' END AS target_source,
         COALESCE(f.use_litres < 0.5 * f.litres_prev28, false) AS is_suspect_low,
         COALESCE(f.per_cow > 1.5 * f.per_cow_prev28, false) AS is_suspect_high,
         -- Herd milk per milking cow above 18 L/day is implausible: not scoreable.
         COALESCE(f.per_cow > 18, false) AS is_implausible_volume
  FROM flagged f
)
SELECT t.date, date_trunc('week', t.date)::date AS week_start, date_trunc('month', t.date)::date AS month,
       CASE WHEN t.date < DATE '2017-01-01' THEN 'burn_in'
            WHEN t.date < DATE '2024-01-01' THEN 'development' ELSE 'test' END AS time_block,
       COALESCE(t.n_herd, 0) AS n_herd, COALESCE(t.calves, 0) AS calves,
       COALESCE(t.heifers_open, 0) AS heifers_open, COALESCE(t.heifers_pregnant, 0) AS heifers_pregnant,
       COALESCE(t.milking, 0) AS milking, COALESCE(t.dry_open, 0) AS dry_open,
       COALESCE(t.dry_pregnant, 0) AS dry_pregnant, COALESCE(t.bulls, 0) AS bulls,
       COALESCE(t.unknown_state, 0) AS unknown_state,
       COALESCE(cv.calvings, 0) AS calvings, COALESCE(dr.dry_offs, 0) AS dry_offs,
       COALESCE(ai.ais, 0) AS ais, COALESCE(ab.real_abortions, 0) AS real_abortions,
       COALESCE(x.deaths, 0) AS deaths, COALESCE(x.culls, 0) AS culls, COALESCE(x.sales, 0) AS sales,
       COALESCE(x.exits, 0) AS exits, COALESCE(ie.inferred_exits, 0) AS inferred_exits,
       COALESCE(en.entries, 0) AS entries, COALESCE(en.births, 0) AS births,
       COALESCE(en.external_entries, 0) AS external_entries,
       -- Information only (not the target): shipments and DelPro history totals from core.herd_day.
       h.milk_shipped, h.milk_internal, h.milk_delpro_cows, h.milk_delpro_unidentified,
       COALESCE(h.milk_delpro_cows, 0) + COALESCE(h.milk_delpro_unidentified, 0) AS milk_delpro_total,
       h.milk_hand_milked_est,
       t.cow_litres / NULLIF(t.litres, 0) AS identified_share,
       (t.use_litres IS NULL) AS data_gap,
       t.target_source,
       t.use_litres AS target_litres,
       t.is_suspect_low, t.is_suspect_high,
       t.per_cow AS target_litres_per_cow,
       (t.target_source IS NOT NULL AND NOT t.is_suspect_low AND NOT t.is_suspect_high
        AND NOT t.is_implausible_volume) AS is_scoreable,
       t.n_herd AS cells_herd, t.milking AS cells_milking,
       COALESCE(w.is_complete, false) AS weather_is_complete,
       w.temp_mean_c, w.temp_max_c, w.rh_mean_pct, w.rain_total_mm,
       w.thi_mean, w.thi_max, w.hours_thi_above,
       COALESCE(he.mastitis_episodes, 0) AS mastitis_episodes,
       COALESCE(he.udder_teat_episodes, 0) AS udder_teat_episodes,
       COALESCE(he.preventive_episodes, 0) AS preventive_episodes,
       COALESCE(he.other_health_episodes, 0) AS other_health_episodes,
       COALESCE(v.vaccinations, 0) AS vaccinations,
       COALESCE(se.n_sessions, 0) AS n_sessions, COALESCE(se.n_blood_alarms, 0) AS n_blood_alarms,
       COALESCE(se.n_conductivity_alarms, 0) AS n_conductivity_alarms,
       -- Here: cows in lactation by calving/dry-off records (with or without milk that day).
       COALESCE(lc.lactating_recorded, 0) AS milking_with_inferred,
       CASE WHEN t.is_sparse THEN 0 ELSE COALESCE(t.cows, 0) END AS cows_with_identified_milk,
       t.is_implausible_volume,
       (t.target_source IS NOT NULL AND NOT t.is_suspect_low AND NOT t.is_suspect_high) AS is_scoreable_v1,
       -- Appended (model_input2 only): observed-milk detail from core.animal_daily.
       COALESCE(t.records, 0) AS milk_observed_records,
       t.cow_litres AS milk_observed_cow_litres,
       t.placeholder_litres AS milk_observed_placeholder_litres,
       COALESCE(t.cows, 0) AS observed_milking_cows,
       COALESCE(lc.lactating_unrecorded, 0) AS lactating_unrecorded,
       COALESCE(lc.adult_no_recorded_calving, 0) AS adult_no_recorded_calving,
       t.litres AS milk_observed_litres,
       t.is_sparse AS is_sparse_day,
       COALESCE(t.high_records, 0) AS milk_excluded_high_records,
       t.high_litres AS milk_excluded_high_litres,
       t.record_type AS milk_record_type,
       t.herd_measured AS herd_milk_measured,
       (t.record_type = 'cow_sample') AS herd_milk_is_estimated,
       t.per_recorded_cow AS milk_per_recorded_cow,
       t.reassigned_litres AS milk_reassigned_to_unidentified
FROM target t
LEFT JOIN lact lc ON lc.date = t.date
LEFT JOIN core.herd_day h ON h.date = t.date
LEFT JOIN core.weather_day w ON w.date = t.date
LEFT JOIN calvings cv ON cv.date = t.date
LEFT JOIN dry_offs dr ON dr.date = t.date
LEFT JOIN ais ai ON ai.date = t.date
LEFT JOIN abortions ab ON ab.date = t.date
LEFT JOIN exits x ON x.date = t.date
LEFT JOIN inferred ie ON ie.date = t.date
LEFT JOIN entries en ON en.date = t.date
LEFT JOIN health he ON he.date = t.date
LEFT JOIN vaccination v ON v.date = t.date
LEFT JOIN session se ON se.date = t.date;
CREATE UNIQUE INDEX ON model_input2.day_panel (date);

-- 10. period_panel: same columns as model_input.period_panel (weeks Monday start, calendar
--    months), then appended observed-milk columns. Distinct cows are counted per period.
DROP TABLE IF EXISTS model_input2.period_panel;
CREATE TABLE model_input2.period_panel AS
WITH grouped AS (
  SELECT CASE WHEN GROUPING(week_start) = 0 THEN 'week' ELSE 'month' END AS grain,
         COALESCE(week_start, month) AS period_start,
         CASE WHEN GROUPING(week_start) = 0 THEN 7
              ELSE (MIN(month) + interval '1 month')::date - MIN(month) END AS expected_days,
         COUNT(*) AS n_days, COUNT(*) FILTER (WHERE is_scoreable) AS n_scoreable_days,
         COUNT(*) FILTER (WHERE is_suspect_high) AS n_suspect_high_days,
         COUNT(DISTINCT target_source) AS n_sources, MIN(target_source) AS any_source,
         SUM(target_litres) AS target_litres,
         AVG(n_herd) AS avg_herd, AVG(calves) AS avg_calves, AVG(heifers_open) AS avg_heifers_open,
         AVG(heifers_pregnant) AS avg_heifers_pregnant, AVG(milking) AS avg_milking,
         AVG(dry_open) AS avg_dry_open, AVG(dry_pregnant) AS avg_dry_pregnant, AVG(bulls) AS avg_bulls,
         SUM(calvings) AS calvings, SUM(dry_offs) AS dry_offs, SUM(ais) AS ais,
         SUM(real_abortions) AS real_abortions, SUM(deaths) AS deaths, SUM(culls) AS culls,
         SUM(sales) AS sales, SUM(exits) AS exits, SUM(inferred_exits) AS inferred_exits,
         SUM(births) AS births, SUM(external_entries) AS external_entries,
         SUM(milk_shipped) AS milk_shipped, SUM(milk_delpro_total) AS milk_delpro_total,
         SUM(milk_hand_milked_est) AS milk_hand_milked_est,
         SUM(milk_observed_cow_litres) FILTER (WHERE NOT data_gap) / NULLIF(SUM(target_litres), 0) AS identified_share,
         COUNT(*) FILTER (WHERE data_gap) AS n_gap_days,
         AVG(thi_mean) AS thi_mean, MAX(thi_max) AS thi_max, SUM(hours_thi_above) AS hours_thi_above,
         SUM(rain_total_mm) AS rain_total_mm,
         SUM(mastitis_episodes) AS mastitis_episodes, SUM(udder_teat_episodes) AS udder_teat_episodes,
         SUM(preventive_episodes) AS preventive_episodes, SUM(other_health_episodes) AS other_health_episodes,
         SUM(vaccinations) AS vaccinations, SUM(n_sessions) AS n_sessions,
         SUM(n_blood_alarms) AS n_blood_alarms, SUM(n_conductivity_alarms) AS n_conductivity_alarms,
         AVG(milking_with_inferred) AS avg_milking_with_inferred,
         COUNT(*) FILTER (WHERE is_implausible_volume) AS n_implausible_volume_days,
         SUM(milk_observed_records) AS milk_observed_records,
         COUNT(*) FILTER (WHERE milk_observed_records > 0) AS n_observed_days,
         AVG(observed_milking_cows) AS avg_observed_milking_cows,
         AVG(lactating_unrecorded) AS avg_lactating_unrecorded,
         AVG(adult_no_recorded_calving) AS avg_adult_no_recorded_calving,
         SUM(milk_observed_litres) AS milk_observed_litres,
         COUNT(*) FILTER (WHERE is_sparse_day) AS n_sparse_days,
         SUM(milk_excluded_high_records) AS milk_excluded_high_records,
         SUM(milk_excluded_high_litres) AS milk_excluded_high_litres,
         SUM(herd_milk_measured) AS herd_milk_measured,
         SUM(target_litres) FILTER (WHERE herd_milk_is_estimated) AS herd_milk_estimated,
         COUNT(*) FILTER (WHERE milk_record_type = 'herd_total') AS n_herd_total_days,
         COUNT(*) FILTER (WHERE milk_record_type = 'cow_sample') AS n_cow_sample_days,
         SUM(milk_reassigned_to_unidentified) AS milk_reassigned_to_unidentified
  FROM model_input2.day_panel
  GROUP BY GROUPING SETS ((week_start), (month))
), cows AS (
  SELECT 'week' AS grain, date_trunc('week', d.milk_date)::date AS period_start,
         COUNT(DISTINCT d.animal_key) AS n
  FROM core.animal_daily d LEFT JOIN core.animal a ON a.animal_key = d.animal_key
  WHERE d.is_yield_valid AND NOT COALESCE(a.is_placeholder, false) AND d.animal_key IS NOT NULL
  GROUP BY 2
  UNION ALL
  SELECT 'month', date_trunc('month', d.milk_date)::date, COUNT(DISTINCT d.animal_key)
  FROM core.animal_daily d LEFT JOIN core.animal a ON a.animal_key = d.animal_key
  WHERE d.is_yield_valid AND NOT COALESCE(a.is_placeholder, false) AND d.animal_key IS NOT NULL
  GROUP BY 2
)
SELECT g.grain, g.period_start,
       CASE WHEN g.period_start < DATE '2017-01-01' THEN 'burn_in'
            WHEN g.period_start < DATE '2024-01-01' THEN 'development' ELSE 'test' END AS time_block,
       g.expected_days, g.n_days, g.n_scoreable_days, g.n_suspect_high_days,
       CASE WHEN g.n_sources = 1 THEN g.any_source WHEN g.n_sources > 1 THEN 'mixed' END AS target_source,
       (g.n_days = g.expected_days AND g.n_scoreable_days = g.expected_days AND g.n_sources = 1) AS is_scoreable,
       g.target_litres, g.avg_herd, g.avg_calves, g.avg_heifers_open, g.avg_heifers_pregnant,
       g.avg_milking, g.avg_dry_open, g.avg_dry_pregnant, g.avg_bulls,
       g.calvings, g.dry_offs, g.ais, g.real_abortions, g.deaths, g.culls, g.sales, g.exits, g.inferred_exits,
       g.births, g.external_entries, g.milk_shipped, g.milk_delpro_total, g.milk_hand_milked_est,
       g.identified_share, g.n_gap_days,
       g.thi_mean, g.thi_max, g.hours_thi_above, g.rain_total_mm,
       g.mastitis_episodes, g.udder_teat_episodes, g.preventive_episodes, g.other_health_episodes,
       g.vaccinations, g.n_sessions, g.n_blood_alarms, g.n_conductivity_alarms,
       g.avg_milking_with_inferred, g.n_implausible_volume_days,
       -- Appended (model_input2 only).
       g.milk_observed_records, g.n_observed_days, g.avg_observed_milking_cows,
       COALESCE(c.n, 0) AS distinct_observed_cows, g.avg_lactating_unrecorded,
       g.avg_adult_no_recorded_calving, g.milk_observed_litres, g.n_sparse_days,
       g.milk_excluded_high_records, g.milk_excluded_high_litres,
       g.herd_milk_measured, g.herd_milk_estimated, g.n_herd_total_days, g.n_cow_sample_days,
       g.milk_reassigned_to_unidentified
FROM grouped g
LEFT JOIN cows c ON c.grain = g.grain AND c.period_start = g.period_start;
CREATE UNIQUE INDEX ON model_input2.period_panel (grain, period_start);

-- 11. Read access for C1 (farmx_model) and the backend (farmx_api).
GRANT USAGE ON SCHEMA model_input2 TO farmx_model, farmx_api;
GRANT SELECT ON ALL TABLES IN SCHEMA model_input2 TO farmx_model, farmx_api;

-- ===================================================================================
-- Checks (aggregates only). Send these results back.
-- ===================================================================================

-- C0: did this build run? Expect new_columns = 5 and day_panel_days = 4038.
SELECT (SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'model_input2' AND table_name IN ('day_panel', 'period_panel')
          AND column_name IN ('is_sparse_day', 'adult_no_recorded_calving', 'milk_observed_litres', 'n_sparse_days')) AS new_columns,
       (SELECT COUNT(*) FROM model_input2.day_panel) AS day_panel_days;

-- C1: monthly observed milk, records and days. total_milk / record_count / days_available
-- must equal the supplied Query 1 exactly; usable_milk excludes sparse days.
SELECT to_char(period_start, 'YYYY-MM') AS month,
       ROUND(milk_observed_litres::numeric, 2) AS total_milk,
       milk_observed_records AS record_count,
       n_observed_days AS days_available,
       distinct_observed_cows,
       n_sparse_days,
       ROUND(target_litres::numeric, 2) AS usable_milk,
       n_days - n_gap_days AS usable_days
FROM model_input2.period_panel
WHERE grain = 'month' AND period_start >= DATE '2015-11-01'
ORDER BY period_start;

-- C2: the same from core directly, as a difference. Expect every column = 0.
WITH core_m AS (
  SELECT date_trunc('month', milk_date)::date AS m, SUM(yield_litres::double precision) AS litres, COUNT(*) AS n
  FROM core.animal_daily WHERE is_yield_valid AND milk_date >= DATE '2015-11-01'
    AND milk_date <= (SELECT last_date FROM model_input2_work.cal)
  GROUP BY 1
)
SELECT COUNT(*) AS months,
       COUNT(*) FILTER (WHERE abs(COALESCE(p.milk_observed_litres, 0) - c.litres) > 0.01) AS months_litres_differ,
       COUNT(*) FILTER (WHERE COALESCE(p.milk_observed_records, 0) <> c.n) AS months_records_differ
FROM core_m c
LEFT JOIN model_input2.period_panel p ON p.grain = 'month' AND p.period_start = c.m;

-- C3: herd consistency. Expect every *_differ = 0.
SELECT COUNT(*) AS days,
       COUNT(*) - COUNT(DISTINCT date) AS duplicate_days,
       COUNT(*) FILTER (WHERE n_herd <> calves + heifers_open + heifers_pregnant + milking
                        + dry_open + dry_pregnant + bulls + unknown_state) AS stock_sum_differ,
       COUNT(*) FILTER (WHERE target_litres IS NOT NULL AND data_gap) AS gap_with_milk,
       COUNT(*) FILTER (WHERE data_gap) AS days_without_observed_milk
FROM model_input2.day_panel;

-- C4: new vs old herd and milk, by year (averages / sums only).
SELECT EXTRACT(year FROM n.date)::int AS year,
       ROUND(AVG(n.n_herd)) AS herd_new, ROUND(AVG(o.n_herd)) AS herd_old,
       ROUND(AVG(n.milking)) AS milking_new, ROUND(AVG(o.milking)) AS milking_old,
       ROUND(AVG(n.dry_open + n.dry_pregnant)) AS dry_new, ROUND(AVG(o.dry_open + o.dry_pregnant)) AS dry_old,
       ROUND(AVG(n.observed_milking_cows)) AS observed_cows_per_day,
       SUM(n.calvings) AS calvings_new, SUM(o.calvings) AS calvings_old,
       SUM(n.exits) AS exits_new, SUM(o.exits) AS exits_old,
       SUM(n.inferred_exits) AS inferred_exits_new, SUM(o.inferred_exits) AS inferred_exits_old,
       ROUND(SUM(n.target_litres)::numeric) AS milk_new, ROUND(SUM(o.target_litres)::numeric) AS milk_old
FROM model_input2.day_panel n
LEFT JOIN model_input.day_panel o ON o.date = n.date
GROUP BY 1 ORDER BY 1;

-- C5: whole-history distinct cows with valid milk (compare with Query 2 = 4,205 incl. any placeholder).
SELECT COUNT(DISTINCT d.animal_key) FILTER (WHERE NOT COALESCE(a.is_placeholder, false)) AS cows,
       COUNT(DISTINCT d.animal_key) FILTER (WHERE a.is_placeholder) AS placeholder_animals,
       COUNT(*) FILTER (WHERE d.animal_key IS NULL) AS unlinked_records
FROM core.animal_daily d LEFT JOIN core.animal a ON a.animal_key = d.animal_key
WHERE d.is_yield_valid AND d.milk_date >= DATE '2015-10-01';

-- C6: event totals by year must equal the core tables they come from (from the panel start,
-- 2015-08-01; earlier events are before the window). Expect every *_diff = 0.
WITH p AS (
  SELECT EXTRACT(year FROM date)::int AS y, SUM(calvings) calvings, SUM(dry_offs) dry_offs, SUM(ais) ais,
         SUM(real_abortions) abortions, SUM(deaths) deaths, SUM(culls) culls, SUM(sales) sales,
         SUM(exits) exits, SUM(entries) entries, SUM(births) births
  FROM model_input2.day_panel GROUP BY 1
), c AS (
  SELECT y,
    (SELECT COUNT(*) FROM core.lactation WHERE NOT is_bad_date AND EXTRACT(year FROM calving_date) = y AND calving_date >= (SELECT start_date FROM model_input2_work.cal)) calvings,
    (SELECT COUNT(*) FROM core.dry_off WHERE NOT is_bad_date AND EXTRACT(year FROM event_date) = y AND event_date >= (SELECT start_date FROM model_input2_work.cal)) dry_offs,
    (SELECT COUNT(*) FROM core.insemination WHERE NOT is_bad_date AND EXTRACT(year FROM insemination_date) = y AND insemination_date >= (SELECT start_date FROM model_input2_work.cal)) ais,
    (SELECT COUNT(*) FROM core.abortion WHERE NOT is_bad_date AND is_auto_generated IS FALSE AND EXTRACT(year FROM event_date) = y AND event_date >= (SELECT start_date FROM model_input2_work.cal)) abortions,
    (SELECT COUNT(*) FROM core.exit WHERE NOT is_bad_date AND exit_type = 'died' AND EXTRACT(year FROM event_date) = y AND event_date >= (SELECT start_date FROM model_input2_work.cal)) deaths,
    (SELECT COUNT(*) FROM core.exit WHERE NOT is_bad_date AND exit_type = 'culled' AND EXTRACT(year FROM event_date) = y AND event_date >= (SELECT start_date FROM model_input2_work.cal)) culls,
    (SELECT COUNT(*) FROM core.exit WHERE NOT is_bad_date AND exit_type = 'sold' AND EXTRACT(year FROM event_date) = y AND event_date >= (SELECT start_date FROM model_input2_work.cal)) sales,
    (SELECT COUNT(*) FROM core.exit WHERE NOT is_bad_date AND EXTRACT(year FROM event_date) = y AND event_date >= (SELECT start_date FROM model_input2_work.cal)) exits,
    (SELECT COUNT(*) FROM core.entry WHERE NOT is_bad_date AND EXTRACT(year FROM event_date) = y AND event_date >= (SELECT start_date FROM model_input2_work.cal)) entries,
    (SELECT COUNT(*) FROM core.calf WHERE EXTRACT(year FROM birth_date) = y AND birth_date >= (SELECT start_date FROM model_input2_work.cal)) calves_in_core_calf
  FROM (SELECT DISTINCT y FROM p) years
)
SELECT p.y AS year, p.calvings, p.calvings - c.calvings AS calvings_diff, p.dry_offs - c.dry_offs AS dry_offs_diff,
       p.ais - c.ais AS ais_diff, p.abortions, p.abortions - c.abortions AS abortions_diff,
       p.deaths - c.deaths AS deaths_diff, p.culls - c.culls AS culls_diff, p.sales - c.sales AS sales_diff,
       p.exits - c.exits AS exits_diff, p.entries - c.entries AS entries_diff,
       p.births AS births_born_on_farm, c.calves_in_core_calf
FROM p JOIN c USING (y) ORDER BY 1;

-- C7: herd balance per month: change in herd vs flows. stock_change - net_flow = animals whose
-- presence starts/ends without a recorded entry/exit (births without entry, inferred exits).
WITH m AS (
  SELECT month,
         (array_agg(n_herd ORDER BY date DESC))[1] AS herd_end,
         (array_agg(n_herd ORDER BY date))[1] AS herd_start,
         SUM(entries) AS entries, SUM(exits) AS exits, SUM(inferred_exits) AS inferred_exits
  FROM model_input2.day_panel GROUP BY month
)
SELECT EXTRACT(year FROM month)::int AS year,
       SUM(herd_end - herd_start) AS stock_change,
       SUM(entries - exits - inferred_exits) AS net_recorded_flow,
       SUM((herd_end - herd_start) - (entries - exits - inferred_exits)) AS unexplained
FROM m GROUP BY 1 ORDER BY 1;

-- C8: milking rule audit by year: milking (in lactation or recorded) vs cows with a record.
SELECT EXTRACT(year FROM date)::int AS year,
       ROUND(AVG(milking)) AS milking,
       ROUND(AVG(milking - lactating_unrecorded)) AS milking_with_milk_record,
       ROUND(AVG(milking_with_inferred)) AS in_lactation_by_records,
       ROUND(AVG(lactating_unrecorded)) AS in_lactation_no_milk_record,
       ROUND(AVG(milking - milking_with_inferred)) AS milking_outside_recorded_lactation,
       ROUND(AVG(adult_no_recorded_calving)) AS adult_no_recorded_calving,
       ROUND(AVG(dry_open + dry_pregnant)) AS dry,
       ROUND(AVG(unknown_state)) AS unknown_state,
       ROUND(AVG(calves)) AS calves, ROUND(AVG(heifers_open + heifers_pregnant)) AS heifers,
       ROUND(AVG(n_herd)) AS herd
FROM model_input2.day_panel GROUP BY 1 ORDER BY 1;

-- C9: animals that entered from outside before 2016 (opening herd): parity and age at entry.
SELECT CASE WHEN e.lactation_no IS NULL THEN 'unknown' WHEN e.lactation_no = 0 THEN '0 (heifer)'
            WHEN e.lactation_no = 1 THEN '1' WHEN e.lactation_no = 2 THEN '2' ELSE '3+' END AS lactation_at_entry,
       CASE WHEN a.birth_date IS NULL THEN 'unknown'
            WHEN e.event_date - a.birth_date < 365 THEN '<12 m'
            WHEN e.event_date - a.birth_date < 730 THEN '12-24 m'
            WHEN e.event_date - a.birth_date < 1095 THEN '24-36 m' ELSE '36+ m' END AS age_at_entry,
       COUNT(DISTINCT e.animal_key) AS animals,
       COUNT(DISTINCT e.animal_key) FILTER (WHERE p.parous_from IS NOT NULL) AS classed_adult
FROM core.entry e
JOIN core.animal a ON a.animal_key = e.animal_key
LEFT JOIN model_input2_work.parous p ON p.animal_key = e.animal_key
WHERE NOT e.is_bad_date AND e.event_date < DATE '2016-01-01'
  AND e.entry_type IS DISTINCT FROM 'born_on_farm'
GROUP BY 1, 2 ORDER BY 1, 2;

-- C10: sparse days (treated as data not available), by year.
SELECT EXTRACT(year FROM date)::int AS year,
       COUNT(*) FILTER (WHERE milk_observed_records > 0) AS days_with_records,
       COUNT(*) FILTER (WHERE is_sparse_day) AS sparse_days,
       ROUND(SUM(milk_observed_litres) FILTER (WHERE is_sparse_day)::numeric) AS sparse_litres_dropped,
       COUNT(*) FILTER (WHERE NOT data_gap) AS usable_days,
       ROUND(SUM(target_litres)::numeric) AS usable_litres
FROM model_input2.day_panel GROUP BY 1 ORDER BY 1;

-- C11: cow daily records above 18 L (eliminated), by year.
SELECT EXTRACT(year FROM date)::int AS year,
       SUM(milk_observed_records) AS valid_records,
       SUM(milk_excluded_high_records) AS records_over_18l,
       ROUND(100.0 * SUM(milk_excluded_high_records) / NULLIF(SUM(milk_observed_records), 0), 2) AS pct_over_18l,
       ROUND(SUM(milk_excluded_high_litres)::numeric) AS litres_over_18l
FROM model_input2.day_panel GROUP BY 1 ORDER BY 1;

-- C12: herd milk by record type, by year (measured vs estimated are never mixed in one column).
SELECT EXTRACT(year FROM date)::int AS year,
       COUNT(*) FILTER (WHERE milk_record_type = 'herd_total') AS herd_total_days,
       COUNT(*) FILTER (WHERE milk_record_type = 'cow_sample') AS cow_sample_days,
       COUNT(*) FILTER (WHERE milk_record_type = 'none') AS no_data_days,
       ROUND(SUM(herd_milk_measured)::numeric) AS measured_litres,
       ROUND(SUM(target_litres) FILTER (WHERE herd_milk_is_estimated)::numeric) AS estimated_litres,
       ROUND(SUM(milk_reassigned_to_unidentified)::numeric) AS reassigned_over_18l_litres,
       ROUND(AVG(milk_per_recorded_cow)::numeric, 1) AS avg_litres_per_recorded_cow,
       ROUND(AVG(target_litres_per_cow)::numeric, 1) AS avg_herd_litres_per_milking_cow,
       COUNT(*) FILTER (WHERE is_implausible_volume) AS implausible_days
FROM model_input2.day_panel GROUP BY 1 ORDER BY 1;
