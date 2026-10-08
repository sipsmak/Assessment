-- Flux Data Engineer Assessment - Part A
-- BigQuery Standard SQL. Replace `project.dataset` with the deployed dataset.
--
-- Modelling approach:
-- My background is primarily Data Vault, so I separate historical ingestion from the
-- reporting layer. Source/history should be preserved upstream; the SQL below derives
-- the current business state and exposes a simpler fact/dimensional model for analytics.
--
-- Status treatment:
-- Cancelled and pending bookings remain in the fact table because they are valid business
-- states, but recognised revenue reporting below includes confirmed bookings only.


-- =========================================================
-- A1) Current version of each booking
-- =========================================================
-- Keep one reporting row per booking_id using the most recent updated_at.
-- Historical versions would remain upstream rather than being physically deleted.
-- If the source can produce two conflicting rows with the same latest updated_at,
-- production logic should use a deterministic source sequence/load timestamp or quarantine
-- the conflict. That issue is explicitly checked in A6.

CREATE OR REPLACE VIEW `project.dataset.v_current_bookings` AS
SELECT b.*
FROM `project.dataset.cleaned_bookings` b
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY booking_id
  ORDER BY updated_at DESC
) = 1;


-- =========================================================
-- A2) Point-in-time FX conversion
-- =========================================================
-- Use the most recent rate effective on or before the booking's created_at date.
-- This is an as-of / point-in-time lookup rather than a latest-rate join.

CREATE OR REPLACE VIEW `project.dataset.v_bookings_with_fx` AS
SELECT
  b.*,
  fx.rate_to_zar,
  fx.effective_from AS fx_effective_from,
  b.revenue * fx.rate_to_zar AS revenue_zar
FROM `project.dataset.v_current_bookings` b
LEFT JOIN `project.dataset.fx_rates` fx
  ON UPPER(TRIM(b.currency)) = UPPER(TRIM(fx.currency))
 AND fx.effective_from <= DATE(b.created_at)
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY b.booking_id
  ORDER BY fx.effective_from DESC
) = 1;


-- =========================================================
-- A3) Reporting model
-- =========================================================
-- The historical/integration layer and reporting layer serve different purposes.
-- The reporting model below is deliberately simple for BI consumption.
--
-- Partition choice:
-- check_in month is used because the common monthly reporting requirement is treated as
-- stay/revenue-period reporting. This enables partition pruning when analysts query a stay
-- period. If the business instead defines monthly revenue by booking-created month, I would
-- switch the partitioning and downstream revenue-month logic to created_at consistently.
--
-- Clustering choice:
-- property_id and booking_channel are common grouping/filter dimensions. booking_status is
-- also clustered because confirmed-only revenue queries are frequent while all statuses are
-- retained in the fact table.

CREATE OR REPLACE TABLE `project.dataset.dim_property` AS
SELECT
  property_id,
  property_name,
  country,
  region,
  room_count,
  property_status
FROM `project.dataset.properties`;

CREATE OR REPLACE TABLE `project.dataset.fact_bookings`
PARTITION BY DATE_TRUNC(check_in, MONTH)
CLUSTER BY property_id, booking_channel, booking_status AS
SELECT
  b.booking_id,
  b.property_id,
  b.check_in,
  b.check_out,
  DATE_DIFF(b.check_out, b.check_in, DAY) AS nights,
  b.num_guests,
  b.room_rate,
  b.currency,
  b.revenue,
  b.rate_to_zar,
  b.revenue_zar,
  b.booking_channel,
  b.booking_status,
  b.created_at,
  b.updated_at
FROM `project.dataset.v_bookings_with_fx` b;

CREATE OR REPLACE VIEW `project.dataset.v_booking_revenue` AS
SELECT
  b.booking_id,
  b.property_id,
  p.property_name,
  p.country,
  p.region,
  b.check_in,
  b.check_out,
  b.nights,
  b.num_guests,
  b.booking_channel,
  b.booking_status,
  b.currency,
  b.revenue,
  b.rate_to_zar,
  b.revenue_zar,
  b.created_at,
  b.updated_at
FROM `project.dataset.fact_bookings` b
LEFT JOIN `project.dataset.dim_property` p USING (property_id);


-- =========================================================
-- A4) Month-on-month confirmed revenue growth in 2025
-- =========================================================
-- Generate the full calendar so a zero-revenue month is not silently skipped by LAG.
-- Cancelled and pending bookings are excluded from recognised revenue.

