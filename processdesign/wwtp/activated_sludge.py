"""Activated sludge / biological nutrient removal: steady-state design.

Method follows the Metcalf & Eddy (5th ed., Ch. 7-8) steady-state approach:
SRT from nitrifier kinetics x safety factor, Monod effluent substrate,
biomass production (heterotrophs + cell debris + nitrifiers) with N-uptake
iteration, aerobic volume from solids inventory, MLE anoxic volume by SDNR,
A2O anaerobic zone by HRT with an rbCOD-limited EBPR estimate, chemical P
trim, oxygen demand with denitrification credit, and alkalinity balance.

Kinetic defaults are M&E 5th ed. Table 8-14 values (recalled, editable) -
calibrate to site data or a whole-plant simulator (e.g. ASM2d) before
final design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.criteria import default_library, custom_check
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import FT3_PER_M3, LB_PER_KG, MGD_TO_M3D, GAL_PER_FT3, load_lbd
from .influent import Influent

PROCESSES = ["CMAS (nitrifying)", "MLE (N removal)", "A2O (N + bio-P)", "Extended aeration"]


@dataclass
class Kinetics:
    mu_H: float = fld(6.0, "Heterotroph mu_max @20C", "g VSS/g VSS-d")
    th_mu_H: float = fld(1.07, "theta, mu_H")
    Ks: float = fld(8.0, "Heterotroph Ks", "g bCOD/m3")
    Y_H: float = fld(0.45, "Heterotroph yield", "g VSS/g bCOD")
    b_H: float = fld(0.12, "Heterotroph decay @20C", "1/d")
    th_b_H: float = fld(1.04, "theta, b_H")
    fd: float = fld(0.15, "Cell debris fraction", "-")
    mu_N: float = fld(0.90, "AOB mu_max @20C", "1/d")
    th_mu_N: float = fld(1.072, "theta, mu_AOB")
    Kn: float = fld(0.50, "AOB Kn", "g NH4-N/m3")
    Ko_N: float = fld(0.50, "AOB oxygen half-saturation", "g O2/m3")
    Y_N: float = fld(0.15, "Nitrifier yield", "g VSS/g NH4-N")
    b_N: float = fld(0.17, "AOB decay @20C", "1/d")
    th_b_N: float = fld(1.029, "theta, b_AOB")
    SDNR20: float = fld(0.07, "Specific denitrification rate @20C", "g NO3-N/g MLVSS-d",
                        help="Anoxic zone design rate; M&E gives F/M_b-dependent values - set from site data")
    th_SDNR: float = fld(1.026, "theta, SDNR")
    vss_tss_bio: float = fld(0.85, "Biomass VSS/TSS", "-")
    n_biomass: float = fld(0.12, "N content of biomass", "g N/g VSS")
    p_biomass: float = fld(0.015, "P content of ordinary biomass", "g P/g VSS")
    p_pao: float = fld(0.05, "P content of effluent VSS under EBPR", "g P/g VSS")
    rbcod_per_p: float = fld(10.0, "rbCOD required per P removed by EBPR", "g/g")
    rbcod_per_no3: float = fld(6.6, "rbCOD consumed per NO3-N entering anaerobic zone", "g/g")


@dataclass
class ASInputs:
    process: str = fld(PROCESSES[1], "Process configuration", choices=PROCESSES)
    nitrify: bool = fld(True, "Nitrification required")
    srt_override: float = fld(0.0, "Aerobic SRT override (0 = calculate)", "d", 0, 60)
    mlss: float = fld(3000.0, "Design MLSS", "mg/L", 1000, 8000)
    do: float = fld(2.0, "Aerobic zone DO", "mg/L", 0.5, 4.0)
    sf: float = fld(1.5, "Nitrification safety factor (peak/avg TKN)", "-", 1.0, 3.0)
    nh3_target: float = fld(1.0, "Effluent NH3-N target", "mg/L", 0.2, 10)
    no3_target: float = fld(8.0, "Effluent NO3-N target (MLE/A2O)", "mg/L", 2, 20)
    tss_eff: float = fld(10.0, "Effluent TSS from secondary clarifier", "mg/L", 2, 30)
    xr: float = fld(8000.0, "RAS concentration", "mg/L", 4000, 15000)
    anaerobic_hrt: float = fld(1.0, "Anaerobic zone HRT (A2O)", "h", 0.25, 3)
    chem_p: bool = fld(False, "Chemical P trim (alum)")
    tp_target: float = fld(1.0, "Effluent TP target", "mg/L", 0.05, 10)
    al_p_molar: float = fld(2.0, "Al : P molar dose ratio", "-", 1.0, 4.0)
    alk_target: float = fld(80.0, "Residual alkalinity target", "mg/L as CaCO3", 40, 200)
    n_trains: int = fld(2, "Aeration trains", "", 1, 12)
    swd_ft: float = fld(18.0, "Basin side water depth", "ft", 10, 30)
    lw_ratio: float = fld(4.0, "Basin length : width", "-", 1, 12)
    o2_peak_factor: float = fld(2.0, "Peak/average oxygen demand factor", "-", 1.0, 4.0)
    diurnal_load_factor: float = fld(1.5, "Diurnal peak / average BOD and NH3 load (regulatory O2 rule)", "-", 1.0, 3.0)
    anoxic_mixing_w_m3: float = fld(5.0, "Anoxic/anaerobic mixing power", "W/m3", 1, 15)
    kinetics: Kinetics = field(default_factory=Kinetics)


class WashoutError(ValueError):
    pass


def _tc(k20, theta, T):
    return k20 * theta ** (T - 20.0)


def min_nitrification_srt(kin: Kinetics, T: float, do: float, n_target: float) -> float:
    mu = _tc(kin.mu_N, kin.th_mu_N, T) * do / (kin.Ko_N + do)
    b = _tc(kin.b_N, kin.th_b_N, T)
    den = n_target * (mu - b) - kin.Kn * b
    if den <= 0:
        raise WashoutError(f"Effluent NH3-N of {n_target} mg/L is unattainable at {T:.1f} C and DO {do} mg/L.")
    return (kin.Kn + n_target) / den


def steady_state(infl: Influent, inp: ASInputs, srt: float, T: float) -> dict:
    """Mass balance at aerobic SRT ``srt`` (d) and temperature ``T`` (C)."""
    k = inp.kinetics
    Q = infl.Q_m3d
    S0 = infl.bCOD
    muH, bH = _tc(k.mu_H, k.th_mu_H, T), _tc(k.b_H, k.th_b_H, T)
    den = srt * (muH - bH) - 1
    if den <= 0:
        raise WashoutError(f"Heterotroph washout at SRT {srt:.2f} d, {T:.1f} C.")
    S = k.Ks * (1 + bH * srt) / den

    nitrify = inp.nitrify or inp.process == PROCESSES[3]
    muN = _tc(k.mu_N, k.th_mu_N, T) * inp.do / (k.Ko_N + inp.do)
    bN = _tc(k.b_N, k.th_b_N, T)
    if nitrify:
        dn = srt * (muN - bN) - 1
        if dn <= 0:
            raise WashoutError(f"Nitrifier washout at SRT {srt:.2f} d, {T:.1f} C - increase SRT or DO.")
        Ne = k.Kn * (1 + bN * srt) / dn
    else:
        Ne = None

    PX_H = Q * k.Y_H * (S0 - S) / (1 + bH * srt) / 1000.0          # kg VSS/d
    PX_D = k.fd * bH * PX_H * srt
    NOx = 0.8 * infl.TKN if nitrify else 0.0
    for _ in range(50):
        PX_N = Q * k.Y_N * NOx / (1 + bN * srt) / 1000.0 if nitrify else 0.0
        PX_bio = PX_H + PX_D + PX_N
        n_syn = k.n_biomass * PX_bio * 1000.0 / Q
        if nitrify:
            new = max(infl.TKN - Ne - n_syn, 0.0)
        else:
            new = 0.0
            Ne = max(infl.TKN - n_syn - 1.0, 0.0)                  # ~1 mg/L refractory organic N
        if abs(new - NOx) < 1e-6:
            NOx = new
            break
        NOx = new
    PX_N = Q * k.Y_N * NOx / (1 + bN * srt) / 1000.0 if nitrify else 0.0
    PX_bio = PX_H + PX_D + PX_N
    nbVSS_kg = Q * infl.nbVSS / 1000.0
    iTSS_kg = Q * infl.iTSS / 1000.0
    PX_VSS = PX_bio + nbVSS_kg
    PX_TSS = PX_bio / k.vss_tss_bio + nbVSS_kg + iTSS_kg
    return dict(S=S, Ne=Ne, NOx=NOx, PX_H=PX_H, PX_D=PX_D, PX_N=PX_N, PX_bio=PX_bio,
                PX_VSS=PX_VSS, PX_TSS=PX_TSS, muH=muH, bH=bH, muN=muN, bN=bN, nitrify=nitrify)


def design_activated_sludge(inp: ASInputs, infl: Influent, lib=None) -> UnitResult:
    lib = lib or default_library()
    k = inp.kinetics
    proc = inp.process
    is_mle = proc in (PROCESSES[1], PROCESSES[2])
    is_a2o = proc == PROCESSES[2]
    is_ext = proc == PROCESSES[3]
    nitrify = inp.nitrify or is_ext or is_mle
    r = UnitResult(f"Activated Sludge - {proc}", "Secondary")
    Tmin, Tmax = infl.T_min, infl.T_max
    Q = infl.Q_m3d

    # ---- SRT -------------------------------------------------------------
    if inp.srt_override > 0:
        srt = inp.srt_override
        srt_basis = "user override"
    elif nitrify:
        srt_min = min_nitrification_srt(k, Tmin, inp.do, inp.nh3_target)
        srt = inp.sf * srt_min
        srt_basis = f"{inp.sf} x theoretical {srt_min:.2f} d at {Tmin} C"
        if is_ext:
            srt = max(srt, 20.0); srt_basis += " (extended aeration min 20 d)"
    else:
        srt = 20.0 if is_ext else 5.0
        srt_basis = "process default"

    cold = steady_state(infl.copy(), _with(inp, nitrify), srt, Tmin)
    warm = steady_state(infl.copy(), _with(inp, nitrify), srt, Tmax)

    # ---- volumes ----------------------------------------------------------
    R = inp.mlss / (inp.xr - inp.mlss)
    mass_tss_kg = cold["PX_TSS"] * srt
    V_aer = mass_tss_kg * 1000.0 / inp.mlss                      # m3
    mlvss = inp.mlss * cold["PX_VSS"] / cold["PX_TSS"]

    NOx = cold["NOx"]
    no3_e = NOx
    IR = 0.0
    V_anox = 0.0
    no3_den_kg = 0.0
    if is_mle and NOx > inp.no3_target:
        no3_e = inp.no3_target
        IR = max(NOx / no3_e - 1.0 - R, 0.0)
        no3_den_kg = Q * (NOx - no3_e) / 1000.0
        sdnr = _tc(k.SDNR20, k.th_SDNR, Tmin)
        V_anox = no3_den_kg * 1000.0 / (sdnr * mlvss)
    V_ana = Q * inp.anaerobic_hrt / 24.0 if is_a2o else 0.0
    V_tot = V_aer + V_anox + V_ana
    srt_total = srt * V_tot / V_aer

    # ---- phosphorus -----------------------------------------------------
    p_syn = k.p_biomass * cold["PX_bio"] * 1000.0 / Q
    p_ebpr = 0.0
    if is_a2o:
        rb_avail = max(infl.rbCOD - k.rbcod_per_no3 * R * no3_e, 0.0)
        p_ebpr = rb_avail / k.rbcod_per_p
    sp_e = max(infl.TP - p_syn - p_ebpr, 0.05)
    p_frac_e = k.p_pao if is_a2o else k.p_biomass
    pp_e = inp.tss_eff * k.vss_tss_bio * p_frac_e
    alum_lb = chem_tss_kg = alk_chem = 0.0
    if inp.chem_p and sp_e + pp_e > inp.tp_target:
        p_rm = sp_e - max(inp.tp_target - pp_e, 0.05)
        mol_p = p_rm / 30.97                                      # mmol/L
        mol_al = inp.al_p_molar * mol_p
        alum_mgl = mol_al / 2 * 594.4                             # Al2(SO4)3.14H2O
        alum_lb = load_lbd(infl.Q_avg, alum_mgl)
        chem_tss_mgl = mol_p * 121.95 + max(mol_al - mol_p, 0) * 78.0
        chem_tss_kg = Q * chem_tss_mgl / 1000.0
        alk_chem = mol_al * 3 * 50.0 / 1                          # mg/L as CaCO3 (3 eq/mol Al)
        sp_e -= p_rm
    tp_e = sp_e + pp_e

    # ---- WAS / RAS ------------------------------------------------------
    PX_TSS_tot = cold["PX_TSS"] + chem_tss_kg
    if chem_tss_kg:
        V_aer *= PX_TSS_tot / cold["PX_TSS"]
        V_tot = V_aer + V_anox + V_ana
        srt_total = srt * V_tot / V_aer
    was_kg = PX_TSS_tot - Q * inp.tss_eff / 1000.0
    was_lb = was_kg * LB_PER_KG
    was_gpd = was_lb / (inp.xr * 8.34) * 1e6

    # ---- oxygen -----------------------------------------------------------
    def o2(ss):
        return (Q * (infl.bCOD - ss["S"]) / 1000.0 - 1.42 * ss["PX_bio"]
                + 4.57 * Q * ss["NOx"] / 1000.0 - 2.86 * (Q * (ss["NOx"] - min(no3_e, ss["NOx"])) / 1000.0 if is_mle else 0.0))
    o2_avg_kg = max(o2(cold), o2(warm))
    o2_avg_lb = o2_avg_kg * LB_PER_KG
    loads = infl.loads()
    o2_key = "as_o2_per_bod_ext" if is_ext else "as_o2_per_bod"
    peak_bod_lb = loads["BOD"] * inp.diurnal_load_factor
    nod = lib.get("as_nod_factor").typical * loads["NH3N"] * inp.diurnal_load_factor if nitrify else 0.0
    o2_10ss_min = lib.get(o2_key).min * peak_bod_lb + nod     # 1.1 (1.5 ext.) x peak BOD5 + 4.6 x peak NH3-N
    o2_design_lb = max(o2_avg_lb * inp.o2_peak_factor, o2_10ss_min)

    # ---- alkalinity -------------------------------------------------------
    denit = (NOx - no3_e) if is_mle else 0.0
    alk_e = infl.alkalinity - 7.14 * NOx + 3.57 * denit - alk_chem
    alk_add_mgl = max(inp.alk_target - alk_e, 0.0)
    alk_add_lb = load_lbd(infl.Q_avg, alk_add_mgl)

    # ---- effluent -----------------------------------------------------------
    sbod_e = cold["S"] / infl.bCOD_BOD
    bod_e = sbod_e + 0.66 * inp.tss_eff
    nh3_e = cold["Ne"] if nitrify else cold["Ne"]
    on_e = 1.0 + k.n_biomass * k.vss_tss_bio * inp.tss_eff
    tkn_e = nh3_e + on_e
    tn_e = tkn_e + no3_e

    # ---- geometry & loading -------------------------------------------------
    V_ft3 = V_tot * FT3_PER_M3
    V_train = V_ft3 / inp.n_trains
    W = math.sqrt(V_train / (inp.swd_ft * inp.lw_ratio))
    L = inp.lw_ratio * W
    hrt = V_tot / Q * 24
    fm = loads["BOD"] / (V_ft3 * GAL_PER_FT3 / 1e6 * mlvss * 8.34)
    fm_mlss = loads["BOD"] / (V_ft3 * GAL_PER_FT3 / 1e6 * inp.mlss * 8.34)
    vol_load = loads["BOD"] / (V_ft3 / 1000.0)

    # ---- report -----------------------------------------------------------
    r.i("Influent flow", infl.Q_avg, "MGD"); r.i("Influent BOD5", infl.BOD, "mg/L")
    r.i("Influent bCOD", infl.bCOD, "mg/L"); r.i("Influent TKN", infl.TKN, "mg/L")
    r.i("Influent TP", infl.TP, "mg/L"); r.i("Design temperature (min / max)", f"{Tmin:g} / {Tmax:g}", "C")
    r.i("MLSS", inp.mlss, "mg/L"); r.i("DO", inp.do, "mg/L"); r.i("RAS concentration", inp.xr, "mg/L")
    r.o("Aerobic SRT", srt, "d"); r.o("SRT basis", srt_basis)
    r.o("Total system SRT", srt_total, "d")
    r.o("Aerobic volume", V_aer * FT3_PER_M3 * GAL_PER_FT3 / 1e6, "MG", 3)
    if V_anox: r.o("Anoxic volume", V_anox * FT3_PER_M3 * GAL_PER_FT3 / 1e6, "MG", 3)
    if V_ana: r.o("Anaerobic volume", V_ana * FT3_PER_M3 * GAL_PER_FT3 / 1e6, "MG", 3)
    r.o("Total bioreactor volume", V_ft3 * GAL_PER_FT3 / 1e6, "MG", 3)
    r.o("Basin size per train (L x W x SWD)", f"{L:.0f} x {W:.0f} x {inp.swd_ft:g}", "ft")
    r.o("Hydraulic retention time", hrt, "h")
    r.o("MLVSS", mlvss, "mg/L")
    r.o("F/M (BOD5/MLVSS)", fm, "1/d", 3)
    r.o("F/M (BOD5/MLSS)", fm_mlss, "1/d", 3)
    r.o("Volumetric BOD5 loading", vol_load, "lb/1000 ft3-d")
    r.o("RAS ratio", R, "x Q"); r.o("RAS flow", R * infl.Q_avg, "MGD", 2)
    if is_mle: r.o("Internal recycle ratio", IR, "x Q")
    r.o("Net sludge production (TSS)", PX_TSS_tot * LB_PER_KG, "lb/d")
    r.o("Observed yield", PX_TSS_tot / (Q * infl.bCOD / 1000.0), "g TSS/g bCOD", 3)
    r.o("WAS solids", was_lb, "lb/d"); r.o("WAS flow (from RAS)", was_gpd, "gpd")
    r.o("Nitrogen nitrified (NOx)", NOx, "mg/L")
    if is_mle: r.o("Nitrate denitrified", denit, "mg/L")
    r.o("Average oxygen demand (AOTR)", o2_avg_lb, "lb O2/d")
    r.o("Regulatory minimum O2 (peak BOD5 + 4.6 x peak NH3-N)", o2_10ss_min, "lb O2/d")
    r.o("Design oxygen demand (AOTR, peak)", o2_design_lb, "lb O2/d")
    r.o("Effluent alkalinity before supplement", alk_e, "mg/L as CaCO3")
    if alk_add_lb: r.o("Supplemental alkalinity", alk_add_lb, "lb CaCO3/d")
    if alk_add_lb: r.o("  as 100% NaOH", alk_add_lb * 0.8, "lb/d")
    if alum_lb: r.o("Alum dose (dry, as 14H2O)", alum_lb, "lb/d")
    if alum_lb: r.o("Alum, 48.5% liquid", alum_lb / 5.4, "gal/d")
    r.o("Effluent sBOD5", sbod_e, "mg/L"); r.o("Effluent BOD5", bod_e, "mg/L")
    r.o("Effluent NH3-N", nh3_e, "mg/L"); r.o("Effluent TKN", tkn_e, "mg/L")
    r.o("Effluent NO3-N", no3_e, "mg/L"); r.o("Effluent TN", tn_e, "mg/L")
    r.o("Effluent TP", tp_e, "mg/L")

    r.c(lib.check(inp.do, "as_do"))
    r.c(lib.check(inp.swd_ft, "as_depth"))
    r.c(lib.check(inp.mlss, "as_mlss"))
    r.c(lib.check(fm_mlss, "as_fm_extended" if (is_ext or nitrify) else "as_fm_conventional"))
    vkey = ("as_vol_load_extended" if (is_ext or nitrify) else
            ("as_vol_load_conventional" if infl.Q_avg >= 1.0 else "as_vol_load_conventional_small"))
    r.c(lib.check(vol_load, vkey))
    if is_ext:
        r.c(lib.check(hrt, "as_ext_hrt"))
    r.c(lib.check(R, "as_ras_ratio"))
    r.c(lib.check(alk_e if not alk_add_lb else inp.alk_target, "as_alk_residual",
                  note="with supplemental alkalinity" if alk_add_lb else ""))
    r.c(lib.check(inp.o2_peak_factor, "as_o2_peak_factor"))
    if is_mle: r.c(lib.check(IR, "as_ir_ratio"))
    if is_a2o: r.c(lib.check(inp.anaerobic_hrt, "as_anaerobic_hrt"))
    if is_mle:
        r.c(custom_check("Influent BOD5/TKN (carbon for denitrification)", infl.BOD / infl.TKN, "-",
                         lo=4.0, source="M&E-5 rule of thumb", note="low ratio may need supplemental carbon"))
    if is_a2o:
        r.c(custom_check("Influent rbCOD/TP (EBPR reliability)", infl.rbCOD / max(infl.TP, 1e-6), "-",
                         lo=15.0, source="M&E-5 typical", note="low ratio: plan chemical P backup"))
    if inp.nitrify and cold["Ne"] and cold["Ne"] > inp.nh3_target * 1.01:
        r.note(f"Predicted effluent NH3-N {cold['Ne']:.2f} mg/L exceeds the target.")
    r.note("Oxygen demand evaluated at both min and max month temperature; the larger governs.")
    r.note("Kinetic coefficients are textbook defaults - calibrate with site data or confirm with a dynamic simulator.")

    r.data.update(
        srt=srt, srt_total=srt_total, V_aer_m3=V_aer, V_anox_m3=V_anox, V_ana_m3=V_ana,
        V_tot_ft3=V_ft3, R=R, IR=IR, mlvss=mlvss, was_lb=was_lb, was_gpd=was_gpd,
        was_vss_lb=was_lb * cold["PX_VSS"] / PX_TSS_tot,
        was_vss_frac=cold["PX_VSS"] / PX_TSS_tot,
        was_N_frac=k.n_biomass * cold["PX_bio"] / PX_TSS_tot,
        was_P_frac=(p_syn + p_ebpr) * Q / 1000.0 / PX_TSS_tot,
        o2_avg_lb=o2_avg_lb, o2_design_lb=o2_design_lb,
        effluent=dict(BOD=bod_e, sBOD=sbod_e, TSS=inp.tss_eff, NH3N=nh3_e, TKN=tkn_e,
                      NO3N=no3_e, TN=tn_e, TP=tp_e, alkalinity=alk_e + alk_add_mgl),
        mlss=inp.mlss, xr=inp.xr, n_trains=inp.n_trains, L_ft=L, W_ft=W,
        mix_kw=(V_anox + V_ana) * inp.anoxic_mixing_w_m3 / 1000, alum_gpd=alum_lb / 5.4, swd_ft=inp.swd_ft, basin_area_ft2=V_ft3 / inp.swd_ft,
        alum_lb=alum_lb, alk_add_lb=alk_add_lb, nitrify=nitrify, process=proc,
    )
    return r


def _with(inp: ASInputs, nitrify: bool) -> ASInputs:
    from dataclasses import replace
    return replace(inp, nitrify=nitrify)
