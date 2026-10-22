-- Milk and herd reconciliation: core.animal_daily vs core.daily_milk vs shipments vs
-- model_input vs c1_output. Run on farmx_app. Aggregates only (one row per month or year).
-- Rebuild script: docs/sql/model_input2_from_core.sql.

-- M1: one row per month, every milk source side by side.
--   ad_*   core.animal_daily (DelPro AnimalDaily), is_yield_valid = TRUE, split cows / placeholder
--   dm_*   core.daily_milk (DelPro HistoryAnimalDailyData), the source model_input uses
--   dp_*   model_input.day_panel (shipments, DelPro total, the C1 target, herd stocks)
WITH ad AS (
    SELECT date_trunc('month', d.milk_date)::date AS month,
           SUM(d.yield_litres) FILTER (WHERE NOT coalesce(a.is_placeholder, false))   AS ad_cow_litres,
           COUNT(*)            FILTER (WHERE NOT coalesce(a.is_placeholder, false))   AS ad_cow_records,
           SUM(d.yield_litres) FILTER (WHERE a.is_placeholder)                         AS ad_placeholder_litres,
           COUNT(*)            FILTER (WHERE a.is_placeholder)                         AS ad_placeholder_records,
           COUNT(*)            FILTER (WHERE d.animal_key IS NULL)                     AS ad_unlinked_records,
           MAX(d.yield_litres)                                                         AS ad_max_record_litres
    FROM core.animal_daily d
    LEFT JOIN core.animal a ON a.animal_key = d.animal_key
    WHERE d.is_yield_valid AND d.milk_date >= DATE '2015-08-01' AND NOT d.is_bad_date
    GROUP BY 1
), dm AS (
    SELECT date_trunc('month', milk_date)::date AS month,
           SUM(yield_litres) FILTER (WHERE NOT is_placeholder) AS dm_cow_litres,
           COUNT(*)          FILTER (WHERE NOT is_placeholder AND yield_litres > 0) AS dm_cow_records,
           SUM(yield_litres) FILTER (WHERE is_placeholder)     AS dm_placeholder_litres
    FROM core.daily_milk
    WHERE milk_date >= DATE '2015-08-01' AND NOT is_bad_date
    GROUP BY 1
), dp AS (
    SELECT month,
           SUM(milk_shipped)      AS dp_shipped,
           SUM(milk_delpro_total) AS dp_delpro_total,
           SUM(target_litres)     AS dp_target_litres,
           MIN(target_source)     AS dp_source_min,
           MAX(target_source)     AS dp_source_max,
           ROUND(AVG(milking))    AS dp_avg_milking,
           ROUND(AVG(n_herd))     AS dp_avg_herd,
           ROUND(AVG(cows_with_identified_milk)) AS dp_avg_cows_identified
    FROM model_input.day_panel
    GROUP BY 1
)
SELECT to_char(dp.month, 'YYYY-MM') AS month,
       ROUND(ad.ad_cow_litres::numeric)         AS ad_cow_litres,
       ad.ad_cow_records,
       ROUND(ad.ad_placeholder_litres::numeric) AS ad_placeholder_litres,
       ad.ad_placeholder_records,
       ad.ad_unlinked_records,
       ROUND(ad.ad_max_record_litres::numeric)  AS ad_max_record_litres,
       ROUND(dm.dm_cow_litres::numeric)         AS dm_cow_litres,
       dm.dm_cow_records,
       ROUND(dm.dm_placeholder_litres::numeric) AS dm_placeholder_litres,
       ROUND(dp.dp_shipped::numeric)            AS dp_shipped,
       ROUND(dp.dp_delpro_total::numeric)       AS dp_delpro_total,
       ROUND(dp.dp_target_litres::numeric)      AS dp_target_litres,
       dp.dp_source_min, dp.dp_source_max,
       dp.dp_avg_milking, dp.dp_avg_herd, dp.dp_avg_cows_identified
