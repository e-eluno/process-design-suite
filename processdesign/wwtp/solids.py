"""Solids handling: gravity thickening, DAF, anaerobic / aerobic digestion,
dewatering. Each unit returns its design result plus a solids stream and a
liquid side stream for the plant recycle balance."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.criteria import default_library, custom_check
from ..core.fields import fld
from ..core.unitop import UnitResult
from ..core.units import GAL_PER_FT3, round_up


@dataclass
class Solids:
    """Sludge stream: dry solids (lb/d), volatile solids (lb/d), concentration (%)."""
    TS_lb: float
    VS_lb: float
    pct: float
    N_lb: float = 0.0
    P_lb: float = 0.0

    @property
    def gpd(self) -> float:
        return self.TS_lb / (self.pct / 100 * 8.34 * 1.02) if self.pct > 0 else 0.0

    @property
    def vs_frac(self) -> float:
        return self.VS_lb / self.TS_lb if self.TS_lb > 0 else 0.0

    def __add__(self, o: "Solids") -> "Solids":
        ts = self.TS_lb + o.TS_lb
        gpd = self.gpd + o.gpd
        pct = ts / (gpd * 8.34 * 1.02) * 100 if gpd else 0.0
        return Solids(ts, self.VS_lb + o.VS_lb, pct, self.N_lb + o.N_lb, self.P_lb + o.P_lb)


@dataclass
class SideStream:
    """Liquid returned to the headworks."""
    gpd: float = 0.0
    TSS_lb: float = 0.0
    VSS_lb: float = 0.0
    NH3_lb: float = 0.0
    TP_lb: float = 0.0

    def __add__(self, o: "SideStream") -> "SideStream":
        return SideStream(self.gpd + o.gpd, self.TSS_lb + o.TSS_lb, self.VSS_lb + o.VSS_lb,
                          self.NH3_lb + o.NH3_lb, self.TP_lb + o.TP_lb)


def _split(feed: Solids, capture: float, out_pct: float) -> tuple[Solids, SideStream]:
    ts = feed.TS_lb * capture
    out = Solids(ts, feed.VS_lb * capture, out_pct, feed.N_lb * capture, feed.P_lb * capture)
    side = SideStream(max(feed.gpd - out.gpd, 0.0), feed.TS_lb - ts, feed.VS_lb - out.VS_lb)
    return out, side


# ---------------------------------------------------------------- thickening
@dataclass
class ThickeningInputs:
    primary_method: str = fld("Gravity thickener", "Primary sludge thickening",
                              choices=["Gravity thickener", "None"])
    gt_slr: float = fld(25.0, "Gravity thickener solids loading", "lb/ft2-d", 10, 35)
    gt_n: int = fld(2, "Gravity thickeners", "", 1, 6)
    gt_capture: float = fld(90.0, "Gravity thickener capture", "%", 70, 98)
    gt_out_pct: float = fld(6.0, "Thickened primary sludge", "%", 3, 10)
    was_method: str = fld("DAF", "WAS thickening", choices=["DAF", "None"])
    daf_slr: float = fld(1.0, "DAF solids loading (with polymer)", "lb/ft2-h", 0.3, 3)
    daf_hours: float = fld(24.0, "DAF operating hours", "h/d", 6, 24)
    daf_n: int = fld(2, "DAF units", "", 1, 6)
    daf_capture: float = fld(95.0, "DAF capture", "%", 80, 99)
    daf_out_pct: float = fld(4.0, "Thickened WAS", "%", 2, 6)
    daf_polymer: float = fld(5.0, "DAF polymer", "lb/dry ton", 0, 20)


def design_thickening(inp: ThickeningInputs, primary: Solids | None, was: Solids, lib=None):
    lib = lib or default_library()
    r = UnitResult("Sludge Thickening", "Solids")
    side = SideStream()
    out = Solids(0, 0, 0)
    gt_data, daf_data = {}, {}
    if primary is not None and primary.TS_lb > 0:
        if inp.primary_method == "Gravity thickener":
            area = primary.TS_lb / inp.gt_slr
            D = round_up(math.sqrt(4 * area / inp.gt_n / math.pi), 1)
            slr = primary.TS_lb / (inp.gt_n * math.pi * D**2 / 4)
            th, s = _split(primary, inp.gt_capture / 100, inp.gt_out_pct)
            r.i("Primary sludge to GT", primary.TS_lb, "lb/d")
            r.o("Gravity thickener diameter", f"{inp.gt_n} @ {D:.0f}", "ft")
            r.o("GT solids loading", slr, "lb/ft2-d")
            r.o("Thickened primary sludge", th.TS_lb, "lb/d"); r.o("Thickened primary volume", th.gpd, "gpd")
            r.o("GT overflow", s.gpd, "gpd")
            r.c(lib.check(slr, "thick_grav_primary_slr"))
            gt_data = {"D": D, "n": inp.gt_n}
            out, side = th, side + s
        else:
            out = primary
    if was.TS_lb > 0:
        if inp.was_method == "DAF":
            area = was.TS_lb / (inp.daf_slr * inp.daf_hours)
            a_each = round_up(area / inp.daf_n, 10)
            slr = was.TS_lb / inp.daf_hours / (a_each * inp.daf_n)
            th, s = _split(was, inp.daf_capture / 100, inp.daf_out_pct)
            r.i("WAS to DAF", was.TS_lb, "lb/d"); r.i("WAS concentration", was.pct, "%")
            r.o("DAF area", f"{inp.daf_n} @ {a_each:.0f}", "ft2")
            r.o("DAF solids loading", slr, "lb/ft2-h")
            r.o("Thickened WAS", th.TS_lb, "lb/d"); r.o("Thickened WAS volume", th.gpd, "gpd")
            r.o("DAF polymer", inp.daf_polymer * was.TS_lb / 2000, "lb/d")
            r.o("DAF subnatant", s.gpd, "gpd")
            r.c(lib.check(slr, "thick_daf_slr"))
            daf_data = {"area": a_each * inp.daf_n, "n": inp.daf_n, "polymer_lbd": inp.daf_polymer * was.TS_lb / 2000}
            out, side = out + th, side + s
        else:
            out = out + was
    r.data.update(gt=gt_data, daf=daf_data)
    r.o("Blended thickened sludge", out.TS_lb, "lb/d"); r.o("Blended concentration", out.pct, "%")
    r.o("Blended volume", out.gpd, "gpd"); r.o("Blended VS fraction", out.vs_frac * 100, "%")
    return r, out, side


# ---------------------------------------------------------------- digestion
@dataclass
class DigestionInputs:
    method: str = fld("Anaerobic (mesophilic)", "Stabilization",
                      choices=["Anaerobic (mesophilic)", "Aerobic", "None"])
    srt_d: float = fld(20.0, "Digester SRT", "d", 5, 80)
    n_units: int = fld(2, "Number of digesters", "", 1, 8)
    swd_ft: float = fld(30.0, "Digester side water depth", "ft", 10, 50)
    temp_C: float = fld(35.0, "Digester temperature (aerobic: minimum liquid T)", "C", 10, 55)
    sludge_in_C: float = fld(15.0, "Raw sludge temperature (winter)", "C", 5, 30)
    heat_loss_factor: float = fld(1.25, "Heat-loss allowance (x sludge heating)", "-", 1.0, 2.0)
    gas_ft3_per_lb_vsd: float = fld(15.0, "Biogas yield", "ft3/lb VS destroyed", 12, 18)
    ch4_pct: float = fld(65.0, "Methane in biogas", "%", 55, 75)
    n_release: float = fld(0.08, "NH3-N released per lb VS destroyed", "lb/lb", 0.03, 0.12)
    p_release: float = fld(0.0, "P released per lb VS destroyed", "lb/lb", 0, 0.05,
                           help="Raise substantially for EBPR sludges (struvite risk)")
    aer_kd_vsr_max: float = fld(50.0, "Aerobic: ultimate VS reduction", "%", 30, 65)
    aer_mixing: float = fld(30.0, "Aerobic: air supply (largest blower out)", "scfm/1000 ft3", 15, 60)


def design_digestion(inp: DigestionInputs, feed: Solids, lib=None):
    lib = lib or default_library()
    if inp.method == "None" or feed.TS_lb <= 0:
        r = UnitResult("Stabilization - none", "Solids")
        r.note("No stabilization selected: biosolids are not Class B unless another PSRP/PFRP is used.")
        return r, feed, SideStream()
    if inp.method.startswith("Anaerobic"):
        return _anaerobic(inp, feed, lib)
    return _aerobic(inp, feed, lib)


def _tank(inp, vol_ft3):
    v_each = vol_ft3 / inp.n_units
    D = round_up(math.sqrt(4 * v_each / (math.pi * inp.swd_ft)), 5)
    return D, inp.n_units * math.pi * D**2 / 4 * inp.swd_ft


def _anaerobic(inp: DigestionInputs, feed: Solids, lib):
    r = UnitResult("Anaerobic Digestion (mesophilic)", "Solids")
    vol = feed.gpd * inp.srt_d / GAL_PER_FT3
    D, vol_act = _tank(inp, vol)
    srt_act = vol_act * GAL_PER_FT3 / feed.gpd
    vsr = min((13.7 * math.log(srt_act) + 18.9) / 100, 0.65)    # M&E high-rate mesophilic correlation
    vsd = feed.VS_lb * vsr
    gas = vsd * inp.gas_ft3_per_lb_vsd
    ch4 = gas * inp.ch4_pct / 100
    heat = feed.gpd * 8.34 * 1.02 * (inp.temp_C - inp.sludge_in_C) * 1.8 * inp.heat_loss_factor
    energy = ch4 * 960                                           # BTU/d, LHV methane ~960 BTU/scf (approx.)
    vs_load = feed.VS_lb / (vol_act / 1000)
    nh3 = vsd * inp.n_release
    out = Solids(feed.TS_lb - vsd, feed.VS_lb - vsd, max(feed.pct * (feed.TS_lb - vsd) / feed.TS_lb, 0.5),
                 max(feed.N_lb - nh3, 0), feed.P_lb - vsd * inp.p_release)
    side = SideStream(NH3_lb=nh3, TP_lb=vsd * inp.p_release)   # leaves with dewatering liquor
    r.i("Feed solids", feed.TS_lb, "lb/d"); r.i("Feed VS", feed.vs_frac * 100, "%")
    r.i("Feed volume", feed.gpd, "gpd"); r.i("Design SRT", inp.srt_d, "d")
    r.o("Digesters", f"{inp.n_units} @ {D:.0f} ft dia x {inp.swd_ft:g} ft SWD")
    r.o("Active volume", vol_act, "ft3"); r.o("Actual SRT", srt_act, "d")
    r.o("VS loading", vs_load, "lb VS/1000 ft3-d")
    r.o("VS reduction", vsr * 100, "%"); r.o("VS destroyed", vsd, "lb/d")
    r.o("Biogas production", gas, "ft3/d"); r.o("Methane", ch4, "ft3/d")
    r.o("Methane energy (LHV)", energy / 1e6, "MMBTU/d")
    r.o("Sludge heating + losses (winter)", heat / 1e6, "MMBTU/d")
    r.o("Digested solids", out.TS_lb, "lb/d")
    r.o("NH3-N released to liquor", nh3, "lb/d")
    r.c(lib.check(srt_act, "ad_srt"))
    r.c(lib.check(vs_load, "ad_vs_load"))
    r.c(custom_check("Methane energy / heating demand", energy / heat if heat else 0, "-", lo=1.0,
                     source="Energy balance", note="supplemental fuel needed if < 1"))
    r.c(custom_check("VS reduction (vector attraction reduction)", vsr * 100, "%", lo=38.0,
                     kind="limit", source="40 CFR 503.33(b)(1)"))
    r.note("PSRP (Class B) by anaerobic digestion: MCRT 15 d at 35-55 C or 60 d at 20 C (40 CFR 503 App. B).")
    r.c(lib.check(inp.swd_ft, "ad_swd"))
    r.data.update(gas_ft3d=gas, vsd=vsd, ch4_ft3d=ch4, D=D, n=inp.n_units, swd=inp.swd_ft, volume=vol_act,
                  heat_mmbtu=heat / 1e6, kind="anaerobic")
    return r, out, side


def _aerobic(inp: DigestionInputs, feed: Solids, lib):
    r = UnitResult("Aerobic Digestion", "Solids")
    vol = feed.gpd * inp.srt_d / GAL_PER_FT3
    D, vol_act = _tank(inp, vol)
    srt_act = vol_act * GAL_PER_FT3 / feed.gpd
    dd = srt_act * inp.temp_C
    vsr = inp.aer_kd_vsr_max / 100 * (1 - math.exp(-0.0025 * dd))   # approximation of M&E degree-day curve
    vsd = feed.VS_lb * vsr
    o2 = 2.3 * vsd
    from .aeration import AIR_DENSITY_STD, O2_MASS_FRAC
    air_o2 = o2 / (0.10 * AIR_DENSITY_STD * O2_MASS_FRAC) / 1440   # coarse bubble ~10% OTE in thick sludge
    air_mix = inp.aer_mixing * vol_act / 1000
    # 40 CFR 503 App. B: 40 d @ 20 C ... 60 d @ 15 C (interpolate; hold endpoints)
    t = min(max(inp.temp_C, 15.0), 20.0)
    srt_req = 60 - (t - 15) * 4
    nh3 = vsd * inp.n_release * 0.3     # most released N is nitrified in aerobic digesters
    out = Solids(feed.TS_lb - vsd, feed.VS_lb - vsd, max(feed.pct * (feed.TS_lb - vsd) / feed.TS_lb, 0.5),
                 max(feed.N_lb - vsd * inp.n_release, 0), feed.P_lb)
    side = SideStream(NH3_lb=nh3)
    r.i("Feed solids", feed.TS_lb, "lb/d"); r.i("Feed volume", feed.gpd, "gpd")
    r.i("SRT", inp.srt_d, "d"); r.i("Minimum liquid temperature", inp.temp_C, "C")
    r.o("Digesters", f"{inp.n_units} @ {D:.0f} ft dia x {inp.swd_ft:g} ft SWD")
    r.o("Volume", vol_act, "ft3"); r.o("Degree-days", dd, "C-d")
    r.o("VS reduction (degree-day estimate)", vsr * 100, "%"); r.o("VS destroyed", vsd, "lb/d")
    r.o("Oxygen requirement", o2, "lb/d"); r.o("Air for O2 (10% OTE)", air_o2, "scfm")
    r.o("Air for mixing", air_mix, "scfm"); r.o("Design air", max(air_o2, air_mix), "scfm")
    r.o("Digested solids", out.TS_lb, "lb/d")
    r.c(custom_check("Aerobic digester SRT vs PSRP requirement at T", srt_act, "d", lo=srt_req,
                     kind="limit", source="40CFR503 App. B (40 d @ 20 C - 60 d @ 15 C)"))
    r.c(lib.check(inp.aer_mixing, "aer_dig_mixing_air"))
    r.c(custom_check("Aerobic digester SRT vs IL basis (27 d at 15 C)", srt_act, "d", lo=27 if inp.temp_C <= 15 else 0,
                     kind="typical", source="IL-35IAC370 370.840", verified=True))
    r.data.update(air_scfm=max(air_o2, air_mix), D=D, n=inp.n_units, swd=inp.swd_ft, volume=vol_act, kind="aerobic")
    return r, out, side


# ---------------------------------------------------------------- dewatering
DEWATER_DEFAULTS = {
    "Centrifuge": dict(cake=22.0, capture=95.0, polymer=25.0, unit_lb_h=1500.0),
    "Belt filter press": dict(cake=18.0, capture=93.0, polymer=15.0, unit_lb_h=1200.0),
    "Screw press": dict(cake=18.0, capture=92.0, polymer=20.0, unit_lb_h=600.0),
}


@dataclass
class DewateringInputs:
    method: str = fld("Centrifuge", "Dewatering equipment", choices=list(DEWATER_DEFAULTS) + ["None"])
    cake_pct: float = fld(0.0, "Cake solids (0 = equipment default)", "%", 0, 40)
    capture_pct: float = fld(0.0, "Solids capture (0 = default)", "%", 0, 99)
    polymer: float = fld(0.0, "Polymer (0 = default)", "lb/dry ton", 0, 60)
    unit_capacity: float = fld(0.0, "Capacity per unit (0 = default)", "lb/h", 0, 10000)
    hours_per_week: float = fld(40.0, "Operating hours per week", "h/wk", 8, 168)
    standby_units: int = fld(1, "Standby units", "", 0, 3)
    cake_density: float = fld(65.0, "Cake bulk density", "lb/ft3", 50, 75)
    truck_yd3: float = fld(20.0, "Haul truck capacity", "yd3", 5, 40)


def design_dewatering(inp: DewateringInputs, feed: Solids, lib=None):
    lib = lib or default_library()
    if inp.method == "None" or feed.TS_lb <= 0:
        r = UnitResult("Dewatering - none (liquid hauling)", "Solids")
        r.o("Liquid biosolids", feed.gpd, "gpd")
        return r, feed, SideStream()
    d = DEWATER_DEFAULTS[inp.method]
    cake = inp.cake_pct or d["cake"]; cap = inp.capture_pct or d["capture"]
    poly = inp.polymer or d["polymer"]; ucap = inp.unit_capacity or d["unit_lb_h"]
    r = UnitResult(f"Dewatering - {inp.method}", "Solids")
    weekly = feed.TS_lb * 7
    lb_h = weekly / inp.hours_per_week
    n_duty = max(1, math.ceil(lb_h / ucap))
    out, side = _split(feed, cap / 100, cake)
    side.NH3_lb = 0.0
    wet_tons = out.TS_lb / (cake / 100) / 2000
    yd3 = out.TS_lb / (cake / 100) / inp.cake_density / 27
    r.i("Feed solids", feed.TS_lb, "lb/d"); r.i("Feed concentration", feed.pct, "%")
    r.i("Operating schedule", inp.hours_per_week, "h/wk")
    r.o("Solids processing rate", lb_h, "lb/h")
    r.o("Units", f"{n_duty} duty + {inp.standby_units} standby @ {ucap:,.0f} lb/h")
    r.o("Cake solids", cake, "%"); r.o("Solids capture", cap, "%")
    r.o("Dry cake", out.TS_lb, "lb/d"); r.o("Wet cake", wet_tons, "wet tons/d")
    r.o("Cake volume", yd3, "yd3/d"); r.o("Truck loads", yd3 * 7 / inp.truck_yd3, "per week")
    r.o("Polymer", poly * feed.TS_lb / 2000, "lb/d active")
    r.o("Filtrate / centrate", side.gpd, "gpd"); r.o("Filtrate TSS", side.TSS_lb, "lb/d")
    r.c(custom_check("Duty units at design throughput", lb_h / (n_duty * ucap), "x capacity", hi=1.0,
                     kind="limit", source="Equipment rating"))
    r.data.update(wet_tons=wet_tons, yd3=yd3, n_units=n_duty + inp.standby_units, unit_lb_h=ucap,
                  polymer_lbd=poly * feed.TS_lb / 2000, method=inp.method, hours=inp.hours_per_week,
                  standby=inp.standby_units)
    return r, out, side
