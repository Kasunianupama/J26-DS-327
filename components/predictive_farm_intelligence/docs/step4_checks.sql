-- Step 4 checks (PFOI milk model). Aggregates only.

-- 1. Milk target by year and source: days, scoreable days, mean litres per scoreable day
SELECT EXTRACT(year FROM date)::int AS year, target_source,
       COUNT(*) AS days, SUM(CASE WHEN is_scoreable THEN 1 ELSE 0 END) AS scoreable_days,
       ROUND(AVG(CASE WHEN is_scoreable THEN target_litres END)::numeric, 1) AS mean_litres_per_day
FROM model_input.day_panel
GROUP BY 1, 2 ORDER BY 1, 2;

-- 2. Reliable cow-days: mean yield by parity and DIM band (shape sanity check)
SELECT CASE WHEN lactation_no = 1 THEN '1' WHEN lactation_no = 2 THEN '2' ELSE '3+' END AS parity,
       CASE WHEN dim <= 60 THEN '0-60' WHEN dim <= 150 THEN '61-150'
            WHEN dim <= 305 THEN '151-305' ELSE '305+' END AS dim_band,
       COUNT(*) AS cow_days, ROUND(AVG(yield_litres)::numeric, 2) AS mean_litres
FROM core.cow_day
WHERE is_reliable AND NOT COALESCE(is_spike, false) AND NOT COALESCE(is_missing_yield, false)
  AND yield_litres > 0 AND lactation_no >= 1
GROUP BY 1, 2 ORDER BY 1, 2;

-- 3. How often days_pregnant is filled on reliable cow-days (pregnancy factor input)
SELECT ROUND(100.0 * AVG(CASE WHEN days_pregnant IS NOT NULL AND days_pregnant >= 0 THEN 1 ELSE 0 END), 1)
           AS pct_with_days_pregnant,
       COUNT(*) AS reliable_cow_days
FROM core.cow_day WHERE is_reliable;
