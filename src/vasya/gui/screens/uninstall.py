# SPDX-License-Identifier: GPL-3.0-or-later
"""Uninstall wizard: what will be removed + level → your projects (export/keep/delete,
only when projects live inside the VASYA folder) → confirm → residue report."""
from html import escape as h
from PySide6.QtWidgets import (QRadioButton, QCheckBox, QPushButton, QButtonGroup, QHBoxLayout,
                               QStackedWidget, QWidget, QVBoxLayout, QLabel, QTextBrowser)
from PySide6.QtCore import Qt
from .base import Screen
from ..i18n import tr, lang
from ..views import error_html, mark
from ... import api
from ...core.util import human_bytes


class UninstallScreen(Screen):
    title_key = "nav_uninstall"

    def build(self):
        self.auto_hide_bar = True  # the report page shows the result; no stray "Done" bar
        self.crumbs = QLabel(); self.crumbs.setTextFormat(Qt.RichText); self.v.addWidget(self.crumbs)
        self.pages = QStackedWidget(); self.v.addWidget(self.pages, 1)
        # page 0: inventory + level
        l = self._page()
        self.r1 = QRadioButton(tr("un_level1")); self.r2 = QRadioButton(tr("un_level2"))
        g = QButtonGroup(self); g.addButton(self.r1); g.addButton(self.r2); self.r1.setChecked(True)
        self.cb_docker = QCheckBox(tr("un_docker")); self.cb_docker.setChecked(True)
        for w in (self.r1, self.r2, self.cb_docker):
            l.addWidget(w)
        self.inv_view = QTextBrowser(); l.addWidget(self.inv_view, 1)
        self.b_inv = QPushButton(tr("refresh")); self.b_inv.clicked.connect(self.inventory); l.addWidget(self.b_inv)
        # page 1: projects
        l = self._page()
        # a QTextBrowser, not a word-wrapped QLabel: the label under-reported its height inside the
        # QStackedWidget and the project list overlapped the radio buttons (screenshot 21 of the GUI test)
        self.pj_lbl = QTextBrowser(); self.pj_lbl.setMaximumHeight(170)
        l.addWidget(self.pj_lbl)
        self.pg = QButtonGroup(self)
        self.rp_export = QRadioButton(tr("pj_export")); self.rp_keep = QRadioButton(tr("pj_keep"))
        self.rp_delete = QRadioButton(tr("pj_delete"))
        for i, r in enumerate((self.rp_export, self.rp_keep, self.rp_delete)):
            self.pg.addButton(r, i); l.addWidget(r)
        self.rp_keep.setChecked(True)
        l.addStretch(1)
        # page 2: confirm
        l = self._page()
        self.confirm_view = QTextBrowser(); l.addWidget(self.confirm_view, 1)
        self.pkg_box = QVBoxLayout(); l.addLayout(self.pkg_box)   # full level: system packages
        self.pkg_checks = []
        # page 3: report
        l = self._page()
        self.report_view = QTextBrowser(); l.addWidget(self.report_view, 1)
        self.b_stop = QPushButton(tr("stop_nodes")); self.b_stop.clicked.connect(self.stop_nodes)
        l.addWidget(self.b_stop)
        self.add_output(height=120)
        row = QHBoxLayout(); row.addStretch(1)
        self.b_back = QPushButton(tr("back")); self.b_next = QPushButton(tr("next"))
        self.b_run = QPushButton(tr("un_run"))
        self.b_back.clicked.connect(self.back); self.b_next.clicked.connect(self.next)
        self.b_run.clicked.connect(self.uninstall)
        for b in (self.b_back, self.b_next, self.b_run):
            row.addWidget(b)
        self.v.addLayout(row)
        self.report = None
        self.inv = None
        self.goto(0)

    def _page(self):
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); self.pages.addWidget(w); return l

    def goto(self, i):
        self.pages.setCurrentIndex(i)
        names = ("un_s1", "un_s2", "un_s3", "un_s4")
        self.crumbs.setText(" → ".join(f"<b><u>{k + 1}. {tr(n)}</u></b>" if k == i else
                                       f"<span style='color:gray'>{k + 1}. {tr(n)}</span>" for k, n in enumerate(names)))
        self.b_back.setEnabled(0 < i < 3)
        self.b_next.setVisible(i < 2)
        self.b_run.setVisible(i == 2)
        self.b_stop.setVisible(False)
        if i == 1:
            self._enter_projects()
        if i == 2:
            self._enter_confirm()

    def level(self):
        return "components" if self.r1.isChecked() else "full"

    def projects_choice(self):
        return ("export", "keep", "delete")[self.pg.checkedId()]

    def _has_projects(self):
        return bool(self.inv and self.inv.get("user_projects"))

    def next(self):
        i = self.pages.currentIndex()
        if i == 0 and (self.level() == "components" or not self._has_projects()):
            return self.goto(2)
        self.goto(i + 1)

    def back(self):
        i = self.pages.currentIndex()
        if i == 2 and (self.level() == "components" or not self._has_projects()):
            return self.goto(0)
        self.goto(i - 1)

    def on_show(self):
        self.goto(0)
        self.inventory()

    def inventory(self):
        def fin(inv):
            self.inv = inv
            ru = lang() == "ru"
            kinds = "".join(f"<li>{h(k)}: <b>{n}</b></li>" for k, n in inv["by_kind"].items())
            items = "".join(f"<li><small>{h(str(r.get('kind')))} — {h(str(r.get('path') or r.get('name') or r.get('ref') or r.get('config')))}</small></li>"
                            for r in inv["resources"][:300])
            pj = inv.get("user_projects") or []
            self.inv_view.setHtml(
                f"<p>{'Ресурсы, созданные VASYA (только они будут удалены)' if ru else 'Resources created by VASYA (only these are removed)'}: "
                f"<b>{len(inv['resources'])}</b></p><ul>{kinds}</ul>"
                + (f"<p><b>{tr('un_s2')}:</b> {len(pj)}</p>" if pj else "")
                + f"<details><ul>{items}</ul></details>")
        self.run(lambda: api.inventory(self.backend.ctx()), fin, buttons=[self.b_inv])

    def _enter_projects(self):
        pj = (self.inv or {}).get("user_projects") or []
        if not pj:
            self.pj_lbl.setPlainText(tr("pj_none")); return
        self.pj_lbl.setPlainText(("Внутри папки VASYA есть ваши проекты — что с ними сделать?\n" if lang() == "ru" else
                             "Your projects live inside the VASYA folder — what should happen to them?\n")
                            + "\n".join(f"• {p['name']} ({human_bytes(p['bytes'])})" for p in pj))

    def _enter_confirm(self):
        ru = lang() == "ru"
        o = [f"<h3>{tr('un_confirm')}</h3><ul>",
             f"<li>{tr('un_level1') if self.level() == 'components' else tr('un_level2')}</li>"]
        if self.level() == "full":
            o.append(f"<li>Docker: {tr('yes') if self.cb_docker.isChecked() else tr('no')}</li>")
            if self._has_projects():
                o.append(f"<li>{tr('un_s2')}: {tr('pj_' + self.projects_choice())}</li>")
        o.append(f"<li>{'Не трогаются: GNS3, ваши шаблоны/образы/проекты вне папки VASYA, системные пакеты (кроме отмеченных ниже)' if ru else 'Untouched: GNS3, your own templates/images/projects outside the VASYA folder, system packages (except those ticked below)'}</li></ul>")
        self._fill_packages(o, ru)
        self.confirm_view.setHtml("".join(o))

    def _fill_packages(self, o, ru):
        """Offer only packages VASYA installed (were absent before) that nothing
        else installed depends on. Unticked by default; removal asks for the admin password."""
        for c in self.pkg_checks:
            c.setParent(None)
        self.pkg_checks = []
        if self.level() != "full":
            return
        try:
            off = api.system_packages_offer(self.backend.ctx())
        except Exception:
            off = {"removable": [], "kept": []}
        if off["removable"]:
            o.append(f"<p><b>{'Системные пакеты, установленные VASYA — можно удалить (нужен пароль администратора):' if ru else 'System packages VASYA installed — may be removed (admin password needed):'}</b></p>")
        for r in off["removable"]:
            c = QCheckBox(f"{r['package']}" + (f" ({r['for']})" if r.get("for") else ""))
            c.setProperty("pkg", r["package"]); self.pkg_box.addWidget(c); self.pkg_checks.append(c)
        if off["kept"]:
            o.append("<p><small>" + ("Остаются: " if ru else "Kept: ") + "; ".join(
                f"{h(k['package'])} — {h(k['why'])}" for k in off["kept"]) + "</small></p>")

    def chosen_packages(self):
        return [c.property("pkg") for c in self.pkg_checks if c.isChecked()]

    def uninstall(self, force=False):
        if not self.confirm(tr("un_confirm")):
            return
        level, docker, proj = self.level(), self.cb_docker.isChecked(), self.projects_choice()
        pk = self.chosen_packages() if level == "full" else []

        def fin(rep):
            self.report = rep
            self.goto(3)
            if rep.get("status") == "BLOCKED":
                self.report_view.setHtml(error_html(rep["error_ru"] if lang() == "ru" else rep["error"]) +
                                         "<ul>" + "".join(f"<li>{h(n['project'])}: {h(n['name'])}</li>" for n in rep.get("busy", [])) + "</ul>")
                self.b_stop.setVisible(True)
                self.b_back.setEnabled(True)
                return
            c = rep["residue"]["counts"]
            rows = "".join(f"<tr><td>{mark(v == 0)}</td><td>{k}</td><td><b>{v}</b></td></tr>" for k, v in c.items())
            extra = f"<p>{h(rep['projects_saved_to'])}</p>" if rep.get("projects_saved_to") else ""
            self.report_view.setHtml(f"<h2>{mark(rep['residue']['clean'])} CLEAN_UNINSTALL: "
                                     f"{'PASS' if rep['residue']['clean'] else 'FAIL'}</h2><table>{rows}</table>{extra}"
                                     f"<p><small>{h(rep['report_path'])}</small></p>")
            for k, v in c.items():
                self.log(f"{k}: {v}")
            self.log(f"CLEAN_UNINSTALL: {'PASS' if rep['residue']['clean'] else 'FAIL'}")
        self.run(lambda: api.uninstall(self.backend.ctx(), level, remove_docker=docker, projects=proj,
                                       force=force, system_packages=pk),
                 fin, buttons=[self.b_run, self.b_inv])

    def stop_nodes(self):
        def fin(stopped):
            self.log(f"{tr('stop_nodes')}: {', '.join(stopped)}")
            self.b_stop.setVisible(False)
            self.goto(2)
        self.run(lambda: api.stop_busy_nodes(self.backend.ctx()), fin, buttons=[self.b_stop])
