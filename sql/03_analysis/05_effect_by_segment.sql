-- Q5. Effect by segment: no-show and unfilled-slot rates by variant within payer, specialty,
-- lead-time band, and preferred language. Long format: one row per (dimension, segment, variant).
-- Significance testing with interaction terms and BH correction is in src/analysis.py.

WITH base AS (
    SELECT e.*
    FROM mart_experiment_appointment e
    LEFT JOIN ref_srm_exclusion x
           ON x.clinic_id = e.clinic_id_at_assignment
          AND e.assigned_date_local BETWEEN x.date_from AND x.date_to
    WHERE e.in_slot_universe
      AND x.clinic_id IS NULL
),
long AS (
    SELECT 'payer' AS dimension, payer_type AS segment, variant, is_no_show, is_unfilled FROM base
    UNION ALL
    SELECT 'specialty', specialty, variant, is_no_show, is_unfilled FROM base
    UNION ALL
    SELECT 'lead_time_band', lead_time_band, variant, is_no_show, is_unfilled FROM base
    UNION ALL
    SELECT 'language', preferred_language, variant, is_no_show, is_unfilled FROM base
)
SELECT
    dimension,
    segment,
    variant,
    COUNT(*)                              AS slot_appointments,
    AVG(CAST(is_no_show AS DOUBLE))       AS no_show_rate,
    AVG(CAST(is_unfilled AS DOUBLE))      AS unfilled_slot_rate
FROM long
GROUP BY dimension, segment, variant
ORDER BY dimension, segment, variant;
