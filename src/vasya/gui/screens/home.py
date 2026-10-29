# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QHBoxLayout, QGroupBox
from PySide6.QtGui import QFont
from .base import Screen
from ..i18n import tr
from ... import api, VERSION


def _ok(b):
    return "✔" if b else "✖"


class HomeScreen(Screen):
    title_key = "nav_home"

    def build(self):
        self.verdict_value = None
        self.counts_value = None
        self.verdict = QLabel("…")
        f = QFont(); f.setPointSizeF(f.pointSizeF() * 1.25); f.setBold(True)
        self.verdict.setFont(f)
        self.verdict.setAccessibleName("verdict")
        self.v.addWidget(self.verdict)
        g1 = QGroupBox(f"{tr('version')} / {tr('gns3')}")
        self.info = QLabel(); self.info.setWordWrap(True); self.info.setTextInteractionFlags(
            self.info.textInteractionFlags() | self.info.textInteractionFlags().TextSelectableByMouse)
        QHBoxLayout(g1).addWidget(self.info)
        self.v.addWidget(g1)
        g2 = QGroupBox(tr("runtimes")); self.rt = QLabel(); QHBoxLayout(g2).addWidget(self.rt)
        self.v.addWidget(g2)
        g3 = QGroupBox(tr("components")); grid = QGridLayout(g3)
        self.cnt = {}
        for i, k in enumerate(("catalog", "ready", "installed", "runtime_verified", "errors")):
            lab = {"catalog": "catalog_n", "ready": "ready_n", "installed": "installed_n",
                   "runtime_verified": "verified_n", "errors": "errors_n"}[k]
            n = QLabel("–"); fn = QFont(); fn.setPointSizeF(fn.pointSizeF() * 2); fn.setBold(True)
            n.setFont(fn); n.setAccessibleName(f"count-{k}")
            grid.addWidget(n, 0, i); grid.addWidget(QLabel(tr(lab)), 1, i)
            self.cnt[k] = n
        self.byrt = QLabel(); grid.addWidget(self.byrt, 2, 0, 1, 5)
        self.v.addWidget(g3)
        row = QHBoxLayout()
        self.b_refresh = QPushButton(tr("refresh")); self.b_refresh.clicked.connect(self.refresh)
        self.b_resume = QPushButton(tr("resume")); self.b_resume.clicked.connect(self.do_resume)
        self.b_install = QPushButton(tr("nav_install")); self.b_install.clicked.connect(lambda: self.main.go("install"))
        self.b_import = QPushButton(tr("import_payload")); self.b_import.clicked.connect(self.do_import)
        self.b_import.setVisible(False)
        for b in (self.b_refresh, self.b_resume, self.b_install, self.b_import):
            row.addWidget(b)
        row.addStretch(1)
        self.v.addLayout(row)
        self.add_output(120)
        self.auto_hide_bar = True

    def on_show(self):
        self.refresh()

    def _render(self, s):
        self.verdict_value = api.verdict(s)
        c = s["components"]
        self.counts_value = {k: c[k] for k in ("catalog", "ready", "installed", "runtime_verified", "errors")}
        self.verdict.setText(f"{tr('verdict')}: {tr('V_' + self.verdict_value)}")
        g = s["gns3"]
        kind = tr("managed") if g["managed"] else tr("existing")
        api_txt = (f"{g['api_base']} — {'API OK ' + str(g['version']) if g['api_ok'] else 'API —'}"
                   if g["api_base"] else "—")
        self.info.setText(f"VASYA GNS LAB <b>{VERSION}</b><br>{tr('root')}: {s['root']}<br>"
                          f"GNS3: {tr('present') if g['present'] else tr('absent')}"
                          f"{' (' + kind + ')' if g['api_base'] else ''} · {api_txt}<br>"
                          f"Mode: {s['mode'] or '—'}")
        self.rt.setText("   ".join(f"{_ok(v)} {k}" for k, v in s["runtimes"].items()))
        for k, w in self.cnt.items():
            w.setText(str(c[k]))
        self.byrt.setText("  ·  ".join(f"{rt}: {v['installed']}/{v['ready']} ({v['runtime_verified']} ✔)"
                                       for rt, v in c["by_runtime"].items()))
        self.b_resume.setVisible(bool(s["incomplete_transactions"]))
        self.b_import.setVisible(c["ready"] == 0)   # Windows Setup: app first, images from the parts

    def refresh_sync(self):
        s = api.status(self.backend.ctx())
        self._render(s)
        return s

    def refresh(self):
        self.run(lambda: api.status(self.backend.ctx()), self._render, buttons=[self.b_refresh])

    def do_import(self, manifest=None):
        ctx = self.backend.ctx()
        m = manifest or api.find_release_manifest(ctx)
        if not m:
            from PySide6.QtWidgets import QFileDialog
            m, _ = QFileDialog.getOpenFileName(self, tr("import_hint"), "", "VASYA parts (*.parts.json)")
            if not m:
                return

        def fin(r):
            self.log(f"import-payload: {r.get('status')} {r.get('error') or r.get('files', '')}")
            self.refresh()
        self.run(lambda: api.import_payload(self.backend.ctx(), m), fin, buttons=[self.b_import])

    def do_resume(self):
        def fin(r):
            self.log(f"resume: {r.get('status')} {r.get('txid', '')}")
            self.refresh()
        self.run(lambda: api.resume(self.backend.ctx(), progress=self.task.emit_progress
                                    if self.task else None), fin, buttons=[self.b_resume])
