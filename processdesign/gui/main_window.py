"""Desktop application window (PySide6)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence, QFont, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QToolBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget, QDialog, QDialogButtonBox, QSpinBox, QComboBox,
                               QDoubleSpinBox, QGroupBox, QFormLayout)

from .. import APP_NAME, __version__
from ..core.criteria import default_library, CriteriaLibrary
from ..core.report import render_wwtp_report, write_wwtp_report
from ..core.charts import plant_charts
from ..wwtp.plant import PlantInputs, run_plant, SECTIONS
from ..wwtp.influent import sc_appendix_a_table, sc_appendix_a_flow, ten_states_population_basis
from .forms import DataclassForm

STATUS_COLORS = {"PASS": "#2e7d4f", "WARN": "#a86b00", "FAIL": "#b3261e", "INFO": "#5d6873"}


class FlowEstimatorDialog(QDialog):
    """Design-flow estimator: SC R.61-67 Appendix A or Ten States per-capita."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Design flow estimator")
        self.resize(720, 520)
        self.table = sc_appendix_a_table()
        lay = QVBoxLayout(self)
        tabs = QTabWidget(); lay.addWidget(tabs)

        # SC Appendix A
        sc = QWidget(); v = QVBoxLayout(sc)
        v.addWidget(QLabel("SC R.61-67 Appendix A unit contributory loadings. Enter unit counts:"))
        self.grid = QTableWidget(len(self.table), 4)
        self.grid.setHorizontalHeaderLabels(["Establishment", "Unit", "gpd/unit", "Count"])
        for i, row in enumerate(self.table):
            for j, val in enumerate((row["type"], row["unit"], f"{row['gpd']:g}")):
                it = QTableWidgetItem(val); it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.grid.setItem(i, j, it)
            self.grid.setItem(i, 3, QTableWidgetItem("0"))
        self.grid.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.grid.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.grid.itemChanged.connect(self._update)
        v.addWidget(self.grid)
        self.sc_total = QLabel("Total: 0 gpd"); v.addWidget(self.sc_total)
        tabs.addTab(sc, "SC R.61-67 App. A")

        # Ten States per-capita
        ts = QWidget(); f = QFormLayout(ts)
        self.pop = QSpinBox(); self.pop.setRange(0, 10_000_000); self.pop.setValue(10000)
        self.gpcd = QDoubleSpinBox(); self.gpcd.setRange(10, 500); self.gpcd.setValue(100)
        f.addRow("Population", self.pop); f.addRow("Flow (gpcd)", self.gpcd)
        self.ts_out = QLabel(); f.addRow("Result", self.ts_out)
        self.pop.valueChanged.connect(self._update); self.gpcd.valueChanged.connect(self._update)
        tabs.addTab(ts, "Ten States per capita")
        self.tabs = tabs

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Use this flow")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.result = {}
        self._update()

    def _update(self, *_):
        entries = []
        for i in range(len(self.table)):
            try:
                n = float(self.grid.item(i, 3).text() or 0)
            except (ValueError, AttributeError):
                n = 0
            if n:
                entries.append((i, n))
        sc = sc_appendix_a_flow(entries)
        self.sc_total.setText(f"Total: {sc['total_gpd']:,.0f} gpd  ({sc['total_mgd']:.4f} MGD)")
        try:
            ts = ten_states_population_basis(self.pop.value(), self.gpcd.value())
            self.ts_out.setText(f"{ts['Q_avg']:.4f} MGD;  BOD {ts['BOD']:.0f} mg/L, TSS {ts['TSS']:.0f} mg/L, "
                                f"TKN {ts['TKN']:.1f} mg/L")
        except ValueError as e:
            ts = {"Q_avg": 0.0}
            self.ts_out.setText(str(e))
        self.result = {"sc": sc, "ts": ts}

    def chosen(self) -> dict:
        if self.tabs.currentIndex() == 0:
            return {"Q_avg": self.result["sc"]["total_mgd"]}
        return dict(self.result["ts"])


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.inputs = PlantInputs()
        self.lib: CriteriaLibrary = default_library()
        self.path: Path | None = None
        self.dirty = False
        self.result = None
        self.resize(1280, 820)
        self._build()
        self._title()

    # ---------------------------------------------------------------- UI
    def _build(self):
        tb = QToolBar("Main"); tb.setMovable(False); self.addToolBar(tb)
        def act(text, slot, key=None):
            a = QAction(text, self); a.triggered.connect(slot)
            if key: a.setShortcut(QKeySequence(key))
            tb.addAction(a); return a
        act("New", self.new_project, QKeySequence.New)
        act("Open...", self.open_project, QKeySequence.Open)
        act("Save", self.save_project, QKeySequence.Save)
        act("Save As...", self.save_as)
        tb.addSeparator()
        act("Run Design", self.run, "F5")
        act("Export Report...", self.export_report)
        act("Open Report in Browser", self.open_in_browser)
        tb.addSeparator()
        act("Flow Estimator...", self.flow_estimator)
        act("Load Criteria File...", self.load_criteria)

        split = QSplitter()
        self.nav = QListWidget(); self.nav.setMaximumWidth(240)
        self.stack = QStackedWidget()
        split.addWidget(self.nav); split.addWidget(self.stack); split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        self._build_pages()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.statusBar().showMessage("Ready - edit inputs, then Run Design (F5).")

    def _build_pages(self):
        self.nav.clear()
        while self.stack.count():
            w = self.stack.widget(0); self.stack.removeWidget(w); w.deleteLater()
        self.forms = []
        for key, title in SECTIONS:
            obj = getattr(self.inputs, key)
            form = DataclassForm(obj, title)
            form.changed.connect(self._on_change)
            self.forms.append(form)
            page = QWidget(); v = QVBoxLayout(page)
            if key == "influent":
                self.derived = QLabel(); self.derived.setWordWrap(True)
                self.derived.setStyleSheet("background:#f4f6f8;padding:8px;border-radius:4px")
                v.addWidget(self.derived)
            v.addWidget(form)
            sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(page)
            self.stack.addWidget(sc)
            self.nav.addItem(QListWidgetItem(title))
        self.nav.addItem(QListWidgetItem("Results"))
        self.stack.addWidget(self._results_page())
        self._update_derived()

    def _results_page(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.summary = QLabel("Run the design to see results."); self.summary.setWordWrap(True)
        f = QFont(); f.setPointSize(11); self.summary.setFont(f)
        v.addWidget(self.summary)
        tabs = QTabWidget(); v.addWidget(tabs, 1)
        self.compliance = QTableWidget(0, 4)
        self.compliance.setHorizontalHeaderLabels(["Parameter", "Predicted (mg/L)", "Limit (mg/L)", "Status"])
        self.compliance.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tabs.addTab(self.compliance, "Compliance")
        self.tree = QTreeWidget(); self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Item", "Value", "Unit / range", "Status", "Basis"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tabs.addTab(self.tree, "Unit processes")
        self.balance = QTableWidget(); tabs.addTab(self.balance, "Mass balance")
        self.costs = QTableWidget(0, 3)
        self.costs.setHorizontalHeaderLabels(["Item", "Amount", "Unit"])
        self.costs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        tabs.addTab(self.costs, "Costs")
        self.fig_host = QWidget(); self.fig_layout = QVBoxLayout(self.fig_host)
        fig_scroll = QScrollArea(); fig_scroll.setWidgetResizable(True); fig_scroll.setWidget(self.fig_host)
        tabs.addTab(fig_scroll, "Figures")
        self.preview = QTextBrowser(); tabs.addTab(self.preview, "Report preview")
        return w

    # ---------------------------------------------------------------- state
    def _on_change(self):
        self.dirty = True
        self._title()
        self._update_derived()

    def _update_derived(self):
        i = self.inputs.influent
        L = i.loads()
        msgs = i.validate()
        txt = (f"<b>Derived:</b> max-day {i.Q_maxday:.2f} MGD · peak hour {i.Q_peak:.2f} MGD · "
               f"bCOD {i.bCOD:.0f} · nbVSS {i.nbVSS:.0f} · iTSS {i.iTSS:.0f} mg/L<br>"
               f"Loads: BOD {L['BOD']:,.0f} · TSS {L['TSS']:,.0f} · TKN {L['TKN']:,.0f} · TP {L['TP']:,.0f} lb/d")
        if msgs:
            txt += "<br><span style='color:#b3261e'>" + "<br>".join(msgs) + "</span>"
        if hasattr(self, "derived"):
            self.derived.setText(txt)

    def _title(self):
        name = self.path.name if self.path else "Untitled"
        self.setWindowTitle(f"{APP_NAME} {__version__} - WWTP - {name}{' *' if self.dirty else ''}")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, APP_NAME, "Discard unsaved changes?",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return r == QMessageBox.Yes

    # ---------------------------------------------------------------- actions
    def new_project(self):
        if not self._confirm_discard():
            return
        self.inputs = PlantInputs(); self.path = None; self.dirty = False; self.result = None
        self._build_pages(); self._title()

    def open_project(self):
        if not self._confirm_discard():
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Open project", "", "Project (*.json)")
        if not fn:
            return
        try:
            self.inputs = PlantInputs.load(fn)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not open project:\n{e}"); return
        self.path = Path(fn); self.dirty = False; self.result = None
        self._build_pages(); self._title()

    def save_project(self):
        if self.path is None:
            return self.save_as()
        self.inputs.save(self.path); self.dirty = False; self._title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)

    def save_as(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save project", "project.json", "Project (*.json)")
        if fn:
            self.path = Path(fn); self.save_project()

    def load_criteria(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Load criteria override", "", "Criteria (*.json)")
        if fn:
            try:
                self.lib = default_library().merged(fn)
                self.statusBar().showMessage(f"Criteria override loaded: {Path(fn).name}", 5000)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, APP_NAME, f"Invalid criteria file:\n{e}")

    def flow_estimator(self):
        dlg = FlowEstimatorDialog(self)
        if dlg.exec() == QDialog.Accepted:
            vals = dlg.chosen()
            if vals.get("Q_avg", 0) <= 0:
                return
            for k, v in vals.items():
                setattr(self.inputs.influent, k, float(v))
            for f in self.forms:
                f.refresh()
            self._on_change()

    def run(self):
        try:
            self.result = run_plant(self.inputs, self.lib)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Design could not be completed:\n{e}")
            return
        self._show_results()
        self.nav.setCurrentRow(self.nav.count() - 1)

    def _show_results(self):
        r = self.result
        c = r.counts()
        col = STATUS_COLORS.get(r.status, "#000")
        self.summary.setText(
            f"<b>Overall: <span style='color:{col}'>{r.status}</span></b> — {c['PASS']} pass, "
            f"{c['WARN']} warnings, {c['FAIL']} failures. Recycle "
            f"{'converged' if r.converged else 'NOT converged'} in {r.iterations} iterations."
            + "".join(f"<br>&#9888; {w}" for w in r.warnings))
        self.compliance.setRowCount(len(r.compliance))
        for i, row in enumerate(r.compliance):
            vals = [row["param"], f"{row['predicted']:.2f}", f"{row['limit']:.1f}" if row["limit"] else "-", row["status"]]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 3: it.setForeground(QColor(STATUS_COLORS.get(v, "#000")))
                self.compliance.setItem(i, j, it)
        self.tree.clear()
        for u in r.units:
            top = QTreeWidgetItem([u.name, "", "", u.status, ""])
            top.setForeground(3, QColor(STATUS_COLORS.get(u.status, "#000")))
            f = top.font(0); f.setBold(True); top.setFont(0, f)
            outs = QTreeWidgetItem(["Results"])
            for p in u.outputs:
                outs.addChild(QTreeWidgetItem([p.label, p.text(), p.unit]))
            chk = QTreeWidgetItem(["Checks"])
            for ck in u.checks:
                it = QTreeWidgetItem([ck.label + (f" - {ck.message}" if ck.message else ""),
                                      f"{ck.value:,.3g} {ck.unit}", ck.range_text, ck.status,
                                      ck.source + ("" if ck.verified else " (unverified)")])
                it.setForeground(3, QColor(STATUS_COLORS.get(ck.status, "#000")))
                chk.addChild(it)
            top.addChildren([outs, chk])
            for n in u.notes:
                top.addChild(QTreeWidgetItem(["Note: " + n]))
            self.tree.addTopLevelItem(top)
            top.setExpanded(u.status != "PASS"); chk.setExpanded(u.status != "PASS")
        cols = ["Stream", "Q (MGD)", "BOD5", "TSS", "TKN", "NH3-N", "NO3-N", "TP"]
        self.balance.setColumnCount(len(cols)); self.balance.setHorizontalHeaderLabels(cols)
        self.balance.setRowCount(len(r.streams))
        for i, s in enumerate(r.streams):
            row = [s["name"], f"{s['Q']:.3f}"] + [("-" if s[k] is None else f"{s[k]:.1f}")
                                                   for k in ("BOD", "TSS", "TKN", "NH3N", "NO3N", "TP")]
            for j, v in enumerate(row):
                self.balance.setItem(i, j, QTableWidgetItem(v))
        self.balance.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        cu = next((u for u in r.units if u.name.startswith("Cost Estimate")), None)
        self.costs.setRowCount(len(cu.outputs) if cu else 0)
        for i, prm in enumerate(cu.outputs if cu else []):
            for j, v in enumerate((prm.label, prm.text(), prm.unit)):
                it = QTableWidgetItem(v)
                if prm.label.isupper():
                    f = it.font(); f.setBold(True); it.setFont(f)
                self.costs.setItem(i, j, it)
        while self.fig_layout.count():
            w = self.fig_layout.takeAt(0).widget()
            if w: w.deleteLater()
        try:
            for title, png in plant_charts(r).items():
                pm = QPixmap(); pm.loadFromData(png)
                lab = QLabel(); lab.setPixmap(pm.scaledToWidth(min(pm.width(), 900), Qt.SmoothTransformation))
                lab.setToolTip(title)
                self.fig_layout.addWidget(lab)
        except Exception as e:  # noqa: BLE001
            self.fig_layout.addWidget(QLabel(f"Charts unavailable: {e}"))
        self.fig_layout.addStretch(1)
        # the QTextBrowser cannot show data-URI images reliably; the browser export has the figures
        self.preview.setHtml(render_wwtp_report(r, self.lib))

    def _ensure_result(self) -> bool:
        if self.result is None or self.dirty:
            self.run()
        return self.result is not None

    def export_report(self):
        if not self._ensure_result():
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Export report", "wwtp_design_report.html", "HTML (*.html)")
        if fn:
            write_wwtp_report(self.result, fn, self.lib)
            self.statusBar().showMessage(f"Report written: {fn}", 5000)

    def open_in_browser(self):
        if not self._ensure_result():
            return
        tmp = Path(tempfile.gettempdir()) / "wwtp_design_report.html"
        write_wwtp_report(self.result, tmp, self.lib)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(tmp)))

    def closeEvent(self, e):
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow(); w.show()
    sys.exit(app.exec())
