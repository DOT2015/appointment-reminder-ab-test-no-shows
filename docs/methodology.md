# Methodology

All data is synthetic (seed 42). This document covers the methods, assumptions, and limitations. The pre-registered plan is in [experiment_design.md](experiment_design.md).

## Pipeline

`make all` runs `generate -> load -> clean -> analyze -> figures -> dashboard -> report -> powerbi -> sample`. The SQL runs in DuckDB and is written in ANSI style (CTEs, window functions, `AT TIME ZONE`, `DROP TABLE IF EXISTS` + `CREATE TABLE AS`) so it ports to PostgreSQL. One DuckDB-specific idiom remains: `read_csv` in `src/load.py`. In PostgreSQL, use `COPY` instead.

## Estimators

**Difference in proportions with clustered SEs.** The model is OLS of the 0/1 appointment outcome on a treatment indicator. This gives the same point estimate as the difference in rates. The standard errors are cluster-robust (CR1, statsmodels `cov_type="cluster"`) by patient, because a patient's appointments are correlated. The realized design effect is (clustered SE / iid SE)^2.

**CUPED.** The model adds the centred 2024 patient no-show rate plus an indicator for no 2024 history (with the pooled mean imputed). This is the regression form of CUPED (Deng et al., 2013), and it handles the missing-covariate case. Variance reduction = 1 - (SE_cuped / SE_raw)^2. Reduction at the appointment level can exceed the patient-level rho^2, because patients with more appointments also have more pre-period history. That makes their covariate more reliable, and they carry more weight.

**SRM.**
1. Overall chi-square against 50/50.
2. Binomial test per clinic x ISO-week cell, with Benjamini-Hochberg. A cell is flagged at q < 0.01.
3. For a flagged clinic, the longest run of days with control assignments and zero treatment assignments is found. Days with no assignments at all do not break a run, because assignment happens 72 h before a weekday visit, so Wednesdays and Thursdays have none.
4. Cross-check: patients who received two-way (treatment-only) texts but have no assignment row. This found 81 of the 93 dropped patients. The other 12 cancelled or rescheduled before any two-way text was sent.

Why the overall test passes: the gap removed 93 of about 15,600 treatment patients. To reach p < 0.001 overall, about 3.29 x sqrt(N) ≈ 580 patients would have to be missing. This is the main reason to scan by segment.

**Segments.** For each dimension, one interaction model: `is_no_show ~ treat * C(segment) + CUPED covariate`, with patient-clustered SEs. BH is applied across all interaction terms of all four dimensions (q < 0.10). A second model includes payer and language interactions together, to test whether the language effect survives once payer is controlled for.

**Sizing.** Net value = -effect_unfilled x annual slot appointments x $160 - (incremental messages per scheduled appointment x annual scheduled appointments x $0.04 + $18,000). Net value is linear in the effect, so the 95% CI comes straight from the effect's CI. The volume input (2024, opted-in patients) is treated as fixed.

**Power.** Normal approximation for two proportions, inflated by the design effect 1 + (m - 1) x ICC. Achieved power uses the realized n per arm and the realized design effect. The implied ICC is reported from the clustered/iid SE ratio, using the size-weighted mean cluster size.

## Assumptions

- Treatment changes no-shows, late cancels, and refills. It does not change early cancellations or reschedule rates. The generator holds those fixed, although a real reschedule link might raise reschedules.
- Each refilled slot earns the full contribution margin. This is an upper bound if waitlists are thin.
- Annual volume equals 2024 volume. The generator has no growth.

## Limitations

- Synthetic data. The effect sizes, propensity distribution, and costs are assumptions chosen for the exercise.
- Waitlists are shared across arms within a clinic (possible interference, discussed in the design doc).
- The analysis unit for the slot universe is the appointment. Patient-level outcomes, such as care continuity, are not measured.
- Self-pay is 5% of patients, so its CI is wide. The targeted-rollout comparison depends mostly on Medicaid.
- The realized no-show effect in the generated data (-2.70 pp) is larger than the generator parameter (-1.90 pp). The README Validation section explains this sampling variation. The pipeline is validated against the realized values, as the project convention requires.
