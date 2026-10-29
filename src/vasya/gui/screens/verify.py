# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QLabel
from .base import Screen
from ..i18n import tr, lang
from ...errors import explain
from ... import api


class VerifyScreen(Screen):
    """Verify: a human summary on top (what is wrong + what to do), raw lines below."""
    title_key = "nav_verify"

    def build(self):
        self.auto_hide_bar = True
        row = QHBoxLayout()
        self.b_static = QPushButton(tr("verify_static")); self.b_static.clicked.connect(self.static)
        self.b_runtime = QPushButton(tr("verify_runtime")); self.b_runtime.clicked.connect(self.runtime)
        self.b_repair = QPushButton(tr("go_repair")); self.b_repair.clicked.connect(self.go_repair)
        self.b_repair.setVisible(False)
        row.addWidget(self.b_static); row.addWidget(self.b_runtime); row.addWidget(self.b_repair)
        row.addStretch(1)
        self.v.addLayout(row)
        self.summary = QLabel(); self.summary.setTextFormat(Qt.RichText); self.summary.setWordWrap(True)
        self.v.addWidget(self.summary)
        self.add_output()

    def go_repair(self):
        if self.main:
            self.main.go("repair")

    def _summarize(self, bad, total, ok_text):
        if not bad:
            self.summary.setText(f"<b style='color:#2e7d32'>✔ {ok_text}</b>")
            self.b_repair.setVisible(False)
            return
        names = {b["block_id"]: b.get("name") or b["block_id"] for b in self.backend.ctx().blocks()}
        items = []
        for c in bad:
            e = explain(c.get("code") or c.get("detail") or c.get("error") or "", lang(), c.get("detail"))
            items.append(f"<li><b>{names.get(c['block_id'], c['block_id'])}</b> — {e['title']}. "
                         f"<i>{e['recovery']}</i></li>")
        self.summary.setText(f"<b style='color:#c62828'>✖ {tr('verify_bad').format(n=len(bad))}</b>"
                             f"<ul>{''.join(items)}</ul>")
        self.b_repair.setVisible(True)

    def static(self):
        def fin(r):
            self.static_result = r
            for c in r["checks"]:
                self.log(f"{c['status']:<10} {c['block_id']:<40} {c['check']:<12} {c['detail']}")
            self.log(f"== STATIC {r['status']}  failed={r['failed']}  blocks={r['blocks']}")
            bad = [c for c in r["checks"] if c["status"] == "FAIL"]
            self._summarize(bad, r["blocks"], tr("verify_all_ok").format(n=r["blocks"]))
        self.out.clear(); self.summary.clear()
        self.run(lambda: api.static_verify(self.backend.ctx()), fin,
                 buttons=[self.b_static, self.b_runtime])

    def runtime(self, block_ids=None):
        def fin(r):
            self.runtime_result = r
            for x in r.get("results", []):
                self.log(f"{x['status']:<5} {x['block_id']:<40} {x['steps']} {x.get('error') or ''}")
            self.log(f"== RUNTIME {r['status']} {r.get('passed')}/{r.get('total')}")
            bad = [x for x in r.get("results", []) if x["status"] != "PASS"]
            self._summarize(bad, r.get("total"), tr("verify_rt_ok").format(p=r.get("passed"), t=r.get("total")))
        self.out.clear(); self.summary.clear()
        self.run(lambda: api.runtime_verify(self.backend.ctx(), block_ids, progress=self.task.emit_progress),
                 fin, buttons=[self.b_static, self.b_runtime])
