-- Mart: patient-level 2024 (pre-period) no-show history. CUPED covariate.

DROP TABLE IF EXISTS mart_patient_pre_period;
CREATE TABLE mart_patient_pre_period AS
SELECT
    patient_id,
    COUNT(*)                            AS pre_appointments,
    SUM(is_no_show)                     AS pre_no_shows,
    AVG(CAST(is_no_show AS DOUBLE))     AS pre_no_show_rate
FROM fct_appointment_outcome
WHERE in_slot_universe
  AND scheduled_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'
GROUP BY patient_id;
