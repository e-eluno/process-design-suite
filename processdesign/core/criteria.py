"""Design-criteria library and pass/warn/fail checks.

Every number a design is judged against lives in a JSON library (not in code),
carries its source citation, and says whether it has been verified against the
cited text. Firms can ship their own override file (e.g. state rules) without
touching the engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


@dataclass
class Criterion:
    key: str
    desc: str
    unit: str = ""
    min: float | None = None
    max: float | None = None
    typical: float | None = None
    kind: str = "typical"          # limit | typical | info
    source: str = ""
    verified: bool = False
    note: str = ""


@dataclass
class Check:
    label: str
    value: float
    unit: str
    status: str
    min: float | None = None
    max: float | None = None
    source: str = ""
    verified: bool = False
    message: str = ""

    @property
    def range_text(self) -> str:
        lo, hi = self.min, self.max
        if lo is not None and hi is not None:
            return f"{_fmt(lo)} - {_fmt(hi)}"
        if lo is not None:
            return f">= {_fmt(lo)}"
        if hi is not None:
            return f"<= {_fmt(hi)}"
        return "-"

    def to_dict(self) -> dict:
        return {"label": self.label, "value": self.value, "unit": self.unit,
                "status": self.status, "range": self.range_text,
                "source": self.source, "verified": self.verified,
                "message": self.message}


def _fmt(x: float) -> str:
    if x is None:
        return "-"
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    if abs(x) >= 10:
        return f"{x:.1f}".rstrip("0").rstrip(".")
    return f"{x:.3g}"


class CriteriaLibrary:
    def __init__(self, criteria: dict[str, Criterion], sources: dict[str, str] | None = None):
        self.criteria = criteria
        self.sources = sources or {}

    # ---- loading -------------------------------------------------------
    @classmethod
    def from_json(cls, path: str | Path) -> "CriteriaLibrary":
        raw = json.loads(Path(path).read_text())
        crit = {k: Criterion(key=k, **v) for k, v in raw["criteria"].items()}
        return cls(crit, raw.get("_sources", {}))

    def merged(self, override_path: str | Path) -> "CriteriaLibrary":
        """Return a copy with entries from an override JSON applied (partial entries allowed)."""
        raw = json.loads(Path(override_path).read_text())
        crit = {k: Criterion(**vars(c)) for k, c in self.criteria.items()}
        for k, v in raw.get("criteria", {}).items():
            if k in crit:
                for attr, val in v.items():
                    setattr(crit[k], attr, val)
            else:
                crit[k] = Criterion(key=k, **v)
        return CriteriaLibrary(crit, {**self.sources, **raw.get("_sources", {})})

    def to_json(self, path: str | Path) -> None:
        data = {"_sources": self.sources,
                "criteria": {k: {a: v for a, v in vars(c).items() if a != "key"}
                             for k, c in self.criteria.items()}}
        Path(path).write_text(json.dumps(data, indent=2))

    def get(self, key: str) -> Criterion:
        return self.criteria[key]

    # ---- checking ------------------------------------------------------
    def check(self, value: float, key: str, label: str | None = None,
              min_override: float | None = None, max_override: float | None = None,
              note: str = "") -> Check:
        c = self.criteria[key]
        lo = c.min if min_override is None else min_override
        hi = c.max if max_override is None else max_override
        status = PASS
        msg = ""
        if c.kind == "info" or (lo is None and hi is None):
            status = INFO
        else:
            below = lo is not None and value < lo - 1e-9
            above = hi is not None and value > hi + 1e-9
            if below or above:
                status = FAIL if c.kind == "limit" else WARN
                msg = ("below" if below else "above") + (" limit" if c.kind == "limit" else " typical range")
        if note:
            msg = (msg + "; " if msg else "") + note
        return Check(label=label or c.desc, value=value, unit=c.unit, status=status,
                     min=lo, max=hi, source=c.source, verified=c.verified, message=msg)


_DEFAULT: CriteriaLibrary | None = None


def default_library() -> CriteriaLibrary:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = CriteriaLibrary.from_json(DATA_DIR / "criteria_wwtp.json")
    return _DEFAULT


def custom_check(label: str, value: float, unit: str, lo: float | None = None,
                 hi: float | None = None, kind: str = "typical", source: str = "",
                 verified: bool = False, note: str = "") -> Check:
    """Check against a range computed at run time (e.g. PSRP SRT at a given temperature)."""
    c = Criterion(key="_custom", desc=label, unit=unit, min=lo, max=hi, kind=kind,
                  source=source, verified=verified)
    lib = CriteriaLibrary({"_custom": c})
    return lib.check(value, "_custom", label=label, note=note)
