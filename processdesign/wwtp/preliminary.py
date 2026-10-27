"""Preliminary treatment: mechanical bar screens, aerated grit chambers,
flow equalization."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.criteria import default_library, custom_check
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import MGD_TO_CFS, G_FT, GAL_PER_FT3, round_up


@dataclass
class ScreenInputs:
    enabled: bool = fld(True, "Include bar screens")
    n_duty: int = fld(2, "Duty screen channels", "", 1, 10)
    n_standby: int = fld(1, "Standby / bypass channels", "", 0, 4)
    clear_opening_in: float = fld(0.5, "Clear opening", "in", 0.125, 2.0, step=0.125)
    bar_width_in: float = fld(0.25, "Bar width", "in", 0.125, 1.0, step=0.125)
    depth_peak_ft: float = fld(3.0, "Channel water depth at peak", "ft", 0.5, 10)
    v_openings_target: float = fld(2.4, "Target velocity through openings at peak", "ft/s", 1.0, 3.0)
    screenings_ft3_per_MG: float = fld(4.0, "Screenings yield", "ft3/MG", 0.5, 30,
                                        help="M&E 5th: varies strongly with opening size; ~2-8 for 6-12 mm screens")


def design_bar_screen(inp: ScreenInputs, Q_avg: float, Q_peak: float, lib=None) -> UnitResult:
    lib = lib or default_library()
    r = UnitResult("Mechanical Bar Screens", "Preliminary")
    r.i("Peak hourly flow", Q_peak, "MGD"); r.i("Duty channels", inp.n_duty)
    r.i("Clear opening", inp.clear_opening_in, "in"); r.i("Bar width", inp.bar_width_in, "in")

    q_cfs = Q_peak * MGD_TO_CFS / inp.n_duty
    open_frac = inp.clear_opening_in / (inp.clear_opening_in + inp.bar_width_in)
    v_approach = inp.v_openings_target * open_frac
    width = round_up(q_cfs / (v_approach * inp.depth_peak_ft), 0.5)
    v_a = q_cfs / (width * inp.depth_peak_ft)                 # actual approach
    v_o = v_a / open_frac                                     # through clean openings
    hl_clean = (v_o**2 - v_a**2) / (2 * G_FT * 0.7)            # M&E Kirschmer-type orifice form
    v_o50 = 2 * v_o
    hl_50 = (v_o50**2 - v_a**2) / (2 * G_FT * 0.7)
    screenings = inp.screenings_ft3_per_MG * Q_avg

    r.o("Channel width (each)", width, "ft", 1)
    r.o("Approach velocity at peak", v_a, "ft/s")
    r.o("Velocity through openings at peak (clean)", v_o, "ft/s")
    r.o("Head loss, clean", hl_clean, "ft")
    r.o("Head loss, 50% blinded", hl_50, "ft")
    r.o("Screenings volume (avg)", screenings, "ft3/d")
    r.o("Screenings, 30-day", screenings * 30 / 27, "yd3")
    r.c(lib.check(v_o, "screen_v_openings_peak"))
    r.c(lib.check(v_a, "screen_approach_v"))
    r.c(lib.check(inp.clear_opening_in, "screen_clear_opening"))
    if inp.n_standby < 1:
        r.note("No standby/bypass channel: R.61-67 reliability classification normally requires one - confirm.")
    r.note("Confirm approach velocity >= 1.25 ft/s at minimum flow with the hydraulic profile (channel depth varies with flow).")
    r.data.update(width=width, screenings_ft3d=screenings, hl_50=hl_50, n=inp.n_duty + inp.n_standby, q_each=Q_peak / inp.n_duty)
    return r


@dataclass
class GritInputs:
    enabled: bool = fld(True, "Include aerated grit chambers")
    n_units: int = fld(2, "Number of chambers", "", 1, 8)
    detention_min: float = fld(3.0, "Detention at peak flow", "min", 1, 10)
    lw_target: float = fld(4.0, "Target length : width", "-", 2.0, 6.0)
    width_to_depth: float = fld(1.2, "Width : depth ratio", "-", 0.8, 5.0)
    min_depth_ft: float = fld(4.0, "Minimum water depth", "ft", 2, 10)
    air_scfm_per_ft: float = fld(5.0, "Air supply per ft of length", "scfm/ft", 2, 10)
    grit_ft3_per_MG: float = fld(4.0, "Grit yield", "ft3/MG", 0.5, 30)


def design_aerated_grit(inp: GritInputs, Q_avg: float, Q_peak: float, lib=None) -> UnitResult:
    lib = lib or default_library()
    r = UnitResult("Aerated Grit Chambers", "Preliminary")
    r.i("Peak hourly flow", Q_peak, "MGD"); r.i("Chambers", inp.n_units)
    r.i("Detention at peak", inp.detention_min, "min")

    vol_total = Q_peak * 1e6 / GAL_PER_FT3 / 1440 * inp.detention_min
    vol_each = vol_total / inp.n_units
    # solve L = lw*W, D = W/wd for the required volume, then round to buildable dimensions
    width = (vol_each * inp.width_to_depth / inp.lw_target) ** (1 / 3)
    depth = max(round_up(width / inp.width_to_depth, 0.5), inp.min_depth_ft)
    width = round_up(width, 0.5)
    length = round_up(vol_each / (width * depth), 1.0)
    vol_each_act = length * width * depth
    t_act = vol_each_act * inp.n_units / (Q_peak * 1e6 / GAL_PER_FT3 / 1440)
    air = inp.air_scfm_per_ft * length * inp.n_units
    grit = inp.grit_ft3_per_MG * Q_avg

    r.o("Length (each)", length, "ft", 0); r.o("Width (each)", width, "ft", 1)
    r.o("Water depth", depth, "ft", 1)
    r.o("Volume (each)", vol_each_act, "ft3"); r.o("Actual detention at peak", t_act, "min")
    r.o("Length : width", length / width, "-")
    r.o("Total air", air, "scfm"); r.o("Grit volume (avg)", grit, "ft3/d")
    r.c(lib.check(t_act, "grit_aerated_detention"))
    r.c(lib.check(length / width, "grit_aerated_lw"))
    r.c(lib.check(inp.air_scfm_per_ft, "grit_air_per_ft"))
    r.data.update(air_scfm=air, grit_ft3d=grit, length=length, width=width, depth=depth, n=inp.n_units)
    return r


# Typical municipal diurnal pattern (fraction of average, hour 0 = midnight).
DEFAULT_DIURNAL = [0.65, 0.55, 0.48, 0.45, 0.45, 0.52, 0.75, 1.05, 1.30, 1.40, 1.42, 1.40,
                   1.35, 1.30, 1.25, 1.20, 1.18, 1.20, 1.25, 1.28, 1.22, 1.10, 0.95, 0.80]


@dataclass
class EQInputs:
    enabled: bool = fld(False, "Include in-line diurnal flow equalization")
    diurnal: list = fld(DEFAULT_DIURNAL, "Hourly flow pattern (x average, 24 values)")
    contingency: float = fld(1.20, "Volume contingency factor", "-", 1.0, 2.0,
                             help="M&E: add 10-20% for continuous mixing/aeration plus unforeseen changes")
    depth_ft: float = fld(15.0, "Basin water depth", "ft", 6, 30)
    air_scfm_per_kft3: float = fld(12.5, "Mixing air", "scfm/1000 ft3", 5, 30)


def equalization_volume(pattern: list[float], Q_avg_mgd: float) -> tuple[float, list[float]]:
    """Mass-diagram (cumulative inflow minus average outflow) storage in gallons."""
    n = len(pattern)
    mean = sum(pattern) / n
    hourly_gal = [p / mean * Q_avg_mgd * 1e6 / n for p in pattern]
    out = Q_avg_mgd * 1e6 / n
    cum, s = [], 0.0
    for h in hourly_gal:
        s += h - out
        cum.append(s)
    return max(max(cum), 0.0) - min(min(cum), 0.0), cum


def design_equalization(inp: EQInputs, Q_avg: float, PF_peakhour: float, lib=None) -> UnitResult:
    lib = lib or default_library()
    r = UnitResult("Flow Equalization", "Preliminary")
    if len(inp.diurnal) != 24:
        raise ValueError("Diurnal pattern must have 24 hourly values")
    # scale pattern so its peak matches the plant peak-hour factor
    mean = sum(inp.diurnal) / 24
    base = [p / mean for p in inp.diurnal]
    pk = max(base)
    scale = (PF_peakhour - 1.0) / (pk - 1.0) if pk > 1 else 1.0
    pattern = [1.0 + (p - 1.0) * scale for p in base]
    pattern = [max(p, 0.05) for p in pattern]
    rng, cum = equalization_volume(pattern, Q_avg)
    vol_design = rng * inp.contingency
    vol_ft3 = vol_design / GAL_PER_FT3
    area = vol_ft3 / inp.depth_ft
    air = vol_ft3 / 1000 * inp.air_scfm_per_kft3

    r.i("Average flow", Q_avg, "MGD"); r.i("Peak-hour factor applied to pattern", PF_peakhour)
    r.i("Contingency", inp.contingency)
    r.o("Required storage (mass diagram)", rng / 1e6, "MG", 3)
    r.o("Design volume", vol_design / 1e6, "MG", 3)
    r.o("Design volume", vol_ft3, "ft3")
    r.o("Basin plan area", area, "ft2")
    r.o("Storage as % of daily flow", 100 * vol_design / (Q_avg * 1e6), "%")
    r.o("Mixing air", air, "scfm")
    r.c(lib.check(inp.air_scfm_per_kft3, "eq_air_mixing"))
    r.c(lib.check(PF_peakhour, "wet_weather_eq_phf", label="Peak-hour : average (wet-weather EQ trigger)",
                  note="Ten States: consider wet-weather equalization at >= 3:1"))
    r.note("Diurnal EQ dampens hourly peaks; downstream units are sized for max-day flow as the hydraulic peak.")
    r.data.update(volume_gal=vol_design, air_scfm=air, pattern=pattern, cumulative_gal=cum, depth=inp.depth_ft)
    return r
