"""Secondary (final) clarifiers: Ten States SOR/SLR sizing plus
state-point / solids-flux analysis using Vesilind settling parameters."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.criteria import default_library, custom_check
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import round_up, FT_PER_M

PROCESS_CLASS = ["conventional", "nitrifying", "chemP"]


@dataclass
class SecondaryInputs:
    n_units: int = fld(2, "Number of clarifiers", "", 1, 16)
    swd_ft: float = fld(14.0, "Side water depth", "ft", 10, 25)
    sor_avg_design: float = fld(600.0, "Design SOR at average flow", "gpd/ft2", 300, 900)
    ras_max_ratio: float = fld(1.0, "Maximum RAS ratio (solids loading and peak state point)", "x Q", 0.25, 2.0)
    svi: float = fld(150.0, "Design SVI", "mL/g", 50, 400)
    v0_override: float = fld(0.0, "Vesilind V0 from settling tests (0 = SVI correlation)", "m/h", 0, 20)
    k_override: float = fld(0.0, "Vesilind k from settling tests (0 = SVI correlation)", "L/g", 0, 2)
    diameter_step_ft: float = fld(5.0, "Round diameter up to", "ft", 1, 10)
    double_weir: bool = fld(False, "Double-sided (inboard) effluent launder")
    limit_class: str = fld("auto", "Ten States process class",
                           choices=["auto", "conventional", "nitrifying", "chemP"])


def vesilind_from_svi(svi: float) -> tuple[float, float]:
    """Daigger (1995) correlation: ln Vs = 1.871 - (0.1646 + 0.001586 SVI) X.

    Returns V0 (m/h) and k (L/g). Replace with site settling tests when available.
    """
    return math.exp(1.871), 0.1646 + 0.001586 * svi


def limiting_flux(v0_mh: float, k_lg: float, u_mh: float) -> tuple[float, float]:
    """Limiting total flux (kg/m2-h) and underflow concentration (g/L) for underflow velocity u."""
    X = np.linspace(0.5, 30.0, 6000)                     # g/L = kg/m3
    G = v0_mh * X * np.exp(-k_lg * X) + u_mh * X
    # limiting flux = local minimum of total flux curve beyond the gravity-flux peak
    dG = np.gradient(G, X)
    idx = np.where((dG[:-1] < 0) & (dG[1:] >= 0))[0]
    if len(idx):
        GL = float(G[idx[0]])
        return GL, GL / u_mh
    # total-flux curve monotonic: underflow rate high enough that thickening never limits
    return float("inf"), float("inf")


def design_secondary_clarifier(inp: SecondaryInputs, Q_avg: float, Q_peak: float, Q_maxday: float,
                               mlss: float, ras_ratio: float, process_class: str,
                               lib=None) -> UnitResult:
    lib = lib or default_library()
    cls = process_class if inp.limit_class == "auto" else inp.limit_class
    r = UnitResult("Secondary Clarifiers", "Secondary")
    sor_lim = lib.get(f"sec_sor_peak_{cls}").max
    slr_lim = lib.get(f"sec_slr_peak_{cls}").max
    solids_peak = (Q_maxday + inp.ras_max_ratio * Q_avg) * mlss * 8.34   # lb/d

    a_req = max(Q_avg * 1e6 / inp.sor_avg_design, Q_peak * 1e6 / sor_lim, solids_peak / slr_lim)
    governs = ["average SOR", "peak SOR", "peak solids loading"][
        int(np.argmax([Q_avg * 1e6 / inp.sor_avg_design, Q_peak * 1e6 / sor_lim, solids_peak / slr_lim]))]
    D = round_up(math.sqrt(4 * a_req / inp.n_units / math.pi), inp.diameter_step_ft)
    A = inp.n_units * math.pi * D**2 / 4
    sor_avg, sor_pk = Q_avg * 1e6 / A, Q_peak * 1e6 / A
    slr_pk = solids_peak / A
    weir = Q_peak * 1e6 / (inp.n_units * math.pi * (D - 2.0) * (2 if inp.double_weir else 1))

    # ---- state point -------------------------------------------------------------
    # average flow at the design RAS ratio (operating point) and peak hour with the
    # RAS raised to its maximum (the condition the clarifier must survive)
    v0, k = vesilind_from_svi(inp.svi)
    if inp.v0_override > 0 and inp.k_override > 0:
        v0, k = inp.v0_override, inp.k_override
    A_m2 = A / FT_PER_M**2
    X = mlss / 1000.0
    m3h = 3785.41 / 24
    q_avg_m3h, q_pk_m3h = Q_avg * m3h, Q_peak * m3h
    qr_avg = ras_ratio * Q_avg * m3h
    qr_pk = max(inp.ras_max_ratio, ras_ratio) * Q_avg * m3h
    GL_avg, _ = limiting_flux(v0, k, qr_avg / A_m2)
    applied_avg = (q_avg_m3h + qr_avg) * X / A_m2
    u = qr_pk / A_m2
    sor_mh = q_pk_m3h / A_m2
    applied = (q_pk_m3h + qr_pk) * X / A_m2                 # kg/m2-h
    GL, Xu = limiting_flux(v0, k, u)
    vs_X = v0 * math.exp(-k * X)
    ratio_avg = applied_avg / GL_avg if math.isfinite(GL_avg) else 0.0
    flux_ratio = applied / GL if math.isfinite(GL) else 0.0
    if not math.isfinite(GL):
        GL, Xu = 0.0, 0.0
        r.note("Total-flux curve has no minimum at this RAS rate: thickening does not limit (limiting flux reported as 0).")

    r.i("Average / max-day / peak flow", f"{Q_avg:.2f} / {Q_maxday:.2f} / {Q_peak:.2f}", "MGD")
    r.i("MLSS", mlss, "mg/L"); r.i("Design RAS ratio", ras_ratio); r.i("SVI", inp.svi, "mL/g")
    r.i("Ten States class", cls)
    r.o("Governing criterion", governs)
    r.o("Diameter (each)", D, "ft", 0); r.o("Total area", A, "ft2")
    r.o("SOR at average flow", sor_avg, "gpd/ft2"); r.o("SOR at peak hour", sor_pk, "gpd/ft2")
    r.o("Peak solids loading", slr_pk, "lb/d-ft2")
    r.o("Weir loading at peak hour", weir, "gpd/ft")
    r.o("Vesilind V0 / k", f"{v0:.2f} m/h / {k:.3f} L/g")
    r.o("Hindered settling velocity at MLSS", vs_X, "m/h")
    r.o("Peak overflow velocity", sor_mh, "m/h")
    r.o("Applied / limiting flux, average flow @ design RAS", ratio_avg, "-", 2)
    r.o("RAS ratio for peak-hour state point", max(inp.ras_max_ratio, ras_ratio), "x Q")
    r.o("Applied solids flux at peak", applied, "kg/m2-h")
    r.o("Limiting solids flux", GL, "kg/m2-h")
    r.o("Applied / limiting flux", flux_ratio, "-", 2)
    r.o("Underflow concentration at limit", Xu * 1000, "mg/L")

    r.c(lib.check(inp.swd_ft, "sec_swd"))
    r.c(lib.check(sor_pk, f"sec_sor_peak_{cls}"))
    r.c(lib.check(slr_pk, f"sec_slr_peak_{cls}"))
    r.c(lib.check(sor_avg, "sec_sor_avg"))
    wkey = "weir_lt_0.1" if Q_avg < 0.1 else ("weir_0.1_1" if Q_avg <= 1.0 else "weir_gt_1")
    r.c(lib.check(weir, wkey))
    r.c(custom_check("State point: applied / limiting flux at peak hour (max RAS)", flux_ratio, "-", hi=1.0,
                     kind="limit", source="Solids flux theory (Vesilind; Daigger SVI correlation)",
                     note="thickening failure / blanket rise if > 1"))
    r.c(custom_check("State point: overflow / hindered settling velocity", sor_mh / vs_X, "-", hi=1.0,
                     kind="limit", source="Solids flux theory", note="clarification failure if > 1"))
    if inp.n_units < 2:
        r.note("Single final clarifier: verify R.61-67 reliability classification requirements.")
    r.data.update(diameter=D, area=A, Xu=Xu * 1000, flux_ratio=flux_ratio, v0=v0, k=k, u=u, X=X, sor_mh=sor_mh, n=inp.n_units, swd=inp.swd_ft,
                  double_weir=inp.double_weir)
    return r
