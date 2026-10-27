"""Regenerate the example project files: python examples/make_examples.py"""

from pathlib import Path

from processdesign.wwtp.plant import PlantInputs

HERE = Path(__file__).parent


def mle_5mgd():
    p = PlantInputs()
    p.project.name = "Example 5 MGD MLE Plant"
    p.project.location = "Columbia, SC"
    return p


def ext_aeration_0p5mgd():
    q = PlantInputs()
    q.project.name = "Example 0.5 MGD Extended Aeration (aerobic digestion)"
    q.influent.Q_avg = 0.5; q.influent.PF_peakhour = 3.0; q.influent.PF_maxday = 1.8
    q.primary.enabled = False; q.grit.n_units = 1; q.screens.n_duty = 1
    q.activated_sludge.process = "Extended aeration"; q.activated_sludge.swd_ft = 14
    q.aeration.submergence_ft = 13; q.aeration.n_duty = 2
    q.secondary.swd_ft = 12
    q.thickening.primary_method = "None"; q.thickening.was_method = "None"
    q.digestion.method = "Aerobic"; q.digestion.srt_d = 60; q.digestion.temp_C = 15; q.digestion.swd_ft = 14
    q.dewatering.method = "Screw press"; q.dewatering.hours_per_week = 24
    q.disinfection.method = "UV"
    return q


def a2o_10mgd():
    r = PlantInputs()
    r.project.name = "Example 10 MGD A2O with filtration (TP 0.5)"
    r.influent.Q_avg = 10
    r.activated_sludge.process = "A2O (N + bio-P)"; r.activated_sludge.chem_p = True
    r.activated_sludge.tp_target = 0.4; r.activated_sludge.n_trains = 4
    r.primary.n_units = 3; r.secondary.n_units = 4; r.aeration.n_duty = 4
    r.filtration.enabled = True; r.permit.TP = 0.5; r.permit.TN = 10
    return r


if __name__ == "__main__":
    mle_5mgd().save(HERE / "municipal_5mgd_mle.json")
    ext_aeration_0p5mgd().save(HERE / "package_0p5mgd_extended_aeration.json")
    a2o_10mgd().save(HERE / "municipal_10mgd_a2o_tp.json")
    print("examples written")
