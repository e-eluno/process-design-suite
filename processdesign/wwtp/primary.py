"""Primary clarification: circular clarifier sizing, removal performance,
primary sludge production."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.criteria import default_library
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import GAL_PER_FT3, load_lbd, round_up
from .influent import Influent


@dataclass
class PrimaryInputs:
    enabled: bool = fld(True, "Include primary clarifiers")
    n_units: int = fld(2, "Number of clarifiers", "", 1, 12)
    sor_avg_design: float = fld(800.0, "Design SOR at average flow", "gpd/ft2", 400, 1200)
    swd_ft: float = fld(10.0, "Side water depth", "ft", 7, 20)
    receives_was: bool = fld(False, "WAS co-settled in primaries")
    sludge_solids_pct: float = fld(4.0, "Primary sludge solids", "%", 1, 8)
    sludge_sg: float = fld(1.02, "Primary sludge specific gravity", "-", 1.0, 1.1)
    double_weir: bool = fld(True, "Double-sided (inboard) effluent launder")
    diameter_step_ft: float = fld(5.0, "Round diameter up to", "ft", 1, 10)
    n_org_frac_vss: float = fld(0.08, "Organic N content of removed VSS", "g N/g VSS", 0.02, 0.12)
    p_frac_vss: float = fld(0.015, "P content of removed VSS", "g P/g VSS", 0.005, 0.03)


def removal_efficiency(t_h: float) -> tuple[float, float]:
    """Empirical BOD and TSS removal (fraction) vs detention time (h).

    R = t / (a + b t); BOD a=0.018, b=0.020; TSS a=0.0075, b=0.014
    (Crites & Tchobanoglous; reproduced in M&E 5th ed.)
    """
    r_bod = t_h / (0.018 + 0.020 * t_h) / 100.0
    r_tss = t_h / (0.0075 + 0.014 * t_h) / 100.0
    return r_bod, r_tss


def design_primary(inp: PrimaryInputs, infl: Influent, lib=None) -> tuple[UnitResult, Influent, dict]:
    lib = lib or default_library()
    r = UnitResult("Primary Clarifiers", "Primary")
    Q, Qp = infl.Q_avg, infl.Q_peak
    sfx = "WAS" if inp.receives_was else "noWAS"
    sor_pk_lim = lib.get(f"pri_sor_peak_{sfx}").max
    sor_avg_lim = lib.get(f"pri_sor_avg_{sfx}").max
    area_req = max(Q * 1e6 / min(inp.sor_avg_design, sor_avg_lim), Qp * 1e6 / sor_pk_lim)
    a_each = area_req / inp.n_units
    D = round_up(math.sqrt(4 * a_each / math.pi), inp.diameter_step_ft)
    A = inp.n_units * math.pi * D**2 / 4
    sor_avg, sor_pk = Q * 1e6 / A, Qp * 1e6 / A
    V = A * inp.swd_ft
    hrt = V * GAL_PER_FT3 / (Q * 1e6) * 24
    hrt_pk = V * GAL_PER_FT3 / (Qp * 1e6) * 24
    weir_len = inp.n_units * math.pi * (D - 2.0) * (2 if inp.double_weir else 1)   # inboard launder ~1 ft from wall
    weir_load = Qp * 1e6 / weir_len

    r_bod, r_tss = removal_efficiency(hrt)
    tss_rem = infl.TSS * r_tss
    vss_rem = infl.VSS * r_tss
    bod_e = infl.BOD * (1 - r_bod)
    sludge_lb = load_lbd(Q, tss_rem)
    sludge_gpd = sludge_lb / (inp.sludge_solids_pct / 100 * 8.34 * inp.sludge_sg)

    eff = infl.copy(
        BOD=bod_e, TSS=infl.TSS - tss_rem, VSS=infl.VSS - vss_rem,
        COD=infl.sCOD + infl.pCOD * (1 - r_tss),
        TKN=max(infl.TKN - inp.n_org_frac_vss * vss_rem, infl.NH3N),
        TP=max(infl.TP - inp.p_frac_vss * vss_rem, 0.0),
    )
    # keep soluble fractions; BOD removed can't take soluble BOD below sBOD
    if eff.BOD < eff.sBOD:
        eff.BOD = eff.sBOD

    r.i("Average flow", Q, "MGD"); r.i("Peak hourly flow", Qp, "MGD")
    r.i("Clarifiers", inp.n_units); r.i("Side water depth", inp.swd_ft, "ft")
    r.i("Receives WAS", inp.receives_was)
    r.o("Diameter (each)", D, "ft", 0); r.o("Total surface area", A, "ft2")
    r.o("SOR at average flow", sor_avg, "gpd/ft2"); r.o("SOR at peak hour", sor_pk, "gpd/ft2")
    r.o("Detention at average flow", hrt, "h"); r.o("Detention at peak hour", hrt_pk, "h")
    r.o("Weir loading at peak hour", weir_load, "gpd/ft")
    r.o("BOD5 removal", 100 * r_bod, "%"); r.o("TSS removal", 100 * r_tss, "%")
    r.o("Primary effluent BOD5", eff.BOD, "mg/L"); r.o("Primary effluent TSS", eff.TSS, "mg/L")
    r.o("Primary effluent TKN", eff.TKN, "mg/L"); r.o("Primary effluent TP", eff.TP, "mg/L")
    r.o("Primary sludge", sludge_lb, "lb/d"); r.o("Primary sludge volume", sludge_gpd, "gpd")

    r.c(lib.check(sor_avg, f"pri_sor_avg_{sfx}"))
    r.c(lib.check(sor_pk, f"pri_sor_peak_{sfx}"))
    r.c(lib.check(inp.swd_ft, "pri_swd"))
    r.c(lib.check(hrt, "pri_hrt"))
    wkey = "weir_lt_0.1" if Q < 0.1 else ("weir_0.1_1" if Q <= 1.0 else "weir_gt_1")
    r.c(lib.check(weir_load, wkey))
    if inp.n_units < 2:
        r.note("Single clarifier: provide bypass/redundancy per R.61-67 reliability class.")

    sludge = {"TSS_lb": sludge_lb, "VSS_lb": load_lbd(Q, vss_rem), "flow_gpd": sludge_gpd,
              "solids_pct": inp.sludge_solids_pct,
              "N_lb": load_lbd(Q, inp.n_org_frac_vss * vss_rem),
              "P_lb": load_lbd(Q, inp.p_frac_vss * vss_rem)}
    r.data.update(diameter=D, area=A, sludge=sludge, n=inp.n_units, swd=inp.swd_ft, double_weir=inp.double_weir)
    return r, eff, sludge
