-- Staging: SMS message log.
-- Planted issues:
--   1. sent_at is UTC while scheduled_at is clinic-local (3 clinics on Central time).
--      sent_at_local converts to the clinic's zone so "hours before appointment" is correct.
--   2. 2% of delivery_status values are NULL -> 'unknown' (not counted as delivered).

DROP TABLE IF EXISTS stg_message;
CREATE TABLE stg_message AS
SELECT
    m.message_id,
    m.appointment_id,
    m.channel,
    m.sent_at                                                        AS sent_at_utc,
    (m.sent_at AT TIME ZONE 'UTC') AT TIME ZONE c.timezone           AS sent_at_local,
    COALESCE(LOWER(TRIM(m.delivery_status)), 'unknown')              AS delivery_status,
    m.reply_code,
    -- hours between send and appointment, both on clinic-local clock
    EXTRACT(EPOCH FROM (a.scheduled_at - ((m.sent_at AT TIME ZONE 'UTC') AT TIME ZONE c.timezone))) / 3600.0
                                                                     AS hours_before_appt,
    -- the naive (wrong) calculation that treats UTC as local, kept to show the size of the error
    EXTRACT(EPOCH FROM (a.scheduled_at - m.sent_at)) / 3600.0        AS hours_before_appt_naive,
    c.timezone
FROM raw_fact_message_log m
JOIN stg_appointment a ON a.appointment_id = m.appointment_id
JOIN stg_clinic c      ON c.clinic_id = a.clinic_id;
