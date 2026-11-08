-- Q6. Rollout value sizing (point estimates; CIs added in src/analysis.py).
-- Annual volume = 2024 (full pre-period year) appointments for SMS-opted-in patients.
-- Value     = slots recovered x contribution margin per filled slot.
-- Cost      = incremental messages x price per message + annual platform fee.
-- Simulated economics: $0.04 per message, $18,000 per year platform, $160 margin per filled slot.

WITH params AS (
    SELECT 0.04 AS cost_per_message, 18000.0 AS platform_cost, 160.0 AS margin_per_slot
),
exp_base AS (
    SELECT e.*
    FROM mart_experiment_appointment e
    LEFT JOIN ref_srm_exclusion x
           ON x.clinic_id = e.clinic_id_at_assignment
          AND e.assigned_date_local BETWEEN x.date_from AND x.date_to
    WHERE x.clinic_id IS NULL
),
scopes AS (
    SELECT 'full_network' AS scope, payer_type FROM (SELECT DISTINCT payer_type FROM stg_patient) p
    UNION ALL
    SELECT 'medicaid_selfpay_only', payer_type FROM (SELECT DISTINCT payer_type FROM stg_patient) p
    WHERE payer_type IN ('medicaid', 'self_pay')
),
effect AS (       -- unfilled-slot rate difference (treatment - control) within each scope
    SELECT
        s.scope,
        AVG(CASE WHEN e.variant = 'treatment' THEN CAST(e.is_unfilled AS DOUBLE) END)
      - AVG(CASE WHEN e.variant = 'control'   THEN CAST(e.is_unfilled AS DOUBLE) END) AS unfilled_effect,
        AVG(CASE WHEN e.variant = 'treatment' THEN CAST(e.is_no_show AS DOUBLE) END)
      - AVG(CASE WHEN e.variant = 'control'   THEN CAST(e.is_no_show AS DOUBLE) END)  AS no_show_effect
    FROM exp_base e
    JOIN scopes s ON s.payer_type = e.payer_type
    WHERE e.in_slot_universe
    GROUP BY s.scope
),
msg_rate AS (     -- messages per scheduled appointment by variant (all statuses)
    SELECT
        AVG(CASE WHEN e.variant = 'treatment' THEN CAST(COALESCE(m.messages_sent, 0) AS DOUBLE) END)
      - AVG(CASE WHEN e.variant = 'control'   THEN CAST(COALESCE(m.messages_sent, 0) AS DOUBLE) END)
            AS incremental_messages_per_appt
    FROM exp_base e
    LEFT JOIN mart_message_by_appointment m ON m.appointment_id = e.appointment_id
),
volume AS (
    SELECT
        s.scope,
        SUM(CASE WHEN o.in_slot_universe THEN 1 ELSE 0 END) AS annual_slot_appointments,
        COUNT(*)                                            AS annual_scheduled_appointments
    FROM fct_appointment_outcome o
    JOIN scopes s ON s.payer_type = o.payer_type
    WHERE o.sms_opt_in
      AND o.scheduled_date BETWEEN DATE '2024-01-01' AND DATE '2024-12-31'
    GROUP BY s.scope
)
SELECT
    v.scope,
    v.annual_slot_appointments,
    v.annual_scheduled_appointments,
    ef.no_show_effect,
    ef.unfilled_effect,
    -ef.unfilled_effect * v.annual_slot_appointments                        AS slots_recovered_per_year,
    -ef.unfilled_effect * v.annual_slot_appointments * p.margin_per_slot    AS gross_value,
    mr.incremental_messages_per_appt * v.annual_scheduled_appointments * p.cost_per_message
        + p.platform_cost                                                   AS annual_cost,
    -ef.unfilled_effect * v.annual_slot_appointments * p.margin_per_slot
        - (mr.incremental_messages_per_appt * v.annual_scheduled_appointments * p.cost_per_message
           + p.platform_cost)                                               AS net_value
FROM volume v
JOIN effect ef ON ef.scope = v.scope
CROSS JOIN msg_rate mr
CROSS JOIN params p
ORDER BY v.scope;
