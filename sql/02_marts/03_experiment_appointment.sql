-- Mart: appointments in the experiment window (2025-03-03 .. 2025-06-29) for assigned patients.
-- Variant comes from the de-duplicated assignment (first row wins). Rescheduled-into appointments
-- inherit the patient's variant automatically because randomization is at the patient level.
-- SRM exclusions are applied later via ref_srm_exclusion (built by src/analysis.py after detection).

DROP TABLE IF EXISTS mart_experiment_appointment;
CREATE TABLE mart_experiment_appointment AS
SELECT
    o.*,
    s.variant,
    CASE WHEN s.variant = 'treatment' THEN 1 ELSE 0 END AS treat,
    s.assigned_date_local,
    s.clinic_id_at_assignment,
    s.had_conflicting_variants,
    COALESCE(pp.pre_appointments, 0)                    AS pre_appointments,
    pp.pre_no_show_rate
FROM fct_appointment_outcome o
JOIN stg_assignment s           ON s.patient_id = o.patient_id
LEFT JOIN mart_patient_pre_period pp ON pp.patient_id = o.patient_id
WHERE o.scheduled_date BETWEEN DATE '2025-03-03' AND DATE '2025-06-29';
