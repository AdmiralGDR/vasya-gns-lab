# SPDX-License-Identifier: GPL-3.0-or-later
"""Run backend calls off the UI thread; results come back as Qt signals."""
import threading, traceback
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Sig(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str, str)


class Task(QRunnable):
    def __init__(self, fn, *args, **kw):
        super().__init__()
        self.fn, self.args, self.kw = fn, args, kw
        self.sig = _Sig()
        self.cancel = threading.Event()
        self.setAutoDelete(False)

    def emit_progress(self, i, n, a, b):
        self.sig.progress.emit(int(i), int(n), str(a), str(b))

    @Slot()
    def run(self):
        try:
            r = self.fn(*self.args, **self.kw)
            self.sig.done.emit(r)
        except Exception as e:
            self.sig.failed.emit(f"{e}\n{traceback.format_exc(limit=4)}")


_running = []


def start(task, on_done=None, on_fail=None, on_progress=None):
    if on_done:
        task.sig.done.connect(on_done)
    if on_fail:
        task.sig.failed.connect(on_fail)
    if on_progress:
        task.sig.progress.connect(on_progress)
    _running.append(task)
    task.sig.done.connect(lambda *_: _running.remove(task) if task in _running else None)
    task.sig.failed.connect(lambda *_: _running.remove(task) if task in _running else None)
    QThreadPool.globalInstance().start(task)
    return task


def wait_all(ms=600000):
    return QThreadPool.globalInstance().waitForDone(ms)
