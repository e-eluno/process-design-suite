"""Diffused aeration: AOTR -> SOTR conversion, air flow, mixing check,
blower discharge pressure and power."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.criteria import default_library
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import P_ATM_PSI, PSI_PER_FT_WATER, barometric_psi, f_to_c

AIR_DENSITY_STD = 0.0750      # lb/ft3 at 68 F, 14.7 psia, 36% RH (standard ft3)
O2_MASS_FRAC = 0.2315
STD_MOTORS_HP = [5, 7.5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300,
                 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1250, 1500]


@dataclass
class AerationInputs:
    diffuser: str = fld("Fine bubble (membrane disc)", "Diffuser type",
                        choices=["Fine bubble (membrane disc)", "Fine bubble (ceramic dome)", "Coarse bubble"])
    submergence_ft: float = fld(16.0, "Diffuser submergence", "ft", 5, 30)
    sote_per_ft: float = fld(2.0, "SOTE per ft of submergence", "%/ft", 0.5, 3.0,
                             help="Fine bubble ~1.8-2.2 %/ft; coarse bubble ~0.6-0.8 %/ft (vendor data governs)")
    alpha: float = fld(0.50, "Alpha (process/clean water)", "-", 0.2, 1.0)
    beta: float = fld(0.95, "Beta (salinity-surface tension)", "-", 0.8, 1.0)
    fouling: float = fld(0.90, "Fouling factor F", "-", 0.5, 1.0)
    theta: float = fld(1.024, "Temperature correction theta", "-", 1.0, 1.05)
    o2_exit_pct: float = fld(19.0, "O2 in exit gas", "%", 15, 21)
    elevation_ft: float = fld(300.0, "Site elevation", "ft", -200, 10000)
    T_water_C: float = fld(25.0, "Design (summer) water temperature", "C", 4, 40)
    inlet_air_F: float = fld(115.0, "Blower design inlet air temperature", "F", 40, 130)
    piping_loss_psi: float = fld(1.0, "Header / piping losses", "psi", 0, 5)
    diffuser_loss_psi: float = fld(0.5, "Diffuser head loss", "psi", 0, 2)
    blower_eff: float = fld(0.70, "Blower wire-to-air efficiency", "-", 0.4, 0.85)
    n_duty: int = fld(3, "Duty blowers", "", 1, 12)
    n_standby: int = fld(1, "Standby blowers", "", 0, 4)


def cs_freshwater(T_c: float) -> float:
    """Dissolved-oxygen saturation in fresh water at 1 atm (mg/L).

    Benson & Krause equation as given in Standard Methods 4500-O.
    """
    T = T_c + 273.15
    return math.exp(-139.34411 + 1.575701e5 / T - 6.642308e7 / T**2
                    + 1.243800e10 / T**3 - 8.621949e11 / T**4)


def design_aeration(inp: AerationInputs, aotr_lbd: float, do_mgl: float,
                    basin_volume_ft3: float, lib=None, label: str = "Aeration System") -> UnitResult:
    lib = lib or default_library()
    r = UnitResult(label, "Secondary")
    T = inp.T_water_C
    patm = barometric_psi(inp.elevation_ft)
    pd = patm + PSI_PER_FT_WATER * inp.submergence_ft
    depth_factor = 0.5 * (pd / patm + inp.o2_exit_pct / 21.0)
    cs_T_H = cs_freshwater(T) * patm / P_ATM_PSI * depth_factor
    pd_std = P_ATM_PSI + PSI_PER_FT_WATER * inp.submergence_ft
    cs_20 = cs_freshwater(20.0) * 0.5 * (pd_std / P_ATM_PSI + inp.o2_exit_pct / 21.0)
    ratio = (inp.beta * cs_T_H - do_mgl) / cs_20 * inp.theta ** (T - 20) * inp.alpha * inp.fouling
    sotr = aotr_lbd / ratio

    sote = min(inp.sote_per_ft * inp.submergence_ft, 45.0) / 100.0
    air_scfm = sotr / (sote * AIR_DENSITY_STD * O2_MASS_FRAC) / 1440.0
    mixing = air_scfm / (basin_volume_ft3 / 1000.0)
    mix_min = lib.get("as_mixing_air").min
    air_design = max(air_scfm, mix_min * basin_volume_ft3 / 1000.0)

    p1 = patm
    p2 = patm + PSI_PER_FT_WATER * inp.submergence_ft + inp.piping_loss_psi + inp.diffuser_loss_psi
    w = air_design * AIR_DENSITY_STD / 60.0                       # lb/s
    T1 = inp.inlet_air_F + 459.67
    # adiabatic compression: P = w cp T1 / eff * ((p2/p1)^0.283 - 1); cp = 0.24 BTU/lb-R; 1 BTU/s = 1.4148 hp
    hp = w * 0.24 * T1 / inp.blower_eff * ((p2 / p1) ** 0.283 - 1.0) * 1.4148
    hp_each = hp / inp.n_duty
    motor = next((m for m in STD_MOTORS_HP if m >= hp_each * 1.10), STD_MOTORS_HP[-1])
    kwh_yr = hp * 0.7457 * 24 * 365 * 0.6                          # assume average = 60% of design

    r.i("Design AOTR", aotr_lbd, "lb O2/d"); r.i("Operating DO", do_mgl, "mg/L")
    r.i("Diffuser", inp.diffuser); r.i("Submergence", inp.submergence_ft, "ft")
    r.i("Alpha / beta / F", f"{inp.alpha:g} / {inp.beta:g} / {inp.fouling:g}")
    r.i("Water temperature", T, "C"); r.i("Elevation", inp.elevation_ft, "ft")
    r.o("Barometric pressure", patm, "psia")
    r.o("Mid-depth DO saturation at T", cs_T_H, "mg/L")
    r.o("AOTR / SOTR", ratio, "-", 3)
    r.o("Design SOTR", sotr, "lb O2/d")
    r.o("SOTE", 100 * sote, "%")
    r.o("Air for oxygen demand", air_scfm, "scfm")
    r.o("Mixing intensity at O2 air rate", mixing, "scfm/1000 ft3")
    r.o("Design air flow", air_design, "scfm")
    r.o("Blower discharge pressure", p2 - patm, "psig")
    r.o("Total brake power", hp, "hp")
    r.o("Blowers", f"{inp.n_duty} duty + {inp.n_standby} standby @ {air_design/inp.n_duty:,.0f} scfm, {motor} hp motor")
    r.o("Estimated aeration energy", kwh_yr, "kWh/yr")
    r.c(lib.check(mixing if air_scfm >= air_design - 1e-6 else mix_min, "as_mixing_air",
                  note="air increased to mixing minimum" if air_design > air_scfm + 1e-6 else ""))
    r.c(lib.check(inp.diffuser_loss_psi, "as_diffuser_headloss"))
    r.c(lib.check(inp.alpha, "as_alpha_domestic"))
    if inp.n_standby < 1:
        r.note("No standby blower: firm capacity with largest unit out of service is normally required.")
    if mixing < mix_min:
        r.note("Mixing, not oxygen demand, governs air at design; check turndown at minimum loads.")
    r.data.update(sotr=sotr, air_scfm=air_design, hp=hp, motor_hp=motor, p2_psig=p2 - patm)
    return r
