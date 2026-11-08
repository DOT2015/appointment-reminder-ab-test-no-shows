"""Static PNG charts for the README and docs (matplotlib). Reads reports/results.json and reports/tables/."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
TABLES = ROOT / "reports" / "tables"

BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e5e4e0"
PAYER_LABEL = {"commercial": "Commercial", "medicare": "Medicare", "medicaid": "Medicaid", "self_pay": "Self-pay"}


def style():
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 160, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
        "axes.spines.right": False, "axes.titlelocation": "left", "axes.axisbelow": True, "text.color": INK, "legend.frameon": False,
    })


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def headline_forest(res):
    seg = pd.DataFrame(res["segments"])
    rows = [("All patients: no-show rate", res["cuped_no_show"], INK)]
    for p in ["commercial", "medicare", "medicaid", "self_pay"]:
        r = seg[(seg.dimension == "payer") & (seg.segment == p) & (seg.metric == "is_no_show")].iloc[0]
        rows.append((f"   {PAYER_LABEL[p]}: no-show rate", r, INK2))
    rows.append(("All patients: unfilled-slot rate", res["cuped_unfilled"], BLUE))
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    x_lab = max(r["ci_high_pp"] for _, r, _ in rows) + 0.4
    for i, (label, r, col) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.plot([r["ci_low_pp"], r["ci_high_pp"]], [y, y], color=col, lw=2, solid_capstyle="round")
        ax.plot(r["diff_pp"], y, "o", color=col, ms=8, mec="white", mew=1.5)
        ax.text(x_lab, y, f"{r['diff_pp']:+.1f} pp  [{r['ci_low_pp']:+.1f}, {r['ci_high_pp']:+.1f}]",
                va="center", fontsize=8.5, color=INK2)
    ax.set_xlim(right=x_lab + 2.6)
    ax.axvline(0, color=INK2, lw=1)
    ax.axvline(-res["power"]["mde_pp"], color=ORANGE, lw=1.2, ls="--")
    ax.text(-res["power"]["mde_pp"] - 0.1, len(rows) - 0.45, f"pre-registered MDE ({-res['power']['mde_pp']:.1f} pp)",
            color=ORANGE, fontsize=8.5, ha="right", va="bottom")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows][::-1])
    ax.set_ylim(-0.6, len(rows) - 0.1)
    ax.set_xlabel("Treatment effect, percentage points (95% CI, CUPED-adjusted, patient-clustered)")
    ax.set_title("Two-way SMS reminders cut no-shows and unfilled slots (simulated data)")
    ax.grid(axis="y", visible=False)
    save(fig, "01_headline_forest_plot.png")


def srm_chart(res):
    d = pd.read_csv(TABLES / "01_srm_and_assignment_health.csv", parse_dates=["assigned_date"])
    ex = res["srm"]["exclusions"][0]
    c = d[d.clinic_id == ex["clinic_id"]].set_index("assigned_date").sort_index()
    c = c.resample("D").sum(numeric_only=True)
    w = c[["n_control", "n_treatment"]].rolling(7, min_periods=1).sum()
    share = w.n_treatment / (w.n_control + w.n_treatment)
    net = d.groupby("assigned_date")[["n_control", "n_treatment"]].sum().rolling(7, min_periods=1).sum()
    net_share = net.n_treatment / net.sum(axis=1)
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    ax.axvspan(pd.Timestamp(ex["date_from"]), pd.Timestamp(ex["date_to"]) + pd.Timedelta(days=1),
               color=ORANGE, alpha=0.15, lw=0)
    ax.plot(net_share.index, 100 * net_share, color=GRAY, lw=1.5, label="Network (all 24 clinics)")
    ax.plot(share.index, 100 * share, color=BLUE, lw=2, label=f"Clinic {ex['clinic_id']}")
    ax.axhline(50, color=INK2, lw=0.8, ls=":")
    ax.text(pd.Timestamp(ex["date_to"]) + pd.Timedelta(days=9), 4,
            f"{ex['clinic_id']} {ex['date_from']} to {ex['date_to']}:\n{ex['treatment_in_window']} treatment vs "
            f"{ex['control_in_window']} control assignments logged", fontsize=8.5, color=INK2)
    ax.set_ylim(0, 75)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))
    ax.set_ylabel("Treatment share of assignments,\ntrailing 7 days (%)")
    ax.set_title("Assignment health: a logging gap at one clinic (overall split test alone missed it)")
    ax.legend(loc="lower left", fontsize=8.5)
    save(fig, "02_srm_clinic_gap.png")


def guardrail_chart(res):
    nsc, nst = res["primary_no_show"]["control_pp"], res["primary_no_show"]["treatment_pp"]
    unc, unt = res["unfilled_slot"]["control_pp"], res["unfilled_slot"]["treatment_pp"]
    lcc, lct = res["late_cancel"]["control_pp"], res["late_cancel"]["treatment_pp"]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.8), gridspec_kw={"width_ratios": [1, 1.25]})
    ax = axes[0]
    x = np.arange(2)
    ax.bar(x - 0.18, [lcc, nsc], 0.34, color=ORANGE, label="Control (one-way SMS, 48h)")
    ax.bar(x + 0.18, [lct, nst], 0.34, color=BLUE, label="Treatment (two-way SMS, 72h + 24h)")
    for xi, (a, b) in enumerate([(lcc, lct), (nsc, nst)]):
        ax.text(xi - 0.18, a + 0.3, f"{a:.1f}", ha="center", fontsize=8.5, color=INK2)
        ax.text(xi + 0.18, b + 0.3, f"{b:.1f}", ha="center", fontsize=8.5, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels(["Late-cancel rate", "No-show rate"])
    ax.set_ylabel("% of slot appointments")
    ax.set_title("Late cancels rose; no-shows fell")
    ax.legend(fontsize=8, loc="upper left")
    ax.set_ylim(0, max(nsc, lct) * 1.45)
    ax.grid(axis="x", visible=False)
    ax = axes[1]
    unref_c, unref_t = unc - nsc, unt - nst
    ax.barh([1], [nsc], color=ORANGE, height=0.5)
    ax.barh([1], [unref_c], left=[nsc], color=ORANGE, alpha=0.45, height=0.5)
    ax.barh([0], [nst], color=BLUE, height=0.5)
    ax.barh([0], [unref_t], left=[nst], color=BLUE, alpha=0.45, height=0.5)
    ax.text(unc + 0.3, 1, f"{unc:.1f}%", va="center", fontsize=9)
    ax.text(unt + 0.3, 0, f"{unt:.1f}%", va="center", fontsize=9)
    ax.grid(axis="x", visible=False)
    ax.text(nsc / 2, 1, "no-shows", ha="center", va="center", color="white", fontsize=8.5)
    ax.text(nsc + unref_c / 2, 1, "unrefilled\nlate cancels", ha="center", va="center", fontsize=7.5, color=INK)
    ax.text(nst / 2, 0, "no-shows", ha="center", va="center", color="white", fontsize=8.5)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Treatment", "Control"])
    ax.set_xlim(0, unc * 1.25)
    ax.set_xlabel("Unfilled-slot rate (% of slot appointments)")
    ax.set_title("Net: fewer empty slots")
    ax.grid(axis="y", visible=False)
    save(fig, "03_guardrail_unfilled_slots.png")


def cuped_chart(res):
    items = [("No-show, raw", res["primary_no_show"], GRAY), ("No-show, CUPED", res["cuped_no_show"], INK),
             ("Unfilled, raw", res["unfilled_slot"], GRAY), ("Unfilled, CUPED", res["cuped_unfilled"], BLUE)]
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    for i, (lab, r, col) in enumerate(items[::-1]):
        ax.plot([r["ci_low_pp"], r["ci_high_pp"]], [i, i], color=col, lw=2)
        ax.plot(r["diff_pp"], i, "o", color=col, ms=7, mec="white")
        ax.text(r["ci_high_pp"] + 0.1, i, f"CI width {r['ci_high_pp'] - r['ci_low_pp']:.2f} pp", va="center",
                fontsize=8.5, color=INK2)
    ax.set_yticks(range(4))
    ax.set_yticklabels([x[0] for x in items[::-1]])
    ax.axvline(0, color=INK2, lw=1)
    ax.set_xlim(right=0.9)
    vr = res["cuped_no_show"]["variance_reduction"]
    ax.set_title(f"CUPED with 2024 no-show history: {vr:.0%} lower variance on the no-show estimate")
    ax.set_xlabel("Treatment effect, percentage points (95% CI)")
    ax.grid(axis="y", visible=False)
    save(fig, "04_cuped_variance_reduction.png")


def segment_chart(res):
    seg = pd.DataFrame(res["segments"])
    seg = seg[seg.metric == "is_no_show"]
    dims = [("payer", "Payer"), ("specialty", "Specialty"), ("lead_time_band", "Lead time"), ("language", "Language")]
    fig, axes = plt.subplots(1, 4, figsize=(11, 3.6), sharex=True)
    for ax, (dim, title) in zip(axes, dims):
        s = seg[seg.dimension == dim].reset_index(drop=True)
        for i, r in s.iterrows():
            ax.plot([r.ci_low_pp, r.ci_high_pp], [i, i], color=BLUE, lw=2)
            ax.plot(r.diff_pp, i, "o", color=BLUE, ms=6, mec="white")
        ax.axvline(0, color=INK2, lw=1)
        ax.axvline(res["cuped_no_show"]["diff_pp"], color=ORANGE, lw=1, ls="--")
        ax.set_yticks(range(len(s)))
        ax.set_yticklabels([PAYER_LABEL.get(x, x.replace("_", " ")) for x in s.segment], fontsize=8.5)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="y", visible=False)
    axes[0].set_xlabel("No-show effect, pp (95% CI)")
    fig.suptitle("Effect by segment (dashed line = overall effect)", x=0.01, ha="left", fontweight="bold")
    save(fig, "05_segment_effects.png")


def sizing_chart(res):
    sz = pd.DataFrame(res["sizing"])
    labels = {"full_network": "Full network", "medicaid_selfpay_only": "Medicaid + self-pay only"}
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    y = np.arange(len(sz))
    ax.barh(y + 0.18, sz.net_value / 1e3, 0.34, color=BLUE, label="Valued on unfilled slots (decision metric)")
    ax.barh(y - 0.18, sz.net_value_no_show_only / 1e3, 0.34, color=GRAY, label="Valued on no-shows only")
    for i, r in sz.iterrows():
        lo, hi = r.net_value_ci
        ax.plot([lo / 1e3, hi / 1e3], [i + 0.18, i + 0.18], color=INK, lw=1.2)
        ax.text(hi / 1e3 + 15, i + 0.18, f"${r.net_value / 1e3:,.0f}K", va="center", fontsize=8.5)
        ax.text(r.net_value_no_show_only / 1e3 + 15, i - 0.18, f"${r.net_value_no_show_only / 1e3:,.0f}K",
                va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(y)
    ax.set_yticklabels([labels[s] for s in sz.scope])
    ax.set_xlabel("Estimated net annual value, $K (simulated economics; bar = 95% CI)")
    ax.set_title("Rollout scope: network-wide returns about twice the targeted option")
    ax.set_xlim(0, sz.net_value_ci.apply(lambda x: x[1]).max() / 1e3 * 1.2)
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(axis="y", visible=False)
    save(fig, "06_rollout_value.png")


def validation_chart(res, truth):
    t = truth["realized"]
    seg = pd.DataFrame(res["segments"])
    rows = [("No-show, overall", truth["parameters"]["mix_weighted_effect_pp"], t["effect_no_show_pp"],
             res["cuped_no_show"])]
    for p in ["commercial", "medicare", "medicaid", "self_pay"]:
        r = seg[(seg.dimension == "payer") & (seg.segment == p) & (seg.metric == "is_no_show")].iloc[0]
        rows.append((f"No-show, {PAYER_LABEL[p]}", truth["parameters"]["effect_pp"][p], t["by_payer"][p]["effect_pp"], r))
    rows.append(("Late-cancel rate", 100 * (truth["parameters"]["late_cancel"]["treatment"]
                                           - truth["parameters"]["late_cancel"]["control"]),
                 t["effect_late_cancel_pp"], res["late_cancel"]))
    rows.append(("Unfilled-slot rate", truth["parameters"]["unfilled_effect_pp"], t["effect_unfilled_pp"], res["cuped_unfilled"]))
    fig, ax = plt.subplots(figsize=(8, 4))
    for i, (lab, planted, realized, r) in enumerate(rows[::-1]):
        ax.plot([r["ci_low_pp"], r["ci_high_pp"]], [i, i], color=BLUE, lw=2)
        ax.plot(r["diff_pp"], i, "o", color=BLUE, ms=7, mec="white", label="Recovered (95% CI)" if i == 0 else None)
        ax.plot(realized, i, "D", color=AQUA, ms=6, mfc="none", mew=1.6, label="Realized in generated data" if i == 0 else None)
        ax.plot(planted, i, "x", color=ORANGE, ms=7, mew=1.8, label="Generator parameter" if i == 0 else None)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows[::-1]])
    ax.axvline(0, color=INK2, lw=1)
    ax.set_xlabel("Effect, percentage points")
    ax.set_title("Validation: planted vs. recovered effects")
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    ax.grid(axis="y", visible=False)
    save(fig, "07_validation_planted_vs_recovered.png")


def main():
    FIG.mkdir(exist_ok=True)
    style()
    res = json.loads((ROOT / "reports" / "results.json").read_text())
    truth = json.loads((ROOT / "data" / "truth" / "planted_effects.json").read_text())
    headline_forest(res)
    srm_chart(res)
    guardrail_chart(res)
    cuped_chart(res)
    segment_chart(res)
    sizing_chart(res)
    validation_chart(res, truth)
    print(f"wrote {len(list(FIG.glob('*.png')))} figures")


if __name__ == "__main__":
    main()
