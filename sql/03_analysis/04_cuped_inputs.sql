-- Q4. CUPED inputs: patient-level 2024 no-show rate joined to experiment-period outcomes.
-- One row per patient in the analysis population. Patients with no 2024 slot appointments get
-- NULL pre_no_show_rate; src/analysis.py fills them with the pooled mean and adds an indicator.

SELECT
    e.patient_id,
    e.variant,
    e.treat,
    e.payer_type,
    MAX(e.pre_appointments)                 AS pre_appointments,
    MAX(e.pre_no_show_rate)                 AS pre_no_show_rate,
    COUNT(*)                                AS exp_slot_appointments,
    SUM(e.is_no_show)                       AS exp_no_shows,
    SUM(e.is_unfilled)                      AS exp_unfilled,
    AVG(CAST(e.is_no_show AS DOUBLE))       AS exp_no_show_rate
FROM mart_experiment_appointment e
LEFT JOIN ref_srm_exclusion x
       ON x.clinic_id = e.clinic_id_at_assignment
      AND e.assigned_date_local BETWEEN x.date_from AND x.date_to
WHERE e.in_slot_universe
  AND x.clinic_id IS NULL
GROUP BY e.patient_id, e.variant, e.treat, e.payer_type;