FROM dp
LEFT JOIN ad ON ad.month = dp.month
LEFT JOIN dm ON dm.month = dp.month
ORDER BY dp.month;

-- M2: is AnimalDaily only the cow-days DelPro kept because an event points at them?
-- Share of valid animal_daily records that an event, a milk session or a body measure links to.
-- A share near 100% before 2020 means AnimalDaily is an event sample, not a full milk record.
WITH linked AS (
    SELECT animal_daily_key AS k FROM core.event        WHERE animal_daily_key IS NOT NULL
    UNION SELECT animal_daily_key FROM core.milk_session WHERE animal_daily_key IS NOT NULL
    UNION SELECT animal_daily_key FROM core.body_measure WHERE animal_daily_key IS NOT NULL
)
SELECT EXTRACT(year FROM d.milk_date)::int                        AS year,
       COUNT(*)                                                    AS valid_records,
       COUNT(*) FILTER (WHERE l.k IS NOT NULL)                     AS linked_records,
       ROUND(100.0 * COUNT(*) FILTER (WHERE l.k IS NOT NULL) / COUNT(*), 1) AS pct_linked
FROM core.animal_daily d
LEFT JOIN linked l ON l.k = d.record_key
WHERE d.is_yield_valid AND NOT d.is_bad_date
GROUP BY 1 ORDER BY 1;

-- M3: duplicates. Animal-days with more than one record, per source and year.
-- Expect 0 for core.daily_milk cows (the ETL sums them in core.cow_day).
SELECT 'animal_daily_valid' AS source, EXTRACT(year FROM milk_date)::int AS year,
       COUNT(*) AS animal_days, COUNT(*) FILTER (WHERE n > 1) AS animal_days_with_duplicates
FROM (SELECT animal_key, milk_date, COUNT(*) AS n FROM core.animal_daily
      WHERE is_yield_valid AND NOT is_bad_date GROUP BY 1, 2) x GROUP BY 1, 2
UNION ALL
SELECT 'daily_milk_cows', EXTRACT(year FROM milk_date)::int,
       COUNT(*), COUNT(*) FILTER (WHERE n > 1)
FROM (SELECT animal_key, milk_date, COUNT(*) AS n FROM core.daily_milk
      WHERE NOT is_placeholder AND NOT is_bad_date GROUP BY 1, 2) x GROUP BY 1, 2
ORDER BY 1, 2;

-- M4: distinct animals with milk, whole history (2015-10 onward), per source.
-- Also animals that ever calved (core.lactation), i.e. could ever have been milking.
SELECT 'animal_daily_valid_cows' AS what, COUNT(DISTINCT d.animal_key) AS n
FROM core.animal_daily d LEFT JOIN core.animal a ON a.animal_key = d.animal_key
WHERE d.is_yield_valid AND d.milk_date >= DATE '2015-10-01' AND NOT coalesce(a.is_placeholder, false)
UNION ALL
SELECT 'animal_daily_valid_placeholder', COUNT(DISTINCT d.animal_key)
FROM core.animal_daily d JOIN core.animal a ON a.animal_key = d.animal_key
WHERE d.is_yield_valid AND d.milk_date >= DATE '2015-10-01' AND a.is_placeholder
UNION ALL
SELECT 'daily_milk_cows', COUNT(DISTINCT animal_key)
FROM core.daily_milk WHERE NOT is_placeholder AND yield_litres > 0 AND milk_date >= DATE '2015-10-01'
UNION ALL
SELECT 'animals_with_a_calving', COUNT(DISTINCT animal_key)
FROM core.lactation WHERE NOT is_bad_date
UNION ALL
SELECT 'animals_in_core', COUNT(*) FROM core.animal WHERE NOT is_placeholder;

