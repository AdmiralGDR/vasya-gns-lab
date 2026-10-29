# SPDX-License-Identifier: GPL-3.0-or-later
"""Common screen scaffolding: title, busy state, output pane, task runner."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
                               QMessageBox, QFrame)
from .. import workers
from ..i18n import tr


class Screen(QWidget):
    title_key = ""

    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.main = None
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(24, 18, 24, 18)
        self.v.setSpacing(10)
        self.title = QLabel(tr(self.title_key))
        f = QFont(); f.setPointSizeF(f.pointSizeF() * 1.6); f.setBold(True)
        self.title.setFont(f)
        self.title.setAccessibleName("screen-title")
        self.v.addWidget(self.title)
        self.last_result = None
        self.last_error = None
        self.task = None
        self.build()

    def build(self):
        pass

    def add_output(self, height=None):
        self.bar = QProgressBar(); self.bar.setVisible(False); self.bar.setTextVisible(True)
        self.out = QPlainTextEdit(); self.out.setReadOnly(True)
        self.out.setAccessibleName("output")
        if height:
            self.out.setMaximumHeight(height)
        self.v.addWidget(self.bar)
        self.v.addWidget(self.out, 1)

    def log(self, line):
        self.out.appendPlainText(str(line))

    def separator(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine); f.setFrameShadow(QFrame.Sunken)
        self.v.addWidget(f)

    def run(self, fn, on_done, *args, progress=True, buttons=(), **kw):
        """Run backend fn(*args, **kw) in a worker; disable `buttons` meanwhile."""
        for b in buttons:
            b.setEnabled(False)
        if hasattr(self, "bar"):
            self.bar.setVisible(True); self.bar.setRange(0, 0); self.bar.setFormat(tr("busy"))
        t = workers.Task(fn, *args, **kw)
        self.task = t

        import shiboken6

        def alive():
            return shiboken6.isValid(self) and all(shiboken6.isValid(b) for b in buttons)

        def done(r):
            if not alive():
                return
            self.last_result, self.last_error = r, None
            for b in buttons:
                b.setEnabled(True)
            if hasattr(self, "bar"):
                self.bar.setRange(0, 1); self.bar.setValue(1); self.bar.setFormat(tr("done"))
                if getattr(self, "auto_hide_bar", False):
                    self.bar.setVisible(False)
            on_done(r)

        def fail(msg):
            if not alive():
                return
            self.last_error, self.last_result = msg, None
            for b in buttons:
                b.setEnabled(True)
            if hasattr(self, "bar"):
                self.bar.setVisible(False)
            if hasattr(self, "out"):
                self.show_error(msg.splitlines()[0] if msg else msg)
                self.log(f"({tr('details')}: {msg.strip().splitlines()[-1][:300]})")

        def prog(i, n, a, b):
            if not alive():
                return
            human = a.startswith("[")
            if hasattr(self, "bar") and n:
                self.bar.setRange(0, n); self.bar.setValue(i if b != "RUNNING" else max(0, i - 1))
                self.bar.setFormat(a if human else f"{i}/{n} {a}")
            if hasattr(self, "cur_lbl"):
                self.cur_lbl.setText(a)
            if hasattr(self, "out") and b != "RUNNING":
                self.log(a if human else f"[{i}/{n}] {a} {b}")
        workers.start(t, done, fail, prog)
        return t

    def op_progress(self):
        """Progress callback for installer/repair: one human sentence per step."""
        from ...installer.progress_text import describe
        from ..i18n import lang
        task = self.task

        def cb(i, n, op, res):
            task.emit_progress(i, n, describe(i, n, op, res, lang(), op.get("last_error")), res)
        cb.wants_start = True
        return cb

    def show_error(self, err):
        """Human-readable error card in the output pane (never a raw traceback only)."""
        from ...errors import explain, render
        from ..i18n import lang
        e = err if isinstance(err, dict) and "title" in err else explain(err, lang())
        if hasattr(self, "out"):
            self.log(render(e))
        return e

    def confirm(self, text):
        if getattr(self.main, "auto_confirm", False):
            return True
        return QMessageBox.question(self, tr("app_title"), text) == QMessageBox.Yes
