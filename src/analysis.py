"""Experiment analysis: SRM detection, primary metric, guardrails, CUPED, segments, sizing, power.

Runs the SQL in sql/03_analysis/ against data/warehouse.duckdb, adds the statistics that SQL cannot do,
and writes reports/results.json plus small CSV tables in reports/tables/.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "warehouse.duckdb"
SQL = ROOT / "sql" / "03_analysis"
TABLES = ROOT / "reports" / "tables"
RESULTS = ROOT / "reports" / "results.json"

# Pre-registered design values (docs/experiment_design.md)
BASELINE, MDE, ALPHA, POWER = 0.134, 0.015, 0.05, 0.80
PLANNED_M, PLANNED_ICC = 2.6, 0.15
COST_PER_MSG, PLATFORM, MARGIN = 0.04, 18_000.0, 160.0
Z = stats.norm.ppf(0.975)


def run_sql(con, name: str, save: bool = True) -> pd.DataFrame:
    df = con.execute((SQL / name).read_text()).df()
    if save:
        df.to_csv(TABLES / name.replace(".sql", ".csv"), index=False)
    return df


def cluster_diff(df: pd.DataFrame, y: str, extra: str = "") -> dict:
    """Difference in means (treatment - control) via OLS with patient-clustered SEs."""
    d = df.dropna(subset=[y])
    groups = pd.factorize(d.patient_id)[0]
    formula = f"{y} ~ treat" + (f" + {extra}" if extra else "")
    fit = smf.ols(formula, data=d).fit(cov_type="cluster", cov_kwds={"groups": groups})
    iid = smf.ols(formula, data=d).fit()
    b, se = fit.params["treat"], fit.bse["treat"]
    ctrl = d.loc[d.treat == 0, y].mean()
    return {"control": float(ctrl), "treatment": float(d.loc[d.treat == 1, y].mean()),
            "diff": float(b), "se": float(se), "ci_low": float(b - Z * se), "ci_high": float(b + Z * se),
            "p_value": float(fit.pvalues["treat"]), "se_iid": float(iid.bse["treat"]),
            "relative": float(b / ctrl) if ctrl else None, "n": int(len(d)),
            "n_patients": int(d.patient_id.nunique())}


def pp(x: dict) -> dict:
    """Convert a diff dict to percentage points for reporting."""
    out = dict(x)
    for k in ["control", "treatment", "diff", "se", "ci_low", "ci_high", "se_iid"]:
        out[k + "_pp"] = 100 * x[k]
    return out


def srm_detection(con, daily: pd.DataFrame) -> dict:
    n_c, n_t = int(daily.n_control.sum()), int(daily.n_treatment.sum())
    chi_overall = stats.chisquare([n_c, n_t])
    # clinic x ISO-week scan
    daily = daily.copy()
    daily["assigned_date"] = pd.to_datetime(daily.assigned_date)
    daily["week"] = daily.assigned_date - pd.to_timedelta(daily.assigned_date.dt.dayofweek, unit="D")
    wk = daily.groupby(["clinic_id", "week"], as_index=False)[["n_control", "n_treatment"]].sum()
    wk["n"] = wk.n_control + wk.n_treatment
    wk["p_value"] = [stats.binomtest(int(t), int(n), 0.5).pvalue if n > 0 else 1.0
                     for t, n in zip(wk.n_treatment, wk.n)]
    wk["q_value"] = multipletests(wk.p_value, method="fdr_bh")[1]
    wk["flagged"] = wk.q_value < 0.01
    wk.to_csv(TABLES / "srm_clinic_week_scan.csv", index=False)
    exclusions = []
    for clinic in wk.loc[wk.flagged, "clinic_id"].unique():
        flagged_weeks = wk.loc[wk.flagged & (wk.clinic_id == clinic), "week"]
        d = daily[daily.clinic_id == clinic].set_index("assigned_date").sort_index()[
            ["n_control", "n_treatment", "n_unlogged_two_way_patients"]]
        full = d.reindex(pd.date_range(d.index.min(), d.index.max()), fill_value=0)
        # longest run of days with control assignments and zero treatment assignments, overlapping a
        # flagged week. Days with no assignments at all (no appointments 72h later) do not break a run.
        state = np.where((full.n_treatment == 0) & (full.n_control > 0), 1,
                         np.where((full.n_treatment == 0) & (full.n_control == 0), 0, -1))
        runs, start, last_in = [], None, None
        for day, st in zip(full.index, state):
            if st == 1:
                start = day if start is None else start
                last_in = day
            elif st == -1 and start is not None:
                runs.append((start, last_in))
                start = None
        if start is not None:
            runs.append((start, last_in))
        runs = [r for r in runs if any((r[0] <= w + pd.Timedelta(days=6)) and (r[1] >= w) for w in flagged_weeks)]
        if runs:
            r = max(runs, key=lambda r: full.loc[r[0]:r[1], "n_control"].sum())
            cells = full.loc[r[0]:r[1]]
            exclusions.append({"clinic_id": clinic, "date_from": r[0].date().isoformat(),
                               "date_to": r[1].date().isoformat(), "days": int((r[1] - r[0]).days + 1),
                               "control_in_window": int(cells.n_control.sum()),
                               "treatment_in_window": int(cells.n_treatment.sum()),
                               "unlogged_two_way_patients": int(cells.n_unlogged_two_way_patients.sum()),
                               "cell_p_value": float(stats.binomtest(int(cells.n_treatment.sum()),
                                                                     int(cells.n_control.sum() + cells.n_treatment.sum()),
                                                                     0.5).pvalue)})
    ex = pd.DataFrame(exclusions, columns=["clinic_id", "date_from", "date_to"]) if exclusions else \
        pd.DataFrame({"clinic_id": pd.Series(dtype=str), "date_from": pd.Series(dtype=str), "date_to": pd.Series(dtype=str)})
    con.execute("DROP TABLE IF EXISTS ref_srm_exclusion")
    con.register("ex_df", ex[["clinic_id", "date_from", "date_to"]])
    con.execute("CREATE TABLE ref_srm_exclusion AS SELECT clinic_id, CAST(date_from AS DATE) AS date_from, "
                "CAST(date_to AS DATE) AS date_to FROM ex_df")
    con.unregister("ex_df")
    # re-check after exclusion
    keep = np.ones(len(daily), bool)
    for e in exclusions:
        keep &= ~((daily.clinic_id == e["clinic_id"]) & (daily.assigned_date >= e["date_from"])
                  & (daily.assigned_date <= e["date_to"]))
    n_c2, n_t2 = int(daily.loc[keep, "n_control"].sum()), int(daily.loc[keep, "n_treatment"].sum())
    chi_after = stats.chisquare([n_c2, n_t2])
    # clinic-level heterogeneity test (all clinics, whole window) before and after
    cl = daily.groupby("clinic_id")[["n_control", "n_treatment"]].sum()
    cl2 = daily[keep].groupby("clinic_id")[["n_control", "n_treatment"]].sum()
    het_before = stats.chi2_contingency(cl.values)
    het_after = stats.chi2_contingency(cl2.values)
    unlogged_total = int(daily.n_unlogged_two_way_patients.sum())
    return {
        "overall_before": {"control": n_c, "treatment": n_t, "treatment_share": n_t / (n_c + n_t),
                           "chi2": float(chi_overall.statistic), "p_value": float(chi_overall.pvalue)},
        "clinic_heterogeneity_before": {"chi2": float(het_before[0]), "dof": int(het_before[2]),
                                        "p_value": float(het_before[1])},
        "clinic_week_cells": int(len(wk)), "flagged_cells": int(wk.flagged.sum()),
        "flagged_detail": wk[wk.flagged].assign(week=lambda x: x.week.dt.date.astype(str)).to_dict("records"),
        "exclusions": exclusions,
        "overall_after": {"control": n_c2, "treatment": n_t2, "treatment_share": n_t2 / (n_c2 + n_t2),
                          "chi2": float(chi_after.statistic), "p_value": float(chi_after.pvalue)},
        "clinic_heterogeneity_after": {"chi2": float(het_after[0]), "dof": int(het_after[2]),
                                       "p_value": float(het_after[1])},
        "unlogged_two_way_patients_total": unlogged_total,
        "min_detectable_drop_overall": float(stats.norm.ppf(0.9995) * np.sqrt(n_c + n_t)),
    }


def power_analysis(n_per_arm: int, m_bar: float, icc: float) -> dict:
    p1, p2 = BASELINE, BASELINE - MDE
    za, zb = stats.norm.ppf(1 - ALPHA / 2), stats.norm.ppf(POWER)
    n_simple = (za + zb) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / MDE ** 2
    de_plan = 1 + (PLANNED_M - 1) * PLANNED_ICC
    de_real = 1 + (m_bar - 1) * icc
    n_eff = n_per_arm / de_real
    se = np.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / n_eff)
    achieved = stats.norm.cdf(MDE / se - za)
    mde_80 = (za + zb) * se
    return {"baseline": BASELINE, "mde_pp": 100 * MDE, "alpha": ALPHA, "power": POWER,
            "n_per_arm_unclustered": float(n_simple), "planned_appts_per_patient": PLANNED_M,
            "planned_icc": PLANNED_ICC, "design_effect_planned": de_plan,
            "n_per_arm_clustered": float(n_simple * de_plan),
            "realized_slot_appts_per_arm": int(n_per_arm), "realized_appts_per_patient": float(m_bar),
            "realized_icc": float(icc), "design_effect_realized": float(de_real),
            "achieved_power_at_mde": float(achieved), "mde_at_80_power_pp": float(100 * mde_80)}


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    res: dict = {}

    # ---------------------------------------------------------- Q1 SRM
    daily = run_sql(con, "01_srm_and_assignment_health.sql")
    res["srm"] = srm_detection(con, daily)

    # ---------------------------------------------------------- analysis frame
    df = con.execute("""
        SELECT e.*
        FROM mart_experiment_appointment e
        LEFT JOIN ref_srm_exclusion x
               ON x.clinic_id = e.clinic_id_at_assignment
              AND e.assigned_date_local BETWEEN x.date_from AND x.date_to
        WHERE e.in_slot_universe AND x.clinic_id IS NULL
    """).df()
    for c in ["is_no_show", "is_late_cancel", "is_unfilled", "treat"]:
        df[c] = df[c].astype(float)
    df["late_cancel_refilled"] = df.late_cancel_refilled.astype(float)

    # ---------------------------------------------------------- Q2 primary
    prim_sql = run_sql(con, "02_primary_metric_by_variant.sql")
    primary = cluster_diff(df, "is_no_show")
    res["primary_no_show"] = pp(primary)
    sizes = df.groupby("patient_id").size()
    m_bar = float(sizes.mean())
    de_real = (primary["se"] / primary["se_iid"]) ** 2
    m_w = float((sizes ** 2).sum() / sizes.sum())  # size-weighted mean cluster size
    icc = max((de_real - 1) / (m_w - 1), 0.0)
    res["primary_sql_check"] = prim_sql.to_dict("records")

    # ---------------------------------------------------------- Q3 guardrails
    guard = run_sql(con, "03_guardrails_late_cancel_and_refill.sql")
    res["late_cancel"] = pp(cluster_diff(df, "is_late_cancel"))
    res["refill_of_late_cancels"] = pp(cluster_diff(df[df.is_late_cancel == 1], "late_cancel_refilled"))
    res["unfilled_slot"] = pp(cluster_diff(df, "is_unfilled"))
    res["delivery"] = guard[["variant", "messages_sent", "messages_per_appointment", "delivery_rate",
                             "status_unknown_rate"]].to_dict("records")

    # ---------------------------------------------------------- Q4 CUPED
    cup = run_sql(con, "04_cuped_inputs.sql", save=False)
    has = cup[cup.pre_appointments > 0]
    rho = float(np.corrcoef(has.pre_no_show_rate, has.exp_no_show_rate)[0, 1])
    pooled_pre = float(has.pre_no_show_rate.mean())
    df["no_pre"] = df.pre_no_show_rate.isna().astype(float)
    df["x_pre"] = df.pre_no_show_rate.fillna(pooled_pre)
    df["x_pre_c"] = df.x_pre - df.x_pre.mean()
    cuped = cluster_diff(df, "is_no_show", "x_pre_c + no_pre")
    cuped_unf = cluster_diff(df, "is_unfilled", "x_pre_c + no_pre")
    res["cuped_no_show"] = pp(cuped)
    res["cuped_no_show"]["variance_reduction"] = 1 - (cuped["se"] / primary["se"]) ** 2
    res["cuped_unfilled"] = pp(cuped_unf)
    res["cuped_unfilled"]["variance_reduction"] = 1 - (cuped_unf["se"] / res["unfilled_slot"]["se"]) ** 2
    res["cuped_rho_patient_level"] = rho
    res["cuped_rho_n_patients"] = int(len(has))
    res["share_patients_with_pre_period"] = float((cup.pre_appointments > 0).mean())
    # pre-period balance check (chance imbalance that CUPED corrects)
    bal = has.groupby("treat").pre_no_show_rate.mean()
    res["pre_period_balance"] = {"control_pre_rate": float(bal.loc[0]), "treatment_pre_rate": float(bal.loc[1]),
                                 "diff_pp": float(100 * (bal.loc[1] - bal.loc[0]))}

    # ---------------------------------------------------------- Q5 segments
    seg_sql = run_sql(con, "05_effect_by_segment.sql")
    seg_rows, inter_rows = [], []
    dims = {"payer": "payer_type", "specialty": "specialty", "lead_time_band": "lead_time_band",
            "language": "preferred_language"}
    for dim, col in dims.items():
        sub_all = df[df[col] != "unknown"]
        for level, sub in sub_all.groupby(col):
            for metric in ["is_no_show", "is_unfilled"]:
                r = cluster_diff(sub, metric, "x_pre_c + no_pre")
                seg_rows.append({"dimension": dim, "segment": level, "metric": metric, **pp(r)})
        groups = pd.factorize(sub_all.patient_id)[0]
        ref = sub_all[col].value_counts().index[0]
        fit = smf.ols(f"is_no_show ~ treat * C({col}, Treatment('{ref}')) + x_pre_c + no_pre",
                      data=sub_all).fit(cov_type="cluster", cov_kwds={"groups": groups})
        names = [n for n in fit.params.index if n.startswith("treat:")]
        joint = fit.wald_test(" , ".join(f"{n} = 0" for n in names), scalar=True)
        for n in names:
            inter_rows.append({"dimension": dim, "reference": ref, "term": n.split("[T.")[-1].rstrip("]"),
                               "coef_pp": 100 * fit.params[n], "se_pp": 100 * fit.bse[n],
                               "p_value": float(fit.pvalues[n]), "joint_p_value": float(joint.pvalue)})
    # is the language interaction explained by payer mix? (Spanish speakers are more often Medicaid)
    groups = pd.factorize(df.patient_id)[0]
    fit_lp = smf.ols("is_no_show ~ treat * C(payer_type, Treatment('commercial')) "
                     "+ treat * C(preferred_language, Treatment('English')) + x_pre_c + no_pre",
                     data=df).fit(cov_type="cluster", cov_kwds={"groups": groups})
    lang_terms = [n for n in fit_lp.params.index if n.startswith("treat:C(preferred_language")]
    res["language_given_payer"] = [{"term": n.split("[T.")[-1].rstrip("]"), "coef_pp": 100 * fit_lp.params[n],
                                    "p_value": float(fit_lp.pvalues[n])} for n in lang_terms]
    seg = pd.DataFrame(seg_rows)
    inter = pd.DataFrame(inter_rows)
    inter["q_value_bh"] = multipletests(inter.p_value, method="fdr_bh")[1]
    inter["significant_q10"] = inter.q_value_bh < 0.10
    seg.to_csv(TABLES / "segment_effects.csv", index=False)
    inter.to_csv(TABLES / "segment_interactions_bh.csv", index=False)
    res["segments"] = seg[["dimension", "segment", "metric", "control_pp", "treatment_pp", "diff_pp",
                           "ci_low_pp", "ci_high_pp", "p_value", "n"]].to_dict("records")
    res["interactions"] = inter.to_dict("records")
    res["interactions_significant"] = inter[inter.significant_q10][["dimension", "term", "coef_pp",
                                                                    "q_value_bh"]].to_dict("records")

    # ---------------------------------------------------------- Q6 sizing
    size_sql = run_sql(con, "06_rollout_value_sizing.sql")
    scopes = {"full_network": ["commercial", "medicare", "medicaid", "self_pay"],
              "medicaid_selfpay_only": ["medicaid", "self_pay"]}
    sizing = []
    for _, row in size_sql.iterrows():
        sub = df[df.payer_type.isin(scopes[row.scope])]
        eff = cluster_diff(sub, "is_unfilled", "x_pre_c + no_pre")
        eff_ns = cluster_diff(sub, "is_no_show", "x_pre_c + no_pre")
        vol = row.annual_slot_appointments
        cost = row.annual_cost

        def net(e):
            return -e * vol * MARGIN - cost
        sizing.append({
            "scope": row.scope, "annual_slot_appointments": int(vol),
            "annual_scheduled_appointments": int(row.annual_scheduled_appointments),
            "unfilled_effect_pp_raw_sql": 100 * row.unfilled_effect,
            "unfilled_effect_pp": 100 * eff["diff"], "unfilled_ci_pp": [100 * eff["ci_low"], 100 * eff["ci_high"]],
            "slots_recovered": -eff["diff"] * vol,
            "slots_recovered_ci": [-eff["ci_high"] * vol, -eff["ci_low"] * vol],
            "gross_value": -eff["diff"] * vol * MARGIN, "annual_cost": float(cost),
            "net_value": net(eff["diff"]), "net_value_ci": [net(eff["ci_high"]), net(eff["ci_low"])],
            "net_value_no_show_only": net(eff_ns["diff"]),
            "break_even_unfilled_pp": -100 * cost / (vol * MARGIN),
        })
    res["sizing"] = sizing
    full = next(s for s in sizing if s["scope"] == "full_network")
    tgt = next(s for s in sizing if s["scope"] == "medicaid_selfpay_only")
    res["sizing_incremental_full_vs_targeted"] = full["net_value"] - tgt["net_value"]
    pd.DataFrame(sizing).to_csv(TABLES / "rollout_sizing.csv", index=False)

    # ---------------------------------------------------------- power
    n_per_arm = int(df.groupby("treat").size().mean())
    res["power"] = power_analysis(n_per_arm, m_bar, icc)
    res["power"]["realized_size_weighted_cluster"] = m_w

    # ---------------------------------------------------------- data quality summary
    dq = con.execute("""
        SELECT
          (SELECT COUNT(*) FROM raw_fact_appointment)                                        AS appointments,
          (SELECT COUNT(DISTINCT status) FROM raw_fact_appointment)                          AS raw_status_codes,
          (SELECT SUM(CAST(status_corrected_flag AS INT)) FROM stg_appointment)              AS status_corrected,
          (SELECT SUM(CAST(booked_after_scheduled_flag AS INT)) FROM stg_appointment)        AS booked_after_scheduled,
          (SELECT COUNT(*) FROM raw_fact_experiment_assignment)                              AS assignment_rows,
          (SELECT COUNT(*) FROM stg_assignment)                                              AS assigned_patients,
          (SELECT SUM(CAST(had_conflicting_variants AS INT)) FROM stg_assignment)            AS conflicting_patients,
          (SELECT COUNT(*) FROM raw_fact_message_log)                                        AS messages,
          (SELECT SUM(CASE WHEN delivery_status IS NULL THEN 1 ELSE 0 END) FROM raw_fact_message_log) AS null_delivery
    """).df().iloc[0].to_dict()
    tz = con.execute("""
        SELECT timezone, channel,
               MEDIAN(hours_before_appt) AS median_hours_corrected,
               MEDIAN(hours_before_appt_naive) AS median_hours_naive
        FROM stg_message WHERE channel = 'sms_one_way' GROUP BY timezone, channel ORDER BY timezone
    """).df()
    res["data_quality"] = {k: int(v) for k, v in dq.items()}
    res["data_quality"]["tz_check"] = tz.to_dict("records")

    # ---------------------------------------------------------- decision rule (pre-registered)
    u, n = res["cuped_unfilled"], res["cuped_no_show"]
    srm_ok = res["srm"]["overall_after"]["p_value"] >= 0.001
    rules = {
        "srm_passes_after_exclusion": bool(srm_ok),
        "unfilled_ci_below_zero": bool(u["ci_high"] < 0),
        "no_show_ci_below_zero": bool(n["ci_high"] < 0),
        "full_rollout_net_value_lower_ci_positive": bool(full["net_value_ci"][0] > 0),
        "targeted_net_value_lower_ci_positive": bool(tgt["net_value_ci"][0] > 0),
        "delivery_rate_above_95pct": bool(min(r["delivery_rate"] for r in res["delivery"]) > 0.95),
    }
    if srm_ok and rules["unfilled_ci_below_zero"] and rules["full_rollout_net_value_lower_ci_positive"]:
        decision = "roll out network-wide"
    elif srm_ok and rules["targeted_net_value_lower_ci_positive"]:
        decision = "roll out to Medicaid and self-pay only"
    else:
        decision = "stop"
    res["decision_rules"] = rules
    res["decision"] = decision

    RESULTS.write_text(json.dumps(res, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"decision: {decision}")
    print(f"no-show raw {primary['diff']*100:.2f}pp, CUPED {cuped['diff']*100:.2f}pp, "
          f"VR {res['cuped_no_show']['variance_reduction']:.1%}, rho {rho:.3f}")
    print(f"unfilled {res['unfilled_slot']['diff_pp']:.2f}pp; SRM before p={res['srm']['overall_before']['p_value']:.3g}, "
          f"exclusions {res['srm']['exclusions']}")


if __name__ == "__main__":
    main()
