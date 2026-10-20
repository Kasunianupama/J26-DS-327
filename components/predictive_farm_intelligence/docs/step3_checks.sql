-- Step 3 checks (PFOI herd engine). Aggregates only: counts, sums, ratios.
-- Run in farmx_app with your read-only role and send back the numbers.

-- 1. day_cell coverage and average herd size
SELECT MIN(date) AS first_day, MAX(date) AS last_day, COUNT(*) AS n_days,
       ROUND(AVG(herd), 1) AS avg_herd
FROM (SELECT date, SUM(n_animals) AS herd FROM model_input.day_cell GROUP BY date) t;

-- 2. Vocabulary of state_transition_month (do exits/entries appear, and how are they named?)
SELECT from_state, to_state, COUNT(*) AS n_months, SUM(n_moved) AS total_moved
FROM core.state_transition_month
GROUP BY 1, 2 ORDER BY 1, 2;

-- 3. Milking-days rebuilt from core.lactation vs day_cell, by year (ratio near 1 = consistent)
WITH yrs AS (SELECT generate_series(2016, 2023) AS y),
lac AS (
    SELECT l.calving_date,
           LEAST(COALESCE(l.dry_off_date, 'infinity'::date),
                 COALESCE(l.end_date, 'infinity'::date),
                 COALESCE(a.exit_date, 'infinity'::date)) AS milk_end
    FROM core.lactation l LEFT JOIN core.animal a ON a.animal_key = l.animal_key
    WHERE COALESCE(l.is_bad_date, false) = false
),
recon AS (
    SELECT y, SUM(GREATEST(0, LEAST(milk_end, make_date(y + 1, 1, 1))
                              - GREATEST(calving_date, make_date(y, 1, 1)))) AS lactation_days
    FROM yrs CROSS JOIN lac GROUP BY y
),
cell AS (
    SELECT EXTRACT(year FROM date)::int AS y, SUM(n_animals) AS day_cell_days
    FROM model_input.day_cell WHERE state = 'milking' GROUP BY 1
)
SELECT r.y, r.lactation_days, c.day_cell_days,
       ROUND(r.lactation_days::numeric / NULLIF(c.day_cell_days, 0), 3) AS ratio
FROM recon r JOIN cell c USING (y) ORDER BY r.y;

-- 4. Is lactation.conception_date a recorded insemination date or back-calculated?
SELECT COUNT(*) AS lactations_with_conception,
       ROUND(100.0 * AVG(CASE WHEN EXISTS (
                SELECT 1 FROM core.insemination i
                WHERE i.animal_key = l.animal_key
                  AND i.insemination_date = l.conception_date) THEN 1 ELSE 0 END), 1)
           AS pct_on_an_ai_date,
       ROUND(100.0 * AVG(CASE WHEN l.aborted THEN 1 ELSE 0 END), 1) AS pct_aborted
FROM core.lactation l
WHERE l.conception_date IS NOT NULL;

-- 5. Exit types in core.animal for animals under one year (calf sex split uses these)
SELECT sex, exit_type, COUNT(*) AS exits
FROM core.animal
WHERE exit_date IS NOT NULL AND exit_date < birth_date + 365
GROUP BY 1, 2 ORDER BY 1, 2;

-- 6. Does conception_date mark the conceiving service? Compare (next calving - conception)
--    with the calf's recorded gestation. Similar distributions = consistent clocks.
WITH nxt AS (
    SELECT l.conception_date,
           LEAD(l.calving_date) OVER (PARTITION BY l.animal_key ORDER BY l.calving_date) AS next_calving
    FROM core.lactation l
    WHERE COALESCE(l.is_bad_date, false) = false
),
d AS (
    SELECT 'lactation: next calving - conception' AS measure, (next_calving - conception_date) AS days
    FROM nxt WHERE conception_date IS NOT NULL AND next_calving IS NOT NULL
    UNION ALL
    SELECT 'calf: gestation_d', gestation_d FROM core.calf WHERE gestation_d IS NOT NULL
)
SELECT measure, COUNT(*) AS n, ROUND(AVG(days), 1) AS mean_days,
       percentile_cont(0.1) WITHIN GROUP (ORDER BY days) AS p10,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY days) AS p50,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY days) AS p90,
       ROUND(100.0 * AVG(CASE WHEN days > 300 THEN 1 ELSE 0 END), 1) AS pct_over_300
FROM d GROUP BY measure;
