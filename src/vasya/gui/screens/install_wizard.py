# SPDX-License-Identifier: GPL-3.0-or-later
"""Install wizard: Система → Режим → Компоненты → Папка → План → Установка → Проверка → Готово.
Every button calls the same vasya.api the CLI uses; nothing changes before «Установить»."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QRadioButton, QButtonGroup, QCheckBox, QListWidget, QListWidgetItem,
                               QLineEdit, QFileDialog, QPlainTextEdit, QProgressBar, QTextBrowser)
from .base import Screen
from ..i18n import tr, lang
from ..views import plan_html, error_html, mark
from ... import api
from ...tools.registry import detect_all
from ...gns3.discover import discover

STEPS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8")
SYSTEM, MODE, COMPONENTS, FOLDER, PLAN, INSTALL, VERIFY, DONE = range(8)


class InstallWizard(Screen):
    title_key = "nav_install"

    def build(self):
        self.crumbs = QLabel(); self.crumbs.setTextFormat(Qt.RichText); self.v.addWidget(self.crumbs)
        self.pages = QStackedWidget(); self.v.addWidget(self.pages, 1)
        self.plan_result = self.install_result = self.verify_result = self.runtime_result = self.blocked = None
        for f in (self._p_system, self._p_mode, self._p_components, self._p_folder, self._p_plan,
                  self._p_install, self._p_verify, self._p_done):
            f()
        row = QHBoxLayout()
        self.b_back = QPushButton(tr("back")); self.b_next = QPushButton(tr("next"))
        self.b_cancel = QPushButton(tr("cancel"))
        self.b_next.setDefault(True); self.b_next.setAutoDefault(True)
        self.b_back.setShortcut("Alt+Left"); self.b_next.setShortcut("Alt+Right")
        self.b_back.clicked.connect(lambda: self.goto(self.pages.currentIndex() - 1))
        self.b_next.clicked.connect(self.next)
        self.b_cancel.clicked.connect(self.cancel)
        row.addStretch(1)
        for b in (self.b_cancel, self.b_back, self.b_next):
            row.addWidget(b)
        self.v.addLayout(row)
        self.goto(0)

    def _page(self):
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); self.pages.addWidget(w); return l

    def _p_system(self):
        l = self._page()
        ru = lang() == "ru"
        t = QLabel(("<b>VASYA GNS LAB 1.1.0</b> — готовая сетевая лаборатория на базе GNS3: 44 проверенных компонента "
                    "(QEMU 20, Dynamips 3, Docker 21), каталог из 186 устройств, проверка, восстановление и чистое удаление. "
                    "Сначала проверяем, что уже есть на компьютере:") if ru else
                   ("<b>VASYA GNS LAB 1.1.0</b> — a ready GNS3 network lab: 44 verified components (QEMU 20, Dynamips 3, "
                    "Docker 21), a catalog of 186 devices, verify, repair and clean uninstall. First, what is already here:"))
        t.setWordWrap(True); l.addWidget(t)
        self.sys_view = QTextBrowser(); self.sys_view.setOpenExternalLinks(True); l.addWidget(self.sys_view, 1)

    def _p_mode(self):
        l = self._page()
        self.mode_group = QButtonGroup(self)
        self.r_full = QRadioButton(tr("m_complete")); self.r_int = QRadioButton(tr("m_existing"))
        self.r_sel = QRadioButton(tr("m_selective"))
        for i, (r, d) in enumerate(((self.r_full, "m_complete_d"), (self.r_int, "m_existing_d"),
                                    (self.r_sel, "m_selective_d"))):
            f = QFont(); f.setBold(True); r.setFont(f)
            self.mode_group.addButton(r, i); l.addWidget(r)
            dl = QLabel(tr(d)); dl.setWordWrap(True); dl.setContentsMargins(26, 0, 0, 10); l.addWidget(dl)
        self.r_full.setChecked(True)
        self.mode_hint = QLabel(); self.mode_hint.setWordWrap(True); l.addWidget(self.mode_hint)
        l.addStretch(1)

    def _p_components(self):
        l = self._page()
        self.comp_sum = QLabel(); l.addWidget(self.comp_sum)
        row = QHBoxLayout()
        self.b_all = QPushButton(tr("sel_all")); self.b_none = QPushButton(tr("sel_none"))
        self.b_all.clicked.connect(lambda: self._check_all(True)); self.b_none.clicked.connect(lambda: self._check_all(False))
        row.addWidget(self.b_all); row.addWidget(self.b_none); row.addStretch(1); l.addLayout(row)
        self.comp = QListWidget(); self.comp.setAccessibleName("components"); l.addWidget(self.comp, 1)

    def _p_folder(self):
        l = self._page()
        l.addWidget(QLabel(tr("root")))
        r = QHBoxLayout(); self.root_edit = QLineEdit(str(self.backend.root)); self.root_edit.setAccessibleName("root")
        b = QPushButton("…"); b.setAccessibleName("browse"); b.clicked.connect(self._browse)
        r.addWidget(self.root_edit, 1); r.addWidget(b); l.addLayout(r)
        self.loc_msg = QLabel(); self.loc_msg.setWordWrap(True); l.addWidget(self.loc_msg)
        self.api_lbl = QLabel(tr("api_label")); self.api_lbl.setWordWrap(True); l.addWidget(self.api_lbl)
        self.api_edit = QLineEdit(); self.api_edit.setPlaceholderText("http://127.0.0.1:3080"); l.addWidget(self.api_edit)
        self.cb_copy = QCheckBox(tr("allow_copy")); l.addWidget(self.cb_copy)
        self.cb_menu = QCheckBox(tr("register_menu")); l.addWidget(self.cb_menu)
        l.addStretch(1)

    def _p_plan(self):
        l = self._page()
        self.preview = QTextBrowser(); self.preview.setAccessibleName("plan"); l.addWidget(self.preview, 1)

    def _p_install(self):
        l = self._page()
        self.cur_lbl = QLabel(tr("busy")); self.cur_lbl.setWordWrap(True)
        f = QFont(); f.setPointSizeF(f.pointSizeF() * 1.25); self.cur_lbl.setFont(f)
        self.cur_lbl.setAccessibleName("current-operation")
        self.bar = QProgressBar(); self.out = QPlainTextEdit(); self.out.setReadOnly(True)
        l.addWidget(self.cur_lbl); l.addWidget(self.bar); l.addWidget(self.out, 1)

    def _p_verify(self):
        l = self._page()
        self.ver_view = QTextBrowser(); l.addWidget(self.ver_view, 1)
        row = QHBoxLayout()
        self.b_runtime = QPushButton(tr("verify_runtime")); self.b_runtime.clicked.connect(self.runtime_verify)
        row.addWidget(self.b_runtime); row.addStretch(1); l.addLayout(row)

    def _p_done(self):
        l = self._page()
        self.done_view = QTextBrowser(); self.done_view.setAccessibleName("result"); l.addWidget(self.done_view, 1)
        row = QHBoxLayout()
        self.b_open = QPushButton(tr("open_lab")); self.b_open.clicked.connect(lambda: self.main.go("ready"))
        self.b_retry = QPushButton(tr("retry_failed")); self.b_retry.clicked.connect(self.retry_failed)
        self.b_repair = QPushButton(tr("repair_btn")); self.b_repair.clicked.connect(self.repair)
        self.b_resume = QPushButton(tr("resume")); self.b_resume.clicked.connect(self.resume)
        self.b_rollback = QPushButton(tr("rollback")); self.b_rollback.clicked.connect(self.rollback)
        self.b_diag = QPushButton(tr("diag_btn")); self.b_diag.clicked.connect(lambda: self.main.go("diagnostics"))
        self.recovery_buttons = (self.b_retry, self.b_repair, self.b_resume, self.b_rollback, self.b_diag)
        for b in (self.b_open,) + self.recovery_buttons:
            row.addWidget(b)
        row.addStretch(1); l.addLayout(row)

    # ------------------------------------------------------------- navigation
    def mode(self):
        return ("FULL", "INTEGRATION", "SELECTIVE")[self.mode_group.checkedId()]

    def selected_blocks(self):
        if self.mode() != "SELECTIVE":
            return None
        return [self.comp.item(i).data(Qt.UserRole) for i in range(self.comp.count())
                if self.comp.item(i).checkState() == Qt.Checked]

    def explicit_target(self):
        if self.mode() == "FULL" or not self.api_edit.text().strip():
            return None
        return {"api_base": self.api_edit.text().strip()}

    def goto(self, i):
        i = max(0, min(i, len(STEPS) - 1))
        self.pages.setCurrentIndex(i)
        self.crumbs.setText(" → ".join(f"<b><u>{k + 1}. {tr(s)}</u></b>" if k == i else
                                       f"<span style='color:gray'>{k + 1}. {tr(s)}</span>"
                                       for k, s in enumerate(STEPS)))
        self.b_back.setEnabled(0 < i < INSTALL)
        self.b_next.setText(tr("start_install") if i == PLAN else tr("finish") if i == DONE else tr("next"))
        self.b_next.setEnabled(i not in (INSTALL,))
        self.b_cancel.setEnabled(i <= INSTALL)
        getattr(self, f"_enter_{i}", lambda: None)()

    def next(self):
        i = self.pages.currentIndex()
        if i == FOLDER and not self._validate_folder():
            return
        if i == PLAN:
            return self.start_install()
        if i == VERIFY:
            return self._show_done()
        if i == DONE:
            return self.main.go("ready")
        self.goto(i + 1)

    def cancel(self):
        if self.pages.currentIndex() == INSTALL and self.task:
            self.task.cancel.set()
            self.log(tr("cancel") + " → " + tr("rollback").lower() + "…")
        else:
            self.goto(0)

    def _validate_folder(self):
        root = self.root_edit.text().strip()
        ctx = self.backend.ctx()
        probs = ctx.platform.validate_root(root)
        if not probs and ctx.platform.needs_admin_for(root):
            from ...errors import explain
            e = explain("NO_ADMIN", lang())
            probs = [f"{e['title']}: {e['recovery']}"]
        if probs:
            self.loc_msg.setText("✖ " + "; ".join(probs)); return False
        self.loc_msg.setText("")
        self.backend.root = Path(root)
        return True

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("root"), str(Path.home()))
        if d:
            self.root_edit.setText(str(Path(d) / "VASYA-GNS-LAB"))

    def _check_all(self, on):
        for k in range(self.comp.count()):
            self.comp.item(k).setCheckState(Qt.Checked if on else Qt.Unchecked)

    # ------------------------------------------------------------- page entry
    def _enter_0(self):
        ctx = self.backend.ctx()
        self.sys_view.setHtml(tr("busy"))

        def fin(r):
            tools, g = r
            self.system_result = r
            ru = lang() == "ru"
            rows = "".join(f"<tr><td>{mark(v.get('present'))}</td><td><b>{k}</b></td><td>{v.get('version') or ''}</td>"
                           f"<td>{v.get('path') or ''}</td><td>{'' if v.get('accessible') in (None, True) else ('нет доступа' if ru else 'no access')}</td></tr>"
                           for k, v in tools.items())
            ex = g.get("api_ok") or g.get("config") or g.get("gui")
            note = ""
            if ex:
                from ...errors import explain
                e = explain("EXISTING_GNS3", lang())
                note = (f"<p><b>{e['title']}</b>: {g.get('api_base') or ''} {g.get('config') or g.get('gui') or ''}<br>"
                        f"{e['state']}<br>→ {e['recovery']}</p>")
                if g.get("api_ok") and not self.api_edit.text():
                    self.api_edit.setText(g["api_base"])
            self.sys_view.setHtml(f"<table cellpadding=2>{rows}</table>{note}")
        self.run(lambda: (detect_all(ctx.platform, with_versions=True), discover(ctx.platform)), fin)

    def _enter_1(self):
        g = getattr(self, "system_result", (None, {}))[1] or {}
        self.mode_hint.setText(("ℹ " + (f"GNS3 API {g['api_base']}" if g.get("api_ok") else "")) if g.get("api_ok") else "")

    def _enter_2(self):
        ctx = self.backend.ctx()
        self.comp.clear()
        sel = self.mode() == "SELECTIVE"
        by = {}
        for b in ctx.blocks():
            by[b["runtime"]] = by.get(b["runtime"], 0) + 1
            it = QListWidgetItem(f"{b['name']}   [{b['runtime']}]")
            it.setData(Qt.UserRole, b["block_id"]); it.setToolTip(b["block_id"])
            flags = it.flags() | Qt.ItemIsUserCheckable if sel else it.flags() & ~Qt.ItemIsUserCheckable
            it.setFlags(flags); it.setCheckState(Qt.Checked)
            self.comp.addItem(it)
        self.b_all.setVisible(sel); self.b_none.setVisible(sel)
        self.comp_sum.setText(f"{sum(by.values())}: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))

    def _enter_3(self):
        integ = self.mode() != "FULL"
        self.api_lbl.setVisible(integ); self.api_edit.setVisible(integ)

    def _enter_4(self):
        self.preview.setHtml(tr("busy"))
        self.b_next.setEnabled(False)
        self.blocked = None

        def fin(r):
            p, pre = r
            self.plan_result, self.blocked = p, pre
            self.preview.setHtml(plan_html(p, (pre or {}).get("error_ru" if lang() == "ru" else "error")))
            self.b_next.setEnabled(p["preview"]["space_ok"] and not pre)
        ctx_args = (self.mode(), self.selected_blocks(), self.explicit_target())
        self.run(lambda: (api.plan(self.backend.ctx(), *ctx_args, desktop=self.cb_menu.isChecked(),
                                   allow_copy=self.cb_copy.isChecked()),
                          api.preflight(self.backend.ctx(), *ctx_args, allow_copy=self.cb_copy.isChecked())), fin)

    def _enter_6(self):
        self.ver_view.setHtml(tr("verify_wait"))
        self.b_next.setEnabled(False)

        def fin(v):
            self.verify_result = v
            self.ver_view.setHtml(self._verify_html(v))
            self.b_next.setEnabled(True)
        self.run(lambda: api.static_verify(self.backend.ctx()), fin)

    # ------------------------------------------------------------- actions
    def start_install(self):
        self.goto(INSTALL)
        self.out.clear()
        self.cur_lbl.setText(tr("busy"))
        args = (self.mode(), self.selected_blocks(), self.explicit_target())
        self.run(lambda: api.install(self.backend.ctx(), *args, cancel=self.task.cancel,
                                     progress=self.op_progress(), desktop=self.cb_menu.isChecked(),
                                     allow_copy=self.cb_copy.isChecked()), self._installed)

    def _installed(self, r):
        self.install_result = r
        if r["status"] in ("BLOCKED", "CANCELLED"):
            return self._show_done(r)
        self.goto(VERIFY)

    def _verify_html(self, v):
        bad = [c for c in v["checks"] if c["status"] == "FAIL"]
        ok = len({c["block_id"] for c in v["checks"]}) - len({c["block_id"] for c in bad})
        o = [f"<h3>{mark(not bad)} {tr('verify_static')}: {ok}/{v['blocks']}</h3>"]
        for c in bad[:30]:
            o.append(error_html(c.get("code") or c["detail"]).replace("</div>", f"<br><small>{c['block_id']} · {c['check']}</small></div>"))
        return "".join(o)

    def runtime_verify(self):
        def fin(r):
            self.runtime_result = r
            rows = "".join(f"<tr><td>{mark(x['status'] == 'PASS')}</td><td>{x['block_id']}</td><td>{x.get('error') or ''}</td></tr>"
                           for x in r.get("results", []))
            self.ver_view.setHtml(self._verify_html(self.verify_result) +
                                  f"<h3>{tr('verify_runtime')}: {r.get('passed')}/{r.get('total')}</h3><table>{rows}</table>")
        self.run(lambda: api.runtime_verify(self.backend.ctx(), None, progress=self.task.emit_progress), fin,
                 buttons=[self.b_runtime, self.b_next])

    def _show_done(self, r=None):
        r = r or self.install_result or {}
        self.goto(DONE)
        ru = lang() == "ru"
        o = []
        st = r.get("status")
        if st == "BLOCKED":
            o.append(error_html(r["error_ru"] if ru else r["error"]))
        elif st == "CANCELLED":
            o.append(f"<h3>{tr('cancel')}: {'всё созданное откатено' if ru else 'everything created was rolled back'} "
                     f"({len(r.get('undone') or [])})</h3>")
        else:
            res = r.get("results") or []
            new = sum(x["result"] == "NEW" for x in res); reuse = sum(x["result"] == "REUSE" for x in res)
            o.append(f"<h2>{mark(st == 'OK')} {('Установка завершена' if ru else 'Install finished') if st == 'OK' else ('Установка завершена с ошибками' if ru else 'Install finished with errors')}</h2>")
            o.append(f"<p>{'создано' if ru else 'created'}: {new} · {'переиспользовано' if ru else 'reused'}: {reuse} · "
                     f"{'ошибок' if ru else 'failed'}: {len(r.get('failed') or [])}</p>")
            v = self.verify_result
            if v:
                o.append(f"<p>{tr('verify_static')}: {mark(v['status'] == 'PASS')} {v['status']}</p>")
            rv = self.runtime_result
            if rv:
                o.append(f"<p>{tr('verify_runtime')}: {mark(rv['status'] == 'PASS')} "
                         f"{rv.get('passed')}/{rv.get('total')}</p>")
            if r.get("payload", {}).get("adopted"):
                o.append(f"<p>{'Образы сохранены в папке VASYA — распакованный комплект можно удалить.' if ru else 'Images are kept in the VASYA folder — the extracted bundle can be deleted.'}</p>")
            elif r.get("payload", {}).get("reason"):
                o.append(f"<p>⚠ {r['payload']['reason']}</p>")
            seen = set()
            for f in r.get("failed") or []:
                from ...errors import classify
                k = (classify(f["error"]), f.get("block_id"))
                if k in seen:
                    continue
                seen.add(k)
                o.append(error_html(f["error"]).replace("</div>", f"<br><small>{f.get('label') or f.get('block_id') or ''}</small></div>"))
        self.done_view.setHtml("".join(o))
        failed = bool(r.get("failed"))
        self.b_retry.setVisible(failed)
        self.b_repair.setVisible(failed or (self.verify_result or {}).get("status") == "FAIL")
        inc = self.backend.ctx().layout.txn_dir.exists() and bool(api.status(self.backend.ctx(), probe=False)["incomplete_transactions"])
        self.b_resume.setVisible(inc or (st == "BLOCKED" and r.get("code") == "INTERRUPTED"))
        self.b_rollback.setVisible(st in ("OK", "PARTIAL") or inc)
        self.b_diag.setVisible(st not in ("OK",))
        self.b_open.setVisible(st in ("OK", "PARTIAL"))

    def _recovery(self, fn, title):
        self.goto(INSTALL); self.out.clear(); self.cur_lbl.setText(title)
        self.run(fn, self._installed)

    def retry_failed(self):
        self._recovery(lambda: api.retry_failed(self.backend.ctx(), progress=self.op_progress()), tr("retry_failed"))

    def repair(self):
        self._recovery(lambda: api.repair(self.backend.ctx(), progress=self.op_progress()), tr("repair_btn"))

    def resume(self):
        self._recovery(lambda: api.resume(self.backend.ctx(), progress=self.op_progress(),
                                          allow_copy=self.cb_copy.isChecked()), tr("resume"))

    def rollback(self):
        if not self.confirm(tr("rollback") + "?"):
            return

        def fin(r):
            self.install_result = {"status": "CANCELLED", "undone": r.get("undone")}
            self._show_done()
        self.goto(INSTALL); self.run(lambda: api.rollback(self.backend.ctx()), fin)