WITH calendar AS (
  SELECT revenue_month
  FROM UNNEST(
    GENERATE_DATE_ARRAY(
      DATE '2025-01-01',
      DATE '2025-12-01',
      INTERVAL 1 MONTH
    )
  ) AS revenue_month
),
monthly AS (
  SELECT
    DATE_TRUNC(check_in, MONTH) AS revenue_month,
    SUM(revenue_zar) AS revenue_zar
  FROM `project.dataset.fact_bookings`
  WHERE booking_status = 'confirmed'
    AND check_in >= DATE '2025-01-01'
    AND check_in < DATE '2026-01-01'
  GROUP BY 1
),
all_months AS (
  SELECT
    c.revenue_month,
    COALESCE(m.revenue_zar, 0) AS revenue_zar
  FROM calendar c
  LEFT JOIN monthly m USING (revenue_month)
),
with_prior AS (
  SELECT
    revenue_month,
    revenue_zar,
    LAG(revenue_zar) OVER (ORDER BY revenue_month) AS prior_month_revenue_zar
  FROM all_months
)
SELECT
  revenue_month,
  revenue_zar,
  prior_month_revenue_zar,
  SAFE_DIVIDE(
    revenue_zar - prior_month_revenue_zar,
    prior_month_revenue_zar
  ) * 100 AS mom_growth_pct
FROM with_prior
ORDER BY revenue_month;


-- =========================================================
-- A5) Top 2 properties by confirmed revenue within each country
-- =========================================================
-- DENSE_RANK handles ties sensibly: if multiple properties tie for second place,
-- all of them receive rank 2 and are returned.

WITH property_revenue AS (
  SELECT
    p.country,
    b.property_id,
    p.property_name,
    SUM(b.revenue_zar) AS revenue_zar
  FROM `project.dataset.fact_bookings` b
  INNER JOIN `project.dataset.dim_property` p USING (property_id)
  WHERE b.booking_status = 'confirmed'
  GROUP BY 1, 2, 3
),
ranked AS (
  SELECT
    *,
    DENSE_RANK() OVER (
      PARTITION BY country
      ORDER BY revenue_zar DESC
    ) AS revenue_rank
  FROM property_revenue
)
SELECT
  country,
  property_id,
  property_name,
  revenue_zar,
  revenue_rank
FROM ranked
WHERE revenue_rank <= 2
ORDER BY country, revenue_rank, property_name;


-- =========================================================
-- A6) Data-quality / integrity assertions against raw data
-- =========================================================
-- These checks deliberately run against the raw/source-level data so source problems
-- remain visible instead of being silently removed during transformation.
--
-- The raw data is normalised only enough to evaluate the checks. UNION ALL should be used
-- when the raw daily batches are loaded so re-sent/duplicate rows remain observable.
--
-- Checks returned below:
--  1. missing booking business key
--  2. duplicate latest/current-version IDs
--  3. same-timestamp conflicting latest versions
--  4. orphan property references
--  5. missing/non-positive revenue
--  6. unsupported currency
--  7. no applicable historical FX rate
--  8. invalid booking status
--  9. invalid guest count
-- 10. unusually high guest count (monitoring rule; threshold should be business-agreed)
-- 11. invalid stay date range
-- 12. invalid room rate

WITH raw_normalised AS (
  SELECT
    r.*,

    NULLIF(TRIM(CAST(booking_id AS STRING)), '') AS booking_id_clean,
    NULLIF(TRIM(CAST(property_id AS STRING)), '') AS property_id_clean,

    COALESCE(
      SAFE.PARSE_DATE('%Y-%m-%d', TRIM(CAST(check_in AS STRING))),
      SAFE.PARSE_DATE('%d/%m/%Y', TRIM(CAST(check_in AS STRING))),
      SAFE.PARSE_DATE('%e %b %Y', TRIM(CAST(check_in AS STRING)))
    ) AS check_in_date,

    COALESCE(
      SAFE.PARSE_DATE('%Y-%m-%d', TRIM(CAST(check_out AS STRING))),
      SAFE.PARSE_DATE('%d/%m/%Y', TRIM(CAST(check_out AS STRING))),
      SAFE.PARSE_DATE('%e %b %Y', TRIM(CAST(check_out AS STRING)))
    ) AS check_out_date,

    SAFE_CAST(num_guests AS INT64) AS num_guests_num,

    SAFE_CAST(
      REGEXP_REPLACE(TRIM(CAST(room_rate AS STRING)), r'[^0-9.-]', '')
      AS NUMERIC
    ) AS room_rate_num,

    SAFE_CAST(
      REGEXP_REPLACE(TRIM(CAST(revenue AS STRING)), r'[^0-9.-]', '')
      AS NUMERIC
    ) AS revenue_num,

    CASE UPPER(TRIM(CAST(currency AS STRING)))
      WHEN '$' THEN 'USD'
      WHEN 'US$' THEN 'USD'
      WHEN 'USD' THEN 'USD'
      WHEN '€' THEN 'EUR'
      WHEN 'EUR' THEN 'EUR'
      WHEN '£' THEN 'GBP'
      WHEN 'GBP' THEN 'GBP'
      WHEN 'R' THEN 'ZAR'
      WHEN 'ZAR' THEN 'ZAR'
      ELSE NULLIF(UPPER(TRIM(CAST(currency AS STRING))), '')
    END AS currency_clean,

    LOWER(TRIM(CAST(booking_status AS STRING))) AS booking_status_clean,
    SAFE_CAST(created_at AS TIMESTAMP) AS created_ts,
    SAFE_CAST(updated_at AS TIMESTAMP) AS updated_ts

  FROM `project.dataset.raw_bookings` r
),

