"""Influent characterization: flows, concentrations, COD fractionation, loads,
and design-flow estimators (Ten States per-capita, SC R.61-67 Appendix A)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from ..core.fields import fld
from ..core.criteria import DATA_DIR
from ..core.units import load_lbd, MGD_TO_M3D


@dataclass
class Influent:
    """Raw (or combined) wastewater stream. Concentrations in mg/L."""
    Q_avg: float = fld(5.0, "Design average flow", "MGD", 0.001, 500, step=0.1, decimals=3)
    PF_maxday: float = fld(1.5, "Maximum-day peaking factor", "-", 1.0, 5.0, step=0.05)
    PF_peakhour: float = fld(2.5, "Peak-hour peaking factor", "-", 1.0, 6.0, step=0.05)
    BOD: float = fld(220.0, "BOD5", "mg/L", 0, 5000)
    sBOD: float = fld(90.0, "Soluble BOD5", "mg/L", 0, 5000)
    COD: float = fld(500.0, "COD", "mg/L", 0, 20000)
    sCOD: float = fld(190.0, "Soluble COD", "mg/L", 0, 20000)
    rbCOD: float = fld(90.0, "Readily biodegradable COD", "mg/L", 0, 5000)
    sCOD_nb: float = fld(30.0, "Non-biodegradable soluble COD (= effluent sCOD)", "mg/L", 0, 1000)
    TSS: float = fld(220.0, "TSS", "mg/L", 0, 10000)
    VSS: float = fld(190.0, "VSS", "mg/L", 0, 10000)
    TKN: float = fld(40.0, "TKN", "mg/L N", 0, 1000)
    NH3N: float = fld(25.0, "Ammonia-N", "mg/L N", 0, 1000)
    NO3N: float = fld(0.0, "Nitrate-N", "mg/L N", 0, 200)
    TP: float = fld(7.0, "Total phosphorus", "mg/L P", 0, 500)
    alkalinity: float = fld(200.0, "Alkalinity", "mg/L as CaCO3", 0, 2000)
    T_min: float = fld(12.0, "Minimum month temperature", "C", 4, 40)
    T_max: float = fld(25.0, "Maximum month temperature", "C", 4, 40)
    bCOD_BOD: float = fld(1.6, "bCOD/BOD5 ratio", "-", 1.2, 2.2, help="M&E 5th ed. typical 1.6")

    # ---- derived properties ------------------------------------------------
    @property
    def Q_maxday(self) -> float:
        return self.Q_avg * self.PF_maxday

    @property
    def Q_peak(self) -> float:
        return self.Q_avg * self.PF_peakhour

    @property
    def Q_m3d(self) -> float:
        return self.Q_avg * MGD_TO_M3D

    @property
    def bCOD(self) -> float:
        return min(self.bCOD_BOD * self.BOD, self.COD - self.sCOD_nb)

    @property
    def nbCOD(self) -> float:
        return self.COD - self.bCOD

    @property
    def pCOD(self) -> float:
        return max(self.COD - self.sCOD, 0.0)

    @property
    def bpCOD(self) -> float:
        """Biodegradable particulate COD (M&E method)."""
        return max(self.bCOD_BOD * (self.BOD - self.sBOD), 0.0)

    @property
    def nbVSS(self) -> float:
        if self.pCOD <= 0:
            return 0.0
        frac_nb = max(0.0, 1.0 - min(self.bpCOD / self.pCOD, 1.0))
        return frac_nb * self.VSS

    @property
    def iTSS(self) -> float:
        return max(self.TSS - self.VSS, 0.0)

    def loads(self) -> dict[str, float]:
        q = self.Q_avg
        return {k: load_lbd(q, getattr(self, k)) for k in
                ("BOD", "COD", "TSS", "VSS", "TKN", "NH3N", "TP")}

    def validate(self) -> list[str]:
        errs = []
        if self.sBOD > self.BOD: errs.append("Soluble BOD exceeds total BOD.")
        if self.sCOD > self.COD: errs.append("Soluble COD exceeds total COD.")
        if self.rbCOD > self.sCOD: errs.append("rbCOD exceeds soluble COD.")
        if self.VSS > self.TSS: errs.append("VSS exceeds TSS.")
        if self.NH3N > self.TKN: errs.append("Ammonia exceeds TKN.")
        if self.BOD > 0 and not 1.5 <= self.COD / self.BOD <= 3.5:
            errs.append(f"COD/BOD = {self.COD/self.BOD:.2f} is outside the 1.5-3.5 range typical of municipal wastewater.")
        if self.PF_peakhour < self.PF_maxday: errs.append("Peak-hour factor is lower than max-day factor.")
        if self.T_max < self.T_min: errs.append("Maximum temperature is below minimum temperature.")
        return errs

    def copy(self, **changes) -> "Influent":
        return replace(self, **changes)


def blend(a: Influent, q_b: float, conc_b: dict[str, float]) -> Influent:
    """Flow-weighted blend of stream ``a`` with a side stream (flow MGD, concentrations mg/L).

    Used to add recycle streams (thickener overflow, filtrate, backwash) to the influent.
    Missing constituents in ``conc_b`` are taken as zero; COD/BOD fractions of the
    side-stream solids follow the influent's particulate ratios.
    """
    if q_b <= 0:
        return a
    qt = a.Q_avg + q_b
    def mix(attr):
        return (a.Q_avg * getattr(a, attr) + q_b * conc_b.get(attr, 0.0)) / qt
    tss_b, vss_b = conc_b.get("TSS", 0.0), conc_b.get("VSS", 0.0)
    # particulate COD/BOD carried by recycle solids (biomass-like: 1.42 g COD/g VSS)
    cod_b = conc_b.get("COD", 1.42 * vss_b)
    bod_b = conc_b.get("BOD", 0.5 * vss_b)
    pf_md = a.PF_maxday * a.Q_avg / qt + q_b / qt
    pf_ph = a.PF_peakhour * a.Q_avg / qt + q_b / qt
    return replace(
        a, Q_avg=qt, PF_maxday=max(pf_md, 1.0), PF_peakhour=max(pf_ph, 1.0),
        BOD=(a.Q_avg * a.BOD + q_b * bod_b) / qt,
        COD=(a.Q_avg * a.COD + q_b * cod_b) / qt,
        TSS=mix("TSS"), VSS=mix("VSS"), TKN=mix("TKN"), NH3N=mix("NH3N"),
        TP=mix("TP"), alkalinity=mix("alkalinity") if "alkalinity" in conc_b else a.alkalinity,
        sBOD=(a.Q_avg * a.sBOD) / qt + q_b * conc_b.get("sBOD", 0.0) / qt,
        sCOD=(a.Q_avg * a.sCOD) / qt + q_b * conc_b.get("sCOD", 0.0) / qt,
        rbCOD=(a.Q_avg * a.rbCOD) / qt,
        sCOD_nb=a.sCOD_nb,
    )


# ---- design-flow estimators ---------------------------------------------------

def ten_states_population_basis(population: float, gpcd: float = 100.0,
                                bod_lb=0.17, tss_lb=0.20, tkn_lb=0.036) -> dict:
    """Ten States Standards 2014 11.243/11.253 per-capita basis (new systems)."""
    q = population * gpcd / 1e6
    k = gpcd * 8.34e-6            # lb per capita-day per (mg/L); concentration is independent of population
    if k <= 0:
        raise ValueError("gpcd must be positive")
    return {"Q_avg": q, "BOD": bod_lb / k, "TSS": tss_lb / k, "TKN": tkn_lb / k}


def sc_appendix_a_table() -> list[dict]:
    return json.loads((DATA_DIR / "sc_r6167_appA.json").read_text())["items"]


def sc_appendix_a_flow(entries: list[tuple[int, float]]) -> dict:
    """Design flow from SC R.61-67 Appendix A.

    entries: list of (row index in ``sc_appendix_a_table()``, number of units).
    Returns total gpd and an itemized breakdown.
    """
    table = sc_appendix_a_table()
    lines, total = [], 0.0
    for idx, n in entries:
        row = table[idx]
        gpd = row["gpd"] * n
        total += gpd
        lines.append({**row, "count": n, "flow_gpd": gpd})
    return {"total_gpd": total, "total_mgd": total / 1e6, "lines": lines}
