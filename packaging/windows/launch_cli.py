# SPDX-License-Identifier: GPL-3.0-or-later
"""VASYA GNS LAB command line for the Windows Setup.exe install: python launch_cli.py <command>."""
import os, sys
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.dont_write_bytecode = True
for p in (str(APP / "site-packages"), str(APP)):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("VASYA_ROOT", str(ROOT))
if __name__ == "__main__":
    from vasya.cli import main
    sys.exit(main(["--root", str(ROOT)] + sys.argv[1:]))
