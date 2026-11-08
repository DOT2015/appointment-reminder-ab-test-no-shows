-- Staging: dimensions. Trim/standardize text; no business logic.
-- Portable to PostgreSQL (DROP/CREATE TABLE AS, ANSI functions).

DROP TABLE IF EXISTS stg_clinic;
CREATE TABLE stg_clinic AS
SELECT
    TRIM(clinic_id)              AS clinic_id,
    clinic_name,
    LOWER(TRIM(specialty))       AS specialty,
    region,
    timezone,                    -- IANA name; 3 clinics are America/Chicago, the rest America/New_York
    CAST(has_waitlist AS BOOLEAN) AS has_waitlist
FROM raw_dim_clinic;

DROP TABLE IF EXISTS stg_patient;
CREATE TABLE stg_patient AS
SELECT
    TRIM(patient_id)             AS patient_id,
    age_band,
    sex,
    LOWER(TRIM(payer_type))      AS payer_type,
    zip3,
    preferred_language,
    CAST(sms_opt_in AS BOOLEAN)  AS sms_opt_in
FROM raw_dim_patient;

DROP TABLE IF EXISTS stg_provider;
CREATE TABLE stg_provider AS
SELECT TRIM(provider_id) AS provider_id, TRIM(clinic_id) AS clinic_id, LOWER(specialty) AS specialty
FROM raw_dim_provider;
