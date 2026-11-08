-- Mart: one row per appointment with metric flags.
--
-- Metric definitions (also in docs/experiment_design.md):
--   slot universe    = appointments that reached the visit day without an early (>=24h) cancellation
--                      or a reschedule: status IN (completed, no_show, late_cancel).
--   no-show rate     = no_show / slot universe.
--   late-cancel rate = late_cancel / slot universe   (cancelled < 24h before the visit).
--   unfilled-slot rate = (no_show + late_cancel that was not refilled) / slot universe.
--   refill rate      = refilled late cancels / late cancels.

DROP TABLE IF EXISTS fct_appointment_outcome;
CREATE TABLE fct_appointment_outcome AS
SELECT
    a.appointment_id,
    a.patient_id,
    a.clinic_id,
    c.specialty,
    c.timezone,
    a.provider_id,
    a.booked_at,
    a.scheduled_at,
    a.scheduled_date,
    a.lead_time_days,
    CASE
        WHEN a.lead_time_days IS NULL THEN 'unknown'
        WHEN a.lead_time_days <= 2  THEN '0-2 days'
        WHEN a.lead_time_days <= 7  THEN '3-7 days'
        WHEN a.lead_time_days <= 30 THEN '8-30 days'
        ELSE '31+ days'
    END                                                         AS lead_time_band,
    a.status,
    a.status_corrected_flag,
    a.booked_after_scheduled_flag,
    (a.status IN ('completed', 'no_show', 'late_cancel'))       AS in_slot_universe,
    CASE WHEN a.status = 'no_show' THEN 1 ELSE 0 END            AS is_no_show,
    CASE WHEN a.status = 'late_cancel' THEN 1 ELSE 0 END        AS is_late_cancel,
    CASE WHEN a.status = 'late_cancel' THEN COALESCE(a.slot_refilled, 0) END AS late_cancel_refilled,
    CASE WHEN a.status = 'no_show'
           OR (a.status = 'late_cancel' AND COALESCE(a.slot_refilled, 0) = 0) THEN 1 ELSE 0 END AS is_unfilled,
    p.payer_type,
    p.preferred_language,
    p.age_band,
    p.sms_opt_in
FROM stg_appointment a
JOIN stg_clinic  c ON c.clinic_id  = a.clinic_id
JOIN stg_patient p ON p.patient_id = a.patient_id;
