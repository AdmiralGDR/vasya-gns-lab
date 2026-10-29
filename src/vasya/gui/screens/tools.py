# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools registry + Packet Tracer (detection / import of the user's own official installer)."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QFileDialog, QAbstractItemView)
from .base import Screen
from ..i18n import tr, lang
from ... import api
from ...tools.packet_tracer import OFFICIAL_URL


class ToolsScreen(Screen):
    title_key = "nav_tools"

    def build(self):
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Tool", "✔", "Owner", "Version", "Why", "Source / update / removal"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.v.addWidget(self.table, 1)
        g = QGroupBox(tr("pt")); gl = QVBoxLayout(g)
        self.pt_status = QLabel("…"); self.pt_status.setWordWrap(True); gl.addWidget(self.pt_status)
        gl.addWidget(QLabel(tr("pt_note")))
        row = QHBoxLayout()
        self.b_link = QPushButton(tr("pt_link")); self.b_link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(OFFICIAL_URL)))
        self.b_imp = QPushButton(tr("pt_import")); self.b_imp.clicked.connect(self.pick)
        row.addWidget(self.b_link); row.addWidget(self.b_imp); row.addStretch(1); gl.addLayout(row)
        self.v.addWidget(g)
        row2 = QHBoxLayout()
        self.b_menu = QPushButton(tr("menu_register")); self.b_menu.clicked.connect(self.menu_register)
        self.b_unmenu = QPushButton(tr("menu_unregister")); self.b_unmenu.clicked.connect(self.menu_unregister)
        row2.addWidget(self.b_menu); row2.addWidget(self.b_unmenu); row2.addStretch(1)
        self.v.addLayout(row2)
        self.add_output(90)
        self.rows = None

    def on_show(self):
        ctx = self.backend.ctx()

        def fin(r):
            rows, pt = r
            self.rows = rows
            self.table.setRowCount(len(rows))
            for i, t in enumerate(rows):
                vals = [t["name"], "✔" if t["present"] else "✖", t["owner"], t.get("version") or "",
                        t["why_ru"] if lang() == "ru" else t["why_en"],
                        f"{t['source']} | update: {t['update']} | remove: {t['removal']}"]
                for j, v in enumerate(vals):
                    self.table.setItem(i, j, QTableWidgetItem(str(v)))
            self.table.resizeColumnsToContents()
            self.pt_status.setText(f"<b>{pt['status']}</b> {pt.get('path') or ''}<br>" + "<br>".join(pt["notes"]))
        self.run(lambda: (api.tool_registry(ctx.platform), api.packet_tracer_status(ctx)), fin)

    def pick(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("pt_import"), "", "Packet Tracer (*.deb *.exe)")
        if f:
            self.import_installer(f)

    def import_installer(self, f):
        def fin(v):
            self.log(f"verified={v['verified']} sha256={v.get('sha256')}")
            for c in v.get("checks", []):
                self.log("  " + c)
            if v["verified"]:
                self.log("→ " + v["install_command"])
            self.on_show()
        self.run(lambda: api.packet_tracer_import(self.backend.ctx(), f), fin, buttons=[self.b_imp])

    def menu_register(self):
        if not self.confirm(tr("register_menu") + "?"):
            return
        self.run(lambda: api.register_desktop(self.backend.ctx()), lambda r: self.log(str(r)),
                 buttons=[self.b_menu])

    def menu_unregister(self):
        self.run(lambda: api.unregister_desktop(self.backend.ctx()), lambda r: self.log(str(r)),
                 buttons=[self.b_unmenu])
