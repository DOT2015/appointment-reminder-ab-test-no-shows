-- Staging: experiment assignments.
-- Planted issue: 0.7% of patients have a second assignment row with the opposite variant.
-- Rule (pre-registered): the first assignment by assigned_at wins; later rows are discarded.
-- assigned_at is UTC; assigned_date_local converts it to the assignment clinic's time zone.

DROP TABLE IF EXISTS stg_assignment;
CREATE TABLE stg_assignment AS
WITH ranked AS (
    SELECT
        a.*,
        ROW_NUMBER() OVER (PARTITION BY a.patient_id ORDER BY a.assigned_at, a.assignment_row_id) AS rn,
        COUNT(*)     OVER (PARTITION BY a.patient_id)                                          AS n_rows,
        MIN(a.variant) OVER (PARTITION BY a.patient_id)                                        AS min_variant,
        MAX(a.variant) OVER (PARTITION BY a.patient_id)                                        AS max_variant
    FROM raw_fact_experiment_assignment a
)
SELECT
    r.patient_id,
    LOWER(TRIM(r.variant))                              AS variant,
    r.assigned_at                                       AS assigned_at_utc,
    CAST((r.assigned_at AT TIME ZONE 'UTC') AT TIME ZONE c.timezone AS DATE) AS assigned_date_local,
    r.clinic_id_at_assignment,
    (r.n_rows > 1)                                      AS had_duplicate_rows,
    (r.min_variant <> r.max_variant)                    AS had_conflicting_variants
FROM ranked r
JOIN stg_clinic c ON c.clinic_id = r.clinic_id_at_assignment
WHERE r.rn = 1;
