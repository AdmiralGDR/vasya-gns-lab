#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render every screen offscreen (light/dark, RU/EN, 2x HiDPI) for docs/evidence.
usage: QT_QPA_PLATFORM=offscreen screenshots.py ROOT PAYLOAD OUTDIR"""
import os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root, payload, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
from PySide6.QtWidgets import QApplication
app = QApplication([])
from vasya.gui.app import MainWindow, Backend, apply_theme
from vasya.gui import i18n, workers
for lang in ("ru", "en"):
    for theme in ("light", "dark"):
        os.environ["VASYA_THEME"] = theme; i18n.set_lang(lang); apply_theme(app)
        w = MainWindow(Backend(root, payload)); w.resize(1180, 760); w.show()
        for k in w.screens:
            w.go(k); workers.wait_all(120000)
            for _ in range(5):
                app.processEvents()
            w.grab().save(str(out / f"{lang}-{theme}-{k}.png"))
        w.close()
print("ok", len(list(out.glob("*.png"))))
