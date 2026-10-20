-- Retest after the ETL changes E1-E7 (docs/etl_prompt.md). Run on farmx_app.
-- Aggregates and schema metadata only. Names match what the ETL published (2026-10-19):
-- E1 as asked; E3 as cells_milking / milk_hand_milked_est / inferred_exits; E5 as
-- is_suspect_high / target_litres_per_cow.

-- R0: do the new tables and columns exist?
SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE (table_schema = 'model_input' AND table_name = 'day_cell_known')
   OR (table_schema = 'core' AND column_name IN (
        'conception_confirmed_date', 'conception_known_date', 'conception_known_source',
        'is_inferred', 'inferred_reason', 'is_implausible_volume', 'entered_ts'))
   OR (table_schema = 'model_input' AND column_name = 'is_implausible_volume')
ORDER BY 1, 2, 3;

-- R1 (E1): day_cell_known has the same animals per day as day_cell, and fewer or equal
-- pregnant animals. Expect days_total_differs = 0 and days_more_pregnant = 0.
WITH a AS (
    SELECT date, SUM(n_animals) AS n,
           SUM(n_animals) FILTER (WHERE state IN ('heifer_pregnant', 'dry_pregnant')) AS preg
    FROM model_input.day_cell GROUP BY 1
), k AS (
    SELECT date, SUM(n_animals) AS n,
           SUM(n_animals) FILTER (WHERE state IN ('heifer_pregnant', 'dry_pregnant')) AS preg
    FROM model_input.day_cell_known GROUP BY 1
)
SELECT EXTRACT(year FROM a.date)::int                          AS year,
       COUNT(*)                                                AS days,
       COUNT(*) FILTER (WHERE a.n <> k.n)                      AS days_total_differs,
       COUNT(*) FILTER (WHERE k.preg > a.preg)                 AS days_more_pregnant,
       ROUND(AVG(a.preg))                                      AS mean_pregnant_daycell,
       ROUND(AVG(k.preg))                                      AS mean_pregnant_known,
       ROUND(AVG(k.preg::numeric / NULLIF(a.preg, 0)), 3)      AS mean_ratio_known_to_daycell
FROM a JOIN k USING (date)
GROUP BY 1 ORDER BY 1;

-- R1b (E1): lag service -> known date, and how conceptions became known, by year.
SELECT EXTRACT(year FROM conception_date)::int                                   AS year,
       conception_known_source                                                   AS source,
       COUNT(*)                                                                  AS n,
       percentile_cont(0.10) WITHIN GROUP (ORDER BY conception_known_date - conception_date) AS lag_p10,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY conception_known_date - conception_date) AS lag_median,
       percentile_cont(0.90) WITHIN GROUP (ORDER BY conception_known_date - conception_date) AS lag_p90
FROM core.lactation
WHERE conception_date IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2;

-- R1c (E1): leakage check L2 again, against day_cell_known. Expect a_known close to
-- c_confirmable (not to b) on every day.
WITH days AS (
    SELECT d::date AS d
    FROM generate_series(DATE '2018-01-01', DATE '2023-07-01', interval '6 months') AS g(d)
),
first_calving AS (
    SELECT animal_key, MIN(calving_date) AS first_calving
    FROM core.lactation WHERE COALESCE(is_bad_date, false) = false GROUP BY 1
),
heifers AS (
    SELECT days.d, fc.first_calving,
           (SELECT MAX(i.insemination_date) FROM core.insemination i
            WHERE i.animal_key = a.animal_key AND i.insemination_date <= days.d
              AND COALESCE(i.is_bad_date, false) = false) AS last_ai
    FROM days
    JOIN core.animal a
      ON a.sex = 'female' AND a.birth_date <= days.d - 365
     AND COALESCE(a.exit_date, 'infinity'::date) > days.d
     AND COALESCE(a.is_placeholder, false) = false
    LEFT JOIN first_calving fc ON fc.animal_key = a.animal_key
    WHERE fc.first_calving IS NULL OR fc.first_calving > days.d
)
SELECT h.d AS day,
       (SELECT SUM(n_animals) FROM model_input.day_cell dc
        WHERE dc.date = h.d AND dc.state = 'heifer_pregnant')                  AS a_daycell,
       (SELECT SUM(n_animals) FROM model_input.day_cell_known dk
        WHERE dk.date = h.d AND dk.state = 'heifer_pregnant')                  AS a_known,
       COUNT(*) FILTER (WHERE h.first_calving <= h.d + 300)                    AS b_calve_within_300d,
       COUNT(*) FILTER (WHERE h.first_calving <= h.d + 300 AND h.last_ai <= h.d - 35) AS c_confirmable
FROM heifers h GROUP BY h.d ORDER BY h.d;

-- R2 (E2): conceptions with an impossible gestation that are still not flagged. Expect 0.
WITH lac AS (
    SELECT conception_date, is_bad_date,
           LEAD(calving_date) OVER (PARTITION BY animal_key ORDER BY calving_date) AS next_calving
    FROM core.lactation
)
SELECT COUNT(*) FILTER (WHERE (next_calving - conception_date) NOT BETWEEN 240 AND 310)    AS out_of_range,
       COUNT(*) FILTER (WHERE (next_calving - conception_date) NOT BETWEEN 240 AND 310
                          AND NOT COALESCE(is_bad_date, false))                           AS out_of_range_unflagged
FROM lac
WHERE conception_date IS NOT NULL AND next_calving IS NOT NULL;

