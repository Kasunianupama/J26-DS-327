-- Episode checks for the disruption periods (docs/targets.md).
-- Aggregates only: one row per month or per year, herd-level totals. Run on farmx_app.

-- Query 1: monthly herd totals and recording coverage, 2021-01 onward.
-- Pins down the herd-contraction and DelPro-outage months, and shows whether herd
-- events were still recorded during the outage.
SELECT date_trunc('month', date)::date                              AS month,
       COUNT(*)                                                     AS days,
       ROUND(AVG(n_herd))                                           AS avg_herd,
       ROUND(AVG(milking))                                          AS avg_milking,
       SUM(calvings)                                                AS calvings,
       SUM(births)                                                  AS births,
       SUM(dry_offs)                                                AS dry_offs,
       SUM(ais)                                                     AS ais,
       SUM(real_abortions)                                          AS abortions,
       SUM(deaths)                                                  AS deaths,
       SUM(culls)                                                   AS culls,
       SUM(sales)                                                   AS sales,
       SUM(external_entries)                                        AS external_entries,
       COUNT(*) FILTER (WHERE CAST(data_gap AS int) = 1)            AS gap_days,
       COUNT(*) FILTER (WHERE is_scoreable)                         AS scoreable_days,
       SUM(n_sessions)                                              AS milking_sessions
FROM model_input.day_panel
WHERE date >= DATE '2021-01-01'
GROUP BY 1
ORDER BY 1;

-- Query 2: are events recorded in batches? Per year and event type: the mean share of a
-- month's events that fall on its single busiest day, and the mean number of days per
-- month with at least one event. Daily recording gives a low top-day share.
WITH m AS (
    SELECT date_trunc('month', date) AS month,
           SUM(dry_offs) AS dry_sum, MAX(dry_offs) AS dry_max,
           COUNT(*) FILTER (WHERE dry_offs > 0) AS dry_days,
           SUM(calvings) AS calv_sum, MAX(calvings) AS calv_max,
           COUNT(*) FILTER (WHERE calvings > 0) AS calv_days,
           SUM(culls) AS cull_sum, MAX(culls) AS cull_max,
           COUNT(*) FILTER (WHERE culls > 0) AS cull_days,
           SUM(sales) AS sale_sum, MAX(sales) AS sale_max,
           COUNT(*) FILTER (WHERE sales > 0) AS sale_days
    FROM model_input.day_panel
    WHERE date >= DATE '2015-08-01'
    GROUP BY 1
)
SELECT EXTRACT(year FROM month)::int                                       AS year,
       ROUND(AVG(dry_max::numeric  / NULLIF(dry_sum, 0)), 2)              AS dryoff_top_day_share,
       ROUND(AVG(dry_days), 1)                                             AS dryoff_days_per_month,
       ROUND(AVG(calv_max::numeric / NULLIF(calv_sum, 0)), 2)             AS calving_top_day_share,
       ROUND(AVG(calv_days), 1)                                            AS calving_days_per_month,
       ROUND(AVG(cull_max::numeric / NULLIF(cull_sum, 0)), 2)             AS cull_top_day_share,
       ROUND(AVG(cull_days), 1)                                            AS cull_days_per_month,
       ROUND(AVG(sale_max::numeric / NULLIF(sale_sum, 0)), 2)             AS sale_top_day_share,
       ROUND(AVG(sale_days), 1)                                            AS sale_days_per_month
FROM m
GROUP BY 1
ORDER BY 1;

-- Query 3: is the 2024 fall in recorded cows real, or a recording loss?
-- From the 2024-01 origin, recorded milking cows fall about 46 % by Aug 2024 while herd
-- milk rises, which would need litres per cow to almost double. Per month from 2023:
-- litres per recorded milking cow-day, and milking sessions per recorded milking
-- cow-day. Sessions per cow rising well above the usual level means cows are being
-- milked that the herd records no longer count.
SELECT date_trunc('month', date)::date                                   AS month,
       ROUND(AVG(milking))                                               AS avg_milking_recorded,
       ROUND(AVG(n_herd))                                                AS avg_herd_recorded,
       ROUND(SUM(target_litres))                                         AS target_litres,
       MIN(target_source)                                                AS target_source,
       ROUND(SUM(milk_delpro_cows))                                      AS delpro_identified_litres,
       ROUND(SUM(milk_delpro_unidentified))                              AS delpro_unidentified_litres,
       ROUND(SUM(milk_shipped))                                          AS shipped_litres,
       ROUND(AVG(identified_share)::numeric, 3)                          AS mean_identified_share,
       ROUND((SUM(target_litres) / NULLIF(SUM(milking), 0))::numeric, 2) AS litres_per_milking_cow_day,
       ROUND((SUM(n_sessions)::numeric / NULLIF(SUM(milking), 0)), 2)    AS sessions_per_milking_cow_day,
       COUNT(*) FILTER (WHERE CAST(data_gap AS int) = 1)                 AS gap_days
