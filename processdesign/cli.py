"""Command line: run a project file and write the HTML report.

    python -m processdesign.cli run examples/municipal_5mgd_mle.json -o report.html
    python -m processdesign.cli new my_project.json        # write a default project to edit
"""

from __future__ import annotations

import argparse
import sys

from .core.criteria import default_library
from .core.report import write_wwtp_report
from .wwtp.plant import PlantInputs, run_plant


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="processdesign")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="design a WWTP from a project JSON")
    r.add_argument("project")
    r.add_argument("-o", "--output", default="wwtp_design_report.html")
    r.add_argument("--criteria", help="override criteria JSON (state or firm standards)")
    n = sub.add_parser("new", help="write a default WWTP project file")
    n.add_argument("path")
    a = ap.parse_args(argv)

    if a.cmd == "new":
        PlantInputs().save(a.path)
        print(f"Wrote {a.path}")
        return 0
    lib = default_library()
    if a.criteria:
        lib = lib.merged(a.criteria)
    res = run_plant(PlantInputs.load(a.project), lib)
    write_wwtp_report(res, a.output, lib)
    c = res.counts()
    print(f"{res.status}: {c['PASS']} pass, {c['WARN']} warn, {c['FAIL']} fail -> {a.output}")
    for w in res.warnings:
        print("warning:", w)
    return 0 if res.status != "FAIL" else 2


if __name__ == "__main__":
    sys.exit(main())
