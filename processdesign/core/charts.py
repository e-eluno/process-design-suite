"""Static report/GUI charts (matplotlib, PNG bytes).

Palette: validated reference categorical slots 1-3 (blue, orange, aqua) on a
light surface; one y-axis per panel; series identified by legend + label.
"""

from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
REF = "#8a8984"


def _fig(w=7.2, h=3.4, rows=1):
    fig, axs = plt.subplots(rows, 1, figsize=(w, h * rows), dpi=150, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax in axs[:, 0]:
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=INK2, labelsize=8)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
    return fig, axs[:, 0]


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _title(ax, t, sub=None):
    ax.set_title(t, loc="left", fontsize=10, color=INK, fontweight="bold")
    if sub:
        ax.text(0, 1.01, sub, transform=ax.transAxes, fontsize=7.5, color=INK2, va="bottom")


def hydraulic_profile_chart(data: dict) -> bytes:
    st = data["stations"]
    names = [n for n, _ in st]
    el = [e for _, e in st]
    x = np.arange(len(st))
    fig, (ax,) = _fig(7.2, 4.2)
    ax.step(x, el, where="mid", color=S1, linewidth=2, label="Peak-hour water surface")
    ax.plot(x, el, "o", color=S1, markersize=4, markeredgecolor=SURFACE, markeredgewidth=1.5)
    ax.axhline(data["ground"], color=REF, linewidth=1, linestyle="--")
    ax.text(len(st) - 1, data["ground"], "finished grade", color=INK2, fontsize=7.5, va="bottom", ha="right")
    ax.axhline(data["hwl"], color=S3, linewidth=1, linestyle=":")
    ax.text(0, data["hwl"], "receiving HWL", color=INK2, fontsize=7.5, va="bottom", ha="left")
    ax.set_xticks(x)
    ax.set_xticklabels([n.split(" (")[0] for n in names], rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("Elevation (ft)", color=INK2, fontsize=8)
    _title(ax, "Hydraulic profile at peak hour")
    return _png(fig)


def dynamic_chart(data: dict) -> bytes:
    h = np.array(data["hours"])
    fig, (a1, a2) = _fig(7.2, 2.6, rows=2)
    a1.plot(h, data["NH3"], color=S1, linewidth=2, label="NH3-N")
    a1.plot(h, data["NO3"], color=S2, linewidth=2, label="NO3-N")
    a1.plot(h, data["TN"], color=S3, linewidth=2, label="Total N")
    a1.set_ylabel("Effluent (mg/L)", color=INK2, fontsize=8)
    a1.legend(frameon=False, fontsize=7.5, ncol=3, loc="upper left", labelcolor=INK)
    _title(a1, "Effluent nitrogen over a design day (ASM1)")
    a2.plot(h, data["our_lb"], color=S1, linewidth=2, label="Oxygen demand")
    a2.axhline(data["aotr_design_lb"], color=REF, linestyle="--", linewidth=1)
    a2.text(h[0], data["aotr_design_lb"], " design AOTR", color=INK2, fontsize=7.5, va="bottom")
    a2.set_ylabel("O2 demand (lb/d)", color=INK2, fontsize=8)
    a2.set_xlabel("Hour of day", color=INK2, fontsize=8)
    a2.set_xticks(range(0, 25, 3))
    _title(a2, "Aeration oxygen demand vs design capacity")
    return _png(fig)


def system_curve_chart(data: dict, n_duty: int) -> bytes:
    q = np.array([c[0] for c in data["curve"]]); h = np.array([c[1] for c in data["curve"]])
    fig, (ax,) = _fig(6.0, 3.2)
    ax.plot(q, h, color=S1, linewidth=2, label="System curve")
    qd = q.max() / 1.3
    ax.plot([qd], [data["tdh"]], "o", color=S2, markersize=8, markeredgecolor=SURFACE, markeredgewidth=2)
    ax.annotate(f"  design point ({n_duty} pumps)\n  {qd:,.0f} gpm @ {data['tdh']:.1f} ft",
                (qd, data["tdh"]), fontsize=7.5, color=INK2, va="top")
    ax.set_xlabel("Flow (gpm)", color=INK2, fontsize=8); ax.set_ylabel("TDH (ft)", color=INK2, fontsize=8)
    _title(ax, "Influent lift station system curve")
    return _png(fig)


def state_point_chart(data: dict) -> bytes:
    v0, k, u, X, sor = data["v0"], data["k"], data["u"], data["X"], data["sor_mh"]
    xs = np.linspace(0.1, 15, 400)
    gs = v0 * xs * np.exp(-k * xs)
    fig, (ax,) = _fig(6.0, 3.4)
    ax.plot(xs, gs, color=S1, linewidth=2, label="Gravity flux")
    ax.plot(xs, sor * xs, color=S2, linewidth=2, label="Overflow line")
    applied = (sor + u) * X
    ax.plot([0, applied / u], [applied, 0], color=S3, linewidth=2, label="Underflow line")
    ax.plot([X], [sor * X], "o", color=INK, markersize=7, markeredgecolor=SURFACE, markeredgewidth=2)
    ax.annotate("  state point", (X, sor * X), fontsize=7.5, color=INK2)
    ax.set_ylim(0, max(gs.max(), (sor + u) * X) * 1.2)
    ax.set_xlabel("Solids concentration (g/L)", color=INK2, fontsize=8)
    ax.set_ylabel("Solids flux (kg/m2-h)", color=INK2, fontsize=8)
    ax.legend(frameon=False, fontsize=7.5, labelcolor=INK)
    _title(ax, "Final clarifier state point at peak hour (max RAS)")
    return _png(fig)


def cost_chart(items: list) -> bytes:
    areas = {}
    for area, _, c in items:
        areas[area] = areas.get(area, 0) + c
    names = sorted(areas, key=areas.get)
    vals = [areas[n] / 1e6 for n in names]
    fig, (ax,) = _fig(6.0, 0.45 * len(names) + 1.0)
    ax.barh(names, vals, color=S1, height=0.6)
    for y, v in enumerate(vals):
        ax.text(v, y, f"  ${v:,.1f}M", va="center", fontsize=7.5, color=INK)
    ax.grid(axis="y", visible=False); ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_xlabel("Process construction cost ($M, before markups)", color=INK2, fontsize=8)
    ax.set_xlim(0, max(vals) * 1.25)
    _title(ax, "Process construction cost by area")
    return _png(fig)


def plant_charts(result) -> dict[str, bytes]:
    """All charts available for a plant result, keyed by title."""
    out = {}
    pi = result.inputs
    def get(prefix):
        return next((u for u in result.units if u.name.startswith(prefix)), None)
    u = get("Hydraulic Profile")
    if u: out["Hydraulic profile"] = hydraulic_profile_chart(u.data)
    u = get("Secondary Clarifiers")
    if u and "v0" in u.data: out["Clarifier state point"] = state_point_chart(u.data)
    u = get("Dynamic Simulation")
    if u: out["Dynamic simulation"] = dynamic_chart(u.data)
    u = get("Influent Lift Station")
    if u: out["Lift station system curve"] = system_curve_chart(u.data, pi.lift_station.n_duty)
    u = get("Cost Estimate")
    if u: out["Cost by area"] = cost_chart(u.data["items"])
    return out
