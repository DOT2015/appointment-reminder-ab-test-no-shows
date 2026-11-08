-- Mart: message counts per appointment (used for delivery health and messaging cost).

DROP TABLE IF EXISTS mart_message_by_appointment;
CREATE TABLE mart_message_by_appointment AS
SELECT
    appointment_id,
    COUNT(*)                                                        AS messages_sent,
    SUM(CASE WHEN delivery_status = 'delivered' THEN 1 ELSE 0 END)  AS messages_delivered,
    SUM(CASE WHEN delivery_status = 'unknown' THEN 1 ELSE 0 END)    AS messages_status_unknown,
    SUM(CASE WHEN channel = 'sms_two_way' THEN 1 ELSE 0 END)        AS two_way_messages,
    MAX(CASE WHEN reply_code = 'C' THEN 1 ELSE 0 END)               AS confirmed,
    MAX(CASE WHEN reply_code = 'R' THEN 1 ELSE 0 END)               AS tapped_reschedule
FROM stg_message
GROUP BY appointment_id;
