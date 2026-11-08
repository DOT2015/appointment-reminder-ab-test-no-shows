# Experiment Design (pre-registered)

Status: written and frozen before any experiment-period outcome was queried. The numbers in this document are design-time assumptions. Realized values appear in the README and `reports/results.json`, and `tests/test_validation.py` checks that the power calculation in the pipeline reproduces the figures below.

All data is synthetic. The network, stakeholder, and economics are simulated.

## 1. Question and decision

**Question.** Does a two-way SMS reminder (72 h and 24 h before the visit, with a one-tap reschedule link) reduce no-shows and unfilled slots compared with today's one-way SMS at 48 h?

**Decision owner.** Director of Ambulatory Access (simulated 24-clinic network).

**Options.** (a) Roll out network-wide, (b) roll out to targeted payer segments, (c) stop.

## 2. Variants and randomization

| | Control | Treatment |
|---|---|---|
| Message | One-way SMS at 48 h | Two-way SMS at 72 h and 24 h; replies C (confirm), R (reschedule link), X (cancel) |
| Who | SMS-opted-in patients with an appointment in the window | same |

- **Unit of randomization: patient.** Each patient is assigned once, 72 hours before their first appointment in the window. Every later appointment in the window inherits that variant, including appointments created by rescheduling. Appointment-level randomization would let the same patient see both experiences.
- **Split:** 50/50, by hash.
- **Window:** appointments scheduled 2025-03-03 through 2025-06-29 (17 weeks). Calendar 2024 is the pre-period, used for the CUPED covariate.
- **Duplicate assignment rows:** if the log holds more than one row for a patient, the earliest `assigned_at` wins.

## 3. Metrics

All rates use the **slot universe**: appointments that reached the visit day without an early (24 h or more) cancellation or a reschedule, i.e. status in completed, no_show, late_cancel. Early cancellations and reschedules release the slot with time to rebook, so they are not failures of the reminder.

| Role | Metric | Definition |
|---|---|---|
| Primary | No-show rate | no_show / slot universe |
| Decision metric for value | Unfilled-slot rate | (no_show + late_cancel not refilled) / slot universe |
| Guardrail | Late-cancel rate | late_cancel (under 24 h) / slot universe |
| Diagnostic | Refill rate | refilled late cancels / late cancels |
| Health | Delivery rate | delivered messages / messages sent (NULL status = not delivered) |

**Why two outcome metrics.** The no-show rate is the metric the access team already tracks, so it is primary for comparability. But the reminder is expected to turn some no-shows into late cancels. A late cancel can be refilled from a waitlist, and a no-show cannot. The unfilled-slot rate measures the thing that costs money (an empty slot), so it drives the value estimate and the rollout decision. If late cancels rise while unfilled slots fall, the reminder is working as intended. The late-cancel guardrail fails only if unfilled slots do not fall.

## 4. Power and sample size

Inputs: baseline no-show rate 13.4% (2024), minimum detectable effect (MDE) 1.5 pp absolute (13.4% to 11.9%), alpha 0.05 two-sided, power 0.80.

Unclustered, per arm:

n = (z_0.975 + z_0.80)^2 x [p1(1 - p1) + p2(1 - p2)] / MDE^2 = 7.85 x (0.1160 + 0.1048) / 0.000225 ≈ **7,700 appointments per arm**

Clustering: outcomes are appointments, but randomization is by patient. Assuming 2.6 appointments per patient in the window and ICC = 0.15, the design effect is 1 + (2.6 - 1) x 0.15 = **1.24**. That gives **≈ 9,600 appointments per arm**.

Expected supply: about 27,000 appointments per arm among opted-in patients over 17 weeks. That covers the overall test with room to spare, and it supports the planned payer segments. The smallest segment, self-pay at 5%, is expected to have wide intervals and is reported descriptively.

## 5. Analysis plan

1. **Assignment health before any outcome is looked at.**
   - Overall SRM: chi-square goodness of fit against 50/50. Alarm at p < 0.001.
   - Localized SRM: binomial test per clinic x ISO week, Benjamini-Hochberg across cells, flag at q < 0.01. Flagged cells are traced to days. If a logging gap is confirmed (for example, by treatment-only messages with no assignment row), every patient assigned in that clinic-window is excluded from **both** arms, and the split is re-tested.
2. **Primary estimate.** Difference in no-show rate (treatment minus control) from OLS on appointment-level 0/1 outcomes with patient-clustered standard errors. Report pp, 95% CI, and relative change.
3. **CUPED.** Covariate = patient's 2024 no-show rate on slot appointments. Patients with no 2024 history get the pooled mean plus a missing-history indicator. Report the variance reduction achieved. The CUPED estimate is the headline when it is available.
4. **Guardrails.** Same estimator for late-cancel, refill, and unfilled-slot rates.
5. **Segments (planned).** Payer (hypothesis: larger effect for Medicaid and self-pay, which have higher baselines), specialty, lead-time band (0-2, 3-7, 8-30, 31+ days), and preferred language. Each dimension gets a treatment x segment interaction model with clustered SEs. Benjamini-Hochberg across all interaction terms at q < 0.10. Any segment finding that is not pre-registered is labelled exploratory.
6. **Sizing.** Annual slot volume (2024, opted-in patients) x unfilled-slot effect x $160 margin, minus incremental messages x $0.04 and $18,000 per year platform cost. Computed for full-network and Medicaid + self-pay scopes, with 95% CIs carried through from the effect CI.

## 6. Decision rule (written in advance)

- **Roll out network-wide** if all of these hold: the SRM check passes after any documented exclusion; the 95% CI of the unfilled-slot effect is entirely below 0; and the lower 95% bound of full-network net annual value is above $0.
- **Targeted rollout (Medicaid + self-pay)** if the full-network condition fails but the targeted scope's lower bound of net value is above $0.
- **Stop** otherwise, or if delivery rate falls below 95% in either arm without an explanation.

## 7. Known risks

- A reschedule creates a new appointment ID. The original must count as rescheduled, not as a no-show.
- Message timestamps are UTC, while appointment times are clinic-local. Three clinics are on Central time.
- The SMS vendor reports a NULL delivery status for some messages. These count as not delivered.
- Patients share waitlists across arms within a clinic, so treatment-arm refills could use waitlist capacity that control-arm cancellations would otherwise have used. With 50/50 patient-level randomization, this interference is expected to be small. It is noted as a limitation.
