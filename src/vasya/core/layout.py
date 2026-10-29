# SPDX-License-Identifier: GPL-3.0-or-later
"""ONE-ROOT layout: everything VASYA owns lives under a single root directory."""
import os
from pathlib import Path

SUBDIRS = ("App", "Store", "GNS3", "State", "State/txn", "State/receipts", "Logs",
           "Reports", "Demos", "Desktop", "Cache", "Imports")


class Layout:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def __getattr__(self, name):  # convenience: layout.State, layout.Logs ...
        if name in ("App", "Store", "GNS3", "State", "Logs", "Reports", "Demos",
                    "Desktop", "Cache", "Imports"):
            return self.root / name
        raise AttributeError(name)

    @property
    def txn_dir(self):
        return self.root / "State" / "txn"

    @property
    def receipts_dir(self):
        return self.root / "State" / "receipts"

    @property
    def state_file(self):
        return self.root / "State" / "state.json"

    @property
    def lock_file(self):
        return self.root / "State" / "vasya.lock"

    @property
    def user_store(self):
        """CAS for user-imported images (never shipped)."""
        return self.root / "Store" / "user" / "sha256"

    @property
    def managed_gns3(self):
        return self.root / "GNS3"

    def ensure(self):
        for s in SUBDIRS:
            (self.root / s).mkdir(parents=True, exist_ok=True)
        return self

    def exists(self):
        return self.state_file.exists()


def default_root(platform_name=None):
    env = os.environ.get("VASYA_ROOT")
    if env:
        return Path(env).expanduser()
    if (platform_name or os.name) in ("nt", "windows"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "VASYA-GNS-LAB"
    return Path.home() / "VASYA-GNS-LAB"
