"""GUI smoke test.

With PySide6 installed it builds the real window offscreen and runs a design.
Without it, a permissive stub of the Qt API stands in so that every code path in
our GUI modules (form generation, results population, flow estimator) still
executes and catches errors on our side (names, attributes, data plumbing).
"""

import importlib
import os
import sys
import types
from unittest.mock import MagicMock

import pytest


def _install_stub():
    class _Meta(type):
        def __getattr__(cls, name):
            return MagicMock(name=name)

    class _Z(int):
        """Falsy 0 that still answers attribute calls (Qt getters returning objects)."""
        def __new__(cls):
            return int.__new__(cls, 0)

        def __getattr__(self, name):
            return MagicMock(name=name, return_value=_Z())

    class _Q(metaclass=_Meta):
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, name):
            # methods return 0 so count()-style loops terminate and arithmetic works
            return MagicMock(name=name, return_value=_Z())

    def Signal(*a, **k):
        return MagicMock()

    names = ["QAction", "QColor", "QDesktopServices", "QKeySequence", "QFont", "QPixmap", "QUrl", "Qt",
             "QApplication", "QFileDialog", "QHBoxLayout", "QHeaderView", "QLabel", "QListWidget",
             "QListWidgetItem", "QMainWindow", "QMessageBox", "QPushButton", "QScrollArea", "QSplitter",
             "QStackedWidget", "QTableWidget", "QTableWidgetItem", "QTabWidget", "QTextBrowser", "QToolBar",
             "QTreeWidget", "QTreeWidgetItem", "QVBoxLayout", "QWidget", "QDialog", "QDialogButtonBox",
             "QSpinBox", "QComboBox", "QDoubleSpinBox", "QGroupBox", "QFormLayout", "QCheckBox", "QLineEdit"]
    pkg = types.ModuleType("PySide6")
    for sub in ("QtCore", "QtGui", "QtWidgets"):
        m = types.ModuleType(f"PySide6.{sub}")
        for n in names:
            setattr(m, n, type(n, (_Q,), {}))
        m.Signal = Signal
        setattr(pkg, sub, m)
        sys.modules[f"PySide6.{sub}"] = m
    sys.modules["PySide6"] = pkg


def test_gui_builds_and_runs(tmp_path):
    try:
        import PySide6  # noqa: F401
        real = True
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    except ImportError:
        real = False
        _install_stub()
    for mod in ("processdesign.gui.forms", "processdesign.gui.main_window"):
        sys.modules.pop(mod, None)
    mw = importlib.import_module("processdesign.gui.main_window")
    if real:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    w = mw.MainWindow()
    assert len(w.forms) == len(mw.SECTIONS)
    # edit an input through the bound form object, then run
    w.inputs.influent.Q_avg = 2.0
    w._on_change()
    w.run()
    assert w.result is not None and w.result.inputs.influent.Q_avg == 2.0
    # flow estimator dialog logic
    dlg = mw.FlowEstimatorDialog()
    assert "sc" in dlg.result and "ts" in dlg.result
    # form refresh after loading new inputs
    for f in w.forms:
        f.refresh()
    if not real:
        for mod in [m for m in sys.modules if m.startswith("PySide6")] + \
                   ["processdesign.gui.forms", "processdesign.gui.main_window"]:
            sys.modules.pop(mod, None)
