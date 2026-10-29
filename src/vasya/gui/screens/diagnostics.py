# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QPushButton, QLabel, QHBoxLayout
from .base import Screen
from ..i18n import tr
from ... import api


class DiagnosticsScreen(Screen):
    title_key = "nav_diag"

    def build(self):
        self.v.addWidget(QLabel(tr("diag_note")))
        row = QHBoxLayout()
        self.b = QPushButton(tr("diag_btn")); self.b.clicked.connect(self.build_zip)
        self.b_open = QPushButton(tr("open_folder")); self.b_open.setEnabled(False)
        self.b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent))))
        row.addWidget(self.b); row.addWidget(self.b_open); row.addStretch(1)
        self.v.addLayout(row)
        self.add_output()
        self.path = None

    def build_zip(self):
        from pathlib import Path

        def fin(r):
            self.path = Path(r["path"])
            self.log(f"✔ {r['path']}")
            for f in r["files"]:
                self.log(f"   {f['file']:<34} {f['bytes']:>9} B {'(redacted)' if f['redactions'] else ''}")
            self.b_open.setEnabled(True)
        self.out.clear()
        self.run(lambda: api.diagnostics_zip(self.backend.ctx()), fin, buttons=[self.b])
