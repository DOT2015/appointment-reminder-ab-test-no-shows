"""Fill README.md and docs/executive_summary.md from reports/results.json and data/truth/planted_effects.json.

Every number in those two documents comes from this script; templates live in docs/templates/.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "docs" / "templates"
PAYER_LABEL = {"commercial": "Commercial", "medicare": "Medicare", "medicaid": "Medicaid", "self_pay": "Self-pay"}


def f1(x):
    return f"{x:.1f}"


def f2(x):
    return f"{x:.2f}"


def signed(x, d=1):
    return f"{x:+.{d}f}"


def money(x):
    return f"${x:,.0f}"


def kmoney(x):
    return f"${x / 1e3:,.0f}K"


def ci(r, d=1):
    return f"{r['ci_low_pp']:+.{d}f} to {r['ci_high_pp']:+.{d}f}"


def inside(v, r):
    return "yes" if r["ci_low_pp"] <= v <= r["ci_high_pp"] else "no"


def build_context(res: dict, truth: dict) -> dict:
    P, T = truth["parameters"], truth["realized"]
    ns, unf, lc, rf = res["cuped_no_show"], res["cuped_unfilled"], res["late_cancel"], res["refill_of_late_cancels"]
    seg = {(s["dimension"], s["segment"], s["metric"]): s for s in res["segments"]}
    srm = res["srm"]
    ex = srm["exclusions"][0] if srm["exclusions"] else None
    sz = {s["scope"]: s for s in res["sizing"]}
    full, tgt = sz["full_network"], sz["medicaid_selfpay_only"]
    pw = res["power"]
    dq = res["data_quality"]
    inter = {(i["dimension"], i["term"]): i for i in res["interactions"]}
    lang = {r["term"]: r for r in res["language_given_payer"]}
    tz = {r["timezone"]: r for r in dq["tz_check"]}

    c = {
        "decision": res["decision"],
        "ns_drop": f2(abs(ns["diff_pp"])), "unf_drop": f2(abs(unf["diff_pp"])), "lc_rise": f2(abs(lc["diff_pp"])),
        "ns_rel_abs": f"{abs(100 * ns['diff'] / ns['control']):.0f}",
        "ns_c": f1(ns["control_pp"]), "ns_t": f1(ns["treatment_pp"]), "ns_d": signed(ns["diff_pp"], 2),
        "ns_ci": ci(ns, 2), "ns_rel": f"{100 * ns['diff'] / ns['control']:.0f}",
        "ns_raw_d": signed(res["primary_no_show"]["diff_pp"], 2), "ns_raw_ci": ci(res["primary_no_show"], 2),
        "unf_c": f1(unf["control_pp"]), "unf_t": f1(unf["treatment_pp"]), "unf_d": signed(unf["diff_pp"], 2),
        "unf_ci": ci(unf, 2), "unf_raw_d": signed(res["unfilled_slot"]["diff_pp"], 2),
        "lc_c": f1(lc["control_pp"]), "lc_t": f1(lc["treatment_pp"]), "lc_d": signed(lc["diff_pp"], 2),
        "lc_ci": ci(lc, 2), "lc_rel": f"{100 * lc['diff'] / lc['control']:.0f}",
        "rf_c": f"{rf['control_pp']:.0f}", "rf_t": f"{rf['treatment_pp']:.0f}", "rf_d": signed(rf["diff_pp"], 1),
        "rf_ci": ci(rf, 1),
        "vr": f"{100 * ns['variance_reduction']:.0f}",
        "vr_sample": f"{100 * (1 / (1 - ns['variance_reduction']) - 1):.0f}", "vr_unf": f"{100 * unf['variance_reduction']:.0f}",
        "pre_c": f1(100 * res["pre_period_balance"]["control_pre_rate"]),
        "pre_t": f1(100 * res["pre_period_balance"]["treatment_pre_rate"]),
        "rho": f2(res["cuped_rho_patient_level"]), "rho_n": f"{res['cuped_rho_n_patients']:,}",
        "pre_share": f"{100 * res['share_patients_with_pre_period']:.0f}",
        "srm_p_before": f2(srm["overall_before"]["p_value"]),
        "srm_share_before": f"{100 * srm['overall_before']['treatment_share']:.2f}",
        "srm_n_c": f"{srm['overall_before']['control']:,}", "srm_n_t": f"{srm['overall_before']['treatment']:,}",
        "srm_p_after": f2(srm["overall_after"]["p_value"]),
        "srm_share_after": f"{100 * srm['overall_after']['treatment_share']:.2f}",
        "srm_het_p_before": f"{srm['clinic_heterogeneity_before']['p_value']:.2f}",
        "srm_cells": f"{srm['clinic_week_cells']:,}", "srm_flagged": str(srm["flagged_cells"]),
        "srm_min_drop": f"{srm['min_detectable_drop_overall']:,.0f}",
        "srm_clinic": ex["clinic_id"] if ex else "none", "srm_from": ex["date_from"] if ex else "-",
        "srm_to": ex["date_to"] if ex else "-", "srm_days": str(ex["days"]) if ex else "0",
        "srm_ex_c": str(ex["control_in_window"]) if ex else "0",
        "srm_ex_t": str(ex["treatment_in_window"]) if ex else "0",
        "srm_cell_p": f"{ex['cell_p_value']:.0e}" if ex else "-",
        "srm_unlogged": str(ex["unlogged_two_way_patients"]) if ex else "0",
        "full_net": kmoney(full["net_value"]), "full_lo": kmoney(full["net_value_ci"][0]),
        "full_hi": kmoney(full["net_value_ci"][1]), "full_slots": f"{full['slots_recovered']:,.0f}",
        "full_slots_lo": f"{full['slots_recovered_ci'][0]:,.0f}", "full_slots_hi": f"{full['slots_recovered_ci'][1]:,.0f}",
        "full_cost": kmoney(full["annual_cost"]), "full_vol": f"{full['annual_slot_appointments']:,}",
        "full_ns_only": kmoney(full["net_value_no_show_only"]),
        "full_breakeven": f2(abs(full["break_even_unfilled_pp"])),
        "tgt_net": kmoney(tgt["net_value"]), "tgt_lo": kmoney(tgt["net_value_ci"][0]),
        "tgt_hi": kmoney(tgt["net_value_ci"][1]), "tgt_slots": f"{tgt['slots_recovered']:,.0f}",
        "tgt_cost": kmoney(tgt["annual_cost"]), "tgt_eff": signed(tgt["unfilled_effect_pp"], 1),
        "incr_full": kmoney(res["sizing_incremental_full_vs_targeted"]),
        "n_unclustered": f"{pw['n_per_arm_unclustered']:,.0f}", "n_clustered": f"{pw['n_per_arm_clustered']:,.0f}",
        "de_plan": f2(pw["design_effect_planned"]), "n_real": f"{pw['realized_slot_appts_per_arm']:,}",
        "m_real": f2(pw["realized_appts_per_patient"]), "de_real": f2(pw["design_effect_realized"]),
        "icc_real": f2(pw["realized_icc"]), "power_real": f"{100 * pw['achieved_power_at_mde']:.0f}",
        "mde80": f2(pw["mde_at_80_power_pp"]),
        "dq_appts": f"{dq['appointments']:,}", "dq_codes": str(dq["raw_status_codes"]),
        "dq_corrected": f"{dq['status_corrected']:,}", "dq_bad_lead": f"{dq['booked_after_scheduled']:,}",
        "dq_assign_rows": f"{dq['assignment_rows']:,}", "dq_assigned": f"{dq['assigned_patients']:,}",
        "dq_conflict": f"{dq['conflicting_patients']:,}", "dq_msgs": f"{dq['messages']:,}",
        "dq_null_deliv": f"{dq['null_delivery']:,}",
        "dq_null_deliv_pct": f"{100 * dq['null_delivery'] / dq['messages']:.1f}",
        "tz_central_naive": f1(tz["America/Chicago"]["median_hours_naive"]),
        "tz_central_fixed": f1(tz["America/Chicago"]["median_hours_corrected"]),
        "tz_east_naive": f1(tz["America/New_York"]["median_hours_naive"]),
        "delivery_min": f"{100 * min(d['delivery_rate'] for d in res['delivery']):.1f}",
        "medicaid_inter": signed(inter[("payer", "medicaid")]["coef_pp"], 1),
        "medicaid_q": f"{inter[('payer', 'medicaid')]['q_value_bh']:.0e}",
        "spanish_inter": signed(inter[("language", "Spanish")]["coef_pp"], 1),
        "spanish_q": f2(inter[("language", "Spanish")]["q_value_bh"]),
        "spanish_adj": signed(lang["Spanish"]["coef_pp"], 1), "spanish_adj_p": f2(lang["Spanish"]["p_value"]),
        "n_sig": str(len(res["interactions_significant"])), "n_inter": str(len(res["interactions"])),
    }
    for p in PAYER_LABEL:
        s = seg[("payer", p, "is_no_show")]
        c[f"{p}_d"], c[f"{p}_ci"] = signed(s["diff_pp"], 1), ci(s, 1)
        c[f"{p}_c"] = f1(s["control_pp"])
    # validation table
    rows = []

    def vrow(name, planted, realized, r, d=2):
        rows.append(f"| {name} | {planted} | {signed(realized, d)} | {signed(r['diff_pp'], d)} ({ci(r, d)}) "
                    f"| {inside(realized, r)} |")
    vrow("No-show effect, all payers (pp)", signed(P["mix_weighted_effect_pp"], 2), T["effect_no_show_pp"], ns)
    for p, lab in PAYER_LABEL.items():
        vrow(f"No-show effect, {lab} (pp)", signed(P["effect_pp"][p], 2), T["by_payer"][p]["effect_pp"],
             seg[("payer", p, "is_no_show")])
    vrow("Late-cancel effect (pp)", signed(100 * (P["late_cancel"]["treatment"] - P["late_cancel"]["control"]), 2),
         T["effect_late_cancel_pp"], lc)
    vrow("Refill of late cancels, treatment minus control (pp)",
         signed(100 * (P["refill_late_cancel"]["treatment"] - P["refill_late_cancel"]["control"]), 1),
         100 * (T["by_variant"]["treatment"]["refill_late_cancel"] - T["by_variant"]["control"]["refill_late_cancel"]),
         rf, 1)
    vrow("Unfilled-slot effect (pp)", signed(P["unfilled_effect_pp"], 2), T["effect_unfilled_pp"], unf)
    rows.append(f"| Pre/post patient no-show correlation (rho) | about 0.55 | {T['rho_pre_vs_experiment']:.3f} | "
                f"{res['cuped_rho_patient_level']:.3f} | {'yes' if abs(T['rho_pre_vs_experiment'] - res['cuped_rho_patient_level']) < 0.02 else 'no'} |")
    b = P["srm_bug"]
    found = ex is not None and ex["clinic_id"] == b["clinic"] and ex["date_from"] == b["from"] and ex["date_to"] == b["to"]
    rows.append(f"| SRM logging gap: clinic and dates | {b['clinic']}, {b['from']} to {b['to']} | "
                f"{T['srm_treatment_rows_dropped']} treatment rows dropped | "
                f"{c['srm_clinic']}, {c['srm_from']} to {c['srm_to']} ({c['srm_unlogged']} unlogged patients found via message log) "
                f"| {'yes' if found else 'no'} |")
    rows.append(f"| Patients with conflicting duplicate assignments | 0.7% of patients | {T['duplicate_assignment_rows']} | "
                f"{dq['conflicting_patients']} | {'yes' if dq['conflicting_patients'] == T['duplicate_assignment_rows'] else 'no'} |")
    rows.append(f"| Rescheduled originals mis-coded as no-show | 60% of reschedules | {T['rescheduled_miscoded_as_no_show']:,} | "
                f"{dq['status_corrected']:,} corrected | partial: originals whose new booking fell after 2025-12-31 have no link |")
    c["validation_table"] = "\n".join(rows)
    c["truth_ns_c"] = f1(100 * T["by_variant"]["control"]["no_show"])
    c["truth_ns_t"] = f1(100 * T["by_variant"]["treatment"]["no_show"])
    c["truth_ns_eff"] = signed(T["effect_no_show_pp"], 2)
    c["truth_expected_eff"] = signed(T["expected_effect_given_latent"]["overall_pp"], 2)
    c["planted_eff"] = signed(P["mix_weighted_effect_pp"], 2)
    c["n_rows_appt"] = f"{T['rows']['fact_appointment']:,}"
    c["n_rows_msg"] = f"{T['rows']['fact_message_log']:,}"
    c["n_rows_assign"] = f"{T['rows']['fact_experiment_assignment']:,}"
    return c


def main():
    res = json.loads((ROOT / "reports" / "results.json").read_text())
    truth = json.loads((ROOT / "data" / "truth" / "planted_effects.json").read_text())
    ctx = build_context(res, truth)
    for tpl, out in [("README.md.tmpl", ROOT / "README.md"),
                     ("executive_summary.md.tmpl", ROOT / "docs" / "executive_summary.md")]:
        text = (TPL / tpl).read_text().format_map(ctx)
        out.write_text(text)
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
