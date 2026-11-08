-- Q2. Primary metric: appointment-level no-show rate by variant (slot universe, SRM exclusions applied).
-- Point estimates only; cluster-robust CIs (patients have several appointments) are in src/analysis.py.

SELECT
    e.variant,
    COUNT(DISTINCT e.patient_id)                       AS patients,
    COUNT(*)                                           AS slot_appointments,
    SUM(e.is_no_show)                                  AS no_shows,
    AVG(CAST(e.is_no_show AS DOUBLE))                  AS no_show_rate
FROM mart_experiment_appointment e
LEFT JOIN ref_srm_exclusion x
       ON x.clinic_id = e.clinic_id_at_assignment
      AND e.assigned_date_local BETWEEN x.date_from AND x.date_to
WHERE e.in_slot_universe
  AND x.clinic_id IS NULL
GROUP BY e.variant
ORDER BY e.variant;
