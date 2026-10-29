# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QLineEdit, QComboBox
from .base import Screen
from ..i18n import tr
from ...core.oplog import read_entries


class LogsScreen(Screen):
    title_key = "nav_logs"

    def build(self):
        row = QHBoxLayout()
        self.q = QLineEdit(); self.q.setPlaceholderText(tr("search"))
        self.res = QComboBox()
        for r in ("", "FAIL", "NEW", "REUSE", "REMOVED", "OK", "PASS"):
            self.res.addItem(r or tr("all"), r or None)
        self.b = QPushButton(tr("refresh")); self.b.clicked.connect(self.on_show)
        for w in (self.q, self.res, self.b):
            row.addWidget(w)
        self.v.addLayout(row)
        self.q.returnPressed.connect(self.on_show); self.res.currentIndexChanged.connect(self.on_show)
        self.add_output()

    def on_show(self):
        ents = read_entries(self.backend.ctx().layout.Logs, limit=3000)
        q, rf = self.q.text().lower(), self.res.currentData()
        lines = []
        for e in ents:
            if rf and e.get("result") != rf:
                continue
            ln = (f"{e['timestamp']} {e.get('txid') or '-'} {e.get('operation_id') or '-'} "
                  f"{e['action']} {e.get('target')} -> {e['result']}" + (f"  ERROR={e['error']}" if e.get("error") else ""))
            if q and q not in ln.lower():
                continue
            lines.append(ln)
        self.out.setPlainText("\n".join(lines[-2000:]) or "(empty)")
        self.title.setText(f"{tr('nav_logs')} — {len(lines)}")
