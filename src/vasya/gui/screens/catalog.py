# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalog of all 186 components: search, filters, details, own-image import."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
                               QPushButton, QTextBrowser, QSplitter, QFileDialog, QHeaderView,
                               QAbstractItemView)
from .base import Screen
from ..i18n import tr, lang
from ...catalog.catalog import STATUSES, STATUS_TEXT
from ... import api


class CatalogScreen(Screen):
    title_key = "nav_catalog"

    def build(self):
        row = QHBoxLayout()
        self.q = QLineEdit(); self.q.setPlaceholderText(tr("search")); self.q.setClearButtonEnabled(True)
        self.f_status = QComboBox(); self.f_status.addItem(tr("all"), None)
        for s in STATUSES:
            self.f_status.addItem(s, s)
        self.f_cat = QComboBox(); self.f_rt = QComboBox()
        self.b_import = QPushButton(tr("own_image")); self.b_import.clicked.connect(self.pick_image)
        for w in (self.q, self.f_status, self.f_cat, self.f_rt, self.b_import):
            row.addWidget(w)
        self.v.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", tr("status"), tr("runtime"), tr("category"), "Vendor", "ID"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.detail = QTextBrowser(); self.detail.setOpenExternalLinks(True)
        sp = QSplitter(Qt.Vertical); sp.addWidget(self.table); sp.addWidget(self.detail)
        sp.setSizes([420, 200])
        self.v.addWidget(sp, 1)
        self.b_register = QPushButton(tr("register")); self.b_register.setEnabled(False)
        self.b_register.clicked.connect(self.register)
        self.v.addWidget(self.b_register)
        self.analysis = None
        self.add_output(90)
        self.q.textChanged.connect(self.reload); self.f_status.currentIndexChanged.connect(self.reload)
        self.f_cat.currentIndexChanged.connect(self.reload); self.f_rt.currentIndexChanged.connect(self.reload)
        self.table.itemSelectionChanged.connect(self.show_detail)
        self._filled = False

    def on_show(self):
        ctx = self.backend.ctx()
        if not self._filled:
            self.f_cat.addItem(tr("all"), None); self.f_rt.addItem(tr("all"), None)
            for c in ctx.catalog.categories():
                self.f_cat.addItem(c, c)
            for r in ctx.catalog.runtimes():
                self.f_rt.addItem(r, r)
            self._filled = True
        self.reload()

    def reload(self, *_):
        ctx = self.backend.ctx()
        st = ctx.state.load()
        rows = ctx.catalog.search(self.q.text(), status=self.f_status.currentData(),
                                  category=self.f_cat.currentData(), runtime=self.f_rt.currentData())
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            inst = st["components"].get(e["block_id"], {})
            mark = " ✔" if inst.get("installed") else ""
            vals = [e["name"] + mark, e.get("status_effective") or e["status"], e["runtime"],
                    e["category"], e["vendor"], e["block_id"]]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v)); it.setData(Qt.UserRole, e["block_id"])
                self.table.setItem(i, j, it)
        self.table.setSortingEnabled(True)
        self.title.setText(f"{tr('nav_catalog')} — {len(rows)}/{len(ctx.catalog)}")

    def show_detail(self):
        items = self.table.selectedItems()
        if not items:
            return
        e = self.backend.ctx().catalog.get(items[0].data(Qt.UserRole))
        r = e["resources"]
        st = STATUS_TEXT.get(e["status"], ("", ""))[0 if lang() == "ru" else 1]
        imgs = "<br>".join(f"{i['filename']} ({i.get('size') or '?'} B, md5 {i.get('md5') or '?'})"
                           for i in e["required_images"]) or (e.get("docker_image") or "—")
        self.detail.setHtml(
            f"<h3>{e['name']} <small>{e['version']}</small></h3><b>{e['vendor']}</b> · {e['category_ru'] if lang()=='ru' else e['category']} · {e['runtime']}<br>"
            f"<b>{tr('status')}:</b> {e['status']} — {st}<br><b>Назначение / Purpose:</b> "
            f"{e['purpose_ru'] if lang()=='ru' else e['purpose_en']}<br>"
            f"<b>RAM</b> {r.get('ram_mb') or '?'} MB · CPU {r.get('cpus') or 1} · KVM {r.get('kvm') or '—'} · "
            f"console {r.get('console') or '—'}<br><b>Images:</b><br>{imgs}<br>"
            f"<b>Reason:</b> {e['reason']}<br><b>Action:</b> {e['action_required']}<br>"
            f"{('<a href=' + chr(34) + e['vendor_url'] + chr(34) + '>' + e['vendor_url'] + '</a>') if e['vendor_url'] else ''}"
            f"<p>{e['description'][:600]}</p>")

    def pick_image(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("own_image"))
        if f:
            self.analyse(f)

    def analyse(self, path):
        def fin(a):
            self.analysis = a
            self.log(f"{a.get('type')} {a.get('size_human')} format_ok={a.get('format_ok')} "
                     f"verdict={a.get('verdict')} → {a.get('suggested_block')}")
            for m in a.get("matches") or []:
                self.log(f"   {m['block_id']} score={m['score']} {','.join(m['why'])}")
            self.b_register.setEnabled(a.get("verdict") == "VERIFIED_MATCH")
        self.run(lambda: api.analyse_image(self.backend.ctx(), path), fin, buttons=[self.b_import])

    def register(self):
        a = self.analysis
        if not a:
            return
        def fin(rec):
            self.log(f"registered {a['suggested_block']}: {rec['sha256'][:16]}… → Store/user")
            self.reload()
        self.run(lambda: api.register_image(self.backend.ctx(), a, a["suggested_block"]), fin,
                 buttons=[self.b_register])