-- R3 (E3): the ETL did not add inferred lactations (no is_inferred column); it added
-- day_panel.cells_milking / cells_herd, milk_hand_milked_est and inferred_exits. Re-run
-- episode_checks.sql query 5 (cows giving milk without an open lactation), then this:
-- recorded milking (day_panel.milking and cells_milking) vs cows giving identified milk,
-- from 2026-04. Expect ratio within 5 % of 1 when the identified share is >= 0.8.
WITH giving AS (
    SELECT milk_date, COUNT(DISTINCT animal_key) AS cows
    FROM core.cow_day
    WHERE milk_date >= DATE '2026-04-01' AND yield_litres > 0
      AND NOT COALESCE(is_placeholder, false)
    GROUP BY 1
)
SELECT date_trunc('month', p.date)::date                              AS month,
       ROUND(AVG(p.milking))                                          AS milking_recorded,
       ROUND(AVG(p.cells_milking))                                    AS cells_milking,
       ROUND(AVG(g.cows))                                             AS cows_giving_milk,
       ROUND(AVG(p.identified_share)::numeric, 3)                     AS identified_share,
       ROUND((AVG(p.milking) / NULLIF(AVG(g.cows), 0))::numeric, 3)   AS ratio_milking_to_giving
FROM model_input.day_panel p JOIN giving g ON g.milk_date = p.date
GROUP BY 1 ORDER BY 1;

-- R4 (E4): exits by type and month, 2023 onward (counts only).
SELECT date_trunc('month', exit_date)::date AS month, LOWER(COALESCE(exit_type, 'unknown')) AS exit_type,
       COUNT(*) AS n
FROM core.animal
WHERE exit_date >= DATE '2023-01-01' AND NOT COALESCE(is_placeholder, false)
GROUP BY 1, 2 ORDER BY 1, 2;

-- R5 (E5): milk volume per recorded milking cow-day, the new is_suspect_high flag,
-- hand-milked estimate and inferred exits, Sep 2025 onward. Expect no scoreable month
-- above 20 L per recorded milking cow-day.
SELECT date_trunc('month', date)::date                                       AS month,
       ROUND(SUM(target_litres))                                             AS target_litres,
       ROUND((SUM(target_litres) / NULLIF(SUM(milking), 0))::numeric, 2)     AS litres_per_milking_cow_day,
       ROUND(AVG(target_litres_per_cow)::numeric, 2)                         AS mean_target_litres_per_cow,
       ROUND(SUM(milk_hand_milked_est))                                      AS hand_milked_est_litres,
       COUNT(*) FILTER (WHERE is_suspect_high)                               AS suspect_high_days,
       COUNT(*) FILTER (WHERE is_scoreable)                                  AS scoreable_days,
       SUM(inferred_exits)                                                   AS inferred_exits,
       SUM(sales)                                                            AS sales,
       ROUND(AVG(identified_share)::numeric, 3)                              AS identified_share
FROM model_input.day_panel
WHERE date >= DATE '2025-09-01'
GROUP BY 1 ORDER BY 1;

-- R6: then re-run episode_checks.sql queries 1, 3, 4 and 5 and leakage_checks.sql L1
-- to see the before/after on the same aggregates.

-- ===================== follow-up after the first retest (2026-10-19) =====================

-- R3b (E3): inferred lactations by month and reason, and whether day_cell counts them.
SELECT date_trunc('month', calving_date)::date AS month, inferred_reason, COUNT(*) AS inferred_lactations
FROM core.lactation
WHERE is_inferred
GROUP BY 1, 2 ORDER BY 1, 2;

-- R5b (E5): implausible-volume days and whether they are still scoreable, by month.
SELECT date_trunc('month', date)::date                                     AS month,
       COUNT(*) FILTER (WHERE is_implausible_volume)                       AS implausible_days,
       COUNT(*) FILTER (WHERE is_implausible_volume AND is_scoreable)      AS implausible_and_scoreable,
       COUNT(*) FILTER (WHERE is_suspect_high)                             AS suspect_high_days
FROM model_input.day_panel
WHERE date >= DATE '2024-01-01'
GROUP BY 1 ORDER BY 1;

-- R7 (E7): how late are events entered? Per table and year: events, median days from
-- event to entry, and shares entered more than 7 / 30 / 90 days late. Counts only.
WITH ev AS (
    SELECT 'calving_record' AS tbl, event_ts, entered_ts FROM core.calving_record
    UNION ALL SELECT 'dry_off', event_ts, entered_ts FROM core.dry_off
    UNION ALL SELECT 'exit', event_ts, entered_ts FROM core.exit
    UNION ALL SELECT 'abortion', event_ts, entered_ts FROM core.abortion
    UNION ALL SELECT 'preg_check', event_ts, entered_ts FROM core.preg_check
    UNION ALL SELECT 'entry', event_ts, entered_ts FROM core.entry
)
SELECT tbl, EXTRACT(year FROM event_ts)::int AS year, COUNT(*) AS events,
       COUNT(*) FILTER (WHERE entered_ts IS NULL) AS no_entry_time,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM entered_ts - event_ts) / 86400) AS median_lag_days,
       ROUND(AVG(CASE WHEN entered_ts - event_ts > interval '7 days' THEN 1.0 ELSE 0.0 END), 3)  AS share_gt_7d,
       ROUND(AVG(CASE WHEN entered_ts - event_ts > interval '30 days' THEN 1.0 ELSE 0.0 END), 3) AS share_gt_30d,
       ROUND(AVG(CASE WHEN entered_ts - event_ts > interval '90 days' THEN 1.0 ELSE 0.0 END), 3) AS share_gt_90d
FROM ev
WHERE event_ts IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2;
