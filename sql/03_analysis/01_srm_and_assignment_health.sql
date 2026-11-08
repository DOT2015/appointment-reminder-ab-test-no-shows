-- Q1. Is randomization healthy?
-- Daily assignment counts by clinic and variant (clinic-local assignment date), after de-duplication.
-- src/analysis.py uses this to run (a) the overall SRM chi-square test and (b) a clinic x day scan
-- (binomial test per cell, Benjamini-Hochberg) that localizes any logging gap.
-- Also returns the cross-check: patients who received two-way (treatment-only) texts in the window
-- but have no assignment row.

WITH daily AS (
    SELECT
        clinic_id_at_assignment                                  AS clinic_id,
        assigned_date_local                                      AS assigned_date,
        SUM(CASE WHEN variant = 'control'   THEN 1 ELSE 0 END)   AS n_control,
        SUM(CASE WHEN variant = 'treatment' THEN 1 ELSE 0 END)   AS n_treatment
    FROM stg_assignment
    GROUP BY clinic_id_at_assignment, assigned_date_local
),
two_way_unassigned AS (
    SELECT o.clinic_id, CAST(MIN(o.scheduled_at) AS DATE) AS first_appt_date, o.patient_id
    FROM fct_appointment_outcome o
    JOIN mart_message_by_appointment m ON m.appointment_id = o.appointment_id
    LEFT JOIN stg_assignment s         ON s.patient_id = o.patient_id
    WHERE m.two_way_messages > 0
      AND s.patient_id IS NULL
    GROUP BY o.clinic_id, o.patient_id
)
SELECT
    d.clinic_id,
    d.assigned_date,
    d.n_control,
    d.n_treatment,
    COALESCE(u.n_unlogged_two_way_patients, 0) AS n_unlogged_two_way_patients
FROM daily d
LEFT JOIN (
    -- first in-window appointment is 72h after assignment; shift back to the assignment date
    SELECT clinic_id, first_appt_date - 3 AS assigned_date, COUNT(*) AS n_unlogged_two_way_patients
    FROM two_way_unassigned
    GROUP BY clinic_id, first_appt_date - 3
) u ON u.clinic_id = d.clinic_id AND u.assigned_date = d.assigned_date
ORDER BY d.clinic_id, d.assigned_date;
