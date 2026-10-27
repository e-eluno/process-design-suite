"""Auto-generated input forms: one widget per dataclass field, driven by the
field metadata in ``core.fields``. Edits are written straight back to the
dataclass instance."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget, QHBoxLayout)

from ..core.fields import field_specs


class DataclassForm(QWidget):
    changed = Signal()

    def __init__(self, obj, title: str | None = None, parent=None):
        super().__init__(parent)
        self.obj = obj
        self._widgets = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox(title) if title else QWidget()
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        outer.addWidget(box)
        for spec in field_specs(obj):
            w = self._make_widget(spec)
            if w is None:
                continue
            label = QLabel(spec["label"] + (f"  [{spec['unit']}]" if spec.get("unit") else ""))
            if spec.get("help"):
                label.setToolTip(spec["help"]); w.setToolTip(spec["help"])
            form.addRow(label, w)
            self._widgets[spec["name"]] = w
        # nested dataclasses (e.g. kinetic coefficients) get their own group
        for f in fields(obj):
            val = getattr(obj, f.name)
            if is_dataclass(val):
                sub = DataclassForm(val, title=f.name.replace("_", " ").title())
                sub.changed.connect(self.changed)
                outer.addWidget(sub)
        outer.addStretch(1)

    # ------------------------------------------------------------------
    def _make_widget(self, spec):
        name, val = spec["name"], spec["value"]
        if spec.get("choices"):
            w = QComboBox(); w.addItems([str(c) for c in spec["choices"]])
            w.setCurrentText(str(val))
            w.currentTextChanged.connect(lambda t, n=name: self._set(n, t))
        elif isinstance(val, bool):
            w = QCheckBox(); w.setChecked(val)
            w.toggled.connect(lambda b, n=name: self._set(n, bool(b)))
        elif isinstance(val, int):
            w = QSpinBox()
            w.setRange(int(spec["min"] if spec["min"] is not None else 0),
                       int(spec["max"] if spec["max"] is not None else 10**6))
            w.setValue(val)
            w.valueChanged.connect(lambda v, n=name: self._set(n, int(v)))
        elif isinstance(val, float):
            w = QDoubleSpinBox()
            dec = spec.get("decimals")
            if dec is None:
                dec = 3 if abs(val) < 10 else (2 if abs(val) < 1000 else 1)
            w.setDecimals(dec)
            w.setRange(spec["min"] if spec["min"] is not None else -1e9,
                       spec["max"] if spec["max"] is not None else 1e9)
            w.setSingleStep(spec.get("step") or (0.1 if abs(val) < 10 else 1.0))
            w.setValue(val)
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda v, n=name: self._set(n, float(v)))
        elif isinstance(val, list):
            w = QLineEdit(", ".join(f"{x:g}" for x in val))
            w.editingFinished.connect(lambda n=name, ww=w: self._set_list(n, ww))
        elif isinstance(val, str):
            w = QLineEdit(val)
            w.textChanged.connect(lambda t, n=name: self._set(n, t))
        else:
            return None
        return w

    def _set(self, name, value):
        setattr(self.obj, name, value)
        self.changed.emit()

    def _set_list(self, name, w: QLineEdit):
        try:
            vals = [float(x) for x in w.text().replace(";", ",").split(",") if x.strip()]
        except ValueError:
            w.setStyleSheet("border:1px solid #b3261e"); return
        w.setStyleSheet("")
        self._set(name, vals)

    def refresh(self):
        """Reload widget values from the object (after Open / New)."""
        for spec in field_specs(self.obj):
            w = self._widgets.get(spec["name"])
            if w is None:
                continue
            w.blockSignals(True)
            v = spec["value"]
            if isinstance(w, QComboBox): w.setCurrentText(str(v))
            elif isinstance(w, QCheckBox): w.setChecked(bool(v))
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)): w.setValue(v)
            elif isinstance(w, QLineEdit):
                w.setText(", ".join(f"{x:g}" for x in v) if isinstance(v, list) else str(v))
            w.blockSignals(False)
