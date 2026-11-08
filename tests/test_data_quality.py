"""Row counts, uniqueness, referential integrity, null thresholds, and cleaning rules."""
from conftest import scalar


def test_row_counts(con, truth):
    rows = truth["realized"]["rows"]
    for t, n in rows.items():
        assert scalar(con, f"SELECT COUNT(*) FROM raw_{t}") == n
    assert 50_000 <= rows["fact_appointment"] <= 500_000
    assert rows["dim_clinic"] == 24 and rows["dim_provider"] == 180 and rows["dim_patient"] == 90_000


def test_date_coverage(con):
    lo, hi = con.execute("SELECT MIN(scheduled_date), MAX(scheduled_date) FROM stg_appointment").fetchone()
    assert str(lo) <= "2024-01-03" and str(hi) >= "2025-12-29"


def test_primary_keys_unique(con):
    for t, k in [("stg_appointment", "appointment_id"), ("stg_patient", "patient_id"), ("stg_clinic", "clinic_id"),
                 ("stg_message", "message_id"), ("stg_assignment", "patient_id"),
                 ("fct_appointment_outcome", "appointment_id")]:
        assert scalar(con, f"SELECT COUNT(*) - COUNT(DISTINCT {k}) FROM {t}") == 0, t


def test_referential_integrity(con):
    assert scalar(con, """SELECT COUNT(*) FROM stg_appointment a LEFT JOIN stg_patient p USING (patient_id)
                          WHERE p.patient_id IS NULL""") == 0
    assert scalar(con, """SELECT COUNT(*) FROM stg_appointment a LEFT JOIN stg_clinic c USING (clinic_id)
                          WHERE c.clinic_id IS NULL""") == 0
    assert scalar(con, """SELECT COUNT(*) FROM raw_fact_message_log m LEFT JOIN stg_appointment a USING (appointment_id)
                          WHERE a.appointment_id IS NULL""") == 0
    assert scalar(con, """SELECT COUNT(*) FROM stg_appointment a WHERE rescheduled_from_appointment_id IS NOT NULL
                          AND rescheduled_from_appointment_id NOT IN (SELECT appointment_id FROM stg_appointment)""") == 0


def test_status_normalized(con):
    assert scalar(con, "SELECT COUNT(*) FROM stg_appointment WHERE status = 'unknown'") == 0
    assert scalar(con, "SELECT COUNT(DISTINCT status) FROM stg_appointment") == 5
    assert scalar(con, "SELECT COUNT(DISTINCT status) FROM raw_fact_appointment") > 5


def test_rescheduled_parents_not_no_show(con):
    assert scalar(con, """SELECT COUNT(*) FROM stg_appointment p
                          JOIN stg_appointment c ON c.rescheduled_from_appointment_id = p.appointment_id
                          WHERE p.status <> 'rescheduled'""") == 0


def test_assignment_dedup(con, truth):
    raw = scalar(con, "SELECT COUNT(*) FROM raw_fact_experiment_assignment")
    dedup = scalar(con, "SELECT COUNT(*) FROM stg_assignment")
    assert raw - dedup == truth["realized"]["duplicate_assignment_rows"]


def test_null_thresholds(con):
    share = scalar(con, "SELECT AVG(CASE WHEN delivery_status IS NULL THEN 1.0 ELSE 0 END) FROM raw_fact_message_log")
    assert 0.01 < share < 0.03
    assert scalar(con, "SELECT COUNT(*) FROM stg_message WHERE delivery_status IS NULL") == 0
    for col in ["patient_id", "clinic_id", "scheduled_at", "status"]:
        assert scalar(con, f"SELECT COUNT(*) FROM stg_appointment WHERE {col} IS NULL") == 0


def test_timezone_conversion(con):
    # one-way reminders are scheduled 48 h before the visit; after conversion the median is 48 h in both zones
    for tz in ["America/Chicago", "America/New_York"]:
        med = scalar(con, f"""SELECT MEDIAN(hours_before_appt) FROM stg_message
                              WHERE channel = 'sms_one_way' AND timezone = '{tz}'""")
        assert abs(med - 48) < 0.2, tz


def test_lead_time_errors_flagged(con, truth):
    n = scalar(con, "SELECT SUM(CAST(booked_after_scheduled_flag AS INT)) FROM stg_appointment")
    assert n == truth["realized"]["booked_after_scheduled_rows"]
    assert scalar(con, "SELECT COUNT(*) FROM stg_appointment WHERE lead_time_days < 0") == 0


def test_slot_universe_rates_sum(con):
    bad = scalar(con, """SELECT COUNT(*) FROM fct_appointment_outcome
                         WHERE is_unfilled = 1 AND NOT (is_no_show = 1 OR is_late_cancel = 1)""")
    assert bad == 0
