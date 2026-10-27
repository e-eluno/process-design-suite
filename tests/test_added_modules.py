"""Tests for pumping, hydraulic profile, dynamic ASM1, reliability and cost modules."""

import math

import numpy as np
import pytest

from processdesign.core.hydraulics import (hazen_williams_hf, parshall_head, launder_upstream_depth,
                                           rect_weir_head, vnotch_head)
from processdesign.core.criteria import FAIL, PASS
from processdesign.wwtp.plant import PlantInputs, run_plant
from processdesign.wwtp.pumping import LiftStationInputs, design_lift_station
from processdesign.wwtp.dynamic import _rates, ASM1Params, I, influent_vector
from processdesign.wwtp.influent import Influent


def test_hazen_williams_hand_calc():
    # 1000 gpm, 8 in, 1000 ft, C=120 -> ~ 10.44*1000*1000^1.85/(120^1.85*8^4.8655)
    hf = hazen_williams_hf(1000, 8, 1000, 120)
    assert hf == pytest.approx(10.44 * 1000 * 1000 ** 1.85 / (120 ** 1.85 * 8 ** 4.8655))
    assert 18 < hf < 24         # pipe tables: ~2.1 ft/100 ft for 1000 gpm in 8-in, C=120


def test_weir_and_flume_inverse():
    assert 3.33 * 10 * rect_weir_head(10.0, 10.0) ** 1.5 == pytest.approx(10.0, rel=1e-6)
    h = vnotch_head(0.05)
    assert 2.5 * h ** 2.5 == pytest.approx(0.05)
    W = 2.0; ha = parshall_head(20.0, W)
    assert 4 * W * ha ** (1.522 * W ** 0.026) == pytest.approx(20.0)
    q, b = 10.0, 2.0
    hc = (q ** 2 / (32.174 * b ** 2)) ** (1 / 3)
    assert launder_upstream_depth(q, b) == pytest.approx(math.sqrt(3) * hc)


def test_wet_well_volume_rule():
    inp = LiftStationInputs(cycle_min=10, n_duty=2)
    r = design_lift_station(inp, 2.0, 5.0, 0.8)
    q_pump = 5.0 * 694.444 / 2
    assert r.data["wetwell_ft3"] * 7.4805 == pytest.approx(10 * q_pump / 4, rel=1e-3)
    assert r.data["tdh"] > inp.static_lift_ft


def test_asm1_nitrogen_continuity():
    """Nitrogen continuity of the ASM1 rate matrix (N2 from denitrification added back)."""
    p = ASM1Params()
    C = np.zeros((1, 13))
    C[0, I["SS"]], C[0, I["XS"]], C[0, I["XBH"]], C[0, I["XBA"]] = 50, 100, 1500, 100
    C[0, I["XI"]], C[0, I["XP"]] = 500, 200
    C[0, I["SO"]], C[0, I["SNO"]], C[0, I["SNH"]], C[0, I["SND"]], C[0, I["XND"]] = 2, 5, 20, 2, 5
    R = _rates(C, p, 15.0)[0]
    n = (R[I["SNH"]] + R[I["SND"]] + R[I["XND"]] + R[I["SNO"]]
         + p.iXB * (R[I["XBH"]] + R[I["XBA"]]) + p.iXP * R[I["XP"]])
    # nitrate is formed from ammonia and lost to N2 under anoxic growth: add N2 production back
    io = p.KOH / (p.KOH + C[0, I["SO"]]); no = C[0, I["SNO"]] / (p.KNO + C[0, I["SNO"]])
    r2 = p.muH * C[0, I["SS"]] / (p.KS + C[0, I["SS"]]) * io * no * p.etag * C[0, I["XBH"]]
    n2 = (1 - p.YH) / (2.86 * p.YH) * r2
    assert n + n2 == pytest.approx(0.0, abs=1e-6)


def test_influent_fractionation_sums_to_cod():
    inf = Influent()
    v = influent_vector(inf)
    assert v[I["SI"]] + v[I["SS"]] + v[I["XI"]] + v[I["XS"]] == pytest.approx(inf.COD)


@pytest.fixture(scope="module")
def default_result():
    return run_plant(PlantInputs())


def test_hydraulic_profile_monotonic(default_result):
    st = default_result.unit("hydraulics").data["stations"]
    el = [e for _, e in st]
    assert all(a >= b - 1e-9 for a, b in zip(el, el[1:]))     # upstream to downstream, never rising
    assert el[-1] == pytest.approx(PlantInputs().hydraulics.receiving_hwl)


def test_dynamic_runs_and_is_plausible(default_result):
    d = default_result.unit("dynamic").data
    assert len(d["hours"]) >= 90
    assert 1.1 < max(d["our_lb"]) / np.mean(d["our_lb"]) < 3.0
    assert min(d["NH3"]) >= 0


def test_cost_markup_arithmetic(default_result):
    c = default_result.unit("costs")
    ci = PlantInputs().costs
    proc = sum(x for _, _, x in c.data["items"])
    direct = proc * (1 + (ci.sitework_pct + ci.yard_piping_pct + ci.electrical_ic_pct) / 100)
    expected = direct * (1 + ci.contractor_pct / 100) * (1 + ci.contingency_pct / 100) * (1 + ci.engineering_pct / 100)
    assert c.data["capital"] == pytest.approx(expected)
    assert c.data["npv"] > c.data["capital"]


def test_reliability_class_I_flags_gaps():
    p = PlantInputs()
    p.reliability.rel_class = "I"
    p.screens.n_standby = 0
    res = run_plant(p)
    rel = next(u for u in res.units if u.name.startswith("Reliability"))
    failed = {c.label for c in rel.checks if c.status == FAIL}
    assert any("bar screen" in f for f in failed)
    assert any("Holding basin" in f for f in failed)


def test_reliability_class_III_passes_default():
    rel = next(u for u in run_plant(PlantInputs()).units if u.name.startswith("Reliability"))
    assert rel.status == PASS
