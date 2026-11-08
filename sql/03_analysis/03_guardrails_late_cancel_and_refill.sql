-- Q3. Guardrails: late-cancel rate, refill rate of late-cancelled slots, unfilled-slot rate,
-- and message delivery health, by variant.

WITH base AS (
    SELECT e.*
    FROM mart_experiment_appointment e
    LEFT JOIN ref_srm_exclusion x
           ON x.clinic_id = e.clinic_id_at_assignment
          AND e.assigned_date_local BETWEEN x.date_from AND x.date_to
    WHERE x.clinic_id IS NULL
),
slot AS (
    SELECT
        variant,
        COUNT(*)                                            AS slot_appointments,
        AVG(CAST(is_late_cancel AS DOUBLE))                 AS late_cancel_rate,
        SUM(is_late_cancel)                                 AS late_cancels,
        AVG(CAST(late_cancel_refilled AS DOUBLE))           AS refill_rate_of_late_cancels,
        AVG(CAST(is_unfilled AS DOUBLE))                    AS unfilled_slot_rate
    FROM base
    WHERE in_slot_universe
    GROUP BY variant
),
msg AS (
    SELECT
        b.variant,
        COUNT(*)                                                         AS scheduled_appointments,
        SUM(COALESCE(m.messages_sent, 0))                                AS messages_sent,
        SUM(COALESCE(m.messages_delivered, 0))                           AS messages_delivered,
        SUM(COALESCE(m.messages_status_unknown, 0))                      AS messages_status_unknown,
        AVG(CAST(COALESCE(m.messages_sent, 0) AS DOUBLE))                AS messages_per_appointment
    FROM base b
    LEFT JOIN mart_message_by_appointment m ON m.appointment_id = b.appointment_id
    GROUP BY b.variant
)
SELECT
    s.*,
    m.scheduled_appointments,
    m.messages_sent,
    m.messages_per_appointment,
    CAST(m.messages_delivered AS DOUBLE) / NULLIF(m.messages_sent, 0)       AS delivery_rate,
    CAST(m.messages_status_unknown AS DOUBLE) / NULLIF(m.messages_sent, 0)  AS status_unknown_rate
FROM slot s
JOIN msg m ON m.variant = s.variant
ORDER BY s.variant;
