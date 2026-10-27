"""Generic nested-dataclass <-> dict/JSON conversion for project files."""

from __future__ import annotations

import json
import typing
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path


def to_dict(obj) -> dict:
    return asdict(obj)


def from_dict(cls, data: dict):
    """Build dataclass ``cls`` from ``data``; unknown keys are ignored, missing keys keep defaults
    (so project files stay readable as the program adds new inputs)."""
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        ftype = hints.get(f.name)
        if is_dataclass(ftype) and isinstance(val, dict):
            val = from_dict(ftype, val)
        elif ftype is float and isinstance(val, int) and not isinstance(val, bool):
            val = float(val)
        kwargs[f.name] = val
    return cls(**kwargs)


def save_json(obj, path: str | Path, meta: dict | None = None) -> None:
    payload = {"format": "process-design-suite/project", "version": 1, **(meta or {}),
               "data": to_dict(obj)}
    Path(path).write_text(json.dumps(payload, indent=2))


def load_json(cls, path: str | Path):
    raw = json.loads(Path(path).read_text())
    return from_dict(cls, raw.get("data", raw))
