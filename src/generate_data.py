"""Generate the synthetic outpatient appointment / SMS-reminder experiment dataset.

All data is synthetic (seed 42). No real patients, clinics, or organizations.

Outputs
-------
data/raw/*.csv                 six raw tables, with planted data-quality issues
data/truth/planted_effects.json generator parameters and realized planted values

Design notes (see docs/data_dictionary.md and docs/methodology.md)
- Each patient has a latent no-show propensity p_i ~ Beta(mean = payer rate, concentration KAPPA).
  This creates the pre-period / experiment-period correlation used by CUPED.
- Treatment scales p_i by (1 - relative payer effect), so the mean effect per payer equals the
  planted absolute effect in percentage points.
- "Slot universe" = appointments that reached the day of the visit without an early (>=24h)
  cancellation or a reschedule: completed + no_show + late_cancel. All rates use this denominator.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TRUTH = ROOT / "data" / "truth"

# ---------------------------------------------------------------- parameters
N_PATIENTS = 90_000
N_CLINICS = 24
N_PROVIDERS = 180
START, END = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")
EXP_START, EXP_END = pd.Timestamp("2025-03-03"), pd.Timestamp("2025-06-29")  # inclusive dates
PRE_START, PRE_END = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")

PAYERS = ["commercial", "medicare", "medicaid", "self_pay"]
PAYER_MIX = [0.50, 0.22, 0.23, 0.05]
CONTROL_NS = {"commercial": 0.09, "medicare": 0.12, "medicaid": 0.22, "self_pay": 0.24}
EFFECT_PP = {"commercial": -0.010, "medicare": -0.015, "medicaid": -0.040, "self_pay": -0.030}
KAPPA = 1.3  # Beta concentration of latent no-show propensity (tuned for rho ~ 0.55)

LATE_CANCEL = {"control": 0.060, "treatment": 0.075}
REFILL_LATE = {"control": 0.25, "treatment": 0.60}
REFILL_EARLY = 0.85
EARLY_CANCEL = 0.08
RESCHEDULE = 0.012

SPECIALTIES = ["primary_care", "cardiology", "orthopedics", "behavioral_health", "dermatology", "ob_gyn"]
VISIT_FACTOR = {"primary_care": 1.0, "cardiology": 0.9, "orthopedics": 0.8,
                "behavioral_health": 2.2, "dermatology": 0.6, "ob_gyn": 1.4}
LEAD_MEDIAN = {"primary_care": 10, "cardiology": 21, "orthopedics": 14,
               "behavioral_health": 7, "dermatology": 28, "ob_gyn": 14}
CENTRAL_CLINICS = {"C05", "C12", "C21"}
SRM_CLINIC = "C17"
SRM_FROM, SRM_TO = pd.Timestamp("2025-04-07"), pd.Timestamp("2025-04-15")  # inclusive local dates

MWC = sum(m * CONTROL_NS[p] for p, m in zip(PAYERS, PAYER_MIX))   # 0.134
MWE = sum(m * EFFECT_PP[p] for p, m in zip(PAYERS, PAYER_MIX))     # -0.019
MSG_COST, PLATFORM_COST, MARGIN = 0.04, 18_000, 160  # used by analysis; recorded here for truth


def make_clinics(rng):
    ids = [f"C{i:02d}" for i in range(1, N_CLINICS + 1)]
    spec = [SPECIALTIES[(i - 16) % 6] for i in range(N_CLINICS)]  # C17 -> primary care
    weight = rng.lognormal(0, 0.35, N_CLINICS)
    weight[ids.index(SRM_CLINIC)] = weight.mean() * 1.8  # C17 is the largest primary-care hub
    weight = weight / weight.sum()
    tz = ["America/Chicago" if c in CENTRAL_CLINICS else "America/New_York" for c in ids]
    region = ["West" if c in CENTRAL_CLINICS else ["North", "South", "East"][i % 3] for i, c in enumerate(ids)]
    clinics = pd.DataFrame({
        "clinic_id": ids, "clinic_name": [f"Clinic {c[1:]}" for c in ids], "specialty": spec,
        "region": region, "timezone": tz, "has_waitlist": rng.random(N_CLINICS) < 0.5,
    })
    return clinics, weight


def make_providers(rng, clinics, weight):
    alloc = np.maximum(3, np.round(weight * N_PROVIDERS)).astype(int)
    while alloc.sum() > N_PROVIDERS:
        alloc[np.argmax(alloc)] -= 1
    while alloc.sum() < N_PROVIDERS:
        alloc[np.argmin(alloc)] += 1
    rows = []
    k = 1
    for cid, spec, n in zip(clinics.clinic_id, clinics.specialty, alloc):
        for _ in range(n):
            rows.append((f"P{k:03d}", cid, spec))
            k += 1
    return pd.DataFrame(rows, columns=["provider_id", "clinic_id", "specialty"])


def make_patients(rng, clinics, weight):
    n = N_PATIENTS
    payer = rng.choice(PAYERS, n, p=PAYER_MIX)
    age_band = np.empty(n, dtype=object)
    bands_young = ["18-34", "35-49", "50-64"]
    for p in PAYERS:
        m = payer == p
        if p == "medicare":
            age_band[m] = rng.choice(["50-64", "65-74", "75+"], m.sum(), p=[0.08, 0.55, 0.37])
        elif p == "medicaid":
            age_band[m] = rng.choice(["0-17", *bands_young], m.sum(), p=[0.30, 0.35, 0.22, 0.13])
        else:
            age_band[m] = rng.choice(["0-17", *bands_young, "65-74"], m.sum(), p=[0.15, 0.32, 0.27, 0.22, 0.04])
    sex = rng.choice(["F", "M"], n, p=[0.55, 0.45])
    lang = np.where(payer == "medicaid", rng.choice(["English", "Spanish", "Other"], n, p=[0.68, 0.27, 0.05]),
                    rng.choice(["English", "Spanish", "Other"], n, p=[0.87, 0.10, 0.03]))
    opt_p = np.where(payer == "medicare", 0.70, 0.82)
    opt_in = rng.random(n) < opt_p
    zip3 = rng.choice([f"{z:03d}" for z in range(460, 476)], n)
    home = rng.choice(N_CLINICS, n, p=weight)
    # latent no-show propensity
    mu = np.array([CONTROL_NS[p] for p in payer])
    latent = rng.beta(mu * KAPPA, (1 - mu) * KAPPA)
    spec = clinics.specialty.values[home]
    rate = rng.gamma(1.4, 1 / 1.4, n) * np.array([VISIT_FACTOR[s] for s in spec])
    pats = pd.DataFrame({
        "patient_id": [f"PT{i:06d}" for i in range(1, n + 1)], "age_band": age_band, "sex": sex,
        "payer_type": payer, "zip3": zip3, "preferred_language": lang, "sms_opt_in": opt_in,
    })
    return pats, home, latent, rate


def business_days():
    d = pd.date_range(START, END, freq="D")
    d = d[d.dayofweek < 5]
    hol = pd.to_datetime(["2024-01-01", "2024-05-27", "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25",
                          "2025-01-01", "2025-05-26", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25"])
    return d[~d.isin(hol)]


def to_utc(local: pd.Series, tz: pd.Series) -> pd.Series:
    out = pd.Series(pd.NaT, index=local.index, dtype="datetime64[ns]")
    for z in tz.unique():
        m = tz == z
        out[m] = (local[m].dt.tz_localize(z, ambiguous="NaT", nonexistent="shift_forward")
                  .dt.tz_convert("UTC").dt.tz_localize(None))
    return out


def draw_outcomes(rng, df, latent, treat):
    """Return canonical status + refill flag for appointments in df (all assumed in the slot path)."""
    n = len(df)
    lc_p = np.where(treat, LATE_CANCEL["treatment"], LATE_CANCEL["control"])
    payer = df.payer_type.values
    rel = np.array([-EFFECT_PP[p] / CONTROL_NS[p] for p in payer])
    p_ns = latent * np.where(treat, 1 - rel, 1.0)
    u = rng.random(n)
    status = np.full(n, "completed", dtype=object)
    early = u < EARLY_CANCEL
    u2 = rng.random(n)
    lc = (~early) & (u2 < lc_p)
    ns_cond = np.minimum(p_ns / (1 - lc_p), 0.98)
    ns = (~early) & (~lc) & (rng.random(n) < ns_cond)
    status[early] = "cancelled"
    status[lc] = "late_cancel"
    status[ns] = "no_show"
    refill = np.full(n, np.nan)
    refill[early] = rng.random(early.sum()) < REFILL_EARLY
    rp = np.where(treat, REFILL_LATE["treatment"], REFILL_LATE["control"])
    refill[lc] = rng.random(n)[lc] < rp[lc]
    return status, refill


def main():
    rng = np.random.default_rng(SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    TRUTH.mkdir(parents=True, exist_ok=True)

    clinics, weight = make_clinics(rng)
    providers = make_providers(rng, clinics, weight)
    pats, home, latent, rate = make_patients(rng, clinics, weight)

    # ------------------------------------------------------------ appointments
    bdays = business_days()
    dow_w = np.array([1.12, 1.05, 1.0, 1.0, 0.83])[bdays.dayofweek]
    dow_w = dow_w / dow_w.sum()
    n_appt = rng.poisson(rate * 4.1)
    pat_idx = np.repeat(np.arange(N_PATIENTS), n_appt)
    n = len(pat_idx)
    day = bdays.values[rng.choice(len(bdays), n, p=dow_w)]
    slot = rng.integers(0, 27, n)  # 08:00 .. 16:40 in 20-minute slots
    sched = pd.Series(day) + pd.to_timedelta(8 * 60 + 20 * slot, unit="m")
    away = rng.random(n) < 0.12
    clinic_idx = np.where(away, rng.choice(N_CLINICS, n, p=weight), home[pat_idx])
    appt = pd.DataFrame({"pidx": pat_idx, "scheduled_at": sched.values, "cidx": clinic_idx})
    appt["clinic_id"] = clinics.clinic_id.values[appt.cidx]
    appt["specialty"] = clinics.specialty.values[appt.cidx]
    appt["timezone"] = clinics.timezone.values[appt.cidx]
    # provider: random within clinic
    prov_by_clinic = providers.groupby("clinic_id").provider_id.apply(list).to_dict()
    appt["provider_id"] = [prov_by_clinic[c][k % len(prov_by_clinic[c])]
                           for c, k in zip(appt.clinic_id, rng.integers(0, 1000, n))]
    med = appt.specialty.map(LEAD_MEDIAN).values
    lead_days = np.where(rng.random(n) < 0.08, rng.integers(0, 2, n), rng.lognormal(np.log(med), 0.8))
    lead_days = np.minimum(lead_days, 120)
    lead_h = lead_days * 24 + rng.uniform(-6, 6, n)
    lead_h = np.maximum(lead_h, 1.0)
    appt["booked_at"] = appt.scheduled_at - pd.to_timedelta(lead_h, unit="h")
    appt["payer_type"] = pats.payer_type.values[appt.pidx]
    appt["patient_id"] = pats.patient_id.values[appt.pidx]
    appt["opt_in"] = pats.sms_opt_in.values[appt.pidx]
    appt = appt.sort_values(["scheduled_at", "pidx"]).reset_index(drop=True)
    appt["sched_date"] = appt.scheduled_at.dt.normalize()

    # ------------------------------------------------------------ experiment assignment (patient level)
    in_win = (appt.sched_date >= EXP_START) & (appt.sched_date <= EXP_END) & appt.opt_in
    first = appt[in_win].groupby("pidx").head(1)
    assign = pd.DataFrame({
        "pidx": first.pidx.values,
        "patient_id": first.patient_id.values,
        "clinic_id_at_assignment": first.clinic_id.values,
        "assigned_local": (first.scheduled_at - pd.Timedelta(hours=72)).values,
        "tz": first.timezone.values,
    })
    assign["variant"] = np.where(rng.random(len(assign)) < 0.5, "treatment", "control")
    assign["assigned_at"] = to_utc(assign.assigned_local, assign.tz)
    variant_of = dict(zip(assign.pidx, assign.variant))

    appt["variant_true"] = appt.pidx.map(variant_of)
    appt["in_experiment"] = in_win & appt.variant_true.notna()
    treat = (appt.in_experiment & (appt.variant_true == "treatment")).values

    # ------------------------------------------------------------ reschedules (new appointment ids)
    resch = (rng.random(len(appt)) < RESCHEDULE) & (appt.booked_at < appt.scheduled_at - pd.Timedelta(hours=30)).values
    status, refill = draw_outcomes(rng, appt, latent[appt.pidx.values], treat)
    status = np.where(resch, "rescheduled", status)
    refill = np.where(resch, np.nan, refill)
    appt["status"] = status
    appt["slot_refilled_flag"] = refill
    appt["rescheduled_from_appointment_id"] = None

    orig = appt[resch].copy()
    newa = orig.copy()
    shift_days = rng.integers(3, 29, len(newa))
    newa["scheduled_at"] = orig.scheduled_at + pd.to_timedelta(shift_days, unit="D")
    wkend = newa.scheduled_at.dt.dayofweek >= 5
    newa.loc[wkend, "scheduled_at"] += pd.Timedelta(days=2)
    newa = newa[newa.scheduled_at <= END + pd.Timedelta(hours=23)]
    orig_kept = orig.loc[newa.index]
    newa["booked_at"] = orig_kept.scheduled_at - pd.to_timedelta(rng.uniform(26, 96, len(newa)), unit="h")
    newa["sched_date"] = newa.scheduled_at.dt.normalize()
    # new appointment inherits the patient's variant (patient-level randomization)
    nwin = (newa.sched_date >= EXP_START) & (newa.sched_date <= EXP_END) & newa.variant_true.notna()
    newa["in_experiment"] = nwin
    ntreat = (nwin & (newa.variant_true == "treatment")).values
    st2, rf2 = draw_outcomes(rng, newa, latent[newa.pidx.values], ntreat)
    newa["status"], newa["slot_refilled_flag"] = st2, rf2
    newa["orig_index"] = newa.index
    appt = pd.concat([appt, newa], ignore_index=False)
    appt["row_key"] = np.arange(len(appt))
    appt = appt.sort_values(["scheduled_at", "row_key"]).reset_index()
    appt["appointment_id"] = [f"A{i:07d}" for i in range(1, len(appt) + 1)]
    # link rescheduled children to parents
    parent_id = appt[appt.orig_index.isna()].set_index("index").appointment_id
    child = appt.orig_index.notna()
    appt.loc[child, "rescheduled_from_appointment_id"] = appt.loc[child, "orig_index"].astype(int).map(parent_id).values
    appt["is_treat"] = appt.in_experiment.astype(bool) & (appt.variant_true == "treatment")

    # status_updated_at
    n = len(appt)
    sa, ba = appt.scheduled_at, appt.booked_at
    span_h = ((sa - ba).dt.total_seconds() / 3600).values
    upd = sa + pd.to_timedelta(rng.uniform(0.5, 3, n), unit="h")
    m_c = appt.status.eq("cancelled").values
    upd[m_c] = (ba[m_c] + pd.to_timedelta(np.maximum(span_h[m_c] - 24, 0.1) * rng.random(m_c.sum()), unit="h")).values
    m_l = appt.status.eq("late_cancel").values
    upd[m_l] = (sa[m_l] - pd.to_timedelta(rng.uniform(1, 23.5, m_l.sum()), unit="h")).values
    m_r = appt.status.eq("rescheduled").values
    resched_children = appt[child].set_index("rescheduled_from_appointment_id").booked_at
    upd[m_r] = appt.loc[m_r, "appointment_id"].map(resched_children).fillna(sa[m_r] - pd.Timedelta(hours=30)).values
    appt["status_updated_at"] = upd

    # ------------------------------------------------------------ truth (clean data, before messiness)
    universe = appt.status.isin(["completed", "no_show", "late_cancel"])
    exp = appt[appt.in_experiment.astype(bool) & universe].copy()
    exp["ns"] = exp.status.eq("no_show")
    exp["lc"] = exp.status.eq("late_cancel")
    exp["unfilled"] = exp.ns | (exp.lc & (exp.slot_refilled_flag != 1))

    def rates(g):
        return {"no_show": g.ns.mean(), "late_cancel": g.lc.mean(), "unfilled": g.unfilled.mean(),
                "refill_late_cancel": g.loc[g.lc, "slot_refilled_flag"].mean(), "n_appointments": int(len(g))}

    # expected (sample-average) treatment effect given each appointment's latent propensity
    rel_e = exp.payer_type.map({p: -EFFECT_PP[p] / CONTROL_NS[p] for p in PAYERS}).values
    exp["ite"] = -rel_e * latent[exp.pidx.values]
    sate = {"overall_pp": 100 * float(exp.ite.mean()),
            "by_payer_pp": {p: 100 * float(exp.loc[exp.payer_type == p, "ite"].mean()) for p in PAYERS}}
    realized = {v: rates(exp[exp.variant_true == v]) for v in ["control", "treatment"]}
    by_payer = {}
    for p in PAYERS:
        c = exp[(exp.variant_true == "control") & (exp.payer_type == p)].ns.mean()
        t = exp[(exp.variant_true == "treatment") & (exp.payer_type == p)].ns.mean()
        by_payer[p] = {"control": c, "treatment": t, "effect_pp": 100 * (t - c)}
    # rho: patient-level corr of pre-period vs experiment-period no-show rate
    pre = appt[(appt.sched_date <= PRE_END) & universe].groupby("pidx").status.apply(lambda s: (s == "no_show").mean())
    post = exp.groupby("pidx").ns.mean()
    both = pd.concat([pre.rename("pre"), post.rename("post")], axis=1).dropna()
    rho = float(both.corr().iloc[0, 1])

    # ------------------------------------------------------------ messages
    msgs = []
    opt = appt.opt_in.values
    for offset, which in [(48, "std"), (72, "t72"), (24, "t24")]:
        if which == "std":
            m = opt & ~appt.is_treat.values
        else:
            m = appt.is_treat.values.copy()
        send_local = appt.scheduled_at - pd.Timedelta(hours=offset)
        m &= (appt.booked_at < send_local).values
        cancelled_before = appt.status.isin(["cancelled", "rescheduled"]).values & (appt.status_updated_at < send_local).values
        m &= ~cancelled_before
        if which == "t24":  # late cancels triggered before the 24h text get no 24h text
            m &= ~(appt.status.eq("late_cancel").values & (appt.status_updated_at < send_local).values)
        sub = appt.loc[m, ["appointment_id", "timezone", "status"]].copy()
        sub["sent_local"] = send_local[m].values
        sub["kind"] = which
        msgs.append(sub)
    msg = pd.concat(msgs, ignore_index=True)
    msg["sent_at"] = to_utc(msg.sent_local, msg.timezone) + pd.to_timedelta(rng.integers(0, 300, len(msg)), unit="s")
    msg = msg.sort_values("sent_at").reset_index(drop=True)
    nm = len(msg)
    msg["message_id"] = [f"M{i:07d}" for i in range(1, nm + 1)]
    msg["delivery_status"] = rng.choice(["delivered", "failed", "undelivered"], nm, p=[0.965, 0.025, 0.010])
    two_way = msg.kind.ne("std").values
    reply = np.full(nm, None, dtype=object)
    r = rng.random(nm)
    delivered = msg.delivery_status.eq("delivered").values
    reply[two_way & delivered & (r < 0.48)] = "C"   # confirm
    reply[two_way & delivered & (r >= 0.48) & (r < 0.51)] = "R"  # reschedule link tapped
    lc_24 = two_way & delivered & msg.status.eq("late_cancel").values & (msg.kind.eq("t24").values) & (r < 0.75)
    reply[lc_24] = "X"  # cancel
    msg["reply_code"] = reply
    msg["channel"] = np.where(two_way, "sms_two_way", "sms_one_way")
    msg.loc[rng.random(nm) < 0.02, "delivery_status"] = None  # planted: 2% null delivery_status

    # ------------------------------------------------------------ planted messiness
    # status code variants
    variants = {
        "no_show": (["no_show", "NOSHOW", "No Show", "NS"], [0.55, 0.2, 0.15, 0.10]),
        "completed": (["completed", "Completed", "COMPLETED"], [0.8, 0.15, 0.05]),
        "cancelled": (["cancelled", "Cancelled", "CANCELED"], [0.8, 0.1, 0.1]),
        "late_cancel": (["late_cancel", "Late Cancel", "LATE_CANCEL"], [0.8, 0.1, 0.1]),
        "rescheduled": (["rescheduled", "Rescheduled"], [0.85, 0.15]),
    }
    raw_status = appt.status.values.astype(object).copy()
    for canon, (opts, probs) in variants.items():
        m = appt.status.values == canon
        raw_status[m] = rng.choice(opts, m.sum(), p=probs)
    # 60% of rescheduled originals were closed out as no-shows by the source system
    m_r = appt.status.values == "rescheduled"
    miscode = m_r & (rng.random(len(appt)) < 0.6)
    raw_status[miscode] = rng.choice(["NOSHOW", "No Show", "no_show"], miscode.sum())
    appt["status_raw"] = raw_status
    # 0.5% booked_at after scheduled_at (entry error)
    bad = rng.random(len(appt)) < 0.005
    appt.loc[bad, "booked_at"] = appt.loc[bad, "scheduled_at"] + pd.to_timedelta(rng.uniform(1, 10, bad.sum()), unit="D")
    appt["lead_time_days"] = np.floor((appt.scheduled_at - appt.booked_at).dt.total_seconds() / 86400).astype(int)

    # assignment log: SRM bug and duplicates
    a = assign.copy()
    a_local_date = a.assigned_local.dt.normalize()
    srm_drop = ((a.variant == "treatment") & (a.clinic_id_at_assignment == SRM_CLINIC)
                & (a_local_date >= SRM_FROM) & (a_local_date <= SRM_TO))
    n_dropped = int(srm_drop.sum())
    a_logged = a[~srm_drop].copy()
    dup = a_logged.sample(frac=0.007, random_state=SEED).copy()
    dup["variant"] = np.where(dup.variant == "treatment", "control", "treatment")
    dup["assigned_at"] = dup.assigned_at + pd.to_timedelta(rng.uniform(1, 20, len(dup)), unit="D")
    a_out = pd.concat([a_logged, dup]).sample(frac=1, random_state=SEED)
    a_out = a_out[["patient_id", "variant", "assigned_at", "clinic_id_at_assignment"]]
    a_out.insert(0, "assignment_row_id", np.arange(1, len(a_out) + 1))

    # ------------------------------------------------------------ write
    fmt = "%Y-%m-%d %H:%M:%S"
    pats.to_csv(RAW / "dim_patient.csv", index=False)
    clinics.to_csv(RAW / "dim_clinic.csv", index=False)
    providers.to_csv(RAW / "dim_provider.csv", index=False)
    out = appt[["appointment_id", "patient_id", "clinic_id", "provider_id", "booked_at", "scheduled_at",
                "lead_time_days", "status_raw", "status_updated_at", "slot_refilled_flag",
                "rescheduled_from_appointment_id"]].rename(columns={"status_raw": "status"})
    out["slot_refilled_flag"] = out.slot_refilled_flag.map({1.0: "Y", 0.0: "N"})
    for c in ["booked_at", "scheduled_at", "status_updated_at"]:
        out[c] = out[c].dt.strftime(fmt)
    out.to_csv(RAW / "fact_appointment.csv", index=False)
    a_out["assigned_at"] = a_out.assigned_at.dt.strftime(fmt)
    a_out.to_csv(RAW / "fact_experiment_assignment.csv", index=False)
    mo = msg[["message_id", "appointment_id", "sent_at", "channel", "delivery_status", "reply_code"]].copy()
    mo["sent_at"] = mo.sent_at.dt.strftime(fmt)
    mo.to_csv(RAW / "fact_message_log.csv", index=False)

    n_t = int((a.variant == "treatment").sum())
    n_c = int((a.variant == "control").sum())
    truth = {
        "seed": SEED,
        "parameters": {
            "payer_mix": dict(zip(PAYERS, PAYER_MIX)), "control_no_show": CONTROL_NS,
            "effect_pp": {k: 100 * v for k, v in EFFECT_PP.items()},
            "mix_weighted_control": sum(m * CONTROL_NS[p] for p, m in zip(PAYERS, PAYER_MIX)),
            "mix_weighted_effect_pp": 100 * sum(m * EFFECT_PP[p] for p, m in zip(PAYERS, PAYER_MIX)),
            "late_cancel": LATE_CANCEL, "refill_late_cancel": REFILL_LATE, "beta_concentration": KAPPA,
            "unfilled_control": 100 * (MWC + LATE_CANCEL["control"] * (1 - REFILL_LATE["control"])),
            "unfilled_treatment": 100 * (MWC + MWE + LATE_CANCEL["treatment"] * (1 - REFILL_LATE["treatment"])),
            "unfilled_effect_pp": 100 * (MWE + LATE_CANCEL["treatment"] * (1 - REFILL_LATE["treatment"])
                                         - LATE_CANCEL["control"] * (1 - REFILL_LATE["control"])),
            "srm_bug": {"clinic": SRM_CLINIC, "from": str(SRM_FROM.date()), "to": str(SRM_TO.date()),
                        "dropped": "treatment assignment rows"},
            "duplicate_assignment_share": 0.007, "reschedule_share": RESCHEDULE,
            "null_delivery_share": 0.02, "booked_after_scheduled_share": 0.005,
            "cost": {"per_message": MSG_COST, "platform_per_year": PLATFORM_COST, "margin_per_filled_slot": MARGIN},
        },
        "realized": {
            "by_variant": realized,
            "effect_no_show_pp": 100 * (realized["treatment"]["no_show"] - realized["control"]["no_show"]),
            "effect_unfilled_pp": 100 * (realized["treatment"]["unfilled"] - realized["control"]["unfilled"]),
            "effect_late_cancel_pp": 100 * (realized["treatment"]["late_cancel"] - realized["control"]["late_cancel"]),
            "by_payer": by_payer,
            "expected_effect_given_latent": sate,
            "rho_pre_vs_experiment": rho,
            "rho_n_patients": int(len(both)),
            "assigned_patients_true": {"control": n_c, "treatment": n_t},
            "srm_treatment_rows_dropped": n_dropped,
            "logged_split_treatment_share": (n_t - n_dropped) / (n_t + n_c - n_dropped),
            "duplicate_assignment_rows": int(len(dup)),
            "rescheduled_originals": int(m_r.sum()), "rescheduled_miscoded_as_no_show": int(miscode.sum()),
            "booked_after_scheduled_rows": int(bad.sum()),
            "rows": {"dim_patient": len(pats), "dim_clinic": len(clinics), "dim_provider": len(providers),
                     "fact_appointment": len(out), "fact_experiment_assignment": len(a_out),
                     "fact_message_log": len(mo)},
        },
    }
    (TRUTH / "planted_effects.json").write_text(json.dumps(truth, indent=2, default=float))
    print(json.dumps(truth["realized"], indent=1, default=float))


if __name__ == "__main__":
    main()
