# SPDX-License-Identifier: GPL-3.0-or-later
from PySide6.QtWidgets import QPushButton, QLabel
from .base import Screen
from ..i18n import tr
from ... import api


class RepairScreen(Screen):
    title_key = "nav_repair"

    def build(self):
        l = QLabel("Проверка → карантин повреждённых файлов VASYA → повторная установка недостающего из "
                   "хранилища (без повторного копирования исправных образов). Ваши собственные файлы не трогаются."
                   if tr("yes") == "да" else
                   "Verify → quarantine damaged VASYA files → re-place missing items from the store. "
                   "Your own files are never touched.")
        l.setWordWrap(True); self.v.addWidget(l)
        self.b = QPushButton(tr("repair_btn")); self.b.clicked.connect(self.repair)
        self.v.addWidget(self.b)
        self.add_output()

    def repair(self):
        def fin(r):
            if r["status"] == "BLOCKED":
                self.show_error(r["error_ru"] if tr("yes") == "да" else r["error"]); return
            self.log(f"REPAIR {r['status']}  damaged_before={r['damaged_before']}  "
                     f"quarantined={len(r['quarantined'])}  failed_after={r['failed_after']}")
            for f in r.get("failed") or []:
                self.show_error(f["error"])
        self.out.clear()
        self.run(lambda: api.repair(self.backend.ctx(), progress=self.op_progress()), fin, buttons=[self.b])