FROM model_input.day_panel
WHERE date >= DATE '2023-01-01'
GROUP BY 1
ORDER BY 1;

-- Query 4: per-cow milk, aggregated (user request 2026-10-19; placeholder excluded in v2). Is "litres per recorded
-- milking cow" inflated by the division? Per month from 2023, using only milk that is
-- attached to a cow (core.cow_day): cows with any yield per day, litres per identified
-- cow-day, percentiles of per-cow daily yield, and the share of cow-days above 20 L.
-- Compare cows_with_yield_per_day with avg_milking_recorded (query 3): if far more cows
-- give milk than the herd records count as milking, the denominator is too small.
WITH d AS (
    SELECT milk_date, animal_key, SUM(yield_litres) AS litres
    FROM core.cow_day
    WHERE milk_date >= DATE '2023-01-01' AND yield_litres > 0
      AND NOT COALESCE(is_placeholder, false)  -- unidentified milk sits on a placeholder key
    GROUP BY 1, 2
)
SELECT date_trunc('month', milk_date)::date                                     AS month,
       COUNT(DISTINCT milk_date)                                                AS days_with_yield,
       ROUND(COUNT(*)::numeric / COUNT(DISTINCT milk_date))                     AS cows_with_yield_per_day,
       ROUND(SUM(litres))                                                       AS identified_litres,
       ROUND((SUM(litres) / COUNT(*))::numeric, 2)                              AS litres_per_identified_cow_day,
       ROUND(percentile_cont(0.10) WITHIN GROUP (ORDER BY litres)::numeric, 1)  AS p10_litres,
       ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY litres)::numeric, 1)  AS median_litres,
       ROUND(percentile_cont(0.90) WITHIN GROUP (ORDER BY litres)::numeric, 1)  AS p90_litres,
       ROUND(AVG(CASE WHEN litres > 20 THEN 1.0 ELSE 0.0 END)::numeric, 3)      AS share_cow_days_over_20l
FROM d
GROUP BY 1
ORDER BY 1;

-- Query 5: cows that give milk without an open lactation record (2025-09 onward).
-- From Jun 2026 about 100-115 more cows give identified milk each day than day_panel
-- counts as milking. Per month: mean cows a day giving milk, split by whether
-- core.lactation has a lactation covering that day (calved on or before the day, not
-- yet dried off). Counts only.
WITH d AS (
    SELECT DISTINCT milk_date, animal_key
    FROM core.cow_day
    WHERE milk_date >= DATE '2025-09-01' AND yield_litres > 0
      AND NOT COALESCE(is_placeholder, false)
),
flag AS (
    SELECT d.milk_date,
           EXISTS (SELECT 1 FROM core.lactation l
                   WHERE l.animal_key = d.animal_key
                     AND l.calving_date <= d.milk_date
                     AND (l.dry_off_date IS NULL OR l.dry_off_date > d.milk_date)) AS has_lactation,
           EXISTS (SELECT 1 FROM core.lactation l
                   WHERE l.animal_key = d.animal_key) AS any_lactation_ever
    FROM d
)
SELECT date_trunc('month', milk_date)::date                                             AS month,
       COUNT(DISTINCT milk_date)                                                        AS days,
       ROUND(COUNT(*)::numeric / COUNT(DISTINCT milk_date))                             AS cows_giving_milk_per_day,
       ROUND(COUNT(*) FILTER (WHERE has_lactation)::numeric / COUNT(DISTINCT milk_date)) AS with_open_lactation,
       ROUND(COUNT(*) FILTER (WHERE NOT has_lactation AND any_lactation_ever)::numeric
             / COUNT(DISTINCT milk_date))                                               AS lactation_closed_or_later,
       ROUND(COUNT(*) FILTER (WHERE NOT any_lactation_ever)::numeric
             / COUNT(DISTINCT milk_date))                                               AS never_any_lactation
FROM flag
GROUP BY 1
ORDER BY 1;
