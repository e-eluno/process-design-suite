"""US-customary <-> SI conversion constants used across all modules.

Convention: public inputs/outputs are US customary (MGD, mg/L, ft, lb/d, psi,
deg F where noted). Kinetic calculations run internally in SI (m3/d, g/m3, kg/d).
"""

import math

MGD_TO_M3D = 3785.411784          # 1 MGD in m3/d
MGD_TO_CFS = 1.547228670          # 1 MGD in ft3/s
MGD_TO_GPM = 694.4444444          # 1 MGD in gal/min
GAL_PER_FT3 = 7.480519
FT3_PER_M3 = 35.31467
LB_PER_KG = 2.204623
KG_PER_LB = 0.45359237
LB_FACTOR = 8.34                  # lb/d = MGD x mg/L x 8.34
G_FT = 32.174                     # ft/s2
PSI_PER_FT_WATER = 0.4335
P_ATM_PSI = 14.696
FT_PER_M = 3.28084


def load_lbd(q_mgd: float, conc_mgl: float) -> float:
    """Mass load in lb/d from flow (MGD) and concentration (mg/L)."""
    return q_mgd * conc_mgl * LB_FACTOR


def conc_mgl(load_lbd_: float, q_mgd: float) -> float:
    return load_lbd_ / (q_mgd * LB_FACTOR) if q_mgd > 0 else 0.0


def kgd_to_lbd(kgd: float) -> float:
    return kgd * LB_PER_KG


def c_to_f(t_c: float) -> float:
    return t_c * 9.0 / 5.0 + 32.0


def f_to_c(t_f: float) -> float:
    return (t_f - 32.0) * 5.0 / 9.0


def barometric_psi(elevation_ft: float) -> float:
    """Standard-atmosphere barometric pressure at elevation (psia)."""
    return P_ATM_PSI * (1.0 - 6.8754e-6 * elevation_ft) ** 5.2559


def round_up(x: float, step: float) -> float:
    return math.ceil(x / step - 1e-9) * step
