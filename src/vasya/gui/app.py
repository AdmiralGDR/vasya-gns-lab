# SPDX-License-Identifier: GPL-3.0-or-later
"""VASYA GNS LAB Manager — PySide6 GUI entry point."""
import os, sys
from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QPalette, QColor, QGuiApplication
from PySide6.QtWidgets import (QApplication, QMainWindow, QListWidget, QListWidgetItem,
                               QStackedWidget, QWidget, QHBoxLayout)
from .. import api, VERSION
from ..core.layout import default_root
from .i18n import tr

ICON = Path(__file__).resolve().parent.parent / "data" / "icons" / "vasya-gns-lab.svg"


class Backend:
    """Thin holder for root/payload; every screen calls vasya.api through it."""

    def __init__(self, root=None, payload=None):
        self.root = Path(root or default_root())
        self.payload = payload

    def ctx(self):
        return api.open_ctx(self.root, self.payload)


def apply_theme(app):
    """Follow the system light/dark preference (Qt >= 6.5 colorScheme)."""
    app.setStyle("Fusion")
    dark = False
    try:
        dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        pass
    if os.environ.get("VASYA_THEME") in ("dark", "light"):
        dark = os.environ["VASYA_THEME"] == "dark"
    if not dark:
        app.setPalette(app.style().standardPalette())  # reset after a dark session
    if dark:
        p = QPalette()
        for role, c in ((QPalette.Window, "#1f2227"), (QPalette.WindowText, "#e6e6e6"),
                        (QPalette.Base, "#16181c"), (QPalette.AlternateBase, "#24272d"),
                        (QPalette.Text, "#e6e6e6"), (QPalette.Button, "#2a2e35"),
                        (QPalette.ButtonText, "#e6e6e6"), (QPalette.Highlight, "#2f6fdf"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#2a2e35"),
                        (QPalette.ToolTipText, "#e6e6e6"), (QPalette.PlaceholderText, "#8a8f98")):
            p.setColor(role, QColor(c))
        app.setPalette(p)
    app.setProperty("vasya_dark", dark)
    accent = "#2f6fdf"
    app.setStyleSheet(f"""
        QListWidget#nav {{ border: none; padding-top: 12px; font-size: 11pt; }}
        QListWidget#nav::item {{ padding: 9px 14px; border-radius: 6px; margin: 1px 8px; }}
        QListWidget#nav::item:selected {{ background: {accent}; color: white; }}
        QGroupBox {{ font-weight: bold; border: 1px solid palette(mid); border-radius: 8px;
                     margin-top: 14px; padding: 10px 8px 8px 8px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        QPushButton {{ padding: 6px 14px; border-radius: 6px; }}
        QPushButton:default {{ background: {accent}; color: white; }}
    """)
    return dark


class MainWindow(QMainWindow):
    def __init__(self, backend):
        super().__init__()
        from .screens import (home, install_wizard, catalog, verify, repair, uninstall, logs,
                              diagnostics, tools, firstrun)
        self.backend = backend
        self.setWindowTitle(f"{tr('app_title')} {VERSION}")
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1180, 760)
        self.nav = QListWidget()
        self.nav.setFixedWidth(220)
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setAccessibleName("navigation")
        self.stack = QStackedWidget()
        self.screens = {}
        specs = [("home", "nav_home", home.HomeScreen), ("install", "nav_install", install_wizard.InstallWizard),
                 ("catalog", "nav_catalog", catalog.CatalogScreen), ("verify", "nav_verify", verify.VerifyScreen),
                 ("repair", "nav_repair", repair.RepairScreen), ("uninstall", "nav_uninstall", uninstall.UninstallScreen),
                 ("logs", "nav_logs", logs.LogsScreen), ("diagnostics", "nav_diag", diagnostics.DiagnosticsScreen),
                 ("tools", "nav_tools", tools.ToolsScreen), ("ready", "nav_ready", firstrun.FirstRunScreen)]
        for i, (key, label, cls) in enumerate(specs):
            w = cls(backend)
            w.main = self
            self.screens[key] = w
            self.stack.addWidget(w)
            it = QListWidgetItem(f"{tr(label)}")
            it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
            QShortcut(QKeySequence(f"Alt+{(i + 1) % 10}"), self, activated=lambda k=key: self.go(k))
        self.nav.currentRowChanged.connect(self._row)
        c = QWidget(); lay = QHBoxLayout(c); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.nav); lay.addWidget(self.stack, 1)
        self.setCentralWidget(c)
        self.nav.setCurrentRow(0)

    def _row(self, r):
        self.stack.setCurrentIndex(r)
        w = self.stack.currentWidget()
        if hasattr(w, "on_show"):
            w.on_show()

    def go(self, key):
        keys = list(self.screens)
        self.nav.setCurrentRow(keys.index(key))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="vasya-gns-manager")
    ap.add_argument("--root"); ap.add_argument("--payload"); ap.add_argument("--lang", choices=["ru", "en"])
    ap.add_argument("--screen", default=None)
    a, rest = ap.parse_known_args(argv)
    if a.lang:
        from . import i18n
        i18n.set_lang(a.lang)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication([sys.argv[0]] + rest)
    app.setApplicationName("vasya-gns-manager")
    app.setDesktopFileName("vasya-gns-lab")
    app.setWindowIcon(QIcon(str(ICON)))
    apply_theme(app)
    w = MainWindow(Backend(a.root, a.payload))
    st = w.backend.ctx().state.load()
    if a.screen:
        w.go(a.screen)
    elif st["components"] and not st.get("first_run_done"):
        w.go("ready")
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
