"""Pumping: influent lift station (wet well, force main, system curve, TDH,
power) and in-plant RAS / WAS / internal-recycle pumps."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.criteria import default_library, custom_check
from ..core.fields import fld
from ..core.hydraulics import STD_PIPE_IN, hazen_williams_hf, pipe_velocity, velocity_head
from ..core.unitop import UnitResult
from ..core.units import MGD_TO_GPM, MGD_TO_CFS, GAL_PER_FT3, round_up
from .aeration import STD_MOTORS_HP


def motor_for(bhp: float, sf: float = 1.15) -> float:
    return next((m for m in [1, 1.5, 2, 3] + STD_MOTORS_HP if m >= bhp * sf), STD_MOTORS_HP[-1])


@dataclass
class LiftStationInputs:
    enabled: bool = fld(True, "Include influent lift station")
    n_duty: int = fld(2, "Duty pumps (meet peak hour)", "", 1, 8)
    n_standby: int = fld(1, "Standby pumps", "", 0, 4)
    vfd: bool = fld(True, "Variable-frequency drives")
    static_lift_ft: float = fld(25.0, "Static lift (wet well LWL to discharge)", "ft", 2, 200)
    wetwell_lwl_el: float = fld(0.0, "Wet well low water elevation (0 = use static lift above)", "ft", 0, 10000,
                                help="When set, static lift = hydraulic-profile headworks WSE - this elevation")
    force_main_ft: float = fld(800.0, "Force main length", "ft", 10, 50000)
    force_main_in: float = fld(0.0, "Force main diameter (0 = auto)", "in", 0, 72)
    hw_c: float = fld(120.0, "Hazen-Williams C (aged)", "-", 80, 150)
    minor_k: float = fld(12.0, "Sum of minor-loss coefficients", "-", 0, 50)
    cycle_min: float = fld(10.0, "Minimum pump cycle time (constant speed basis)", "min", 4, 30)
    wetwell_diam_ft: float = fld(16.0, "Wet well inside diameter", "ft", 4, 60)
    solids_passage_in: float = fld(3.0, "Pump solids passage", "in", 2, 6)
    pump_eff: float = fld(0.75, "Pump efficiency", "-", 0.4, 0.9)
    wire_eff: float = fld(0.90, "Motor x drive efficiency", "-", 0.7, 0.98)


@dataclass
class ProcessPumpInputs:
    ras_n_duty: int = fld(2, "RAS duty pumps", "", 1, 12)
    ras_n_standby: int = fld(1, "RAS standby pumps", "", 0, 4)
    ras_tdh_ft: float = fld(20.0, "RAS pump TDH", "ft", 5, 80)
    was_tdh_ft: float = fld(30.0, "WAS pump TDH", "ft", 5, 120)
    was_hours: float = fld(24.0, "WAS pumping hours per day", "h/d", 1, 24)
    ir_tdh_ft: float = fld(4.0, "Internal recycle pump TDH", "ft", 1, 15)
    pump_eff: float = fld(0.70, "Pump efficiency", "-", 0.4, 0.9)
    wire_eff: float = fld(0.90, "Motor x drive efficiency", "-", 0.7, 0.98)


def system_curve(static, length, d_in, c, k, q_gpm):
    hf = hazen_williams_hf(q_gpm, d_in, length, c)
    v = pipe_velocity(q_gpm / 448.83, d_in)
    return static + hf + k * velocity_head(v)


def design_lift_station(inp: LiftStationInputs, Q_avg: float, Q_peak: float, Q_min: float, lib=None):
    lib = lib or default_library()
    r = UnitResult("Influent Lift Station", "Pumping")
    q_pk = Q_peak * MGD_TO_GPM
    q_avg = Q_avg * MGD_TO_GPM
    q_pump = q_pk / inp.n_duty
    # force main: smallest standard size keeping peak velocity <= 6 ft/s, and >= 2 ft/s with one pump
    if inp.force_main_in > 0:
        d = inp.force_main_in
    else:
        # largest standard size that still gives >= 2 ft/s with one pump (limits friction head),
        # provided peak velocity stays <= 8 ft/s; otherwise smallest size with peak <= 6 ft/s
        ok = [x for x in STD_PIPE_IN if pipe_velocity(q_pump / 448.83, x) >= 2.0
              and pipe_velocity(q_pk / 448.83, x) <= 8.0]
        d = max(ok) if ok else next((x for x in STD_PIPE_IN if pipe_velocity(q_pk / 448.83, x) <= 6.0), STD_PIPE_IN[-1])
    v_pk = pipe_velocity(q_pk / 448.83, d)
    v_one = pipe_velocity(q_pump / 448.83, d)
    tdh = system_curve(inp.static_lift_ft, inp.force_main_ft, d, inp.hw_c, inp.minor_k, q_pk)
    tdh_one = system_curve(inp.static_lift_ft, inp.force_main_ft, d, inp.hw_c, inp.minor_k, q_pump)
    bhp = q_pump * tdh / (3960 * inp.pump_eff)
    motor = motor_for(bhp)
    # wet well active volume for the cycle time (one constant-speed pump): V = T q / 4
    v_active = inp.cycle_min * q_pump / 4                      # gal
    area = math.pi * inp.wetwell_diam_ft ** 2 / 4
    drawdown = v_active / GAL_PER_FT3 / area
    fill_avg = v_active / q_avg
    kwh_yr = q_avg * tdh * 0.746 / (3960 * inp.pump_eff * inp.wire_eff) * 24 * 365
    curve = [(f * q_pk, system_curve(inp.static_lift_ft, inp.force_main_ft, d, inp.hw_c, inp.minor_k, f * q_pk))
             for f in [i / 10 for i in range(0, 14)]]

    r.i("Peak hourly flow", Q_peak, "MGD"); r.i("Average flow", Q_avg, "MGD")
    r.i("Pumps", f"{inp.n_duty} duty + {inp.n_standby} standby"); r.i("Static lift", inp.static_lift_ft, "ft")
    r.i("Force main length", inp.force_main_ft, "ft")
    r.o("Capacity per pump", q_pump, "gpm"); r.o("Firm capacity", q_pump * inp.n_duty, "gpm")
    r.o("Force main diameter", d, "in", 0)
    r.o("Force main velocity, peak", v_pk, "ft/s"); r.o("Force main velocity, one pump", v_one, "ft/s")
    r.o("TDH at peak", tdh, "ft"); r.o("TDH, one pump", tdh_one, "ft")
    r.o("Brake horsepower per pump", bhp, "hp"); r.o("Motor", motor, "hp")
    r.o("Wet well active volume", v_active, "gal"); r.o("Pump-cycle drawdown", drawdown, "ft")
    r.o("Fill time at average flow", fill_avg, "min")
    r.o("Annual pumping energy", kwh_yr, "kWh/yr")
    r.c(lib.check(v_one, "ps_force_main_v", label="Force main velocity with one pump running"))
    r.c(lib.check(v_pk, "ps_force_main_v", label="Force main velocity at peak"))
    r.c(lib.check(fill_avg, "ps_wetwell_fill"))
    r.c(lib.check(inp.cycle_min, "ps_cycle_time"))
    r.c(lib.check(inp.solids_passage_in, "ps_solids_passage"))
    r.c(custom_check("Firm capacity (largest pump out) / peak flow", (inp.n_duty + inp.n_standby - 1) * q_pump / q_pk,
                     "-", lo=1.0, kind="limit", source="SC-R61-67.400 C.2/D.5; 10SS-2014 42.2"))
    if inp.vfd:
        r.note("With VFDs, verify minimum speed delivers >= 2 ft/s in the force main and stays above the static head.")
    r.note("Without standby power, provide emergency storage (MO 10 CSR 20-8.130: 2 h at peak hour for >= 100,000 gpd).")
    r.data.update(bhp_total=bhp * inp.n_duty, motor_hp=motor, n_total=inp.n_duty + inp.n_standby,
                  kwh_yr=kwh_yr, curve=curve, tdh=tdh, fm_in=d, wetwell_ft3=v_active / GAL_PER_FT3)
    return r


def design_process_pumps(inp: ProcessPumpInputs, Q_avg: float, ras_max: float, ras_avg: float,
                         was_gpd: float, ir_ratio: float, lib=None):
    r = UnitResult("Process Pumps (RAS / WAS / IR)", "Pumping")
    eff = inp.pump_eff * inp.wire_eff
    q_ras_max = ras_max * Q_avg * MGD_TO_GPM
    q_ras_each = q_ras_max / inp.ras_n_duty
    ras_bhp = q_ras_each * inp.ras_tdh_ft / (3960 * inp.pump_eff)
    q_was = was_gpd / (inp.was_hours * 60)
    was_bhp = max(q_was, 1) * inp.was_tdh_ft / (3960 * inp.pump_eff)
    q_ir = ir_ratio * Q_avg * MGD_TO_GPM
    ir_bhp = q_ir * inp.ir_tdh_ft / (3960 * inp.pump_eff)
    kwh = ((ras_avg * Q_avg * MGD_TO_GPM) * inp.ras_tdh_ft + q_was * inp.was_tdh_ft * inp.was_hours / 24
           + q_ir * inp.ir_tdh_ft) / (3960 * eff) * 0.746 * 8760
    r.i("RAS ratio (avg / max)", f"{ras_avg:.2f} / {ras_max:.2f}"); r.i("WAS", was_gpd, "gpd")
    r.i("Internal recycle ratio", ir_ratio)
    r.o("RAS pumps", f"{inp.ras_n_duty} duty + {inp.ras_n_standby} standby @ {q_ras_each:,.0f} gpm, {motor_for(ras_bhp)} hp")
    r.o("WAS pumps", f"1 duty + 1 standby @ {q_was:,.0f} gpm, {motor_for(was_bhp)} hp")
    if q_ir > 0:
        r.o("Internal recycle pumping", q_ir, "gpm"); r.o("IR brake horsepower (total)", ir_bhp, "hp")
    r.o("Annual process pumping energy", kwh, "kWh/yr")
    r.c(custom_check("RAS firm capacity (largest out) / maximum RAS", (inp.ras_n_duty + inp.ras_n_standby - 1) / inp.ras_n_duty,
                     "-", lo=1.0, kind="limit", source="SC-R61-67.400 D.5 (pump backup)"))
    r.data.update(hp=ras_bhp * inp.ras_n_duty + was_bhp + ir_bhp, kwh_yr=kwh,
                  n_pumps=inp.ras_n_duty + inp.ras_n_standby + 2 + (2 if q_ir > 0 else 0))
    return r
