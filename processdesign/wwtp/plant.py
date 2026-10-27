"""Whole-plant WWTP design: runs the liquid and solids trains in sequence,
returns side streams (thickener overflow, DAF subnatant, filtrate, filter
backwash) to the primary influent, and iterates to a converged mass balance."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.criteria import default_library, PASS, WARN, FAIL
from ..core.fields import fld
from ..core.serialize import save_json, load_json
from ..core.unitop import UnitResult
from ..core.units import load_lbd, conc_mgl, FT3_PER_M3
from .influent import Influent, blend
from .preliminary import ScreenInputs, GritInputs, EQInputs, design_bar_screen, design_aerated_grit, design_equalization
from .primary import PrimaryInputs, design_primary
from .activated_sludge import ASInputs, design_activated_sludge, PROCESSES
from .aeration import AerationInputs, design_aeration
from .clarifier import SecondaryInputs, design_secondary_clarifier
from .tertiary import FilterInputs, DisinfectionInputs, design_filter, design_disinfection
from .solids import (Solids, SideStream, ThickeningInputs, DigestionInputs, DewateringInputs,
                     design_thickening, design_digestion, design_dewatering)
from .pumping import LiftStationInputs, ProcessPumpInputs, design_lift_station, design_process_pumps
from .hydraulic_profile import HydraulicInputs, design_hydraulic_profile
from .dynamic import DynamicInputs, design_dynamic
from .reliability import ReliabilityInputs, design_reliability
from .costs import CostInputs, estimate_costs


@dataclass
class ProjectInfo:
    name: str = fld("New WWTP Design", "Project name")
    client: str = fld("", "Client / owner")
    location: str = fld("", "Location")
    engineer: str = fld("", "Prepared by")
    notes: str = fld("", "Notes")


@dataclass
class PermitLimits:
    BOD: float = fld(30.0, "BOD5 (monthly avg; 0 = none)", "mg/L", 0, 100)
    TSS: float = fld(30.0, "TSS (monthly avg; 0 = none)", "mg/L", 0, 100)
    NH3N: float = fld(2.0, "NH3-N (monthly avg; 0 = none)", "mg/L", 0, 50)
    TN: float = fld(0.0, "Total N (monthly avg; 0 = none)", "mg/L", 0, 100)
    TP: float = fld(0.0, "Total P (monthly avg; 0 = none)", "mg/L", 0, 20)


@dataclass
class RecycleInputs:
    enabled: bool = fld(True, "Return side streams to primary influent")
    max_iter: int = fld(40, "Maximum iterations", "", 1, 200)
    tolerance_pct: float = fld(0.1, "Convergence tolerance", "%", 0.001, 5)


@dataclass
class PlantInputs:
    project: ProjectInfo = field(default_factory=ProjectInfo)
    influent: Influent = field(default_factory=Influent)
    permit: PermitLimits = field(default_factory=PermitLimits)
    screens: ScreenInputs = field(default_factory=ScreenInputs)
    grit: GritInputs = field(default_factory=GritInputs)
    equalization: EQInputs = field(default_factory=EQInputs)
    primary: PrimaryInputs = field(default_factory=PrimaryInputs)
    activated_sludge: ASInputs = field(default_factory=ASInputs)
    aeration: AerationInputs = field(default_factory=AerationInputs)
    secondary: SecondaryInputs = field(default_factory=SecondaryInputs)
    filtration: FilterInputs = field(default_factory=FilterInputs)
    disinfection: DisinfectionInputs = field(default_factory=DisinfectionInputs)
    thickening: ThickeningInputs = field(default_factory=ThickeningInputs)
    digestion: DigestionInputs = field(default_factory=DigestionInputs)
    dewatering: DewateringInputs = field(default_factory=DewateringInputs)
    recycle: RecycleInputs = field(default_factory=RecycleInputs)
    lift_station: LiftStationInputs = field(default_factory=LiftStationInputs)
    process_pumps: ProcessPumpInputs = field(default_factory=ProcessPumpInputs)
    hydraulics: HydraulicInputs = field(default_factory=HydraulicInputs)
    dynamic: DynamicInputs = field(default_factory=DynamicInputs)
    reliability: ReliabilityInputs = field(default_factory=ReliabilityInputs)
    costs: CostInputs = field(default_factory=CostInputs)

    def save(self, path):
        save_json(self, path, {"module": "wwtp"})

    @classmethod
    def load(cls, path):
        return load_json(cls, path)


# Ordered (section key, display title) for GUI navigation and reports
SECTIONS = [
    ("project", "Project"), ("influent", "Influent & Flows"), ("permit", "Permit Limits"),
    ("screens", "Bar Screens"), ("grit", "Grit Removal"), ("equalization", "Equalization"),
    ("primary", "Primary Clarifiers"), ("activated_sludge", "Activated Sludge / BNR"),
    ("aeration", "Aeration System"), ("secondary", "Secondary Clarifiers"),
    ("filtration", "Tertiary Filtration"), ("disinfection", "Disinfection"),
    ("thickening", "Thickening"), ("digestion", "Digestion"), ("dewatering", "Dewatering"),
    ("recycle", "Recycle Streams"), ("lift_station", "Influent Lift Station"),
    ("process_pumps", "Process Pumps"), ("hydraulics", "Hydraulic Profile"),
    ("dynamic", "Dynamic Simulation"), ("reliability", "Reliability Class"), ("costs", "Cost Basis"),
]

UNIT_KEYS = [("Mechanical Bar Screens", "screens"), ("Aerated Grit", "grit"), ("Flow Equalization", "equalization"),
             ("Primary Clarifiers", "primary"), ("Activated Sludge", "activated_sludge"),
             ("Aeration System", "aeration"), ("Secondary Clarifiers", "secondary"), ("Tertiary Filters", "filter"),
             ("Chlorine Contact", "disinfection"), ("UV Disinfection", "disinfection"),
             ("Sludge Thickening", "thickening"), ("Anaerobic Digestion", "digestion"),
             ("Aerobic Digestion", "digestion"), ("Dewatering", "dewatering"),
             ("Influent Lift Station", "lift"), ("Process Pumps", "process_pumps"),
             ("Hydraulic Profile", "hydraulics"), ("Dynamic Simulation", "dynamic"), ("Cost Estimate", "costs")]


def unit_data(units) -> dict:
    out = {}
    for u in units:
        for prefix, key in UNIT_KEYS:
            if u.name.startswith(prefix):
                out[key] = u.data
    return out


@dataclass
class PlantResult:
    inputs: PlantInputs
    units: list[UnitResult]
    streams: list[dict]
    sludge: list[dict]
    compliance: list[dict]
    iterations: int
    converged: bool
    warnings: list[str]

    def unit(self, key: str):
        for u in self.units:
            for prefix, k in UNIT_KEYS:
                if k == key and u.name.startswith(prefix):
                    return u
        return None

    @property
    def status(self) -> str:
        s = {u.status for u in self.units} | {c["status"] for c in self.compliance}
        return FAIL if FAIL in s else (WARN if WARN in s else PASS)

    def counts(self) -> dict:
        out = {PASS: 0, WARN: 0, FAIL: 0}
        for u in self.units:
            for c in u.checks:
                if c.status in out:
                    out[c.status] += 1
        return out


def _stream(name: str, q: float, **c) -> dict:
    return {"name": name, "Q": q, **{k: c.get(k) for k in ("BOD", "TSS", "TKN", "NH3N", "NO3N", "TP")}}


def _side_conc(side: SideStream) -> tuple[float, dict]:
    q = side.gpd / 1e6
    if q <= 0:
        return 0.0, {}
    tss, vss = conc_mgl(side.TSS_lb, q), conc_mgl(side.VSS_lb, q)
    nh3 = conc_mgl(side.NH3_lb, q)
    return q, {"TSS": tss, "VSS": vss, "NH3N": nh3, "TKN": nh3 + 0.08 * vss,
               "TP": conc_mgl(side.TP_lb, q) + 0.02 * vss, "BOD": 0.5 * vss, "COD": 1.42 * vss}


def run_plant(pi: PlantInputs, lib=None) -> PlantResult:
    lib = lib or default_library()
    raw = pi.influent
    warnings = list(raw.validate())
    side = SideStream()
    converged = not pi.recycle.enabled
    iterations = 0

    for it in range(pi.recycle.max_iter if pi.recycle.enabled else 1):
        iterations = it + 1
        units: list[UnitResult] = []
        # ---- headworks (raw flow) ----
        if pi.screens.enabled:
            units.append(design_bar_screen(pi.screens, raw.Q_avg, raw.Q_peak, lib))
        if pi.grit.enabled:
            units.append(design_aerated_grit(pi.grit, raw.Q_avg, raw.Q_peak, lib))
        down = raw
        if pi.equalization.enabled:
            units.append(design_equalization(pi.equalization, raw.Q_avg, raw.PF_peakhour, lib))
            down = raw.copy(PF_peakhour=raw.PF_maxday)

        # ---- recycle returns to primary influent ----
        q_side, c_side = _side_conc(side)
        pri_in = blend(down, q_side, c_side) if pi.recycle.enabled else down

        primary_sludge = None
        if pi.primary.enabled:
            pr, sec_in, ps = design_primary(pi.primary, pri_in, lib)
            units.append(pr)
            primary_sludge = Solids(ps["TSS_lb"], ps["VSS_lb"], ps["solids_pct"], ps["N_lb"], ps["P_lb"])
        else:
            sec_in = pri_in

        asr = design_activated_sludge(pi.activated_sludge, sec_in, lib)
        units.append(asr)
        d = asr.data
        V_aer_ft3 = d["V_aer_m3"] * FT3_PER_M3
        units.append(design_aeration(pi.aeration, d["o2_design_lb"], pi.activated_sludge.do, V_aer_ft3, lib))
        cls = "chemP" if pi.activated_sludge.chem_p else ("nitrifying" if d["nitrify"] else "conventional")
        units.append(design_secondary_clarifier(pi.secondary, sec_in.Q_avg, sec_in.Q_peak, sec_in.Q_maxday,
                                                d["mlss"], d["R"], cls, lib))
        eff = dict(d["effluent"])
        bw_side = SideStream()
        if pi.filtration.enabled:
            fr = design_filter(pi.filtration, sec_in.Q_avg, sec_in.Q_peak, eff["TSS"], lib)
            units.append(fr)
            dtss = eff["TSS"] - fr.data["tss_out"]
            k = pi.activated_sludge.kinetics
            eff["TSS"] = fr.data["tss_out"]
            eff["BOD"] = max(eff["BOD"] - 0.66 * dtss, eff["sBOD"])
            eff["TKN"] -= k.n_biomass * k.vss_tss_bio * dtss
            eff["TN"] = eff["TKN"] + eff["NO3N"]
            pfrac = k.p_pao if d["process"] == PROCESSES[2] else k.p_biomass
            eff["TP"] = max(eff["TP"] - pfrac * k.vss_tss_bio * dtss, 0.02)
            bw_side = SideStream(fr.data["recycle_gpd"], fr.data["recycle_tss_lb"],
                                 0.8 * fr.data["recycle_tss_lb"])
        units.append(design_disinfection(pi.disinfection, sec_in.Q_avg, sec_in.Q_peak, lib))

        # ---- solids train ----
        was = Solids(d["was_lb"], d["was_vss_lb"], d["xr"] / 1e4,
                     d["was_lb"] * d["was_N_frac"], d["was_lb"] * d["was_P_frac"])
        tr, thick, s_thick = design_thickening(pi.thickening, primary_sludge, was, lib)
        units.append(tr)
        dg, digested, s_dig = design_digestion(pi.digestion, thick, lib)
        units.append(dg)
        dw, cake, s_dw = design_dewatering(pi.dewatering, digested, lib)
        units.append(dw)
        # digester release leaves in the dewatering liquor
        s_dw = SideStream(s_dw.gpd, s_dw.TSS_lb, s_dw.VSS_lb, s_dig.NH3_lb, s_dig.TP_lb)
        if pi.dewatering.method == "None":
            s_dw = SideStream()   # liquid hauled; liquor leaves with biosolids
        new_side = s_thick + s_dw + bw_side

        if not pi.recycle.enabled:
            break
        tol = pi.recycle.tolerance_pct / 100
        def close(a, b):
            return abs(a - b) <= tol * max(abs(b), 1e-6) + 1e-6
        if it > 0 and close(new_side.TSS_lb, side.TSS_lb) and close(new_side.NH3_lb, side.NH3_lb) \
                and close(new_side.gpd, side.gpd):
            side = new_side
            converged = True
            break
        side = new_side

    if pi.recycle.enabled and not converged:
        warnings.append(f"Recycle loop did not converge in {iterations} iterations.")

    # ---- post-process modules (no effect on the mass balance) ----
    ud = unit_data(units)
    def insert_after(prefix, res):
        idx = next((i for i, u in enumerate(units) if u.name.startswith(prefix)), len(units) - 1)
        units.insert(idx + 1, res)
    ras_max = max(pi.secondary.ras_max_ratio, d["R"])
    if pi.dynamic.enabled:
        try:
            dyn = design_dynamic(pi.dynamic, sec_in, d, pi.activated_sludge.do, d["o2_design_lb"],
                                 pi.equalization.diurnal, nh3_limit=pi.permit.NH3N)
            insert_after("Aeration System", dyn)
        except Exception as e:   # noqa: BLE001 - keep the steady design usable
            warnings.append(f"Dynamic simulation did not complete: {e}")
    pumps = design_process_pumps(pi.process_pumps, sec_in.Q_avg, ras_max, d["R"], d["was_gpd"], d["IR"], lib)
    insert_after("Secondary Clarifiers", pumps)
    ud = unit_data(units)
    hyd = None
    if pi.hydraulics.enabled:
        hyd = design_hydraulic_profile(pi.hydraulics, sec_in.Q_peak, ras_max * sec_in.Q_avg, ud, lib)
        units.append(hyd)
    if pi.lift_station.enabled:
        ls_in = pi.lift_station
        if hyd is not None and ls_in.wetwell_lwl_el > 0:
            from dataclasses import replace as _rep
            ls_in = _rep(ls_in, static_lift_ft=hyd.data["headworks_wse"] - ls_in.wetwell_lwl_el)
        units.insert(0, design_lift_station(ls_in, raw.Q_avg, raw.Q_peak, raw.Q_avg * 0.4, lib))
    ud = unit_data(units)
    if pi.reliability.enabled:
        units.append(design_reliability(pi.reliability, pi, ud, raw.Q_avg, raw.Q_peak))
    if pi.costs.enabled:
        units.append(estimate_costs(pi.costs, pi, ud, raw.Q_avg))

    # ---- mass balance tables ----
    q_side, c_side = _side_conc(side)
    streams = [
        _stream("Raw influent", raw.Q_avg, BOD=raw.BOD, TSS=raw.TSS, TKN=raw.TKN, NH3N=raw.NH3N,
                NO3N=raw.NO3N, TP=raw.TP),
    ]
    if q_side:
        streams.append(_stream("Recycle side streams", q_side, BOD=c_side["BOD"], TSS=c_side["TSS"],
                               TKN=c_side["TKN"], NH3N=c_side["NH3N"], NO3N=0.0, TP=c_side["TP"]))
    streams.append(_stream("Primary influent (with recycle)", pri_in.Q_avg, BOD=pri_in.BOD, TSS=pri_in.TSS,
                           TKN=pri_in.TKN, NH3N=pri_in.NH3N, NO3N=pri_in.NO3N, TP=pri_in.TP))
    if pi.primary.enabled:
        streams.append(_stream("Primary effluent", sec_in.Q_avg, BOD=sec_in.BOD, TSS=sec_in.TSS,
                               TKN=sec_in.TKN, NH3N=sec_in.NH3N, NO3N=sec_in.NO3N, TP=sec_in.TP))
    streams.append(_stream("Final effluent", sec_in.Q_avg, BOD=eff["BOD"], TSS=eff["TSS"], TKN=eff["TKN"],
                           NH3N=eff["NH3N"], NO3N=eff["NO3N"], TP=eff["TP"]))

    sludge = []
    if primary_sludge:
        sludge.append({"name": "Primary sludge", "TS": primary_sludge.TS_lb, "VS": primary_sludge.VS_lb,
                       "pct": primary_sludge.pct, "gpd": primary_sludge.gpd})
    sludge += [
        {"name": "Waste activated sludge", "TS": was.TS_lb, "VS": was.VS_lb, "pct": was.pct, "gpd": was.gpd},
        {"name": "Thickened blend", "TS": thick.TS_lb, "VS": thick.VS_lb, "pct": thick.pct, "gpd": thick.gpd},
        {"name": "Stabilized sludge", "TS": digested.TS_lb, "VS": digested.VS_lb, "pct": digested.pct,
         "gpd": digested.gpd},
        {"name": "Biosolids to disposal", "TS": cake.TS_lb, "VS": cake.VS_lb, "pct": cake.pct, "gpd": cake.gpd},
    ]

    compliance = []
    for key, label in (("BOD", "BOD5"), ("TSS", "TSS"), ("NH3N", "NH3-N"), ("TN", "Total N"), ("TP", "Total P")):
        limit = getattr(pi.permit, key)
        pred = eff[key]
        if limit and limit > 0:
            st = PASS if pred <= 0.8 * limit else (WARN if pred <= limit else FAIL)
        else:
            st = "INFO"
        compliance.append({"param": label, "predicted": pred, "limit": limit or None, "status": st,
                           "note": "predicted > 80% of limit (little margin for variability)" if st == WARN else ""})

    return PlantResult(pi, units, streams, sludge, compliance, iterations, converged, warnings)
