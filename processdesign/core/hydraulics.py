"""Shared hydraulic relations (US customary)."""

from __future__ import annotations

import math

from .units import G_FT, MGD_TO_CFS

STD_PIPE_IN = [4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 30, 36, 42, 48, 54, 60, 66, 72, 84, 96, 108, 120]


def pipe_velocity(q_cfs: float, d_in: float) -> float:
    a = math.pi * (d_in / 12) ** 2 / 4
    return q_cfs / a


def hazen_williams_hf(q_gpm: float, d_in: float, length_ft: float, c: float = 120.0) -> float:
    """Friction loss (ft) - Hazen-Williams, Q in gpm, D in inches."""
    if q_gpm <= 0:
        return 0.0
    return 10.44 * length_ft * q_gpm ** 1.85 / (c ** 1.85 * d_in ** 4.8655)


def velocity_head(v_fps: float) -> float:
    return v_fps ** 2 / (2 * G_FT)


def select_pipe(q_cfs: float, v_target: float, v_min: float = 0.0) -> float:
    """Smallest standard diameter whose full-pipe velocity is <= v_target."""
    for d in STD_PIPE_IN:
        if pipe_velocity(q_cfs, d) <= v_target:
            return d
    return STD_PIPE_IN[-1]


def rect_weir_head(q_cfs: float, length_ft: float, contractions: int = 0) -> float:
    """Sharp-crested rectangular weir head (ft), Francis: Q = 3.33 (L - 0.1 n H) H^1.5."""
    h = (q_cfs / (3.33 * length_ft)) ** (2 / 3)
    for _ in range(20):
        le = max(length_ft - 0.1 * contractions * h, 0.1)
        h = (q_cfs / (3.33 * le)) ** (2 / 3)
    return h


def vnotch_head(q_cfs_per_notch: float, angle_deg: float = 90.0) -> float:
    """V-notch weir head (ft): Q = 2.5 tan(theta/2) H^2.5 (cfs)."""
    return (q_cfs_per_notch / (2.5 * math.tan(math.radians(angle_deg) / 2))) ** 0.4


def launder_upstream_depth(q_cfs: float, width_ft: float) -> float:
    """Upstream depth of a level, free-discharging collection launder with
    uniform lateral inflow: h0 = sqrt(3) * hc (Camp / M&E)."""
    hc = (q_cfs ** 2 / (G_FT * width_ft ** 2)) ** (1 / 3)
    return math.sqrt(3) * hc


def parshall_head(q_cfs: float, throat_ft: float) -> float:
    """Upstream head Ha (ft) for a Parshall flume, 1-8 ft throat: Q = 4 W Ha^(1.522 W^0.026)."""
    n = 1.522 * throat_ft ** 0.026
    return (q_cfs / (4 * throat_ft)) ** (1 / n)


def mgd_to_cfs(q):
    return q * MGD_TO_CFS
