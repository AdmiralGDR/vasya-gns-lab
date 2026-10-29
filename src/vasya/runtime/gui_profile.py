# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated GNS3 GUI profile (gns3_gui.conf) next to VASYA's managed server.

Mirrors what was configured by hand on a tested install: the GNS3 GUI started by VASYA uses
XDG_CONFIG_HOME=<root>/.../xdg/config, so ~/.config/GNS3 is never created or changed. VASYA sets only
the keys below and keeps everything else the user (or the GUI) wrote there.
"""
import json, os, shutil
from pathlib import Path

GUI_VERSION = "2.2.61"
# exactly the reader command tested on a real install (Wireshark started on the live pcap of a link)
WIRESHARK_READER = 'tail -f -c +0b {{pcap_file}} | {ws} -o "gui.window_title:{{project}} {{link_description}}" -k -i -'


def xdg_root(layout):
    return layout.managed_gns3 / "xdg"


def conf_path(layout):
    return xdg_root(layout) / "config" / "GNS3" / "2.2" / "gns3_gui.conf"


def gui_env(layout, base=None):
    env = dict(base if base is not None else os.environ)
    for k, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                   ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        env[k] = str(xdg_root(layout) / sub)
    return env


def wanted(which=shutil.which, vpcs=None):
    ws = which("wireshark")
    out = {"MainWindow": {"hide_setup_wizard": True, "hide_getting_started_dialog": True,
                          "check_for_update": False}}
    if ws:
        out["PacketCapture"] = {"command_auto_start": True, "packet_capture_analyzer_command": "",
                                "packet_capture_reader_command": WIRESHARK_READER.format(ws=ws)}
    vv = which("vncviewer")
    if vv:
        out["MainWindow"]["vnc_console_command"] = f"{vv} {{host}}:{{port}}"
    if vpcs:
        out["VPCS"] = {"vpcs_path": str(vpcs)}
    return out


def write_profile(layout, which=shutil.which, vpcs=None, home=None):
    """Merge VASYA's keys into the isolated gns3_gui.conf; returns {"path", "set": [section.key]}."""
    p = conf_path(layout)
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        cur = {}
        p.replace(p.with_name(p.name + ".corrupt"))   # keep the user's bytes, start clean
    cur.setdefault("type", "settings"); cur.setdefault("version", GUI_VERSION)
    changed = []
    for sec, kv in wanted(which, vpcs).items():
        s = cur.setdefault(sec, {})
        for k, v in kv.items():
            if s.get(k) != v:
                s[k] = v; changed.append(f"{sec}.{k}")
    if "vnc_console_command" in cur.get("MainWindow", {}) and hasattr(layout, "State"):
        from ..core import side_effects
        side_effects.record(layout, "vncviewer", home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(cur, indent=4, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)
    return {"path": str(p), "set": changed}
