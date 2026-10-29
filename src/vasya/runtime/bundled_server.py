# SPDX-License-Identifier: GPL-3.0-or-later
"""Bundled GNS3 server 2.2.61: pre-installed pure site-packages per CPython minor
version under App/runtime/gns3server/pyXY (built offline by scripts/build_bundle.py).
Lives inside <root>/App after INSTALL_APP, so it is removed with the VASYA folder
and never touches system Python or apt."""
import sys
from pathlib import Path

GNS3_VERSION = "2.2.61"
LAUNCHER = """#!/usr/bin/env python3
# VASYA GNS LAB: bundled gns3server %s (selects the build matching this python)
import os, sys
here = os.path.dirname(os.path.realpath(__file__))
d = os.path.join(here, "..", "runtime", "gns3server", "py%%d%%d" %% sys.version_info[:2])
if not os.path.isdir(d):
    sys.stderr.write("VASYA: no bundled gns3server for python %%d.%%d\\n" %% sys.version_info[:2])
    sys.exit(3)
sys.path.insert(0, os.path.abspath(d))
from gns3server.main import main
sys.exit(main())
""" % GNS3_VERSION


def tag(vi=None):
    vi = vi or sys.version_info
    return f"py{vi[0]}{vi[1]}"


def available(app_dir):
    """Path of the runtime for the current python inside app_dir, or None."""
    if not app_dir:
        return None
    d = Path(app_dir) / "runtime" / "gns3server" / tag()
    return d if (d / "gns3server" / "main.py").exists() else None


def launcher(app_dir):
    return Path(app_dir) / "bin" / "gns3server"


def write_launcher(app_dir):
    p = launcher(app_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(LAUNCHER)
    p.chmod(0o755)
    return p
