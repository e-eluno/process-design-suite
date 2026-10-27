"""Plant hydraulic profile at peak hourly flow.

Computed upstream from the receiving-water high water level: outfall pipe,
disinfection, filters, final clarifier weirs and launder, aeration basin
effluent weir, primary clarifier weirs, grit, Parshall flume and screens.
Each structure's water surface elevation (WSE) is reported with the
top-of-wall needed for the chosen freeboard.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..core.criteria import default_library, custom_check
from ..core.fields import fld
from ..core.hydraulics import (hazen_williams_hf, pipe_velocity, velocity_head, select_pipe,
                               rect_weir_head, vnotch_head, launder_upstream_depth, parshall_head)
from ..core.unitop import UnitResult
from ..core.units import MGD_TO_CFS


@dataclass
class HydraulicInputs:
    enabled: bool = fld(True, "Compute hydraulic profile")
    receiving_hwl: float = fld(100.0, "Receiving water high water level (e.g. 100-yr)", "ft", -100, 10000)
    ground_el: float = fld(110.0, "Finished grade at plant", "ft", -100, 10000)
    outfall_ft: float = fld(500.0, "Outfall pipe length", "ft", 0, 20000)
    yard_pipe_ft: float = fld(150.0, "Typical yard pipe length between structures", "ft", 10, 2000)
    pipe_v_design: float = fld(3.0, "Yard pipe design velocity at peak", "ft/s", 1.5, 6)
    pipe_c: float = fld(120.0, "Hazen-Williams C (yard piping)", "-", 80, 150)
    k_pipe: float = fld(1.5, "Pipe entrance + exit + bends K", "-", 0.5, 5)
    free_fall_ft: float = fld(0.5, "Free fall below each effluent weir", "ft", 0.1, 2)
    launder_width_ft: float = fld(1.5, "Clarifier launder width", "ft", 0.5, 4)
    notch_spacing_in: float = fld(8.0, "V-notch spacing", "in", 4, 24)
    cct_bend_k: float = fld(3.2, "Chlorine contact 180-deg bend K (per bend)", "-", 1, 5)
    uv_loss_ft: float = fld(1.0, "UV channel loss incl. level-control weir", "ft", 0.2, 3)
    filter_loss_ft: float = fld(2.0, "Filter loss at terminal headloss", "ft", 0.5, 10)
    flume_throat_ft: float = fld(2.0, "Parshall flume throat width", "ft", 1, 8)
    screen_loss_ft: float = fld(0.0, "Screen loss (0 = use screen design, 50% blinded)", "ft", 0, 5)
    freeboard_ft: float = fld(1.5, "Freeboard above peak WSE", "ft", 0.5, 4)


def design_hydraulic_profile(inp: HydraulicInputs, Q_peak: float, Q_ras_max: float, units: dict, lib=None):
    """``units`` maps short keys to UnitResult.data dicts from the process design."""
    lib = lib or default_library()
    r = UnitResult("Hydraulic Profile (peak hour)", "Hydraulics")
    q = Q_peak * MGD_TO_CFS
    qr = Q_ras_max * MGD_TO_CFS
    stations = []                     # (name, WSE) downstream -> upstream
    wse = inp.receiving_hwl
    stations.append(("Receiving water HWL", wse))

    def pipe(name, qcfs, length):
        nonlocal wse
        d = select_pipe(qcfs, inp.pipe_v_design)
        hf = hazen_williams_hf(qcfs * 448.83, d, length, inp.pipe_c)
        hm = inp.k_pipe * velocity_head(pipe_velocity(qcfs, d))
        wse += hf + hm
        stations.append((f"{name} ({d:.0f} in pipe)", wse))
        return d

    def weir_drop():
        nonlocal wse
        wse += inp.free_fall_ft

    pipe("Outfall", q, inp.outfall_ft)

    # disinfection
    dis = units.get("disinfection", {})
    if "volume_ft3" in dis:                      # chlorine contact tank
        n_bends = max(int(dis.get("path_len", 300) / max(dis.get("channel_len", 60), 1)) - 1, 0)
        w = dis.get("channel_width", 6.0)
        v = q / (w * dis.get("depth", 10.0))
        weir_drop()
        wse += rect_weir_head(q, w)                # effluent weir across channel
        stations.append(("Chlorine contact effluent weir crest + head", wse))
        wse += n_bends * inp.cct_bend_k * velocity_head(v)
        stations.append(("Chlorine contact tank inlet", wse))
    else:
        weir_drop()
        wse += inp.uv_loss_ft
        stations.append(("UV channel inlet", wse))
    pipe("To disinfection", q, inp.yard_pipe_ft)

    if units.get("filter"):
        weir_drop()
        wse += inp.filter_loss_ft
        stations.append(("Tertiary filter influent", wse))
        pipe("To filters", q, inp.yard_pipe_ft)

    # final clarifiers: V-notch weirs into launder
    sec = units.get("secondary", {})
    n, D = sec.get("n", 2), sec.get("diameter", 80.0)
    q_each = q / n
    weir_len = math.pi * (D - 2.0) * (2 if sec.get("double_weir") else 1)
    notches = weir_len * 12 / inp.notch_spacing_in
    h0 = launder_upstream_depth(q_each / 2, inp.launder_width_ft)   # launder flow splits two ways to the outlet box
    wse_launder = wse + inp.free_fall_ft + h0
    stations.append(("Final clarifier launder (upstream end)", wse_launder))
    wse = wse_launder + inp.free_fall_ft + vnotch_head(q_each / notches)
    stations.append(("Final clarifier water surface", wse))
    # aeration basin -> clarifiers carries Q + RAS
    pipe("Mixed liquor to clarifiers", q + qr, inp.yard_pipe_ft)
    wse += velocity_head(1.0) * 2                # center-well inlet loss allowance
    asb = units.get("aeration", {})
    weir_drop()
    wse += rect_weir_head((q + qr) / asb.get("n_trains", 2), asb.get("width_ft", 30.0))
    stations.append(("Aeration basin water surface", wse))

    pri = units.get("primary")
    pipe("Primary effluent to aeration", q, inp.yard_pipe_ft)
    if pri:
        n, D = pri.get("n", 2), pri.get("diameter", 60.0)
        q_each = q / n
        weir_len = math.pi * (D - 2.0) * (2 if pri.get("double_weir") else 1)
        notches = weir_len * 12 / inp.notch_spacing_in
        wse += inp.free_fall_ft + launder_upstream_depth(q_each / 2, inp.launder_width_ft)
        stations.append(("Primary clarifier launder", wse))
        wse += inp.free_fall_ft + vnotch_head(q_each / notches)
        stations.append(("Primary clarifier water surface", wse))
        pipe("Grit effluent to primaries", q, inp.yard_pipe_ft)

    grit = units.get("grit")
    if grit:
        weir_drop()
        wse += rect_weir_head(q / grit.get("n", 2), grit.get("width", 8.0))
        stations.append(("Grit chamber water surface", wse))
    ha = parshall_head(q, inp.flume_throat_ft)
    wse += 0.3 * ha                               # free-flow loss at <= 70% submergence (approx.)
    stations.append((f"Parshall flume upstream (Ha = {ha:.2f} ft)", wse))
    scr = units.get("screens", {})
    wse += inp.screen_loss_ft or scr.get("hl_50", 0.5)
    stations.append(("Screen channel upstream", wse))

    stations.reverse()
    for name, el in stations:
        r.o(name, el, "ft", 2)
    total = stations[0][1] - inp.receiving_hwl
    r.i("Peak hourly flow", Q_peak, "MGD"); r.i("Maximum RAS", Q_ras_max, "MGD")
    r.i("Receiving water HWL", inp.receiving_hwl, "ft"); r.i("Finished grade", inp.ground_el, "ft")
    r.o("Total plant head loss", total, "ft")
    r.o("Headworks WSE above grade", stations[0][1] - inp.ground_el, "ft", 2)
    lowest_tank = min(el for name, el in stations if "water surface" in name.lower())
    r.c(custom_check("Lowest process water surface above receiving HWL", lowest_tank - inp.receiving_hwl, "ft",
                     lo=0.5, kind="limit", source="Gravity discharge at design flood stage",
                     note="effluent pumping needed if negative"))
    r.c(lib.check(inp.freeboard_ft * 12, "hyd_freeboard", label="Freeboard used for top-of-wall"))
    r.note("Influent lift station discharges to the screen channel; set its static lift to "
           f"{stations[0][1]:.1f} ft minus the wet-well low water level.")
    r.note("Losses use full-pipe flow and simplified structure losses; verify with a detailed profile at final design.")
    r.data.update(stations=stations, headworks_wse=stations[0][1], total_loss=total,
                  freeboard=inp.freeboard_ft, ground=inp.ground_el, hwl=inp.receiving_hwl)
    return r
