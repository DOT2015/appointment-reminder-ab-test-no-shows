"""Export a Power BI star schema (CSV) from DuckDB to powerbi/csv/, and a data/sample/ extract.

Full exports exceed 10 MB, so powerbi/csv/ is gitignored; `make powerbi` recreates it.
data/sample/ holds up to 1,000 rows of each raw table (committed).
"""
from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
OUT = ROOT / "powerbi" / "csv"
SAMPLE = ROOT / "data" / "sample"

QUERIES = {
    "dim_patient": "SELECT * FROM stg_patient",
    "dim_clinic": "SELECT * FROM stg_clinic",
    "dim_provider": "SELECT * FROM stg_provider",
    "dim_date": """
        SELECT CAST(d AS DATE) AS date_key, EXTRACT(year FROM d) AS year, EXTRACT(month FROM d) AS month,
               EXTRACT(isodow FROM d) AS iso_dow, CAST(d AS DATE) BETWEEN DATE '2025-03-03' AND DATE '2025-06-29' AS in_experiment
        FROM generate_series(TIMESTAMP '2024-01-01', TIMESTAMP '2025-12-31', INTERVAL 1 DAY) t(d)""",
    "fact_appointment": """
        SELECT appointment_id, patient_id, clinic_id, provider_id, scheduled_date AS date_key, lead_time_band, status,
               in_slot_universe, is_no_show, is_late_cancel, late_cancel_refilled, is_unfilled
        FROM fct_appointment_outcome""",
    "fact_experiment_appointment": """
        SELECT e.appointment_id, e.patient_id, e.clinic_id, e.scheduled_date AS date_key, e.variant, e.treat,
               e.in_slot_universe, e.is_no_show, e.is_late_cancel, e.late_cancel_refilled, e.is_unfilled,
               e.pre_no_show_rate, (x.clinic_id IS NOT NULL) AS srm_excluded
        FROM mart_experiment_appointment e
        LEFT JOIN ref_srm_exclusion x ON x.clinic_id = e.clinic_id_at_assignment
              AND e.assigned_date_local BETWEEN x.date_from AND x.date_to""",
}


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, q in QUERIES.items():
        con.execute(f"COPY ({q}) TO '{OUT / (name + '.csv')}' (HEADER, DELIMITER ',')")
    SAMPLE.mkdir(parents=True, exist_ok=True)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'raw_%'").fetchall():
        name = t[4:]
        con.execute(f"COPY (SELECT * FROM {t} USING SAMPLE 1000 ROWS (reservoir, 42)) "
                    f"TO '{SAMPLE / (name + '.csv')}' (HEADER, DELIMITER ',')")
    size = sum(f.stat().st_size for f in OUT.glob("*.csv")) / 1e6
    print(f"powerbi/csv: {len(QUERIES)} tables, {size:.1f} MB; data/sample refreshed")


if __name__ == "__main__":
    main()
