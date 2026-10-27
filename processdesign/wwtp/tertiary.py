"""Tertiary treatment and disinfection: filtration, chlorination with
dechlorination, UV."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.criteria import default_library, custom_check
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import GAL_PER_FT3, MGD_TO_GPM, load_lbd, round_up


@dataclass
class FilterInputs:
    enabled: bool = fld(False, "Include tertiary filtration")
    media: str = fld("Cloth disk", "Filter type", choices=["Cloth disk", "Granular (dual media)"])
    rate_peak: float = fld(5.0, "Design loading at peak hour", "gpm/ft2", 1, 10)
    n_units: int = fld(3, "Number of filters (incl. one out of service)", "", 2, 20)
    backwash_pct: float = fld(3.0, "Backwash / reject as % of forward flow", "%", 0.5, 10)
    tss_removal: float = fld(70.0, "TSS removal", "%", 30, 95)


def design_filter(inp: FilterInputs, Q_avg: float, Q_peak: float, tss_in: float, lib=None):
    lib = lib or default_library()
    r = UnitResult(f"Tertiary Filters - {inp.media}", "Tertiary")
    gpm_pk = Q_peak * MGD_TO_GPM
    a_total = gpm_pk / inp.rate_peak
    a_each = round_up(a_total / (inp.n_units - 1), 10)               # firm capacity, one unit out
    rate_all = gpm_pk / (a_each * inp.n_units)
    rate_firm = gpm_pk / (a_each * (inp.n_units - 1))
    bw_gpd = Q_avg * 1e6 * inp.backwash_pct / 100
    tss_out = tss_in * (1 - inp.tss_removal / 100)
    bw_tss_lb = load_lbd(Q_avg, tss_in - tss_out)
    key = "filter_rate_cloth" if inp.media.startswith("Cloth") else "filter_rate_granular"

    r.i("Peak hourly flow", Q_peak, "MGD"); r.i("Units", inp.n_units); r.i("Influent TSS", tss_in, "mg/L")
    r.o("Filter area per unit", a_each, "ft2"); r.o("Total installed area", a_each * inp.n_units, "ft2")
    r.o("Loading at peak, all units", rate_all, "gpm/ft2")
    r.o("Loading at peak, one unit out", rate_firm, "gpm/ft2")
    r.o("Backwash / reject flow (to headworks)", bw_gpd, "gpd")
    r.o("Effluent TSS", tss_out, "mg/L")
    r.c(lib.check(rate_firm, key, label="Filter loading at peak with one unit out of service"))
    r.c(lib.check(inp.n_units, "filter_units"))
    r.data.update(recycle_gpd=bw_gpd, recycle_tss_lb=bw_tss_lb, tss_out=tss_out,
                  area_each=a_each, n=inp.n_units, area_total=a_each * inp.n_units)
    return r


@dataclass
class DisinfectionInputs:
    method: str = fld("Chlorination + dechlorination", "Disinfection method",
                      choices=["Chlorination + dechlorination", "UV"])
    # chlorination
    contact_peak_min: float = fld(15.0, "Contact time at daily peak flow", "min", 5, 60)
    contact_avg_min: float = fld(30.0, "Contact time at average flow", "min", 10, 120)
    n_basins: int = fld(2, "Contact basins / compartments", "", 1, 6)
    cl2_dose: float = fld(6.0, "Chlorine dose (average)", "mg/L", 1, 35,
                          help="TN Design Criteria 10.2.2.2: activated sludge 2-8, nitrified 2-6 mg/L")
    cl2_residual: float = fld(1.0, "Residual before dechlorination", "mg/L", 0.1, 5)
    swd_ft: float = fld(10.0, "Contact basin depth", "ft", 4, 20)
    channel_width_ft: float = fld(6.0, "Serpentine channel width", "ft", 2, 20)
    channel_length_ft: float = fld(60.0, "Pass length between bends", "ft", 10, 300)
    hypo_trade_pct: float = fld(12.5, "Sodium hypochlorite strength", "trade %", 5, 15)
    bisulfite_lb_per_gal: float = fld(4.25, "Sodium bisulfite solution (38%)", "lb NaHSO3/gal", 2, 6)
    # UV
    uv_dose: float = fld(30.0, "Design UV dose (end of lamp life, fouled)", "mJ/cm2", 10, 150)
    uvt_pct: float = fld(65.0, "Design UV transmittance", "%", 40, 90)
    uv_intensity: float = fld(10.0, "Vendor average intensity at design UVT", "mW/cm2", 1, 50,
                              help="Obtain from the selected vendor's validated dose model")
    uv_lamps_per_mgd: float = fld(12.0, "Vendor lamps per MGD at design UVT", "lamps/MGD", 1, 200)
    uv_kw_per_lamp: float = fld(0.33, "Power per lamp", "kW", 0.05, 2)
    uv_banks_duty: int = fld(2, "Duty banks / channels", "", 1, 10)
    uv_banks_redundant: int = fld(1, "Redundant banks / channels", "", 0, 4)


def design_disinfection(inp: DisinfectionInputs, Q_avg: float, Q_peak: float, lib=None) -> UnitResult:
    lib = lib or default_library()
    if inp.method.startswith("UV"):
        return _design_uv(inp, Q_avg, Q_peak, lib)
    r = UnitResult("Chlorine Contact + Dechlorination", "Disinfection")
    v_pk = Q_peak * 1e6 / GAL_PER_FT3 / 1440 * inp.contact_peak_min
    v_avg = Q_avg * 1e6 / GAL_PER_FT3 / 1440 * inp.contact_avg_min
    vol_ft3 = max(v_pk, v_avg)
    governs = "average-flow contact time" if v_avg >= v_pk else "peak-flow contact time"
    area = vol_ft3 / inp.swd_ft
    path_len = area / inp.channel_width_ft
    passes = max(math.ceil(path_len / inp.channel_length_ft), 1)
    t_avg = vol_ft3 * GAL_PER_FT3 / (Q_avg * 1e6) * 1440
    t_pk = vol_ft3 * GAL_PER_FT3 / (Q_peak * 1e6) * 1440
    cl2_lb = load_lbd(Q_avg, inp.cl2_dose)
    cl2_pk = load_lbd(Q_peak, inp.cl2_dose)
    hypo_lb_gal = inp.hypo_trade_pct * 10 / 1000 * 8.345           # trade % = g/100 mL available Cl2
    nahso3_lb = load_lbd(Q_avg, 1.46 * inp.cl2_residual)
    hypo_gpd = cl2_lb / hypo_lb_gal
    r.i("Average / peak flow", f"{Q_avg:.2f} / {Q_peak:.2f}", "MGD")
    r.i("Contact time at peak / average", f"{inp.contact_peak_min:g} / {inp.contact_avg_min:g}", "min")
    r.i("Chlorine dose", inp.cl2_dose, "mg/L"); r.i("Residual to dechlorinate", inp.cl2_residual, "mg/L")
    r.o("Governing criterion", governs)
    r.o("Contact basin volume", vol_ft3, "ft3"); r.o("Plan area", area, "ft2")
    r.o("Flow-path length", path_len, "ft"); r.o("Passes", passes)
    r.o("Length : width", path_len / inp.channel_width_ft, "-")
    r.o("Contact time at peak flow", t_pk, "min"); r.o("Contact time at average flow", t_avg, "min")
    r.o("Chlorine use, average", cl2_lb, "lb/d"); r.o("Chlorine feed capacity, peak", cl2_pk, "lb/d")
    r.o(f"Sodium hypochlorite ({inp.hypo_trade_pct:g} trade %)", hypo_gpd, "gal/d")
    r.o("Sodium bisulfite (1.46 mg/mg Cl2)", nahso3_lb, "lb/d")
    r.o("Sodium bisulfite solution", nahso3_lb / inp.bisulfite_lb_per_gal, "gal/d")
    r.o("30-day hypochlorite storage", 30 * hypo_gpd, "gal")
    r.c(lib.check(t_pk, "cl2_contact_peak"))
    r.c(lib.check(t_avg, "cl2_contact_avg"))
    r.c(lib.check(path_len / inp.channel_width_ft, "cl2_contact_lw"))
    if inp.n_basins < 2:
        r.note("Single contact basin: TN 10.2.2.5 recommends duplicate compartments; check R.61-67 reliability class.")
    r.note("Hypochlorite degrades in storage; size storage for the decay rate at site temperature.")
    r.data.update(volume_ft3=vol_ft3, channel_width=inp.channel_width_ft, depth=inp.swd_ft,
                  path_len=path_len, channel_len=inp.channel_length_ft, n_basins=inp.n_basins,
                  hypo_gpd=hypo_gpd, bisulfite_gpd=nahso3_lb / inp.bisulfite_lb_per_gal,
                  capacity_one_out_mgd=vol_ft3 * (inp.n_basins - 1) / inp.n_basins * GAL_PER_FT3
                  / inp.contact_avg_min * 1440 / 1e6)
    return r


def _design_uv(inp: DisinfectionInputs, Q_avg, Q_peak, lib) -> UnitResult:
    r = UnitResult("UV Disinfection", "Disinfection")
    t_s = inp.uv_dose / inp.uv_intensity
    vol_gal = Q_peak * 1e6 / 86400 * t_s
    lamps = math.ceil(Q_peak * inp.uv_lamps_per_mgd)
    lamps_inst = math.ceil(lamps * (inp.uv_banks_duty + inp.uv_banks_redundant) / inp.uv_banks_duty)
    kw_avg = lamps * inp.uv_kw_per_lamp * max(Q_avg / Q_peak, 0.3)
    r.i("Peak hourly flow", Q_peak, "MGD"); r.i("Design dose", inp.uv_dose, "mJ/cm2")
    r.i("Design UVT", inp.uvt_pct, "%"); r.i("Average intensity (vendor)", inp.uv_intensity, "mW/cm2")
    r.o("Required exposure time", t_s, "s"); r.o("Irradiated volume at peak", vol_gal, "gal")
    r.o("Lamps, duty at peak", lamps); r.o("Lamps installed (n+1 banks)", lamps_inst)
    r.o("Banks", f"{inp.uv_banks_duty} duty + {inp.uv_banks_redundant} redundant")
    r.o("Average UV power (flow-paced)", kw_avg, "kW")
    r.c(lib.check(inp.uvt_pct, "uv_uvt"))
    r.c(lib.check(inp.uv_dose, "uv_dose"))
    r.c(custom_check("UV redundancy (n+1 banks/channels at peak hour)", inp.uv_banks_redundant, "banks", lo=1,
                     kind="limit", source="TN-DC 10.4.2.4", verified=True))
    r.note("UV sizing is an estimate. Final design must use the vendor's validated dose-delivery model "
           "at the design UVT and peak flow.")
    n_tot = inp.uv_banks_duty + inp.uv_banks_redundant
    r.data.update(lamps=lamps_inst, kw_avg=kw_avg, Q_peak=Q_peak,
                  capacity_one_out_mgd=Q_peak * (n_tot - 1) / inp.uv_banks_duty)
    return r
