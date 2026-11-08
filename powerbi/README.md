# Power BI model

`make powerbi` (part of `make all`) writes a star schema to `powerbi/csv/`. The full export is about 37 MB, so it is gitignored and rebuilt from the generator. No `.pbix` file is committed.

## Tables

| Table | Grain | Key |
|---|---|---|
| fact_appointment | appointment (2024-2025) | appointment_id |
| fact_experiment_appointment | appointment in the experiment window, for assigned patients | appointment_id |
| dim_patient | patient | patient_id |
| dim_clinic | clinic | clinic_id |
| dim_provider | provider | provider_id |
| dim_date | day | date_key |

## Load

1. Get Data > Text/CSV, and load each file from `powerbi/csv/`.
2. Model view relationships (single direction, many-to-one):
   - fact_* `patient_id` -> dim_patient `patient_id`
   - fact_* `clinic_id` -> dim_clinic `clinic_id`
   - fact_appointment `provider_id` -> dim_provider `provider_id`
   - fact_* `date_key` -> dim_date `date_key` (mark dim_date as the date table)
3. Set `in_slot_universe`, `srm_excluded`, and `treat` to True/False type.

## DAX measures

```DAX
Slot Appts = CALCULATE ( COUNTROWS ( fact_experiment_appointment ),
    fact_experiment_appointment[in_slot_universe] = TRUE (), fact_experiment_appointment[srm_excluded] = FALSE () )

No-Show Rate = DIVIDE (
    CALCULATE ( SUM ( fact_experiment_appointment[is_no_show] ),
        fact_experiment_appointment[in_slot_universe] = TRUE (), fact_experiment_appointment[srm_excluded] = FALSE () ),
    [Slot Appts] )

Unfilled Slot Rate = DIVIDE (
    CALCULATE ( SUM ( fact_experiment_appointment[is_unfilled] ),
        fact_experiment_appointment[in_slot_universe] = TRUE (), fact_experiment_appointment[srm_excluded] = FALSE () ),
    [Slot Appts] )

Late Cancel Rate = DIVIDE (
    CALCULATE ( SUM ( fact_experiment_appointment[is_late_cancel] ),
        fact_experiment_appointment[in_slot_universe] = TRUE (), fact_experiment_appointment[srm_excluded] = FALSE () ),
    [Slot Appts] )

No-Show Effect (pp) =
    100 * ( CALCULATE ( [No-Show Rate], fact_experiment_appointment[variant] = "treatment" )
          - CALCULATE ( [No-Show Rate], fact_experiment_appointment[variant] = "control" ) )
```

These measures give point estimates. The clustered and CUPED confidence intervals come from `src/analysis.py` (`reports/results.json`) and are not recomputed in DAX.
