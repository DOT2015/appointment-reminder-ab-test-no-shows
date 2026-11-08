-- Staging: appointments.
-- Fixes planted issues:
--   1. Inconsistent status codes ('NOSHOW', 'No Show', 'NS', 'Completed', 'CANCELED', ...) -> 5 canonical codes.
--   2. Rescheduled originals that the source system closed out as no-shows. If another appointment
--      points to this one via rescheduled_from_appointment_id, the original is 'rescheduled'.
--   3. 0.5% of rows have booked_at after scheduled_at (entry error). Kept for outcome metrics,
--      lead time set to NULL and flagged.

DROP TABLE IF EXISTS stg_appointment;
CREATE TABLE stg_appointment AS
WITH normalized AS (
    SELECT
        a.*,
        CASE
            WHEN UPPER(REPLACE(REPLACE(TRIM(a.status), ' ', ''), '_', '')) IN ('NOSHOW', 'NS') THEN 'no_show'
            WHEN UPPER(TRIM(a.status)) = 'COMPLETED' THEN 'completed'
            WHEN UPPER(TRIM(a.status)) IN ('CANCELLED', 'CANCELED') THEN 'cancelled'
            WHEN UPPER(REPLACE(REPLACE(TRIM(a.status), ' ', ''), '_', '')) = 'LATECANCEL' THEN 'late_cancel'
            WHEN UPPER(TRIM(a.status)) = 'RESCHEDULED' THEN 'rescheduled'
            ELSE 'unknown'
        END AS status_normalized
    FROM raw_fact_appointment a
),
reschedule_children AS (
    SELECT rescheduled_from_appointment_id AS parent_appointment_id,
           MIN(booked_at)                  AS rebooked_at
    FROM raw_fact_appointment
    WHERE rescheduled_from_appointment_id IS NOT NULL
    GROUP BY rescheduled_from_appointment_id
)
SELECT
    n.appointment_id,
    n.patient_id,
    n.clinic_id,
    n.provider_id,
    n.booked_at,
    n.scheduled_at,                                    -- clinic-local wall time
    CAST(n.scheduled_at AS DATE)                       AS scheduled_date,
    CASE WHEN n.booked_at <= n.scheduled_at THEN n.lead_time_days END AS lead_time_days,
    CASE WHEN c.parent_appointment_id IS NOT NULL THEN 'rescheduled'
         ELSE n.status_normalized END                  AS status,
    n.status                                           AS status_raw,
    (c.parent_appointment_id IS NOT NULL
        AND n.status_normalized <> 'rescheduled')      AS status_corrected_flag,
    (n.booked_at > n.scheduled_at)                     AS booked_after_scheduled_flag,
    n.status_updated_at,
    CASE n.slot_refilled_flag WHEN 'Y' THEN 1 WHEN 'N' THEN 0 END AS slot_refilled,
    n.rescheduled_from_appointment_id
FROM normalized n
LEFT JOIN reschedule_children c
       ON c.parent_appointment_id = n.appointment_id;
