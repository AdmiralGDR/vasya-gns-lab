# SPDX-License-Identifier: GPL-3.0-or-later
"""Known side effects OUTSIDE the VASYA folder caused by tools VASYA configures (not by VASYA's own
code). Recorded with a preexisting flag when VASYA wires the tool up, and listed in the uninstall
report. Never deleted automatically: the directory may hold the user's own data later on.

Found on a test install: TigerVNC vncviewer (set as the GNS3 GUI VNC console command) creates ~/.vnc on first run.
"""
from pathlib import Path
from .util import load_json, write_json, utc_now

KNOWN = {"vncviewer": {"path": "~/.vnc",
                       "why": "TigerVNC vncviewer creates ~/.vnc (default.tigervnc, x509 store) on first use"}}


def receipt_path(layout):
    return layout.State / "receipts" / "external-side-effects.json"


def record(layout, tool, home=None):
    """Call when VASYA configures `tool`. First record wins (keeps the original preexisting flag)."""
    k = KNOWN.get(tool)
    if not k:
        return None
    p = Path(k["path"].replace("~", str(home or Path.home()), 1))
    rec = load_json(receipt_path(layout), {"items": []})
    for it in rec["items"]:
        if it["tool"] == tool and it["path"] == str(p):
            return it
    it = {"tool": tool, "path": str(p), "preexisting": p.exists(), "why": k["why"], "recorded_at": utc_now()}
    rec["items"].append(it)
    receipt_path(layout).parent.mkdir(parents=True, exist_ok=True)
    write_json(receipt_path(layout), rec)
    return it


def report(layout):
    """[{path, exists, preexisting, why, suggestion}] for the uninstall report."""
    out = []
    for it in load_json(receipt_path(layout), {"items": []})["items"]:
        p = Path(it["path"])
        if not p.exists():
            continue
        out.append(dict(it, exists=True, suggestion=(
            f"created after VASYA set up {it['tool']}; remove it yourself if you do not use "
            f"{it['tool']} elsewhere: rm -r {p}") if not it["preexisting"] else "existed before VASYA; not ours"))
    return out
