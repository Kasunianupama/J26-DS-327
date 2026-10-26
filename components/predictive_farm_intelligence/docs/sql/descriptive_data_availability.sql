-- Farm X descriptive data-availability audit.
--
-- Privacy: every result is an aggregate. No animal key, source identifier, name,
-- or row-level record is returned. Run this yourself against farmx_app; AI agents
-- must never execute it or receive row-level output.
--
-- Definitions used here:
--   usable yield       positive, non-placeholder core.cow_day record
--   reliable yield     usable yield with is_reliable = true
--   sensor record      valid, non-placeholder core.milk_session row
--   cow-day overlap    the same pseudonymous cow has both kinds of record that day;
--                      only the aggregate number of matching cow-days is returned
--   farm-wide gap      model_input2 expects milking cows, but no identified cow has
--                      a usable yield record that day
--   partial gap        at least one cow is observed, but at least one expected
--                      lactating cow is unrecorded
--
-- model_input2 is required only for Queries 5 and 6. All other queries use core only.
-- Exact diagnosis/treatment/vaccination labels may contain locally entered text. Keep
-- those results local; if sharing results with an AI, share reviewed categories and
-- counts only, not free-text labels that could contain a person or supplier name.

BEGIN TRANSACTION READ ONLY;

-- Q1. One-row inventory: date coverage and total record counts.
WITH y AS (
    SELECT MIN(milk_date) FILTER (
               WHERE yield_litres > 0
                 AND NOT COALESCE(is_missing_yield, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS first_date,
           MAX(milk_date) FILTER (
               WHERE yield_litres > 0
                 AND NOT COALESCE(is_missing_yield, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS last_date,
           COUNT(*) FILTER (
               WHERE yield_litres > 0
                 AND NOT COALESCE(is_missing_yield, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS usable_yield_records,
           COUNT(DISTINCT milk_date) FILTER (
               WHERE yield_litres > 0
                 AND NOT COALESCE(is_missing_yield, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS days_with_usable_yield,
           COUNT(DISTINCT animal_key) FILTER (
               WHERE yield_litres > 0
                 AND NOT COALESCE(is_missing_yield, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS cows_with_usable_yield,
           COUNT(*) FILTER (
               WHERE yield_litres > 0
                 AND COALESCE(is_reliable, false)
                 AND NOT COALESCE(is_missing_yield, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS reliable_yield_records
    FROM core.cow_day
), s AS (
    SELECT MIN(milk_date) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS first_date,
           MAX(milk_date) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS last_date,
           COUNT(*) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS sensor_records,
           COUNT(DISTINCT milk_date) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
                 AND NOT COALESCE(is_placeholder, false)
           ) AS days_with_sensors,
           COUNT(DISTINCT animal_key) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
                 AND NOT COALESCE(is_placeholder, false)
                 AND NOT COALESCE(is_unlinked_animal, false)
           ) AS cows_with_linked_sensors
    FROM core.milk_session
), l AS (
    SELECT MIN(calving_date) FILTER (WHERE NOT COALESCE(is_bad_date, false)) AS first_calving,
           MAX(calving_date) FILTER (WHERE NOT COALESCE(is_bad_date, false)) AS last_calving,
           COUNT(*) FILTER (WHERE NOT COALESCE(is_bad_date, false)) AS lactations,
           COUNT(DISTINCT animal_key) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
           ) AS cows_with_lactations,
           COUNT(conception_date) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
           ) AS lactations_with_conception,
           COUNT(dry_off_date) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
           ) AS lactations_with_dry_off
    FROM core.lactation
), i AS (
    SELECT MIN(insemination_date) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
           ) AS first_insemination,
           MAX(insemination_date) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
           ) AS last_insemination,
           COUNT(*) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
           ) AS inseminations,
           COUNT(DISTINCT animal_key) FILTER (
               WHERE NOT COALESCE(is_bad_date, false)
           ) AS cows_with_inseminations
    FROM core.insemination
)
SELECT y.first_date AS yield_first_date,
       y.last_date AS yield_last_date,
       (y.last_date - y.first_date + 1) AS yield_calendar_span_days,
       y.usable_yield_records,
       y.days_with_usable_yield,
       y.cows_with_usable_yield,
       y.reliable_yield_records,
       s.first_date AS sensor_first_date,
       s.last_date AS sensor_last_date,
       (s.last_date - s.first_date + 1) AS sensor_calendar_span_days,
       s.sensor_records,
       s.days_with_sensors,
       s.cows_with_linked_sensors,
       l.first_calving,
       l.last_calving,
       l.lactations,
       l.cows_with_lactations,
       l.lactations_with_conception,
       l.lactations_with_dry_off,
       i.first_insemination,
       i.last_insemination,
       i.inseminations,
       i.cows_with_inseminations
FROM y CROSS JOIN s CROSS JOIN l CROSS JOIN i;

-- Q2. Observed cow milk-yield coverage by month.
-- This answers how many cows, calendar days, and usable/reliable cow-day records exist.
SELECT date_trunc('month', milk_date)::date AS month,
       COUNT(DISTINCT milk_date) FILTER (
           WHERE yield_litres > 0
             AND NOT COALESCE(is_missing_yield, false)
             AND NOT COALESCE(is_placeholder, false)
       ) AS days_with_usable_yield,
       COUNT(DISTINCT animal_key) FILTER (
           WHERE yield_litres > 0
             AND NOT COALESCE(is_missing_yield, false)
             AND NOT COALESCE(is_placeholder, false)
       ) AS cows_with_usable_yield,
       COUNT(*) FILTER (
           WHERE yield_litres > 0
             AND NOT COALESCE(is_missing_yield, false)
             AND NOT COALESCE(is_placeholder, false)
       ) AS usable_cow_days,
       COUNT(*) FILTER (
           WHERE yield_litres > 0
             AND COALESCE(is_reliable, false)
             AND NOT COALESCE(is_missing_yield, false)
             AND NOT COALESCE(is_placeholder, false)
       ) AS reliable_cow_days,
       ROUND(AVG(yield_litres) FILTER (
           WHERE yield_litres > 0
             AND NOT COALESCE(is_missing_yield, false)
             AND NOT COALESCE(is_placeholder, false)
       )::numeric, 2) AS mean_litres_per_observed_cow_day
FROM core.cow_day
GROUP BY 1
ORDER BY 1;

-- Q3. Sensor/yield overlap by month at two levels:
--   calendar-day overlap: both sources have at least one record on the date;
--   cow-day overlap: the same linked cow occurs in both sources on the date.
WITH y AS (
    SELECT DISTINCT milk_date, animal_key
    FROM core.cow_day
    WHERE yield_litres > 0
      AND NOT COALESCE(is_missing_yield, false)
      AND NOT COALESCE(is_placeholder, false)
), s AS (
    SELECT DISTINCT milk_date, animal_key
    FROM core.milk_session
    WHERE NOT COALESCE(is_bad_date, false)
      AND NOT COALESCE(is_placeholder, false)
      AND NOT COALESCE(is_unlinked_animal, false)
), yd AS (
    SELECT milk_date, COUNT(*) AS yield_cow_days FROM y GROUP BY 1
), sd AS (
    SELECT milk_date, COUNT(*) AS sensor_cow_days FROM s GROUP BY 1
), od AS (
    SELECT y.milk_date, COUNT(*) AS overlapping_cow_days
    FROM y JOIN s USING (milk_date, animal_key)
    GROUP BY 1
), dates AS (
    SELECT COALESCE(yd.milk_date, sd.milk_date) AS milk_date,
           COALESCE(yd.yield_cow_days, 0) AS yield_cow_days,
           COALESCE(sd.sensor_cow_days, 0) AS sensor_cow_days,
           COALESCE(od.overlapping_cow_days, 0) AS overlapping_cow_days
    FROM yd
    FULL JOIN sd USING (milk_date)
    LEFT JOIN od ON od.milk_date = COALESCE(yd.milk_date, sd.milk_date)
)
SELECT date_trunc('month', milk_date)::date AS month,
       COUNT(*) FILTER (WHERE yield_cow_days > 0) AS yield_days,
       COUNT(*) FILTER (WHERE sensor_cow_days > 0) AS sensor_days,
       COUNT(*) FILTER (
           WHERE yield_cow_days > 0 AND sensor_cow_days > 0
       ) AS overlapping_calendar_days,
       SUM(yield_cow_days) AS yield_cow_days,
       SUM(sensor_cow_days) AS sensor_cow_days,
       SUM(overlapping_cow_days) AS overlapping_cow_days,
       ROUND(100.0 * SUM(overlapping_cow_days)
             / NULLIF(SUM(yield_cow_days), 0), 1) AS pct_yield_cow_days_with_sensor,
       ROUND(100.0 * SUM(overlapping_cow_days)
             / NULLIF(SUM(sensor_cow_days), 0), 1) AS pct_sensor_cow_days_with_yield
FROM dates
GROUP BY 1
ORDER BY 1;

-- Q4. Available calving and reproductive history by year.
WITH years AS (
    SELECT EXTRACT(year FROM calving_date)::int AS year
    FROM core.lactation
    WHERE calving_date IS NOT NULL
    UNION
    SELECT EXTRACT(year FROM insemination_date)::int
    FROM core.insemination
    WHERE insemination_date IS NOT NULL
    UNION
    SELECT EXTRACT(year FROM birth_date)::int
    FROM core.calf
    WHERE birth_date IS NOT NULL
), l AS (
    SELECT EXTRACT(year FROM calving_date)::int AS year,
           COUNT(*) AS calvings,
           COUNT(DISTINCT animal_key) AS cows_calving,
           COUNT(*) FILTER (WHERE conception_date IS NOT NULL) AS conception_histories,
           COUNT(*) FILTER (WHERE dry_off_date IS NOT NULL) AS dry_off_histories,
           COUNT(*) FILTER (WHERE n_services IS NOT NULL) AS service_count_histories,
           COUNT(*) FILTER (WHERE COALESCE(aborted, false)) AS aborted_lactations
    FROM core.lactation
    WHERE calving_date IS NOT NULL
      AND NOT COALESCE(is_bad_date, false)
    GROUP BY 1
), i AS (
    SELECT EXTRACT(year FROM insemination_date)::int AS year,
           COUNT(*) AS inseminations,
           COUNT(DISTINCT animal_key) AS cows_inseminated,
           COUNT(DISTINCT insemination_date) AS days_with_inseminations
    FROM core.insemination
    WHERE insemination_date IS NOT NULL
      AND NOT COALESCE(is_bad_date, false)
    GROUP BY 1
), c AS (
    SELECT EXTRACT(year FROM birth_date)::int AS year,
           COUNT(*) AS calves_recorded,
           COUNT(DISTINCT birth_date) AS days_with_calf_records
    FROM core.calf
    WHERE birth_date IS NOT NULL
    GROUP BY 1
)
SELECT y.year,
       COALESCE(l.calvings, 0) AS calvings,
       COALESCE(l.cows_calving, 0) AS cows_calving,
       COALESCE(l.conception_histories, 0) AS conception_histories,
       COALESCE(l.dry_off_histories, 0) AS dry_off_histories,
       COALESCE(l.service_count_histories, 0) AS service_count_histories,
       COALESCE(l.aborted_lactations, 0) AS aborted_lactations,
       COALESCE(i.inseminations, 0) AS inseminations,
       COALESCE(i.cows_inseminated, 0) AS cows_inseminated,
       COALESCE(i.days_with_inseminations, 0) AS days_with_inseminations,
       COALESCE(c.calves_recorded, 0) AS calves_recorded,
       COALESCE(c.days_with_calf_records, 0) AS days_with_calf_records,
       ROUND(100.0 * l.conception_histories / NULLIF(l.calvings, 0), 1)
           AS pct_lactations_with_conception,
       ROUND(100.0 * l.dry_off_histories / NULLIF(l.calvings, 0), 1)
           AS pct_lactations_with_dry_off,
       ROUND(100.0 * l.service_count_histories / NULLIF(l.calvings, 0), 1)
           AS pct_lactations_with_service_count
FROM years y
LEFT JOIN l USING (year)
LEFT JOIN i USING (year)
LEFT JOIN c USING (year)
ORDER BY y.year;

-- Q5. Are milk-yield gaps farm-wide or partial?
-- Uses model_input2's reconstructed milking population. Monthly output only.
SELECT date_trunc('month', date)::date AS month,
       COUNT(*) FILTER (WHERE milking > 0) AS expected_milking_days,
       COUNT(*) FILTER (
           WHERE milking > 0 AND observed_milking_cows = 0
       ) AS farm_wide_yield_gap_days,
       COUNT(*) FILTER (
           WHERE observed_milking_cows > 0 AND lactating_unrecorded > 0
       ) AS partial_yield_gap_days,
       COUNT(*) FILTER (
           WHERE observed_milking_cows > 0 AND lactating_unrecorded = 0
       ) AS fully_observed_lactation_days,
       ROUND(AVG(milking), 1) AS avg_expected_milking_cows,
       ROUND(AVG(observed_milking_cows), 1) AS avg_observed_milking_cows,
       ROUND(AVG(lactating_unrecorded), 1) AS avg_lactating_unrecorded,
       ROUND(100.0 * SUM(observed_milking_cows)
             / NULLIF(SUM(milking), 0), 1) AS observed_vs_expected_pct,
       COUNT(*) FILTER (WHERE is_sparse_day) AS sparse_days,
       COUNT(*) FILTER (WHERE milk_record_type = 'none') AS no_usable_milk_days
FROM model_input2.day_panel
GROUP BY 1
ORDER BY 1;

-- Q6. During the sensor era, were missing sensor/yield matches farm-wide or partial?
-- A farm-wide sensor gap has usable cow yield that day but no valid sensor records.
-- A partial overlap day has both sources, but not every yield cow-day matches a sensor cow-day.
WITH sensor_era AS (
    SELECT MIN(milk_date) AS first_sensor_date
    FROM core.milk_session
    WHERE NOT COALESCE(is_bad_date, false)
      AND NOT COALESCE(is_placeholder, false)
), y AS (
    SELECT milk_date, animal_key
    FROM core.cow_day, sensor_era
    WHERE milk_date >= first_sensor_date
      AND yield_litres > 0
      AND NOT COALESCE(is_missing_yield, false)
      AND NOT COALESCE(is_placeholder, false)
    GROUP BY 1, 2
), s AS (
    SELECT milk_date, animal_key
    FROM core.milk_session
    WHERE NOT COALESCE(is_bad_date, false)
      AND NOT COALESCE(is_placeholder, false)
      AND NOT COALESCE(is_unlinked_animal, false)
    GROUP BY 1, 2
), yd AS (
    SELECT milk_date, COUNT(*) AS yield_cows FROM y GROUP BY 1
), sd AS (
    SELECT milk_date, COUNT(*) AS sensor_cows FROM s GROUP BY 1
), od AS (
    SELECT y.milk_date, COUNT(*) AS overlap_cows
    FROM y JOIN s USING (milk_date, animal_key)
    GROUP BY 1
), d AS (
    SELECT p.date,
           COALESCE(yd.yield_cows, 0) AS yield_cows,
           COALESCE(sd.sensor_cows, 0) AS sensor_cows,
           COALESCE(od.overlap_cows, 0) AS overlap_cows
    FROM model_input2.day_panel p
    CROSS JOIN sensor_era e
    LEFT JOIN yd ON yd.milk_date = p.date
    LEFT JOIN sd ON sd.milk_date = p.date
    LEFT JOIN od ON od.milk_date = p.date
    WHERE p.date >= e.first_sensor_date
)
SELECT date_trunc('month', date)::date AS month,
       COUNT(*) FILTER (WHERE yield_cows > 0) AS days_with_yield,
       COUNT(*) FILTER (WHERE sensor_cows > 0) AS days_with_sensors,
       COUNT(*) FILTER (
           WHERE yield_cows > 0 AND sensor_cows = 0
       ) AS farm_wide_sensor_gap_days,
       COUNT(*) FILTER (
           WHERE yield_cows > 0 AND sensor_cows > 0 AND overlap_cows < yield_cows
       ) AS partial_sensor_overlap_days,
       COUNT(*) FILTER (
           WHERE yield_cows > 0 AND overlap_cows = yield_cows
       ) AS full_sensor_overlap_days,
       SUM(yield_cows) AS yield_cow_days,
       SUM(sensor_cows) AS sensor_cow_days,
       SUM(overlap_cows) AS overlapping_cow_days,
       ROUND(100.0 * SUM(overlap_cows) / NULLIF(SUM(yield_cows), 0), 1)
           AS pct_yield_cow_days_with_sensor
FROM d
GROUP BY 1
ORDER BY 1;

-- Q7. Overall disease, treatment, and vaccination availability.
-- unique_names is a count only. The detailed aggregate name distribution is in Q8.
-- Vaccination schemas differ by publish version, so to_jsonb safely checks several
-- possible name fields without requiring every field to exist as a table column.
WITH events AS (
    SELECT 'disease'::text AS source_type,
           h.start_date AS event_date,
           COALESCE(NULLIF(BTRIM(h.diagnosis_name), ''),
                    NULLIF(BTRIM(h.diagnosis_group), ''),
                    NULLIF(BTRIM(h.health_group), ''),
                    'unspecified') AS event_name
    FROM core.health_episode h
    WHERE h.start_date IS NOT NULL

    UNION ALL

    SELECT 'treatment',
           th.treatment_start_date,
           COALESCE(NULLIF(BTRIM(th.treatment_name), ''), 'unspecified')
    FROM core.treatment_history th
    WHERE th.treatment_start_date IS NOT NULL
      AND NOT COALESCE(th.is_bad_date, false)
      AND NOT COALESCE(th.is_unlinked_animal, false)

    UNION ALL

    SELECT 'vaccination',
           v.event_date,
           COALESCE(NULLIF(BTRIM(to_jsonb(v)->>'vaccination_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccination_type'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'protocol_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'campaign_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'name'), ''),
                    'unspecified')
    FROM core.vaccination v
    WHERE v.event_date IS NOT NULL
      AND NOT COALESCE(v.is_bad_date, false)
)
SELECT source_type,
       COUNT(*) AS records,
       COUNT(DISTINCT event_name) AS unique_names,
       COUNT(DISTINCT event_date) AS days_with_records,
       MIN(event_date) AS first_record_date,
       MAX(event_date) AS last_record_date
FROM events
GROUP BY source_type
ORDER BY source_type;

-- Q8. Unique disease, treatment, and vaccination names with aggregate counts.
-- No animal identifier or event row is returned. Keep this result local if any label
-- contains a person, supplier, or other confidential free text.
WITH events AS (
    SELECT 'disease'::text AS source_type,
           h.start_date AS event_date,
           COALESCE(NULLIF(BTRIM(h.diagnosis_name), ''),
                    NULLIF(BTRIM(h.diagnosis_group), ''),
                    NULLIF(BTRIM(h.health_group), ''),
                    'unspecified') AS event_name
    FROM core.health_episode h
    WHERE h.start_date IS NOT NULL

    UNION ALL

    SELECT 'treatment',
           th.treatment_start_date,
           COALESCE(NULLIF(BTRIM(th.treatment_name), ''), 'unspecified')
    FROM core.treatment_history th
    WHERE th.treatment_start_date IS NOT NULL
      AND NOT COALESCE(th.is_bad_date, false)
      AND NOT COALESCE(th.is_unlinked_animal, false)

    UNION ALL

    SELECT 'vaccination',
           v.event_date,
           COALESCE(NULLIF(BTRIM(to_jsonb(v)->>'vaccination_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccination_type'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'protocol_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'campaign_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'name'), ''),
                    'unspecified')
    FROM core.vaccination v
    WHERE v.event_date IS NOT NULL
      AND NOT COALESCE(v.is_bad_date, false)
)
SELECT source_type,
       event_name,
       COUNT(*) AS records,
       COUNT(DISTINCT event_date) AS days_with_records,
       MIN(event_date) AS first_record_date,
       MAX(event_date) AS last_record_date
FROM events
GROUP BY source_type, event_name
ORDER BY source_type, records DESC, event_name;

-- Q9. Daily disease, treatment, and vaccination counts.
-- This is one aggregate row per date and source type, not one event row.
WITH events AS (
    SELECT 'disease'::text AS source_type,
           h.start_date AS event_date,
           COALESCE(NULLIF(BTRIM(h.diagnosis_name), ''),
                    NULLIF(BTRIM(h.diagnosis_group), ''),
                    NULLIF(BTRIM(h.health_group), ''),
                    'unspecified') AS event_name
    FROM core.health_episode h
    WHERE h.start_date IS NOT NULL

    UNION ALL

    SELECT 'treatment',
           th.treatment_start_date,
           COALESCE(NULLIF(BTRIM(th.treatment_name), ''), 'unspecified')
    FROM core.treatment_history th
    WHERE th.treatment_start_date IS NOT NULL
      AND NOT COALESCE(th.is_bad_date, false)
      AND NOT COALESCE(th.is_unlinked_animal, false)

    UNION ALL

    SELECT 'vaccination',
           v.event_date,
           COALESCE(NULLIF(BTRIM(to_jsonb(v)->>'vaccination_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccination_type'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'protocol_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'campaign_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'name'), ''),
                    'unspecified')
    FROM core.vaccination v
    WHERE v.event_date IS NOT NULL
      AND NOT COALESCE(v.is_bad_date, false)
)
SELECT event_date AS date,
       source_type,
       event_name,
       COUNT(*) AS records
FROM events
GROUP BY event_date, source_type, event_name
ORDER BY event_date, source_type, records DESC, event_name;

-- Q10. Sensor inventory and aggregate counts by named sensor/measurement.
-- number_of_sensor_fields is repeated for convenience and answers how many distinct
-- documented sensor fields are included. triggered_or_event_count means:
--   boolean fields: number of true flags;
--   kick-offs/reattaches: sum of the recorded event counts;
--   yield measurements: number of non-null measurements.
WITH session_sensor AS (
    SELECT ms.milk_date,
           ms.animal_key,
           NOT COALESCE(ms.is_unlinked_animal, false) AS linked,
           x.sensor_name,
           x.has_value,
           x.occurrences
    FROM core.milk_session ms
    CROSS JOIN LATERAL (VALUES
        ('blood_alarm',
         ms.blood_alarm IS NOT NULL,
         CASE WHEN COALESCE(ms.blood_alarm, false) THEN 1::numeric ELSE 0 END),
        ('conductivity_alarm',
         ms.conductivity_alarm IS NOT NULL,
         CASE WHEN COALESCE(ms.conductivity_alarm, false) THEN 1::numeric ELSE 0 END),
        ('kick_offs',
         ms.kick_offs IS NOT NULL,
         COALESCE(ms.kick_offs, 0)::numeric),
        ('reattaches',
         ms.no_of_reattaches IS NOT NULL,
         COALESCE(ms.no_of_reattaches, 0)::numeric),
        ('manual_detach',
         ms.manual_detach IS NOT NULL,
         CASE WHEN COALESCE(ms.manual_detach, false) THEN 1::numeric ELSE 0 END),
        ('low_yield_flag',
         ms.low_yield IS NOT NULL,
         CASE WHEN COALESCE(ms.low_yield, false) THEN 1::numeric ELSE 0 END),
        ('recorded_session_yield',
         ms.yield_litres IS NOT NULL,
         CASE WHEN ms.yield_litres IS NOT NULL THEN 1::numeric ELSE 0 END),
        ('expected_session_yield',
         ms.expected_litres IS NOT NULL,
         CASE WHEN ms.expected_litres IS NOT NULL THEN 1::numeric ELSE 0 END)
    ) AS x(sensor_name, has_value, occurrences)
    WHERE NOT COALESCE(ms.is_bad_date, false)
      AND NOT COALESCE(ms.is_placeholder, false)
)
SELECT sensor_name,
       COUNT(*) OVER () AS number_of_sensor_fields,
       COUNT(*) FILTER (WHERE has_value) AS session_records_with_value,
       COUNT(DISTINCT milk_date) FILTER (WHERE has_value) AS days_with_value,
       COUNT(DISTINCT animal_key) FILTER (
           WHERE has_value AND linked
       ) AS linked_cows_with_value,
       SUM(occurrences) FILTER (WHERE has_value) AS triggered_or_event_count,
       MIN(milk_date) FILTER (WHERE has_value) AS first_date,
       MAX(milk_date) FILTER (WHERE has_value) AS last_date
FROM session_sensor
GROUP BY sensor_name
ORDER BY sensor_name;

-- Q11. Daily counts for each named sensor/measurement.
-- This returns date x sensor aggregates only; no animal identifier is selected.
WITH session_sensor AS (
    SELECT ms.milk_date,
           ms.animal_key,
           NOT COALESCE(ms.is_unlinked_animal, false) AS linked,
           x.sensor_name,
           x.has_value,
           x.occurrences
    FROM core.milk_session ms
    CROSS JOIN LATERAL (VALUES
        ('blood_alarm',
         ms.blood_alarm IS NOT NULL,
         CASE WHEN COALESCE(ms.blood_alarm, false) THEN 1::numeric ELSE 0 END),
        ('conductivity_alarm',
         ms.conductivity_alarm IS NOT NULL,
         CASE WHEN COALESCE(ms.conductivity_alarm, false) THEN 1::numeric ELSE 0 END),
        ('kick_offs',
         ms.kick_offs IS NOT NULL,
         COALESCE(ms.kick_offs, 0)::numeric),
        ('reattaches',
         ms.no_of_reattaches IS NOT NULL,
         COALESCE(ms.no_of_reattaches, 0)::numeric),
        ('manual_detach',
         ms.manual_detach IS NOT NULL,
         CASE WHEN COALESCE(ms.manual_detach, false) THEN 1::numeric ELSE 0 END),
        ('low_yield_flag',
         ms.low_yield IS NOT NULL,
         CASE WHEN COALESCE(ms.low_yield, false) THEN 1::numeric ELSE 0 END),
        ('recorded_session_yield',
         ms.yield_litres IS NOT NULL,
         CASE WHEN ms.yield_litres IS NOT NULL THEN 1::numeric ELSE 0 END),
        ('expected_session_yield',
         ms.expected_litres IS NOT NULL,
         CASE WHEN ms.expected_litres IS NOT NULL THEN 1::numeric ELSE 0 END)
    ) AS x(sensor_name, has_value, occurrences)
    WHERE NOT COALESCE(ms.is_bad_date, false)
      AND NOT COALESCE(ms.is_placeholder, false)
)
SELECT milk_date AS date,
       sensor_name,
       COUNT(*) FILTER (WHERE has_value) AS session_records_with_value,
       COUNT(DISTINCT animal_key) FILTER (
           WHERE has_value AND linked
       ) AS linked_cows_with_value,
       SUM(occurrences) FILTER (WHERE has_value) AS triggered_or_event_count
FROM session_sensor
GROUP BY milk_date, sensor_name
HAVING COUNT(*) FILTER (WHERE has_value) > 0
ORDER BY milk_date, sensor_name;

-- Q12. Disease, treatment, and vaccination types by year.
-- One aggregate row per year x source x type. No animal or event identifier is returned.
-- Keep exact free-text labels local if they contain confidential names.
WITH events AS (
    SELECT EXTRACT(year FROM h.start_date)::int AS year,
           'disease'::text AS source_type,
           COALESCE(NULLIF(BTRIM(h.diagnosis_name), ''),
                    NULLIF(BTRIM(h.diagnosis_group), ''),
                    NULLIF(BTRIM(h.health_group), ''),
                    'unspecified') AS event_name,
           h.start_date AS event_date
    FROM core.health_episode h
    WHERE h.start_date IS NOT NULL

    UNION ALL

    SELECT EXTRACT(year FROM th.treatment_start_date)::int,
           'treatment',
           COALESCE(NULLIF(BTRIM(th.treatment_name), ''), 'unspecified'),
           th.treatment_start_date
    FROM core.treatment_history th
    WHERE th.treatment_start_date IS NOT NULL
      AND NOT COALESCE(th.is_bad_date, false)
      AND NOT COALESCE(th.is_unlinked_animal, false)

    UNION ALL

    SELECT EXTRACT(year FROM v.event_date)::int,
           'vaccination',
           COALESCE(NULLIF(BTRIM(to_jsonb(v)->>'vaccination_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccination_type'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'vaccine'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'protocol_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'campaign_name'), ''),
                    NULLIF(BTRIM(to_jsonb(v)->>'name'), ''),
                    'unspecified'),
           v.event_date
    FROM core.vaccination v
    WHERE v.event_date IS NOT NULL
      AND NOT COALESCE(v.is_bad_date, false)
)
SELECT year,
       source_type,
       event_name,
       COUNT(*) AS records,
       COUNT(DISTINCT event_date) AS days_with_records
FROM events
GROUP BY year, source_type, event_name
ORDER BY year, source_type, records DESC, event_name;

-- Q13. Each sensor/measurement type by year.
-- Boolean sensors count true flags; kick-offs and reattaches sum recorded events;
-- yield measurements count non-null measurements.
WITH session_sensor AS (
    SELECT EXTRACT(year FROM ms.milk_date)::int AS year,
           ms.milk_date,
           ms.animal_key,
           NOT COALESCE(ms.is_unlinked_animal, false) AS linked,
           x.sensor_name,
           x.has_value,
           x.occurrences
    FROM core.milk_session ms
    CROSS JOIN LATERAL (VALUES
        ('blood_alarm',
         ms.blood_alarm IS NOT NULL,
         CASE WHEN COALESCE(ms.blood_alarm, false) THEN 1::numeric ELSE 0 END),
        ('conductivity_alarm',
         ms.conductivity_alarm IS NOT NULL,
         CASE WHEN COALESCE(ms.conductivity_alarm, false) THEN 1::numeric ELSE 0 END),
        ('kick_offs',
         ms.kick_offs IS NOT NULL,
         COALESCE(ms.kick_offs, 0)::numeric),
        ('reattaches',
         ms.no_of_reattaches IS NOT NULL,
         COALESCE(ms.no_of_reattaches, 0)::numeric),
        ('manual_detach',
         ms.manual_detach IS NOT NULL,
         CASE WHEN COALESCE(ms.manual_detach, false) THEN 1::numeric ELSE 0 END),
        ('low_yield_flag',
         ms.low_yield IS NOT NULL,
         CASE WHEN COALESCE(ms.low_yield, false) THEN 1::numeric ELSE 0 END),
        ('recorded_session_yield',
         ms.yield_litres IS NOT NULL,
         CASE WHEN ms.yield_litres IS NOT NULL THEN 1::numeric ELSE 0 END),
        ('expected_session_yield',
         ms.expected_litres IS NOT NULL,
         CASE WHEN ms.expected_litres IS NOT NULL THEN 1::numeric ELSE 0 END)
    ) AS x(sensor_name, has_value, occurrences)
    WHERE NOT COALESCE(ms.is_bad_date, false)
      AND NOT COALESCE(ms.is_placeholder, false)
)
SELECT year,
       sensor_name,
       COUNT(*) FILTER (WHERE has_value) AS session_records_with_value,
       COUNT(DISTINCT milk_date) FILTER (WHERE has_value) AS days_with_value,
       COUNT(DISTINCT animal_key) FILTER (
           WHERE has_value AND linked
       ) AS linked_cows_with_value,
       SUM(occurrences) FILTER (WHERE has_value) AS triggered_or_event_count
FROM session_sensor
GROUP BY year, sensor_name
ORDER BY year, sensor_name;

-- Q14. THI and weather-record availability by year.
-- This distinguishes the calendar range from genuinely complete daily weather records.
SELECT EXTRACT(year FROM date)::int AS year,
       COUNT(*) AS weather_rows,
       COUNT(DISTINCT date) AS calendar_days_with_weather_row,
       COUNT(*) FILTER (WHERE COALESCE(is_complete, false)) AS complete_weather_days,
       COUNT(thi_mean) AS days_with_thi_mean,
       COUNT(thi_max) AS days_with_thi_max,
       COUNT(hours_thi_above) AS days_with_thi_hours,
       ROUND(100.0 * COUNT(thi_mean) / NULLIF(COUNT(*), 0), 1)
           AS pct_rows_with_thi_mean,
       ROUND(100.0 * COUNT(thi_max) / NULLIF(COUNT(*), 0), 1)
           AS pct_rows_with_thi_max,
       MIN(date) AS first_date_in_year,
       MAX(date) AS last_date_in_year
FROM core.weather_day
GROUP BY EXTRACT(year FROM date)::int
ORDER BY year;

ROLLBACK;
