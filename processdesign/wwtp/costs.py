"""Planning-level (AACE Class 4-5) capital and O&M cost estimate.

Quantities come from the process design (concrete from tank geometry,
equipment from sizes, energy and chemicals from the mass balance). Unit prices
are PLACEHOLDERS - every firm must load its own regional unit-cost basis
(bid tabs, RSMeans) and ENR index before using results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.fields import fld
from ..core.unitop import UnitResult


@dataclass
class CostInputs:
    enabled: bool = fld(True, "Prepare cost estimate")
    # --- index & markups
    enr_base: float = fld(13000.0, "ENR CCI of unit-cost basis", "-", 1000, 50000)
    enr_current: float = fld(13000.0, "ENR CCI for estimate date", "-", 1000, 50000)
    sitework_pct: float = fld(10.0, "Sitework", "% of process", 0, 50)
    yard_piping_pct: float = fld(12.0, "Yard piping", "% of process", 0, 50)
    electrical_ic_pct: float = fld(20.0, "Electrical and I&C", "% of process", 0, 60)
    contractor_pct: float = fld(15.0, "Contractor OH&P, bonds, insurance", "%", 0, 40)
    contingency_pct: float = fld(25.0, "Contingency", "%", 0, 60)
    engineering_pct: float = fld(15.0, "Engineering, legal, administration", "%", 0, 40)
    # --- unit prices (PLACEHOLDERS)
    concrete_cy: float = fld(1500.0, "Structural concrete, in place", "$/CY")
    wall_ft: float = fld(1.5, "Typical wall thickness", "ft", 0.75, 3)
    slab_ft: float = fld(2.0, "Typical base slab thickness", "ft", 1, 4)
    screen_each: float = fld(300000.0, "Mechanical screen + washer/compactor, each", "$")
    grit_each: float = fld(250000.0, "Aerated grit equipment per chamber", "$")
    clarifier_per_ft: float = fld(4000.0, "Clarifier mechanism", "$/ft diameter")
    diffuser_per_scfm: float = fld(35.0, "Fine-bubble diffuser grid", "$/scfm")
    blower_per_hp: float = fld(2500.0, "Blowers installed", "$/hp")
    pump_per_hp: float = fld(3000.0, "Pumps installed (incl. valves)", "$/hp")
    pump_min_each: float = fld(25000.0, "Minimum cost per pump", "$")
    mixer_per_kw: float = fld(15000.0, "Submersible mixers", "$/kW")
    filter_per_ft2: float = fld(600.0, "Tertiary filter equipment", "$/ft2")
    uv_per_lamp: float = fld(4000.0, "UV system", "$/lamp")
    chlorine_feed_ls: float = fld(250000.0, "Hypochlorite / bisulfite storage and feed", "$ lump sum")
    daf_per_ft2: float = fld(3500.0, "DAF thickener", "$/ft2")
    gt_per_ft: float = fld(3000.0, "Gravity thickener mechanism", "$/ft diameter")
    digester_equip_per_ft3: float = fld(25.0, "Digester cover, mixing, heating, gas handling", "$/ft3")
    dewater_per_lbh: float = fld(500.0, "Dewatering equipment", "$/(lb/h capacity)")
    building_ls_per_mgd: float = fld(500000.0, "Operations/process buildings", "$/MGD")
    # --- O&M
    power_kwh: float = fld(0.10, "Electricity", "$/kWh")
    hypo_gal: float = fld(2.0, "Sodium hypochlorite 12.5%", "$/gal")
    bisulfite_gal: float = fld(3.0, "Sodium bisulfite 38%", "$/gal")
    alum_gal: float = fld(2.5, "Liquid alum 48.5%", "$/gal")
    naoh_lb: float = fld(0.35, "Caustic (100% basis)", "$/lb")
    polymer_lb: float = fld(2.5, "Polymer (active)", "$/lb")
    biosolids_wet_ton: float = fld(60.0, "Biosolids hauling + disposal", "$/wet ton")
    staff_fte: float = fld(0.0, "Operations staff (0 = estimate)", "FTE", 0, 200)
    fte_cost: float = fld(95000.0, "Loaded cost per FTE", "$/yr")
    maintenance_pct: float = fld(2.0, "Maintenance", "% of equipment capital / yr")
    biogas_credit: bool = fld(False, "Credit biogas as CHP electricity")
    chp_elec_eff: float = fld(0.35, "CHP electrical efficiency", "-", 0.2, 0.45)
    # --- life cycle
    life_yr: int = fld(20, "Planning period", "yr", 5, 50)
    discount_pct: float = fld(4.0, "Real discount rate", "%", 0, 12)


def _rect_concrete(L, W, H, n, wall, slab):
    walls = 2 * (L + W) * H * wall
    base = (L + 2 * wall) * (W + 2 * wall) * slab
    return n * (walls + base) / 27


def _circ_concrete(D, H, n, wall, slab):
    walls = math.pi * (D + wall) * H * wall
    base = math.pi * (D + 2 * wall) ** 2 / 4 * slab
    return n * (walls + base) / 27


def estimate_costs(ci: CostInputs, pi, u: dict, Q_avg: float) -> UnitResult:
    """``u`` maps keys to UnitResult.data dicts."""
    r = UnitResult("Cost Estimate (planning level)", "Cost")
    fb = 2.0
    w, s = ci.wall_ft, ci.slab_ft
    items: list[tuple[str, str, float]] = []        # (area, item, cost)

    def add(area, item, cost):
        if cost > 0:
            items.append((area, item, cost))

    if "screens" in u:
        add("Headworks", "Mechanical screens", u["screens"]["n"] * ci.screen_each)
    if "grit" in u:
        g = u["grit"]
        add("Headworks", "Grit tanks (concrete)", _rect_concrete(g["length"], g["width"], g["depth"] + fb, g["n"], w, s) * ci.concrete_cy)
        add("Headworks", "Grit equipment", g["n"] * ci.grit_each)
    if "equalization" in u:
        e = u["equalization"]
        side = math.sqrt(e["volume_gal"] / 7.48 / e["depth"])
        add("Headworks", "Equalization basin (concrete)", _rect_concrete(side, side, e["depth"] + fb, 1, w, s) * ci.concrete_cy)
    if "lift" in u:
        lp = u["lift"]
        add("Pumping", "Influent pumps", max(lp["bhp_total"] / max(lp["n_total"] - 1, 1) * ci.pump_per_hp, ci.pump_min_each) * lp["n_total"])
        add("Pumping", "Wet well (concrete)", _circ_concrete(pi.lift_station.wetwell_diam_ft, 25, 1, w, s) * ci.concrete_cy)
    if "primary" in u:
        p = u["primary"]
        add("Primary", "Primary clarifiers (concrete)", _circ_concrete(p["diameter"], p["swd"] + fb, p["n"], w, s) * ci.concrete_cy)
        add("Primary", "Primary clarifier mechanisms", p["n"] * p["diameter"] * ci.clarifier_per_ft)
    a = u["activated_sludge"]
    add("Secondary", "Aeration basins (concrete)", _rect_concrete(a["L_ft"], a["W_ft"], a["swd_ft"] + fb, a["n_trains"], w, s) * ci.concrete_cy)
    add("Secondary", "Diffusers", u["aeration"]["air_scfm"] * ci.diffuser_per_scfm)
    n_bl = pi.aeration.n_duty + pi.aeration.n_standby
    add("Secondary", "Blowers", u["aeration"]["motor_hp"] * n_bl * ci.blower_per_hp)
    add("Secondary", "Anoxic/anaerobic mixers", a.get("mix_kw", 0) * ci.mixer_per_kw)
    if "process_pumps" in u:
        pp = u["process_pumps"]
        add("Secondary", "RAS / WAS / IR pumps", max(pp["hp"] * ci.pump_per_hp, pp["n_pumps"] * ci.pump_min_each))
    sc = u["secondary"]
    add("Secondary", "Final clarifiers (concrete)", _circ_concrete(sc["diameter"], sc["swd"] + fb, sc["n"], w, s) * ci.concrete_cy)
    add("Secondary", "Final clarifier mechanisms", sc["n"] * sc["diameter"] * ci.clarifier_per_ft)
    if "filter" in u:
        add("Tertiary", "Tertiary filters", u["filter"]["area_total"] * ci.filter_per_ft2)
    d = u.get("disinfection", {})
    if "volume_ft3" in d:
        side = math.sqrt(d["volume_ft3"] / d["depth"] / max(d["n_basins"], 1))
        add("Disinfection", "Chlorine contact tanks (concrete)",
            _rect_concrete(side, side, d["depth"] + fb, d["n_basins"], w, s) * ci.concrete_cy * 1.4)   # x1.4 baffle walls
        add("Disinfection", "Chemical storage and feed", ci.chlorine_feed_ls)
    elif "lamps" in d:
        add("Disinfection", "UV system", d["lamps"] * ci.uv_per_lamp)
    t = u.get("thickening", {})
    if t.get("gt"):
        add("Solids", "Gravity thickeners", _circ_concrete(t["gt"]["D"], 14, t["gt"]["n"], w, s) * ci.concrete_cy
            + t["gt"]["n"] * t["gt"]["D"] * ci.gt_per_ft)
    if t.get("daf"):
        add("Solids", "DAF thickeners", t["daf"]["area"] * ci.daf_per_ft2)
    dg = u.get("digestion", {})
    if dg.get("kind"):
        add("Solids", "Digesters (concrete)", _circ_concrete(dg["D"], dg["swd"] + 3, dg["n"], w, s) * ci.concrete_cy)
        add("Solids", "Digester equipment", dg["volume"] * ci.digester_equip_per_ft3)
    dw = u.get("dewatering", {})
    if dw.get("n_units"):
        add("Solids", f"Dewatering ({dw['method']})", dw["n_units"] * dw["unit_lb_h"] * ci.dewater_per_lbh)
    add("Buildings", "Operations / process buildings", Q_avg * ci.building_ls_per_mgd)

    enr = ci.enr_current / ci.enr_base
    items = [(ar, it, c * enr) for ar, it, c in items]
    process = sum(c for _, _, c in items)
    equip = sum(c for _, it, c in items if "concrete" not in it and "buildings" not in it.lower())
    site = process * ci.sitework_pct / 100
    yard = process * ci.yard_piping_pct / 100
    elec = process * ci.electrical_ic_pct / 100
    direct = process + site + yard + elec
    contractor = direct * ci.contractor_pct / 100
    subtotal = direct + contractor
    conting = subtotal * ci.contingency_pct / 100
    construction = subtotal + conting
    eng = construction * ci.engineering_pct / 100
    capital = construction + eng

    # ---- O&M -----------------------------------------------------------
    kwh = {
        "Aeration blowers": u["aeration"]["hp"] * 0.7457 * 8760 * 0.6,
        "Influent pumping": u.get("lift", {}).get("kwh_yr", 0.0),
        "Process pumping": u.get("process_pumps", {}).get("kwh_yr", 0.0),
        "Mixing": a.get("mix_kw", 0.0) * 8760,
        "UV": d.get("kw_avg", 0.0) * 8760,
    }
    if dg.get("kind") == "aerobic":
        kwh["Aerobic digester air"] = dg.get("air_scfm", 0) * u["aeration"]["hp"] / max(u["aeration"]["air_scfm"], 1) * 0.7457 * 8760
    if dw.get("n_units"):
        kwh["Dewatering"] = 40 * dw["hours"] * 52 * max(dw["n_units"] - dw["standby"], 1)   # ~40 kW per running unit
    kwh_total = sum(kwh.values())
    energy = kwh_total * ci.power_kwh
    chem = {
        "Hypochlorite": d.get("hypo_gpd", 0) * 365 * ci.hypo_gal,
        "Bisulfite": d.get("bisulfite_gpd", 0) * 365 * ci.bisulfite_gal,
        "Alum": a.get("alum_gpd", 0) * 365 * ci.alum_gal,
        "Caustic": a.get("alk_add_lb", 0) * 0.8 * 365 * ci.naoh_lb,
        "Polymer": (t.get("daf", {}).get("polymer_lbd", 0) + dw.get("polymer_lbd", 0)) * 365 * ci.polymer_lb,
    }
    chem_total = sum(chem.values())
    biosolids = dw.get("wet_tons", 0) * 365 * ci.biosolids_wet_ton
    fte = ci.staff_fte or round(2 + 3 * Q_avg ** 0.6, 1)
    labor = fte * ci.fte_cost
    maint = equip * ci.maintenance_pct / 100
    credit = 0.0
    if ci.biogas_credit and dg.get("ch4_ft3d"):
        credit = dg["ch4_ft3d"] * 960 * 365 / 3412 * ci.chp_elec_eff * ci.power_kwh
    om = energy + chem_total + biosolids + labor + maint - credit
    i = ci.discount_pct / 100
    pwf = (1 - (1 + i) ** -ci.life_yr) / i if i > 0 else ci.life_yr
    npv = capital + om * pwf
    mg_life = Q_avg * 365 * ci.life_yr

    r.i("ENR adjustment", enr, "x", 3); r.i("Planning period", ci.life_yr, "yr")
    r.i("Discount rate", ci.discount_pct, "%"); r.i("Electricity", ci.power_kwh, "$/kWh")
    for ar, it, c in items:
        r.o(f"[{ar}] {it}", c, "$")
    r.o("Process construction subtotal", process, "$")
    r.o("Sitework + yard piping + electrical/I&C", site + yard + elec, "$")
    r.o("Contractor OH&P", contractor, "$"); r.o("Contingency", conting, "$")
    r.o("Construction cost", construction, "$"); r.o("Engineering / legal / admin", eng, "$")
    r.o("TOTAL CAPITAL COST", capital, "$")
    r.o("Capital cost per gallon of capacity", capital / (Q_avg * 1e6), "$/gpd", 2)
    for k, v in kwh.items():
        if v:
            r.o(f"Energy - {k}", v, "kWh/yr")
    r.o("Energy cost", energy, "$/yr")
    for k, v in chem.items():
        if v:
            r.o(f"Chemical - {k}", v, "$/yr")
    r.o("Biosolids disposal", biosolids, "$/yr")
    r.o("Labor", labor, "$/yr"); r.o("Staff", fte, "FTE", 1)
    r.o("Maintenance", maint, "$/yr")
    if credit:
        r.o("Biogas electricity credit", -credit, "$/yr")
    r.o("TOTAL ANNUAL O&M", om, "$/yr")
    r.o("O&M per MG treated", om / (Q_avg * 365), "$/MG")
    r.o("Present worth (capital + O&M)", npv, "$")
    r.o("Life-cycle cost per 1,000 gal", npv / mg_life / 1000, "$/kgal", 2)
    r.note("PLACEHOLDER UNIT PRICES - replace with a regional cost basis (bid tabulations, RSMeans) and the "
           "matching ENR CCI before using. Planning level only (AACE Class 4-5, about -30% / +50%).")
    r.note("Excludes land, permitting fees, collection system, financing and escalation to midpoint of construction.")
    r.data.update(capital=capital, om=om, npv=npv, items=items, energy_kwh=kwh_total,
                  summary={"Process": process, "Sitework/yard/E&IC": site + yard + elec, "Contractor": contractor,
                           "Contingency": conting, "Engineering": eng})
    return r
