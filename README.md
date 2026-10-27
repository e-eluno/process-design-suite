# Process Design Suite — WWTP Module (v0.2.0)

Desktop process-design program. Python calculation engine + PySide6 desktop GUI.
Module 1 is a complete wastewater treatment plant design suite; later modules
(e.g. water treatment, heat exchange, reactors, separations) plug into the same
`core` package.

## Quick start

```bash
python -m pip install -r requirements.txt
python -m processdesign.gui                       # desktop app
python -m processdesign.cli run examples/municipal_5mgd_mle.json -o report.html
python -m pytest -q                               # 35 verification tests (incl. GUI smoke)
```

## What the WWTP module designs

| Area | Units | Method / basis |
|---|---|---|
| Flows & loads | Influent characterization, COD fractionation, peaking | M&E 5th ed.; Ten States per-capita; **SC R.61-67 Appendix A** flow estimator |
| Preliminary | Bar screens, aerated grit, diurnal EQ (mass diagram) | Velocity/headloss; detention; cumulative-volume method |
| Primary | Circular clarifiers, removal, primary sludge | Ten States SOR/SWD/weir; Crites–Tchobanoglous removal curves |
| Secondary | CMAS, MLE, A2O (EBPR), extended aeration; chemical P trim | M&E steady-state kinetics (SRT x SF, Monod, N-uptake iteration, SDNR anoxic sizing, rbCOD-limited Bio-P) |
| Aeration | AOTR→SOTR, air flow, mixing, blower pressure & power, motor size | M&E alpha/beta/theta with mid-depth saturation; adiabatic compression |
| Final clarifiers | SOR/SLR/weir sizing; state-point (solids flux) analysis | Ten States Table limits by process class; Vesilind with Daigger SVI correlation |
| Tertiary & disinfection | Cloth/granular filters; chlorine contact + dechlorination; UV | Firm capacity with one unit out; CT basin geometry; chemical demand |
| Solids | Gravity thickening, DAF, anaerobic/aerobic digestion, dewatering | M&E loadings, VSR correlations, biogas/heat balance, 40 CFR 503 PSRP checks |
| Plant | Recycle (overflow, subnatant, centrate, backwash) iterated to convergence | Liquid & solids mass balance, permit compliance |
| Pumping | Influent lift station (wet well, force main, system curve, TDH, motors); RAS/WAS/IR pumps | Ten States 42.x; Hazen-Williams; V = T·q/4 cycle rule |
| Hydraulic profile | Peak-hour HGL from receiving HWL to headworks: pipes, weirs, V-notch launders, Parshall flume, screens | Francis/V-notch weirs, Camp launder, Parshall free flow |
| Dynamic simulation | ASM1 anaerobic/anoxic/aerobic tanks in series + point settler, diurnal loading | IWA ASM1, BSM1 default parameters (uncalibrated) |
| Reliability | SC R.61-67.400 Class I / II / III backup requirements | Transcribed 67.400 C–F |
| Cost estimate | Capital from tank geometry + equipment sizes, O&M (energy, chemicals, biosolids, labor), present worth | Placeholder unit prices — load a regional cost basis |

Every unit returns inputs, results, pass/warn/fail checks with citations, and notes.
The HTML report prints cleanly to PDF.

## Design-criteria library

All limits live in `processdesign/core/data/criteria_wwtp.json`, not in code; each entry carries `source` and `verified`.
As of 2026-10-27 the regulatory/standard values were checked against Ten States-derived state rules and SC regulations:
MO 10 CSR 20-8 (clarifiers, weirs, SWD), MPCA Ten States checklist (DO, O2/BOD, mixing, alpha),
IL 35 IAC 370 (screens, grit, aeration loading, NOD, RAS, filters, anaerobic/aerobic digestion),
TN Design Criteria Ch. 4 & 10 (screen approach velocity, Cl2 contact 15 min peak / 30 min average, L:W 30:1, UV dose/UVT/n+1),
OK OAC 252:656 App. A (F/M, grit geometry), 40 CFR 503 App. B (PSRP), SC R.61-67 App. A and 67.400.
Textbook "typical" ranges (M&E) remain marked unverified and only raise warnings.

**Open item:** GLUMRB published a 2026 Ten States edition (paid download). The library is built on 2014-based state adoptions; review against 2026 before release.

## Packaging (Windows / Intel Mac)

```bash
python -m pip install pyinstaller
pyinstaller --name "Process Design Suite" --windowed --add-data "processdesign/core/data:processdesign/core/data" processdesign/gui/__main__.py
```
On Windows use `;` instead of `:` in `--add-data`. Build the Mac app on the Intel Mac (x86_64) so it runs natively there.
PySide6 is LGPL-3.0: ship it dynamically linked (PyInstaller default) and include its license notice.

## Project layout

```
processdesign/
  core/      units, criteria library + checks, field metadata, results, report, serialization
  wwtp/      influent, preliminary, primary, activated_sludge, aeration, clarifier, tertiary, solids, plant
  gui/       auto-generated input forms, main window, flow estimator
  cli.py
examples/    three example projects (+ generator script)
tests/       hand-calculation and regression tests
```

## Limits of this version

The GUI was exercised against a Qt stub in CI here (PySide6 could not be installed in the build sandbox); run `python -m processdesign.gui` on Windows/Mac to confirm on real Qt.
Dynamic model and cost unit prices are uncalibrated defaults. Output is a preliminary design to be reviewed and sealed by a licensed PE.