-- M5: is the milking-cow count inflated (e.g. missed dry-offs)? Only testable where DelPro
-- identified most milk: 2020-08..2021-01 and 2026-06..2026-08. Compare the milking state
-- with cows that actually had identified milk that day (day_panel.cows_with_identified_milk).
-- ratio near identified_share (or above) = milking count fine; far below = inflated milking state
-- or hand-milked cows outside the parlour.
SELECT to_char(month, 'YYYY-MM') AS month,
       ROUND(AVG(milking))                               AS avg_milking_state,
       ROUND(AVG(milking_with_inferred))                 AS avg_milking_with_inferred,
       ROUND(AVG(cows_with_identified_milk))             AS avg_cows_with_identified_milk,
       ROUND(AVG(cows_with_identified_milk)::numeric / NULLIF(AVG(milking), 0), 3) AS ratio,
       ROUND(AVG(identified_share)::numeric, 3)          AS avg_identified_share,
       ROUND(AVG(dry_open + dry_pregnant))               AS avg_dry,
       ROUND(AVG(unknown_state))                         AS avg_unknown_state
FROM model_input.day_panel
WHERE month BETWEEN DATE '2020-08-01' AND DATE '2021-06-01'
   OR month >= DATE '2026-03-01'
GROUP BY month ORDER BY month;

-- M6: internal consistency of model_input. Expect every *_differs column = 0.
WITH c AS (SELECT date, SUM(n_animals) AS n, SUM(n_animals) FILTER (WHERE state = 'milking') AS m
           FROM model_input.day_cell GROUP BY 1),
     ci AS (SELECT date, SUM(n_animals) AS n FROM model_input.day_cell_inferred GROUP BY 1),
     ck AS (SELECT date, SUM(n_animals) AS n FROM model_input.day_cell_known GROUP BY 1),
     pm AS (SELECT period_start, target_litres FROM model_input.period_panel WHERE grain = 'month'),
     dm AS (SELECT month, SUM(target_litres) AS t FROM model_input.day_panel GROUP BY 1)
SELECT (SELECT COUNT(*) FROM model_input.day_panel) AS day_panel_days,
       (SELECT COUNT(*) - COUNT(DISTINCT date) FROM model_input.day_panel) AS day_panel_duplicate_days,
       (SELECT COUNT(*) FROM model_input.day_panel p JOIN c ON c.date = p.date WHERE c.n <> p.n_herd) AS herd_differs,
       (SELECT COUNT(*) FROM model_input.day_panel p JOIN c ON c.date = p.date WHERE c.m <> p.milking) AS milking_differs,
       (SELECT COUNT(*) FROM c JOIN ci USING (date) WHERE c.n <> ci.n) AS inferred_total_differs,
       (SELECT COUNT(*) FROM c JOIN ck USING (date) WHERE c.n <> ck.n) AS known_total_differs,
       (SELECT COUNT(*) FROM pm JOIN dm ON dm.month = pm.period_start
        WHERE abs(coalesce(pm.target_litres, 0) - coalesce(dm.t, 0)) > 1) AS month_target_differs;

-- M7: what the page plots. Monthly milk actuals stored in c1_output for the latest run,
-- next to period_panel. Expect page_actual = period_target (or null where not scoreable).
WITH latest AS (SELECT MAX(origin_date) AS o FROM c1_output.history)
SELECT h.series, COUNT(*) AS months,
       COUNT(*) FILTER (WHERE h.actual IS NULL) AS months_null,
       ROUND(SUM(h.actual)::numeric)            AS sum_page_actual,
       ROUND(SUM(p.target_litres) FILTER (WHERE h.actual IS NOT NULL)::numeric) AS sum_period_target,
       ROUND(SUM(h.actual / NULLIF(p.target_litres, 0)) FILTER (WHERE h.actual IS NOT NULL)::numeric
             / NULLIF(COUNT(*) FILTER (WHERE h.actual IS NOT NULL), 0), 3) AS mean_ratio
FROM c1_output.history h
JOIN latest ON h.origin_date = latest.o
JOIN model_input.period_panel p ON p.grain = 'month' AND p.period_start = h.period
WHERE h.grain IN ('month', 'monthly') AND h.series IN ('herd_milk', 'milk_litres')
GROUP BY h.series;
