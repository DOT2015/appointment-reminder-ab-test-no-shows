"""Self-contained interactive dashboard (Plotly, JS inlined once). Writes dashboard/index.html."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "reports" / "tables"
OUT = ROOT / "dashboard" / "index.html"
BLUE, ORANGE, AQUA, GRAY, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984", "#52514e"
LAYOUT = dict(template="plotly_white", font=dict(family="Inter, Segoe UI, Arial", size=12, color="#0b0b0b"),
              margin=dict(l=60, r=30, t=60, b=50), hoverlabel=dict(font_size=12))
PAYER_LABEL = {"commercial": "Commercial", "medicare": "Medicare", "medicaid": "Medicaid", "self_pay": "Self-pay"}


_N = [0]


def div(fig, first=False):
    _N[0] += 1   # fixed div ids keep the HTML byte-identical between runs
    return pio.to_html(fig, include_plotlyjs=True if first else False, full_html=False, div_id=f"fig{_N[0]}",
                       config={"displaylogo": False, "responsive": True})


def view_health(res):
    d = pd.read_csv(TABLES / "01_srm_and_assignment_health.csv", parse_dates=["assigned_date"])
    net = d.groupby("assigned_date")[["n_control", "n_treatment"]].sum().reset_index()
    f1 = go.Figure()
    f1.add_bar(x=net.assigned_date, y=net.n_control, name="Control", marker_color=ORANGE,
               hovertemplate="%{x|%b %d}: %{y} control<extra></extra>")
    f1.add_bar(x=net.assigned_date, y=net.n_treatment, name="Treatment", marker_color=BLUE,
               hovertemplate="%{x|%b %d}: %{y} treatment<extra></extra>")
    s = res["srm"]
    f1.update_layout(**LAYOUT, barmode="group", height=340, bargap=0.15,
                     title=f"Daily assignments by variant (network). Overall split before exclusion: "
                           f"{100 * s['overall_before']['treatment_share']:.1f}% treatment, "
                           f"chi-square p = {s['overall_before']['p_value']:.2f}",
                     yaxis_title="Patients assigned", legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
    wk = pd.read_csv(TABLES / "srm_clinic_week_scan.csv", parse_dates=["week"])
    wk["share"] = 100 * wk.n_treatment / wk.n
    piv = wk.pivot(index="clinic_id", columns="week", values="share").sort_index(ascending=False)
    qv = wk.pivot(index="clinic_id", columns="week", values="q_value").sort_index(ascending=False)
    nn = wk.pivot(index="clinic_id", columns="week", values="n").sort_index(ascending=False)
    f2 = go.Figure(go.Heatmap(
        z=piv.values, x=[c.strftime("%b %d") for c in piv.columns], y=piv.index, zmin=0, zmax=100, zmid=50,
        colorscale=[[0, ORANGE], [0.5, "#f2f1ee"], [1, BLUE]], colorbar=dict(title="% treatment"),
        customdata=[[[q, n] for q, n in zip(qr, nr)] for qr, nr in zip(qv.values, nn.values)],
        hovertemplate="Clinic %{y}, week of %{x}<br>treatment share %{z:.0f}%<br>n = %{customdata[1]}"
                      "<br>BH q = %{customdata[0]:.2g}<extra></extra>"))
    flagged = "; ".join(f"{e['clinic_id']} {e['date_from']} to {e['date_to']} "
                        f"({e['treatment_in_window']} treatment vs {e['control_in_window']} control)"
                        for e in s["exclusions"]) or "none"
    f2.update_layout(**LAYOUT, height=560, title="SRM scan: treatment share by clinic x week (binomial test per cell, BH)<br>"
                     f"<sup>Flagged and excluded: {flagged}</sup>", xaxis_title="Week starting (assignment date, clinic local)")
    f2.update_layout(margin=dict(l=60, r=30, t=80, b=50))
    g = pd.read_csv(TABLES / "03_guardrails_late_cancel_and_refill.csv")
    f3 = go.Figure()
    f3.add_bar(x=g.variant, y=100 * g.delivery_rate, marker_color=[ORANGE, BLUE], name="Delivered",
               text=[f"{100 * v:.1f}%" for v in g.delivery_rate], textposition="outside",
               hovertemplate="%{x}: %{y:.2f}% delivered<extra></extra>")
    f3.add_bar(x=g.variant, y=100 * g.status_unknown_rate, marker_color=GRAY, name="Status unknown (NULL)",
               text=[f"{100 * v:.1f}%" for v in g.status_unknown_rate], textposition="outside")
    f3.update_layout(**LAYOUT, height=320, barmode="group", yaxis_title="% of messages sent",
                     title="Message delivery by variant", yaxis_range=[0, 110])
    return [f1, f2, f3]


def view_results(res):
    rows = [("No-show rate", "primary_no_show", "cuped_no_show"),
            ("Unfilled-slot rate", "unfilled_slot", "cuped_unfilled"),
            ("Late-cancel rate (guardrail)", "late_cancel", None),
            ("Refill rate of late cancels", "refill_of_late_cancels", None)]
    fig = make_subplots(rows=1, cols=2, column_widths=[0.45, 0.55], horizontal_spacing=0.18,
                        subplot_titles=("Rate by variant (%)", "Treatment effect, pp (95% CI)"))
    labels = [r[0] for r in rows]
    fig.add_bar(y=labels, x=[res[r[1]]["control_pp"] for r in rows], orientation="h", name="Control",
                marker_color=ORANGE, row=1, col=1, hovertemplate="%{y}<br>control %{x:.2f}%<extra></extra>")
    fig.add_bar(y=labels, x=[res[r[1]]["treatment_pp"] for r in rows], orientation="h", name="Treatment",
                marker_color=BLUE, row=1, col=1, hovertemplate="%{y}<br>treatment %{x:.2f}%<extra></extra>")
    for kind, col, off in [("raw", GRAY, 0.15), ("CUPED", BLUE, -0.15)]:
        ys, xs, lo, hi = [], [], [], []
        for i, r in enumerate(rows):
            key = r[1] if kind == "raw" else r[2]
            if key is None:
                continue
            x = res[key]
            ys.append(i + off), xs.append(x["diff_pp"]), lo.append(x["diff_pp"] - x["ci_low_pp"])
            hi.append(x["ci_high_pp"] - x["diff_pp"])
        fig.add_scatter(x=xs, y=ys, mode="markers", name=f"Effect, {kind}", marker=dict(color=col, size=10),
                        error_x=dict(type="data", symmetric=False, array=hi, arrayminus=lo, color=col, thickness=2),
                        row=1, col=2, hovertemplate="%{x:.2f} pp<extra>" + kind + "</extra>")
    fig.add_vline(x=0, line_color=INK2, row=1, col=2)
    fig.update_yaxes(tickvals=list(range(len(rows))), ticktext=labels, autorange="reversed", row=1, col=2)
    fig.update_yaxes(autorange="reversed", row=1, col=1)
    vr = res["cuped_no_show"]["variance_reduction"]
    fig.update_layout(**LAYOUT, height=420, barmode="group",
                      title=f"Primary metric and guardrails. CUPED variance reduction on no-show: {vr:.0%}",
                      legend=dict(orientation="h", y=-0.15))
    return [fig]


def view_segments(res):
    seg = pd.DataFrame(res["segments"])
    dims = ["payer", "specialty", "lead_time_band", "language"]
    fig = go.Figure()
    for i, dim in enumerate(dims):
        for metric, col, name in [("is_no_show", BLUE, "No-show"), ("is_unfilled", AQUA, "Unfilled slot")]:
            s = seg[(seg.dimension == dim) & (seg.metric == metric)]
            fig.add_scatter(x=s.diff_pp, y=[PAYER_LABEL.get(v, v) for v in s.segment], mode="markers", name=name,
                            visible=(i == 0), marker=dict(color=col, size=10),
                            error_x=dict(type="data", symmetric=False, array=s.ci_high_pp - s.diff_pp,
                                         arrayminus=s.diff_pp - s.ci_low_pp, color=col, thickness=2),
                            customdata=s.n, hovertemplate="%{y}: %{x:.2f} pp (n=%{customdata})<extra>" + name + "</extra>")
    buttons = [dict(label=d.replace("_", " ").title(), method="update",
                    args=[{"visible": [j // 2 == i for j in range(2 * len(dims))]}]) for i, d in enumerate(dims)]
    fig.add_vline(x=0, line_color=INK2)
    fig.update_layout(**LAYOUT, height=420, title="Effect by segment, CUPED-adjusted (choose a dimension)",
                      xaxis_title="Treatment effect, pp (95% CI)",
                      updatemenus=[dict(buttons=buttons, direction="right", x=0, y=1.13, xanchor="left", type="buttons")])
    fig.update_layout(margin=dict(l=110, r=30, t=110, b=50))
    sz = pd.DataFrame(res["sizing"])
    names = {"full_network": "Full network", "medicaid_selfpay_only": "Medicaid + self-pay only"}
    tbl = go.Figure(go.Table(
        header=dict(values=["Scope", "Annual slot appts", "Unfilled effect, pp (95% CI)", "Slots recovered / yr",
                            "Annual cost", "Net value / yr (95% CI)", "Net value if valued on no-shows only"],
                    fill_color="#f2f1ee", align="left", font=dict(size=12)),
        cells=dict(values=[
            [names[s] for s in sz.scope], [f"{v:,}" for v in sz.annual_slot_appointments],
            [f"{r.unfilled_effect_pp:.2f} ({r.unfilled_ci_pp[0]:.2f}, {r.unfilled_ci_pp[1]:.2f})" for r in sz.itertuples()],
            [f"{v:,.0f}" for v in sz.slots_recovered], [f"${v:,.0f}" for v in sz.annual_cost],
            [f"${r.net_value:,.0f} (${r.net_value_ci[0]:,.0f} to ${r.net_value_ci[1]:,.0f})" for r in sz.itertuples()],
            [f"${v:,.0f}" for v in sz.net_value_no_show_only]], align="left", height=30)))
    tbl.update_layout(**LAYOUT, height=230, title="Rollout scenarios (simulated economics: $0.04/message, "
                      "$18,000/yr platform, $160 margin per filled slot)")
    return [fig, tbl]


def main():
    res = json.loads((ROOT / "reports" / "results.json").read_text())
    views = {"Experiment health": view_health(res), "Results": view_results(res),
             "Segments and rollout": view_segments(res)}
    first = True
    sections, tabs = [], []
    for i, (name, figs) in enumerate(views.items()):
        html = []
        for f in figs:
            html.append(div(f, first))
            first = False
        sections.append(f'<section id="v{i}" class="view{" active" if i == 0 else ""}">{"".join(html)}</section>')
        tabs.append(f'<button class="tab{" active" if i == 0 else ""}" onclick="show({i})">{name}</button>')
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Appointment reminder A/B test: no-shows</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:Inter,Segoe UI,Arial,sans-serif;margin:0;background:#fcfcfb;color:#0b0b0b}}
header{{padding:18px 28px 6px}} h1{{font-size:20px;margin:0 0 4px}} p.note{{color:#52514e;margin:0;font-size:13px}}
nav{{padding:10px 28px;border-bottom:1px solid #e5e4e0}}
.tab{{border:1px solid #d6d5d0;background:#fff;padding:7px 14px;margin-right:6px;border-radius:6px;cursor:pointer;font-size:13px}}
.tab.active{{background:#2a78d6;color:#fff;border-color:#2a78d6}}
.view{{display:none;padding:8px 28px}} .view.active{{display:block}}
</style></head><body>
<header><h1>Two-way SMS reminders vs. one-way: no-shows and unfilled slots</h1>
<p class="note">All data is synthetic (seed 42), simulated 24-clinic outpatient network, experiment 2025-03-03 to 2025-06-29.
Decision under the pre-registered rule: <b>{res['decision']}</b>.</p></header>
<nav>{''.join(tabs)}</nav>
{''.join(sections)}
<script>
function show(i){{document.querySelectorAll('.view').forEach((v,j)=>v.classList.toggle('active',i===j));
document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',i===j));
window.dispatchEvent(new Event('resize'));}}
</script></body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
