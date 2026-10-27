"""Dataclass field metadata so input forms (GUI, CLI, reports) are generated
from one definition instead of being hand-coded per module."""

from dataclasses import field, fields, is_dataclass, MISSING
from typing import Any


def fld(default: Any, label: str, unit: str = "", lo: float | None = None,
        hi: float | None = None, choices: list | None = None, help: str = "",
        step: float | None = None, decimals: int | None = None):
    meta = {"label": label, "unit": unit, "min": lo, "max": hi,
            "choices": choices, "help": help, "step": step, "decimals": decimals}
    if isinstance(default, (list, dict)):
        return field(default_factory=lambda d=default: type(d)(d), metadata=meta)
    return field(default=default, metadata=meta)


def field_specs(obj_or_cls) -> list[dict]:
    """Return [{name, label, unit, min, max, choices, help, default, type}] for a dataclass."""
    if not is_dataclass(obj_or_cls):
        raise TypeError("expected a dataclass")
    out = []
    for f in fields(obj_or_cls):
        meta = dict(f.metadata) if f.metadata else {}
        if not meta.get("label"):
            continue  # internal field, not user-facing
        if f.default is not MISSING:
            default = f.default
        elif f.default_factory is not MISSING:  # type: ignore[misc]
            default = f.default_factory()        # type: ignore[misc]
        else:
            default = None
        value = getattr(obj_or_cls, f.name) if not isinstance(obj_or_cls, type) else default
        out.append({"name": f.name, "value": value, "default": default,
                    "type": type(default).__name__, **meta})
    return out
