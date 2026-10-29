# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated GNS3 GUI profile: Wireshark reader command set as on a tested install; never ~/.config/GNS3."""
import json
from types import SimpleNamespace
from vasya.runtime import gui_profile as gp

WIRESHARK_READER = ('tail -f -c +0b {pcap_file} | /usr/bin/wireshark -o '
              '"gui.window_title:{project} {link_description}" -k -i -')


def _lay(tmp_path):
    return SimpleNamespace(managed_gns3=tmp_path / "ROOT" / "Runtime" / "gns3")


def test_profile_matches_tested_and_keeps_user_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    lay = _lay(tmp_path)
    p = gp.conf_path(lay); p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"GraphicsView": {"grid_size": 75}, "MainWindow": {"recent_projects": ["x"]}}))
    which = {"wireshark": "/usr/bin/wireshark", "vncviewer": "/usr/bin/vncviewer"}.get
    r = gp.write_profile(lay, which=which, vpcs="/R/Runtime/bin/vpcs")
    d = json.loads(p.read_text())
    assert d["PacketCapture"]["packet_capture_reader_command"] == WIRESHARK_READER
    assert d["MainWindow"]["vnc_console_command"] == "/usr/bin/vncviewer {host}:{port}"
    assert d["VPCS"]["vpcs_path"] == "/R/Runtime/bin/vpcs"
    assert d["GraphicsView"] == {"grid_size": 75} and d["MainWindow"]["recent_projects"] == ["x"]
    assert "PacketCapture.packet_capture_reader_command" in r["set"]
    assert gp.write_profile(lay, which=which, vpcs="/R/Runtime/bin/vpcs")["set"] == []   # idempotent
    assert not (tmp_path / "home" / ".config" / "GNS3").exists()
    env = gp.gui_env(lay, {})
    assert env["XDG_CONFIG_HOME"].startswith(str(lay.managed_gns3))


def test_no_wireshark_no_capture_section(tmp_path):
    lay = _lay(tmp_path)
    gp.write_profile(lay, which=lambda n: None)
    assert "PacketCapture" not in json.loads(gp.conf_path(lay).read_text())


def _lay2(tmp_path):
    return SimpleNamespace(managed_gns3=tmp_path / "ROOT" / "Runtime" / "gns3", State=tmp_path / "ROOT" / "State")


def test_vnc_side_effect_recorded_and_reported_not_deleted(tmp_path):
    from vasya.core import side_effects as se
    from vasya.uninstall.residue import render
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    lay = _lay2(tmp_path)
    gp.write_profile(lay, which={"vncviewer": "/usr/bin/vncviewer"}.get, home=home)
    it = json.loads(se.receipt_path(lay).read_text())["items"][0]
    assert it["path"] == str(home / ".vnc") and it["preexisting"] is False
    assert se.report(lay) == []                       # nothing to say until vncviewer ran
    (home / ".vnc").mkdir(); (home / ".vnc" / "default.tigervnc").write_text("x")
    gp.write_profile(lay, which={"vncviewer": "/usr/bin/vncviewer"}.get, home=home)   # first record wins
    rep = se.report(lay)
    assert len(rep) == 1 and rep[0]["preexisting"] is False and "rm -r" in rep[0]["suggestion"]
    md = render({"level": "full", "root": "R", "started_at": "", "inventory_count": 0, "removed": 0,
                 "absent": 0, "kept": 0, "external_side_effects": rep,
                 "residue": {"counts": {k: 0 for k in ("VASYA_FILES_LEFT", "TEMPLATES_LEFT", "VM_LEFT",
                             "DOCKER_OBJECTS_LEFT", "SHORTCUTS_LEFT", "SYSTEM_CHANGES_LEFT")},
                             "items": {}, "clean": True}})
    assert ".vnc" in md and "not deleted" in md
    assert (home / ".vnc").exists()


def test_preexisting_vnc_dir_is_not_claimed(tmp_path):
    from vasya.core import side_effects as se
    home = tmp_path / "home"; (home / ".vnc").mkdir(parents=True, exist_ok=True)
    lay = _lay2(tmp_path)
    se.record(lay, "vncviewer", home)
    assert se.report(lay)[0]["suggestion"] == "existed before VASYA; not ours"
