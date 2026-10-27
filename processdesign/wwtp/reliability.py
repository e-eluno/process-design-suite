"""SC R.61-67.400 reliability classification checks (Class I / II / III).

Rules transcribed from S.C. Code Regs. 61-67.400 (via Justia, checked
2026-10-27): sludge management (C), Class I (D), Class II (E), Class III (F).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.criteria import custom_check
from ..core.fields import fld
from ..core.unitop import UnitResult

SRC = "SC-R61-67.400"


@dataclass
class ReliabilityInputs:
    enabled: bool = fld(True, "Check SC R.61-67.400 reliability classification")
    rel_class: str = fld("III", "Reliability class", choices=["I", "II", "III"],
                         help="I: discharge near shellfish, designated recreation or water-supply intakes; "
                              "II: near (not in) those areas; III: all others")
    standby_power: bool = fld(True, "Standby power provided for vital components")
    holding_basin_hours: float = fld(0.0, "Holding basin capacity (Class I)", "h of avg flow", 0, 48)


def _chk(r, label, ok_value, lo, rule, unit="-", hi=None):
    r.c(custom_check(label, ok_value, unit, lo=lo, hi=hi, kind="limit", source=f"{SRC} {rule}", verified=True))


def design_reliability(inp: ReliabilityInputs, pi, units: dict, Q_avg: float, Q_peak: float) -> UnitResult:
    c = inp.rel_class
    r = UnitResult(f"Reliability Class {c} (SC R.61-67.400)", "Reliability")
    r.i("Reliability class", c); r.i("Design average flow", Q_avg, "MGD")
    if Q_avg < 0.5:
        r.note("Facility < 500,000 gpd: SCDES may waive reliability requirements (67.400.B).")

    # ---- sludge management (all classes) ----
    dig = units.get("digestion", {})
    if dig.get("kind") == "anaerobic":
        _chk(r, "Anaerobic digesters provided", dig.get("n", 1), 2, "C.3", "tanks")
    if dig.get("kind") == "aerobic":
        _chk(r, "Aerobic digester blowers/aerators (min. 2; 2nd may be shelf spare)", 2, 2, "C.4", "units")
    dw = units.get("dewatering", {})
    if dw.get("method") in ("Centrifuge", "Belt filter press"):
        _chk(r, "Dewatering units beyond duty (largest out of service)", dw.get("standby", 0), 1, "C.6", "units")

    # ---- pumps (C.2 / D.5) ----
    ls = pi.lift_station
    if ls.enabled:
        _chk(r, "Influent pumps: standby so peak is met with one out", ls.n_standby, 1, "C.2 / D.5", "pumps")
    _chk(r, "RAS pumps: standby provided", pi.process_pumps.ras_n_standby, 1, "C.2 / D.5", "pumps")

    # ---- screens ----
    if pi.screens.enabled:
        _chk(r, "Backup bar screen for mechanically cleaned screens", pi.screens.n_standby, 1, "D.4", "screens")

    # ---- aeration basins ----
    need_basins = 1 if c == "III" else 2
    _chk(r, "Aeration basins", pi.activated_sludge.n_trains, need_basins, "D.3 / F.4", "basins")

    # ---- blowers ----
    a = pi.aeration
    _chk(r, "Blowers: oxygen transfer maintained with largest unit out", a.n_standby, 1, "D.8", "standby")
    _chk(r, "Blowers installed", a.n_duty + a.n_standby, 2, "D.8 / F.3", "units")

    # ---- clarifiers / sedimentation ----
    sec_n = pi.secondary.n_units
    pri_n = pi.primary.n_units if pi.primary.enabled else None
    if c == "I":
        if Q_avg > 0.1:
            _chk(r, "Final clarifiers (> 100,000 gpd)", sec_n, 2, "D.6", "units")
        _chk(r, "Final clarifiers: capacity with largest out (fraction of design flow)", (sec_n - 1) / sec_n, 0.75, "D.7")
        if pri_n:
            _chk(r, "Primary clarifiers: capacity with largest out", (pri_n - 1) / pri_n, 0.75, "D.7")
        if pi.filtration.enabled:
            n = pi.filtration.n_units
            _chk(r, "Tertiary filters: capacity with largest out", (n - 1) / n, 0.75, "D.7")
    elif c == "II":
        _chk(r, "Final clarifiers: capacity with largest out", (sec_n - 1) / sec_n, 0.50, "E.3")
        if pri_n:
            _chk(r, "Primary clarifiers: capacity with largest out", (pri_n - 1) / pri_n, 0.50, "E.3")
    else:
        _chk(r, "Final sedimentation basins", sec_n, 2, "F.5", "basins")
        if pri_n:
            _chk(r, "Primary sedimentation basins", pri_n, 2, "F.5", "basins")

    # ---- disinfection ----
    dis = units.get("disinfection", {})
    need = {"I": 0.75, "II": 0.50}.get(c)
    if need and "capacity_one_out_mgd" in dis:
        _chk(r, "Disinfection capacity with largest unit out / design average flow",
             dis["capacity_one_out_mgd"] / Q_avg, need, "D.11 / E.5")

    # ---- holding basin & power ----
    if c == "I":
        _chk(r, "Holding basin (24 h; 12 h with flow equalization)", inp.holding_basin_hours,
             12 if pi.equalization.enabled else 24, "D.2", "h")
    r.c(custom_check("Standby power for vital components", 1.0 if inp.standby_power else 0.0, "-", lo=1.0,
                     kind="limit", source=f"{SRC} D.12 / E.4 / F.6", verified=True))
    return r
