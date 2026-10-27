"""Engine verification: hand calculations, closed-form checks and regressions."""

import json
import math
from pathlib import Path

import pytest

from processdesign.core.criteria import default_library, PASS, FAIL, WARN
from processdesign.core.units import load_lbd, barometric_psi
from processdesign.wwtp.influent import Influent, blend, ten_states_population_basis, sc_appendix_a_table, sc_appendix_a_flow
from processdesign.wwtp.primary import removal_efficiency, PrimaryInputs, design_primary
from processdesign.wwtp.preliminary import equalization_volume
from processdesign.wwtp.activated_sludge import (ASInputs, Kinetics, min_nitrification_srt, steady_state,
                                                 design_activated_sludge, WashoutError, PROCESSES)
from processdesign.wwtp.clarifier import limiting_flux, vesilind_from_svi
from processdesign.wwtp.aeration import cs_freshwater, AerationInputs, design_aeration
from processdesign.wwtp.plant import PlantInputs, run_plant

EX = Path(__file__).parents[1] / "examples"


def test_load_units():
    assert load_lbd(1.0, 1.0) == pytest.approx(8.34)


def test_barometric():
    assert barometric_psi(0) == pytest.approx(14.696)
    assert barometric_psi(5280) == pytest.approx(12.1, abs=0.05)   # Denver ~12.1 psia


def test_primary_removal_hand_calc():
    rb, rt = removal_efficiency(2.0)
    assert rb == pytest.approx(2 / (0.018 + 0.040) / 100)      # 34.5 %
    assert rt == pytest.approx(2 / (0.0075 + 0.028) / 100)     # 56.3 %


def test_equalization_square_wave():
    # 12 h at 1.5Q then 12 h at 0.5Q -> storage = 0.5 * Q/24 * 12 = 0.25 Q
    vol, _ = equalization_volume([1.5] * 12 + [0.5] * 12, 4.0)
    assert vol == pytest.approx(0.25 * 4.0e6)


def test_nitrification_srt_hand_calc():
    k = Kinetics()
    T, do, N = 12.0, 2.0, 0.5
    mu = 0.90 * 1.072 ** (T - 20) * do / (0.5 + do)
    b = 0.17 * 1.029 ** (T - 20)
    expected = (0.5 + N) / (N * (mu - b) - 0.5 * b)
    assert min_nitrification_srt(k, T, do, N) == pytest.approx(expected)
    # and the effluent NH3 at that SRT must equal the target (Monod inverse)
    srt = expected
    assert 0.5 * (1 + b * srt) / (srt * (mu - b) - 1) == pytest.approx(N, rel=1e-9)


def test_monod_effluent_substrate():
    inf = Influent()
    ss = steady_state(inf, ASInputs(), srt=10.0, T=20.0)
    assert ss["S"] == pytest.approx(8 * (1 + 0.12 * 10) / (10 * (6.0 - 0.12) - 1))


def test_nitrogen_balance_in_reactor():
    inf = Influent()
    ss = steady_state(inf, ASInputs(), srt=15.0, T=15.0)
    n_syn = 0.12 * ss["PX_bio"] * 1000 / inf.Q_m3d
    assert inf.TKN == pytest.approx(ss["NOx"] + ss["Ne"] + n_syn, rel=1e-6)


def test_washout_detected():
    with pytest.raises(WashoutError):
        min_nitrification_srt(Kinetics(), 5.0, 0.3, 0.1)


def test_mle_recycle_and_volumes():
    r = design_activated_sludge(ASInputs(process=PROCESSES[1]), Influent())
    d = r.data
    # IR from nitrate balance: NOx/Ne - 1 - R
    eff = d["effluent"]
    assert d["IR"] >= 0
    assert d["V_anox_m3"] > 0
    assert eff["NO3N"] == pytest.approx(8.0)
    assert d["srt_total"] > d["srt"]


def test_limiting_flux_closed_form():
    v0, k, u = 6.49, 0.402, 0.406
    GL, Xu = limiting_flux(v0, k, u)
    # analytic: dG/dX = 0 -> exp(-kX)(kX-1) = u/v0
    from scipy.optimize import brentq
    y = brentq(lambda y: math.exp(-y) * (y - 1) - u / v0, 2.0, 10.0)
    X = y / k
    assert GL == pytest.approx(v0 * X * math.exp(-y) + u * X, rel=2e-3)
    assert Xu == pytest.approx(GL / u)


