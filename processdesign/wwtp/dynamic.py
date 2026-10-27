"""Dynamic simulation of the activated sludge train with IWA ASM1.

Layout: [anaerobic] -> [anoxic] -> aerobic x N (tanks in series) -> point
settler. RAS returns to the first tank, internal recycle from the last
aerobic tank to the anoxic tank, WAS paced to hold the design SRT. Aerobic
DO is held at its set point and the oxygen the aeration system must supply is
computed from the mass balance, giving the diurnal oxygen-demand profile.

Default kinetic and stoichiometric parameters are the BSM1 (Copp, 2002)
ASM1 set at 15 C, temperature-corrected with Arrhenius factors. They are
recalled from the literature - confirm or calibrate before relying on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp

from ..core.criteria import custom_check
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import MGD_TO_M3D, LB_PER_KG
from .influent import Influent
from .preliminary import DEFAULT_DIURNAL

STATES = ["SI", "SS", "XI", "XS", "XBH", "XBA", "XP", "SO", "SNO", "SNH", "SND", "XND", "SALK"]
I = {s: k for k, s in enumerate(STATES)}
PART = [I[s] for s in ("XI", "XS", "XBH", "XBA", "XP", "XND")]
COD_PART = [I[s] for s in ("XI", "XS", "XBH", "XBA", "XP")]


@dataclass
class ASM1Params:
    YA: float = fld(0.24, "Autotroph yield YA", "g COD/g N")
    YH: float = fld(0.67, "Heterotroph yield YH", "g COD/g COD")
    fP: float = fld(0.08, "Inert fraction of biomass fP", "-")
    iXB: float = fld(0.08, "N in biomass iXB", "g N/g COD")
    iXP: float = fld(0.06, "N in endogenous products iXP", "g N/g COD")
    muH: float = fld(4.0, "muH @15C", "1/d")
    KS: float = fld(10.0, "KS", "g COD/m3")
    KOH: float = fld(0.2, "KOH", "g O2/m3")
    KNO: float = fld(0.5, "KNO", "g N/m3")
    bH: float = fld(0.3, "bH @15C", "1/d")
    etag: float = fld(0.8, "Anoxic growth factor eta_g", "-")
    etah: float = fld(0.8, "Anoxic hydrolysis factor eta_h", "-")
    kh: float = fld(3.0, "kh @15C", "g COD/g COD-d")
    KX: float = fld(0.1, "KX", "g COD/g COD")
    muA: float = fld(0.5, "muA @15C", "1/d")
    KNH: float = fld(1.0, "KNH", "g N/m3")
    bA: float = fld(0.05, "bA @15C", "1/d")
    KOA: float = fld(0.4, "KOA", "g O2/m3")
    ka: float = fld(0.05, "Ammonification ka @15C", "m3/g COD-d")
    th_muH: float = fld(1.072, "theta muH")
    th_bH: float = fld(1.04, "theta bH")
    th_muA: float = fld(1.072, "theta muA")
    th_bA: float = fld(1.029, "theta bA")
    th_kh: float = fld(1.04, "theta kh / ka")


@dataclass
class DynamicInputs:
    enabled: bool = fld(True, "Run dynamic ASM1 simulation")
    n_aerobic: int = fld(3, "Aerobic tanks in series", "", 1, 6)
    days_diurnal: int = fld(3, "Diurnal days simulated (after steady start)", "d", 1, 10)
    diurnal_pf: float = fld(1.6, "Dry-weather diurnal peak / average flow", "-", 1.0, 3.0,
                            help="Typical daily diurnal peak; the design peak-hour factor is a wet-weather/hydraulic value")
    conc_swing: float = fld(0.5, "Concentration swing relative to flow swing", "-", 0, 1.5,
                            help="0 = constant concentration (loads follow flow); 1 = concentrations swing as much as flow")
    TSS_COD: float = fld(0.75, "TSS per particulate COD", "g/g", 0.6, 0.9)
    params: ASM1Params = field(default_factory=ASM1Params)


def _rates(C, p, T):
    """ASM1 conversion rates for a (n_tanks x 13) state array; returns (n_tanks x 13)."""
    f = lambda k, th: k * th ** (T - 15.0)
    muH, bH = f(p.muH, p.th_muH), f(p.bH, p.th_bH)
    muA, bA = f(p.muA, p.th_muA), f(p.bA, p.th_bA)
    kh, ka = f(p.kh, p.th_kh), f(p.ka, p.th_kh)
    SS, XS, XBH, XBA = C[:, I["SS"]], C[:, I["XS"]], C[:, I["XBH"]], C[:, I["XBA"]]
    SO, SNO, SNH, SND, XND = (np.maximum(C[:, I[k]], 0) for k in ("SO", "SNO", "SNH", "SND", "XND"))
    SS = np.maximum(SS, 0); XS = np.maximum(XS, 0); XBH = np.maximum(XBH, 1e-6); XBA = np.maximum(XBA, 0)
    mo = SO / (p.KOH + SO); io = p.KOH / (p.KOH + SO); no = SNO / (p.KNO + SNO)
    r1 = muH * SS / (p.KS + SS) * mo * XBH
    r2 = muH * SS / (p.KS + SS) * io * no * p.etag * XBH
    r3 = muA * SNH / (p.KNH + SNH) * SO / (p.KOA + SO) * XBA
    r4 = bH * XBH
    r5 = bA * XBA
    r6 = ka * SND * XBH
    xr = XS / XBH
    r7 = kh * xr / (p.KX + xr) * (mo + p.etah * io * no) * XBH
    r8 = r7 * XND / np.maximum(XS, 1e-9)
    R = np.zeros_like(C)
    YH, YA = p.YH, p.YA
    R[:, I["SS"]] = -(r1 + r2) / YH + r7
    R[:, I["XS"]] = (1 - p.fP) * (r4 + r5) - r7
    R[:, I["XBH"]] = r1 + r2 - r4
    R[:, I["XBA"]] = r3 - r5
    R[:, I["XP"]] = p.fP * (r4 + r5)
    R[:, I["SO"]] = -(1 - YH) / YH * r1 - (4.57 - YA) / YA * r3
    R[:, I["SNO"]] = -(1 - YH) / (2.86 * YH) * r2 + r3 / YA
    R[:, I["SNH"]] = -p.iXB * (r1 + r2) - (p.iXB + 1 / YA) * r3 + r6
    R[:, I["SND"]] = -r6 + r8
    R[:, I["XND"]] = (p.iXB - p.fP * p.iXP) * (r4 + r5) - r8
    R[:, I["SALK"]] = (-p.iXB / 14 * r1 + ((1 - YH) / (14 * 2.86 * YH) - p.iXB / 14) * r2
                       - (p.iXB / 14 + 1 / (7 * YA)) * r3 + r6 / 14)
    return R


def influent_vector(infl: Influent) -> np.ndarray:
    SI = infl.sCOD_nb
    SS = infl.rbCOD
    XS = max(infl.bCOD - SS, 0.0)
    XI = max(infl.COD - infl.bCOD - SI, 0.0)
    org_n = max(infl.TKN - infl.NH3N, 0.0)
    v = np.zeros(13)
    v[I["SI"]], v[I["SS"]], v[I["XI"]], v[I["XS"]] = SI, SS, XI, XS
    v[I["SNH"]], v[I["SND"]], v[I["XND"]] = infl.NH3N, 0.3 * org_n, 0.7 * org_n
    v[I["SNO"]] = infl.NO3N
    v[I["SALK"]] = infl.alkalinity / 50.0
    return v


def simulate(infl: Influent, design: dict, dyn: DynamicInputs, pattern=None) -> dict:
    """design: activated-sludge design data (volumes m3, R, IR, srt_total, effluent TSS, DO, process)."""
    p = dyn.params
    T = infl.T_min
    Qa = infl.Q_m3d
    V_an, V_ax, V_ae = design["V_ana_m3"], design["V_anox_m3"], design["V_aer_m3"]
    vols = ([V_an] if V_an > 0 else []) + ([V_ax] if V_ax > 0 else []) + [V_ae / dyn.n_aerobic] * dyn.n_aerobic
    vols = np.array(vols)
    n = len(vols)
    aer = np.array([False] * (n - dyn.n_aerobic) + [True] * dyn.n_aerobic)
    i_anox = 1 if V_an > 0 and V_ax > 0 else (0 if V_ax > 0 else None)
    R, IR = design["R"], design["IR"]
    srt = design["srt_total"]
    do = design["do"]
    tss_e = design["tss_eff"]
    cin_avg = influent_vector(infl)

    pat = np.array(pattern or DEFAULT_DIURNAL, dtype=float)
    pat = pat / pat.mean()
    pk = pat.max()
    scale = (dyn.diurnal_pf - 1) / (pk - 1) if pk > 1 else 1.0
    pat = np.maximum(1 + (pat - 1) * scale, 0.05)

    def inflow(t, diurnal):
        if not diurnal:
            return Qa, cin_avg
        h = (t * 24.0) % 24.0
        k = int(h); fr = h - k
        fq = pat[k] * (1 - fr) + pat[(k + 1) % 24] * fr
        fc = 1 + dyn.conc_swing * (fq - 1)
        c = cin_avg.copy()
        for s in ("SS", "XS", "XI", "SNH", "SND", "XND"):
            c[I[s]] *= fc
        return Qa * fq, c

    def rhs(t, y, diurnal):
        C = y.reshape(n, 13).copy()
        C[aer, I["SO"]] = do
        Qin, cin = inflow(t, diurnal)
        Qr = R * Qa                       # constant RAS pumping (design ratio)
        Qir = IR * Qa
        last = C[-1]
        tss_last = dyn.TSS_COD * last[COD_PART].sum()
        frac_e = min(tss_e / max(tss_last, 1e-6), 1.0)
        mass = (C[:, COD_PART].sum(axis=1) * vols).sum()
        Qf = Qin + Qr
        # WAS paced so reactor mass / wasting rate = SRT (point settler, no blanket storage):
        # Qw * Xu = M/SRT with Xu = A/(Qr+Qw), A = Qf*X - Qe*Xe  ->  Qw = (M/SRT) Qr / (A - M/SRT)
        x_cod = last[COD_PART].sum()
        A = Qf * x_cod - Qin * frac_e * x_cod
        target = mass / srt
        Qw_eff = min(target * Qr / max(A - target, 1e-6), 0.5 * Qin)
        Qe = Qin - Qw_eff
        ras = last.copy()
        ras[PART] = (Qf * last[PART] - Qe * frac_e * last[PART]) / max(Qr + Qw_eff, 1e-9)
        ras_flow = Qr  # WAS leaves from the underflow; only Qr returns
        dC = np.zeros_like(C)
        Rr = _rates(C, p, T)
        for k in range(n):
            q_in_mix = 0.0; m_in = np.zeros(13)
            if k == 0:
                m_in += Qin * cin + ras_flow * ras; q_in_mix = Qin + ras_flow
                if i_anox == 0 and Qir:
                    m_in += Qir * last; q_in_mix += Qir
            else:
                q_prev = Qin + ras_flow + (Qir if (i_anox is not None and k - 1 >= i_anox) else 0.0)
                m_in += q_prev * C[k - 1]; q_in_mix = q_prev
                if i_anox == k and Qir:
                    m_in += Qir * last; q_in_mix += Qir
            q_out = q_in_mix
            dC[k] = (m_in - q_out * C[k]) / vols[k] + Rr[k]
        dC[aer, I["SO"]] = 0.0
        return dC.ravel()

    def oxygen_and_effluent(t, y, diurnal):
        C = y.reshape(n, 13).copy(); C[aer, I["SO"]] = do
        Qin, cin = inflow(t, diurnal)
        Rr = _rates(C, p, T)
        # O2 transfer required = -(reaction O2 rate) in aerobic tanks (flow term on DO is small, neglected)
        our = -(Rr[aer, I["SO"]] * vols[aer]).sum()     # g/d
        last = C[-1]
        tss_last = dyn.TSS_COD * last[COD_PART].sum()
        frac_e = min(tss_e / max(tss_last, 1e-6), 1.0)
        xe = last[COD_PART] * frac_e
        tkn = (last[I["SNH"]] + last[I["SND"]] + last[I["XND"]] * frac_e
               + p.iXB * (last[I["XBH"]] + last[I["XBA"]]) * frac_e + p.iXP * (last[I["XP"]] + last[I["XI"]]) * frac_e)
        return dict(Q=Qin, our=our, NH3=last[I["SNH"]], NO3=last[I["SNO"]], TKN=tkn,
                    TN=tkn + last[I["SNO"]], sCOD=last[I["SI"]] + last[I["SS"]],
                    MLSS=dyn.TSS_COD * C[0, COD_PART].sum(), alk=last[I["SALK"]] * 50)

    y0 = np.zeros((n, 13))
    y0[:] = cin_avg
    mlss_cod = design["mlss"] / dyn.TSS_COD
    for s, f in (("XBH", 0.35), ("XBA", 0.03), ("XS", 0.05), ("XI", 0.40), ("XP", 0.17)):
        y0[:, I[s]] = f * mlss_cod
    y0[:, I["SS"]] = 2.0; y0[:, I["SNH"]] = 2.0; y0[:, I["SNO"]] = 5.0
    y0[:, I["XND"]] = 0.02 * mlss_cod; y0[aer, I["SO"]] = do; y0[~aer, I["SO"]] = 0.0

    t_ss = max(4 * srt, 60.0)
    s1 = solve_ivp(rhs, (0, t_ss), y0.ravel(), method="BDF", args=(False,), rtol=1e-5, atol=1e-6)
    if not s1.success:
        raise RuntimeError("Steady-state start-up failed: " + s1.message)
    days = dyn.days_diurnal
    t_eval = np.linspace(0, days, days * 96 + 1)
    s2 = solve_ivp(rhs, (0, days), s1.y[:, -1], method="BDF", args=(True,), t_eval=t_eval,
                   rtol=1e-5, atol=1e-6, max_step=1 / 96)
    if not s2.success:
        raise RuntimeError("Diurnal simulation failed: " + s2.message)
    last_day = s2.t >= days - 1 - 1e-9
    ts = [oxygen_and_effluent(t, s2.y[:, j], True) for j, t in zip(np.where(last_day)[0], s2.t[last_day])]
    hours = (s2.t[last_day] - (days - 1)) * 24
    series = {k: np.array([d[k] for d in ts]) for k in ts[0]}
    steady = oxygen_and_effluent(0, s1.y[:, -1], False)
    return dict(hours=hours, series=series, steady=steady, n_tanks=n)


def design_dynamic(dyn: DynamicInputs, infl: Influent, as_data: dict, do: float, aotr_design_lb: float,
                   pattern=None, nh3_limit: float = 0.0) -> UnitResult:
    r = UnitResult("Dynamic Simulation (ASM1, diurnal)", "Secondary")
    design = dict(as_data); design["do"] = do
    design["tss_eff"] = as_data["effluent"]["TSS"]
    sim = simulate(infl, design, dyn, pattern)
    s = sim["series"]
    our_lb = s["our"] / 1000 * LB_PER_KG
    flow_wt = lambda x: float((x * s["Q"]).sum() / s["Q"].sum())
    r.i("Temperature (minimum month)", infl.T_min, "C"); r.i("Tanks in series", sim["n_tanks"])
    r.i("Diurnal peak factor", dyn.diurnal_pf); r.i("SRT held", as_data["srt_total"], "d")
    r.o("Flow-weighted effluent NH3-N", flow_wt(s["NH3"]), "mg/L")
    r.o("Peak effluent NH3-N", float(s["NH3"].max()), "mg/L")
    r.o("Flow-weighted effluent NO3-N", flow_wt(s["NO3"]), "mg/L")
    r.o("Flow-weighted effluent TN", flow_wt(s["TN"]), "mg/L")
    r.o("Peak effluent TN", float(s["TN"].max()), "mg/L")
    r.o("Effluent soluble COD (avg)", flow_wt(s["sCOD"]), "mg/L")
    r.o("MLSS (first tank, daily mean)", float(s["MLSS"].mean()), "mg/L")
    r.o("Oxygen demand, daily average", float(our_lb.mean()), "lb O2/d")
    r.o("Oxygen demand, diurnal peak", float(our_lb.max()), "lb O2/d")
    r.o("Peak / average oxygen demand", float(our_lb.max() / our_lb.mean()), "-", 2)
    r.o("Steady-state model effluent NH3-N", sim["steady"]["NH3"], "mg/L")
    r.c(custom_check("Diurnal peak O2 demand / design AOTR", float(our_lb.max()) / aotr_design_lb, "-", hi=1.0,
                     kind="typical", source="ASM1 dynamic check of aeration capacity (uncalibrated model)",
                     note="raise the O2 peak factor or confirm with calibrated parameters"))
    if nh3_limit > 0:
        r.c(custom_check("Flow-weighted dynamic effluent NH3-N vs permit limit", flow_wt(s["NH3"]), "mg/L",
                         hi=nh3_limit, kind="typical", source="Permit (monthly average)"))
    r.note("ASM1 with BSM1 default parameters (from literature, not calibrated). Point settler: no sludge-blanket storage.")
    r.data.update(hours=sim["hours"].tolist(), **{k: v.tolist() for k, v in s.items()},
                  our_lb=our_lb.tolist(), aotr_design_lb=aotr_design_lb)
    return r
