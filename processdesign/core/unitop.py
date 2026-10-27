"""Result container shared by every unit operation in every module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .criteria import Check, FAIL, WARN


@dataclass
class Param:
    label: str
    value: Any
    unit: str = ""
    decimals: int | None = None

    def text(self) -> str:
        v = self.value
        if isinstance(v, bool):
            return "Yes" if v else "No"
        if isinstance(v, int):
            return f"{v:,d}"
        if isinstance(v, float):
            if self.decimals is not None:
                return f"{v:,.{self.decimals}f}"
            av = abs(v)
            if av == 0:
                return "0"
            if av >= 1000:
                return f"{v:,.0f}"
            if av >= 100:
                return f"{v:,.0f}"
            if av >= 10:
                return f"{v:,.1f}"
            if av >= 1:
                return f"{v:,.2f}"
            return f"{v:.3g}"
        return str(v)


@dataclass
class UnitResult:
    name: str
    category: str
    inputs: list[Param] = field(default_factory=list)
    outputs: list[Param] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)       # machine-readable values for downstream units

    def i(self, label, value, unit="", decimals=None):
        self.inputs.append(Param(label, value, unit, decimals)); return value

    def o(self, label, value, unit="", decimals=None):
        self.outputs.append(Param(label, value, unit, decimals)); return value

    def c(self, check: Check):
        self.checks.append(check); return check

    def note(self, text: str):
        self.notes.append(text)

    @property
    def status(self) -> str:
        sts = {c.status for c in self.checks}
        if FAIL in sts:
            return FAIL
        if WARN in sts:
            return WARN
        return "PASS"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "category": self.category, "status": self.status,
            "inputs": [{"label": p.label, "value": p.text(), "unit": p.unit} for p in self.inputs],
            "outputs": [{"label": p.label, "value": p.text(), "unit": p.unit} for p in self.outputs],
            "checks": [c.to_dict() for c in self.checks],
            "notes": list(self.notes),
        }