def test_vesilind_correlation_reasonable():
    v0, k = vesilind_from_svi(150)
    assert 5 < v0 < 8 and 0.3 < k < 0.5


def test_do_saturation():
    assert cs_freshwater(20) == pytest.approx(9.09, abs=0.03)
    assert cs_freshwater(0) == pytest.approx(14.65, abs=0.05)


def test_blower_power_hand_calc():
    inp = AerationInputs(n_standby=1)
    r = design_aeration(inp, aotr_lbd=10000, do_mgl=2.0, basin_volume_ft3=50000)
    d = r.data
    patm = barometric_psi(inp.elevation_ft)
    p2 = patm + d["p2_psig"]
    w = d["air_scfm"] * 0.075 / 60
    hp = w * 0.24 * (inp.inlet_air_F + 459.67) / inp.blower_eff * ((p2 / patm) ** 0.283 - 1) * 1.4148
    assert d["hp"] == pytest.approx(hp)
    assert d["sotr"] > 10000                     # SOTR always exceeds AOTR in process water


def test_ten_states_per_capita():
    b = ten_states_population_basis(10000)
    assert b["Q_avg"] == pytest.approx(1.0)
    assert b["BOD"] == pytest.approx(0.17 * 10000 / (1.0 * 8.34))


def test_sc_appendix_a():
    t = sc_appendix_a_table()
    idx = next(i for i, r in enumerate(t) if r["type"] == "Residences")
    assert t[idx]["gpd"] == 300
    assert sc_appendix_a_flow([(idx, 100)])["total_gpd"] == 30000


def test_blend_conserves_mass():
    a = Influent(Q_avg=2.0, TSS=200)
    b = blend(a, 0.5, {"TSS": 1000})
    assert load_lbd(b.Q_avg, b.TSS) == pytest.approx(load_lbd(2.0, 200) + load_lbd(0.5, 1000))


def test_project_roundtrip(tmp_path):
    p = PlantInputs()
    p.activated_sludge.kinetics.mu_H = 5.5
    p.influent.Q_avg = 3.3
    f = tmp_path / "p.json"
    p.save(f)
    q = PlantInputs.load(f)
    assert q.activated_sludge.kinetics.mu_H == 5.5 and q.influent.Q_avg == 3.3
    # forward-compatible: unknown keys are ignored
    raw = json.loads(f.read_text()); raw["data"]["influent"]["future_field"] = 1
    f.write_text(json.dumps(raw))
    assert PlantInputs.load(f).influent.Q_avg == 3.3


def test_criteria_override(tmp_path):
    f = tmp_path / "state.json"
    f.write_text(json.dumps({"criteria": {"pri_swd": {"min": 12.0, "source": "State X"}}}))
    lib = default_library().merged(f)
    assert lib.get("pri_swd").min == 12.0
    assert default_library().get("pri_swd").min == 10.0
    assert lib.check(11.0, "pri_swd").status == FAIL


def test_recycle_converges_and_adds_load():
    p = PlantInputs()
    on = run_plant(p)
    p.recycle.enabled = False
    off = run_plant(p)
    assert on.converged
    pri_on = next(s for s in on.streams if s["name"].startswith("Primary influent"))
    pri_off = next(s for s in off.streams if s["name"].startswith("Primary influent"))
    assert pri_on["TKN"] > pri_off["TKN"]          # centrate ammonia returned


@pytest.mark.parametrize("f", sorted(EX.glob("*.json")))
def test_examples_have_no_failures(f):
    res = run_plant(PlantInputs.load(f))
    fails = [(u.name, c.label) for u in res.units for c in u.checks if c.status == FAIL]
    assert not fails, fails
    assert res.converged


def test_every_input_field_labelled():
    from dataclasses import fields, is_dataclass
    from processdesign.core.fields import field_specs
    p = PlantInputs()
    for f in fields(p):
        sec = getattr(p, f.name)
        labelled = {s["name"] for s in field_specs(sec)}
        for g in fields(sec):
            if not is_dataclass(getattr(sec, g.name)):
                assert g.name in labelled, f"{f.name}.{g.name} has no label"


def test_report_renders(tmp_path):
    from processdesign.core.report import write_wwtp_report
    res = run_plant(PlantInputs())
    out = write_wwtp_report(res, tmp_path / "r.html")
    html = out.read_text()
    assert "Effluent compliance" in html and "Activated Sludge" in html and "unverified" in html