latest_timestamp AS (
  SELECT
    booking_id_clean,
    MAX(updated_ts) AS max_updated_ts
  FROM raw_normalised
  WHERE booking_id_clean IS NOT NULL
  GROUP BY booking_id_clean
),

latest_candidates AS (
  SELECT r.*
  FROM raw_normalised r
  INNER JOIN latest_timestamp l
    ON r.booking_id_clean = l.booking_id_clean
   AND r.updated_ts = l.max_updated_ts
),

-- Used for checks that need one representative current row. Conflicting latest rows are
-- separately counted above; in the actual pipeline they should be quarantined rather than
-- trusted as current state.
current_versions AS (
  SELECT *
  FROM latest_candidates
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY booking_id_clean
    ORDER BY updated_ts DESC
  ) = 1
),

current_with_fx AS (
  SELECT
    c.booking_id_clean,
    fx.rate_to_zar
  FROM current_versions c
  LEFT JOIN `project.dataset.fx_rates` fx
    ON c.currency_clean = UPPER(TRIM(fx.currency))
   AND fx.effective_from <= DATE(c.created_ts)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY c.booking_id_clean
    ORDER BY fx.effective_from DESC
  ) = 1
),

quality_results AS (

  SELECT
    'missing_booking_id' AS check_name,
    COUNT(*) AS issue_count
  FROM raw_normalised
  WHERE booking_id_clean IS NULL

  UNION ALL

  SELECT
    'duplicate_current_version_ids',
    COUNT(*)
  FROM (
    SELECT booking_id_clean
    FROM latest_candidates
    GROUP BY booking_id_clean
    HAVING COUNT(*) > 1
  )

  UNION ALL

  SELECT
    'same_timestamp_conflicting_versions',
    COUNT(*)
  FROM (
    SELECT
      booking_id_clean,
      updated_ts
    FROM latest_candidates
    GROUP BY booking_id_clean, updated_ts
    HAVING COUNT(*) > 1
       AND COUNT(DISTINCT TO_JSON_STRING(STRUCT(
         property_id_clean,
         check_in_date,
         check_out_date,
         num_guests_num,
         room_rate_num,
         currency_clean,
         revenue_num,
         TRIM(CAST(booking_channel AS STRING)),
         booking_status_clean,
         created_ts
       ))) > 1
  )

  UNION ALL

  SELECT
    'orphan_properties',
    COUNT(*)
  FROM current_versions c
  LEFT JOIN `project.dataset.properties` p
    ON c.property_id_clean = TRIM(CAST(p.property_id AS STRING))
  WHERE p.property_id IS NULL

  UNION ALL

  SELECT
    'missing_or_non_positive_revenue',
    COUNT(*)
  FROM current_versions
  WHERE revenue_num IS NULL OR revenue_num <= 0

  UNION ALL

  SELECT
    'unsupported_currency',
    COUNT(*)
  FROM current_versions
  WHERE currency_clean IS NULL
     OR currency_clean NOT IN ('ZAR', 'USD', 'EUR', 'GBP')

  UNION ALL

  SELECT
    'bookings_without_applicable_fx',
    COUNT(*)
  FROM current_with_fx
  WHERE rate_to_zar IS NULL

  UNION ALL

  SELECT
    'invalid_booking_status',
    COUNT(*)
  FROM current_versions
  WHERE booking_status_clean IS NULL
     OR booking_status_clean NOT IN ('confirmed', 'pending', 'cancelled')

  UNION ALL

  SELECT
    'invalid_guest_count',
    COUNT(*)
  FROM current_versions
  WHERE num_guests_num IS NULL OR num_guests_num <= 0

  UNION ALL

  SELECT
    'unusually_high_guest_count',
    COUNT(*)
  FROM current_versions
  WHERE num_guests_num > 20

  UNION ALL

  SELECT
    'invalid_date_ranges',
    COUNT(*)
  FROM current_versions
  WHERE check_in_date IS NULL
     OR check_out_date IS NULL
     OR check_out_date <= check_in_date

  UNION ALL

  SELECT
    'invalid_room_rate',
    COUNT(*)
  FROM current_versions
  WHERE room_rate_num IS NULL OR room_rate_num <= 0
)

SELECT
  check_name,
  issue_count
FROM quality_results
ORDER BY check_name;
