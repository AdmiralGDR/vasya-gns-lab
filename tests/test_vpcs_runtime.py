# SPDX-License-Identifier: GPL-3.0-or-later
"""VPCS for the managed server: system vpcs preferred; else the pinned VPCS 0.8.5 package build is
downloaded, verified and placed with a receipt. The integration test starts a VPCS node on VASYA's
own gns3server 2.2.61 and reads its telnet console."""
import hashlib, json, os, socket, time
import pytest
from conftest import have_gns3, _teardown_root, env_path
from vasya import api
from vasya.runtime import gui_deps

STAGE = env_path("VASYA_TEST_STAGE", "Payload")
NETWORK = os.environ.get("VASYA_TEST_NETWORK") == "1"


def test_ensure_vpcs_prefers_system_then_places_with_receipt(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "vpcs").write_bytes(b"#!/bin/sh\necho VPCS\n")
    c = api.open_ctx(tmp_path / "R", None)
    r = gui_deps.ensure_vpcs(c, src_dir=src, which=lambda n: "/usr/bin/vpcs")
    assert r == {"status": "OK", "path": "/usr/bin/vpcs", "source": "system"}
    assert not (c.layout.root / "Runtime" / "bin" / "vpcs").exists()
    r = gui_deps.ensure_vpcs(c, src_dir=src, which=lambda n: None)
    dst = c.layout.root / "Runtime" / "bin" / "vpcs"
    assert r["status"] == "OK" and r["path"] == str(dst) and dst.stat().st_mode & 0o111
    rec = json.loads(gui_deps.receipt_path(c).read_text())
    assert rec["files"][str(dst)]["sha256"] == hashlib.sha256((src / "vpcs").read_bytes()).hexdigest()
    assert gui_deps.ensure_vpcs(c, src_dir=src, which=lambda n: None)["reused"] is True
    out = gui_deps.remove_owned(c)
    assert str(dst) in out["removed"] and not dst.exists()


def test_foreign_vpcs_at_target_is_conflict(tmp_path):
    c = api.open_ctx(tmp_path / "R", None)
    d = c.layout.root / "Runtime" / "bin"; d.mkdir(parents=True)
    (d / "vpcs").write_text("not ours")
    src = tmp_path / "src"; src.mkdir()
    (src / "vpcs").write_bytes(b"#!/bin/sh\n")
    r = gui_deps.ensure_vpcs(c, src_dir=src, which=lambda n: None)
    assert r["status"] == "CONFLICT" and (d / "vpcs").read_text() == "not ours"


def test_offline_without_system_vpcs_is_blocked_not_failed(tmp_path):
    c = api.open_ctx(tmp_path / "R", None)
    r = gui_deps.ensure_vpcs(c, which=lambda n: None)
    assert r["status"] == "BLOCKED" and r["source"] == "vasya-fetched"
    assert not (c.layout.root / "Runtime" / "bin" / "vpcs").exists()


@pytest.mark.skipif(not STAGE or not (STAGE / "manifests").exists(), reason="set VASYA_TEST_STAGE to a staged bundle")
@pytest.mark.skipif(not NETWORK, reason="downloads the pinned VPCS package (set VASYA_TEST_NETWORK=1)")
@have_gns3
def test_vpcs_node_on_managed_server(tmp_path, monkeypatch):
    from vasya.gns3.client import GNS3Client
    from vasya.installer.target import resolve_target
    monkeypatch.setattr(gui_deps, "_which", lambda n: None)  # force the downloaded binary
    monkeypatch.setenv("VASYA_OFFLINE", "0")
    root = tmp_path / "ROOT"
    c = api.open_ctx(root, STAGE)
    try:
        r = api.install(c, "FULL", block_ids=["puppy-linux"])
        assert r["status"] == "OK", r.get("failed")
        conf = (root / "GNS3" / "gns3_server.conf").read_text()
        vp = str(root / "Runtime" / "bin" / "vpcs")
        assert f"vpcs_path = {vp}" in conf
        t = resolve_target(c, c.state.load().get("mode"), start=True)
        cl = GNS3Client(t["api_base"], timeout=60)
        pid = cl.create_project(f"vasya-vpcs-{int(time.time())}")["project_id"]
        try:
            n = cl.post(f"/v2/projects/{pid}/nodes", {"name": "PC1", "node_type": "vpcs", "compute_id": "local"})
            cl.node_action(pid, n["node_id"], "start")
            n = cl.get(f"/v2/projects/{pid}/nodes/{n['node_id']}")
            assert n["status"] == "started"
            time.sleep(1)
            with socket.create_connection(("127.0.0.1", n["console"]), timeout=5) as s:
                s.settimeout(5); s.sendall(b"\r\nshow ip\r\n"); time.sleep(1.5)
                data = b""
                try:
                    while len(data) < 4096:
                        b = s.recv(4096)
                        if not b:
                            break
                        data += b
                except socket.timeout:
                    pass
            txt = data.decode(errors="replace")
            assert "PC1" in txt or "VPCS" in txt, txt
            (tmp_path / "vpcs-console.txt").write_text(
                f"{time.strftime('%Y-%m-%d %H:%M %Z')}: managed gns3server, vpcs_path={vp}\n"
                f"node status={n['status']} console=telnet:{n['console']}\n---\n{txt}\n")
            cl.node_action(pid, n["node_id"], "stop")
        finally:
            cl.delete_project(pid)
    finally:
        _teardown_root(root, STAGE)
