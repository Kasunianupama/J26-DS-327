-- Leakage audit checks (docs/leakage_audit.md). Run on farmx_app.
-- Aggregates and schema metadata only: counts, shares and percentiles, no animal keys.

-- Query L1: how is core.lactation.conception_date set? (audit item L4)
-- For conceptions 2017-2023 followed by a recorded calving: share that fall exactly on an
-- insemination of the same animal, share within 3 days, and the gestation to the next
-- calving. A conception that always sits on an insemination date is the service that
-- led to the calving; a nearly constant gestation (one value very common) means the
-- date was back-calculated from the calving. Either way it is known only once the
-- pregnancy is confirmed.
WITH lac AS (
    SELECT l.animal_key, l.calving_date, l.conception_date,
           LEAD(l.calving_date) OVER (PARTITION BY l.animal_key ORDER BY l.calving_date) AS next_calving
    FROM core.lactation l
    WHERE COALESCE(l.is_bad_date, false) = false
),
c AS (
    SELECT lac.*,
           (lac.next_calving - lac.conception_date) AS gest,
           EXISTS (SELECT 1 FROM core.insemination i
                   WHERE i.animal_key = lac.animal_key
                     AND i.insemination_date = lac.conception_date) AS on_ai_date,
           EXISTS (SELECT 1 FROM core.insemination i
                   WHERE i.animal_key = lac.animal_key
                     AND i.insemination_date BETWEEN lac.conception_date - 3
                                                 AND lac.conception_date + 3) AS near_ai_date
    FROM lac
    WHERE lac.conception_date >= DATE '2017-01-01' AND lac.conception_date < DATE '2024-01-01'
      AND lac.conception_date > lac.calving_date
)
SELECT COUNT(*)                                                                 AS conceptions,
       COUNT(*) FILTER (WHERE next_calving IS NOT NULL)                         AS with_next_calving,
       ROUND(AVG(CASE WHEN on_ai_date THEN 1.0 ELSE 0.0 END), 3)                AS share_on_ai_date,
       ROUND(AVG(CASE WHEN near_ai_date THEN 1.0 ELSE 0.0 END), 3)              AS share_within_3d_of_ai,
       MIN(gest)                                                                AS gest_min,
       percentile_cont(0.05) WITHIN GROUP (ORDER BY gest)                       AS gest_p05,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY gest)                       AS gest_median,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY gest)                       AS gest_p95,
       MAX(gest)                                                                AS gest_max,
       mode() WITHIN GROUP (ORDER BY gest)                                      AS gest_mode,
       ROUND(AVG(CASE WHEN gest = (SELECT mode() WITHIN GROUP (ORDER BY gest) FROM c)
                      THEN 1.0 ELSE 0.0 END), 3)                                AS share_at_mode
FROM c
WHERE next_calving IS NOT NULL;

-- Query L2: are pregnant heifers in day_cell known only in hindsight? (audit item L3)
-- On the 1st of Jan and Jul 2018-2023, compare:
--   a  heifers counted pregnant by day_cell;
--   b  heifers alive and not yet calved whose first calving falls in the next 300 days
--      (pregnant, as known later);
--   c  of b, those whose last insemination before the day was 35+ days earlier
--      (confirmable on the day);
--   d  of b, those whose last insemination was under 35 days earlier (not confirmable);
--   e  heifers with a last insemination 35-285 days earlier, whatever the outcome
--      (what could be known on the day without hindsight).
-- If a is close to b and d is clearly above 0, day_cell pregnancies use later calvings.
WITH days AS (
    SELECT d::date AS d
    FROM generate_series(DATE '2018-01-01', DATE '2023-07-01', interval '6 months') AS g(d)
),
first_calving AS (
    SELECT animal_key, MIN(calving_date) AS first_calving
    FROM core.lactation
    WHERE COALESCE(is_bad_date, false) = false
    GROUP BY 1
),
heifers AS (
    SELECT days.d, a.animal_key, fc.first_calving,
           (SELECT MAX(i.insemination_date) FROM core.insemination i
            WHERE i.animal_key = a.animal_key AND i.insemination_date <= days.d
              AND COALESCE(i.is_bad_date, false) = false) AS last_ai
    FROM days
    JOIN core.animal a
      ON a.sex = 'female'
     AND a.birth_date <= days.d - 365
     AND COALESCE(a.exit_date, 'infinity'::date) > days.d
     AND COALESCE(a.is_placeholder, false) = false
    LEFT JOIN first_calving fc ON fc.animal_key = a.animal_key
    WHERE fc.first_calving IS NULL OR fc.first_calving > days.d
)
SELECT h.d                                                                         AS day,
       (SELECT SUM(n_animals) FROM model_input.day_cell dc
        WHERE dc.date = h.d AND dc.state = 'heifer_pregnant')                       AS a_daycell_pregnant,
       COUNT(*) FILTER (WHERE h.first_calving <= h.d + 300)                         AS b_calve_within_300d,
       COUNT(*) FILTER (WHERE h.first_calving <= h.d + 300 AND h.last_ai <= h.d - 35) AS c_confirmable,
       COUNT(*) FILTER (WHERE h.first_calving <= h.d + 300 AND h.last_ai > h.d - 35)  AS d_not_confirmable,
       COUNT(*) FILTER (WHERE h.last_ai BETWEEN h.d - 285 AND h.d - 35)             AS e_served_35_285d
FROM heifers h
GROUP BY h.d
ORDER BY h.d;

-- Query L3: do core or model_input tables carry record-entry timestamps? (audit item L5)
-- Schema metadata only. If an entry or load timestamp exists, records entered late (for
-- example back-filled after the outage) can be cut "as known" at each origin.
SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema IN ('core', 'model_input')
  AND column_name ~* '(creat|enter|entry|record|insert|updat|modif|load|ingest|_at$|_ts$|timestamp)'
ORDER BY 1, 2, 3;
