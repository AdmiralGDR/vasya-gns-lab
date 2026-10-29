# SPDX-License-Identifier: GPL-3.0-or-later
"""First run: 'Лаборатория готова' + demo labs (created only on request)."""
import shutil, subprocess
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem, QPushButton, QHBoxLayout)
from PySide6.QtCore import Qt
from .base import Screen
from ..i18n import tr, lang
from ... import api
from ...demos import labs


class FirstRunScreen(Screen):
    title_key = "ready_title"

    def build(self):
        self.summary = QLabel(); self.summary.setWordWrap(True); self.v.addWidget(self.summary)
        t = QLabel(tr("ready_text")); t.setWordWrap(True); self.v.addWidget(t)
        self.demos = QListWidget(); self.v.addWidget(self.demos, 1)
        row = QHBoxLayout()
        self.b_create = QPushButton(tr("demo_create")); self.b_create.clicked.connect(self.create)
        self.b_check = QPushButton(tr("demo_check")); self.b_check.clicked.connect(self.check)
        self.b_remove = QPushButton(tr("demo_remove")); self.b_remove.clicked.connect(self.remove)
        self.b_gns3 = QPushButton(tr("open_gns3")); self.b_gns3.clicked.connect(self.open_gns3)
        for b in (self.b_create, self.b_check, self.b_remove, self.b_gns3):
            row.addWidget(b)
        row.addStretch(1); self.v.addLayout(row)
        self.desc = QLabel(); self.desc.setWordWrap(True); self.v.addWidget(self.desc)
        self.demos.currentItemChanged.connect(self.show_desc)
        self.add_output(160)

    def on_show(self):
        ctx = self.backend.ctx()
        s = api.status(ctx, probe=False)
        c = s["components"]
        self.summary.setText(f"<b>{c['installed']}</b> {tr('installed_n')} · <b>{c['runtime_verified']}</b> "
                             f"{tr('verified_n')} · GNS3: {s['gns3']['api_base'] or '—'}")
        if ctx.layout.exists() and ctx.state.load()["components"]:  # never create files just by looking
            with ctx.state.edit() as st:
                st["first_run_done"] = True
        keep = self.current()
        self.demos.blockSignals(True)
        self.demos.clear()
        st = ctx.state.load()
        for d in labs.definitions():
            av = labs.availability(ctx, d)
            made = " [создан]" if d["id"] in st["demos"] else ""
            it = QListWidgetItem(f"{'✔' if av['ready'] else '✖'} {d['title_ru'] if lang()=='ru' else d['title_en']}{made}")
            it.setData(Qt.UserRole, d["id"])
            self.demos.addItem(it)
        self.demos.blockSignals(False)
        rows = [self.demos.item(i).data(Qt.UserRole) for i in range(self.demos.count())]
        if rows:
            self.demos.setCurrentRow(rows.index(keep) if keep in rows else 0)

    def current(self):
        it = self.demos.currentItem()
        return it.data(Qt.UserRole) if it else None

    def show_desc(self, *_):
        d = labs.get(self.current() or "")
        if not d:
            return
        av = labs.availability(self.backend.ctx(), d)
        self.desc.setText(f"{d['description_ru'] if lang()=='ru' else d['description_en']}<br>"
                          f"<b>Blocks:</b> {', '.join(d['required_blocks'])}"
                          f"{' — missing: ' + ', '.join(av['missing_blocks']) if av['missing_blocks'] else ''}<br>"
                          f"<b>Expected:</b> {d['expected_ru'] if lang()=='ru' else d['expected_en']}<br>"
                          f"<b>Steps:</b> {' → '.join(d['steps_ru'])}<br><b>Removal:</b> {d['removal_ru']}")

    def create(self):
        did = self.current()
        base = (self.backend.ctx().state.load().get("gns3") or {}).get("api_base")
        self.run(lambda: api.demo_create(self.backend.ctx(), did, base),
                 lambda r: (self.log(f"✔ {r['name']} {r['project_id']}"), self.on_show()), buttons=[self.b_create])

    def check(self):
        did = self.current()

        def fin(r):
            self.log(f"{r['demo']}: {r['status']}  capture={r.get('capture')}")
            self.log(r["transcript"].get("ping", "")[-400:])
        self.run(lambda: api.demo_check(self.backend.ctx(), did), fin, buttons=[self.b_check])

    def remove(self):
        did = self.current()
        self.run(lambda: api.demo_remove(self.backend.ctx(), did),
                 lambda r: (self.log(f"removed={r}"), self.on_show()), buttons=[self.b_remove])

    def open_gns3(self):
        g = shutil.which("gns3")
        if g:
            subprocess.Popen([g], start_new_session=True)
            self.log("gns3 started")
        else:
            self.log("GNS3 GUI not installed (gns3 not found)")
