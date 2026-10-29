# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline bundle behaviour: bundled gns3server (no system GNS3 needed) and the
payload kept inside <root>/Store so the extracted bundle can be deleted."""
import os, shutil, sys
from pathlib import Path
import pytest
from conftest import have_gns3
from vasya import api
from vasya.core import txn as txnmod
from vasya.core.util import sha256_file
from vasya.gns3.client import GNS3Client
from vasya.runtime import bundled_server as bsrv

from conftest import GNS3RT


@have_gns3
def test_payload_adopted_into_root_bundle_can_be_deleted(tmp_path, payload):
    ctx = api.open_ctx(tmp_path / "root", payload)
    r = api.install(ctx, "FULL")
    assert r["status"] == "OK" and r["payload"]["adopted"], r.get("payload")
    store = (tmp_path / "root" / "Store").resolve()
    assert r["payload"]["payload_root"] == str(store) and r["payload"]["link"] >= 1
    shutil.rmtree(payload)  # user deletes the extracted bundle
    ctx2 = api.open_ctx(tmp_path / "root")
    assert Path(ctx2.payload_root).resolve() == store
    assert api.static_verify(ctx2)["status"] == "PASS"
    f = next(x for x in txnmod.owned_resources(ctx2.layout) if x.get("role") == "image")
    Path(f["path"]).unlink()
    rep = api.repair(ctx2)
    assert rep["status"] == "OK" and sha256_file(f["path"]) == f["sha256"]
    api.uninstall(ctx2, "full", report_dir=tmp_path)
    assert not (tmp_path / "root").exists()


@pytest.mark.skipif(not (GNS3RT / bsrv.tag()).exists(), reason="bundled gns3server build not present")
def test_bundled_gns3server_used_when_none_installed(tmp_path, payload, monkeypatch):
    bundle = tmp_path / "bundle"
    rt = bundle / "App" / "runtime" / "gns3server" / bsrv.tag()
    shutil.copytree(GNS3RT / bsrv.tag(), rt, copy_function=os.link)
    bsrv.write_launcher(bundle / "App")
    monkeypatch.setenv("VASYA_BUNDLE_DIR", str(bundle))
    monkeypatch.delenv("VASYA_GNS3SERVER_BIN", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep)
                                               if not (Path(p) / "gns3server").exists()))
    root = tmp_path / "root"
    ctx = api.open_ctx(root, payload)
    plan = api.plan(ctx, "FULL")
    acts = [o["action"] for o in plan["operations"]]
    assert acts.index("INSTALL_APP") < acts.index("MANAGED_GNS3")
    assert plan["preview"]["server_bundled"]
    gs = next(p for p in plan["preview"]["programs"] if p["id"] == "gns3server")
    assert gs["present"] and "bundled" in gs["path"]
    r = api.install(ctx, "FULL")
    try:
        assert r["status"] == "OK", r.get("failed")
        st = ctx.state.load()["gns3"]
        assert st["server_bin"] == str(bsrv.launcher(root.resolve() / "App"))
        v = GNS3Client(st["api_base"]).version(timeout=5)
        assert "2.2.61" in str(v)
        from vasya.runtime import managed_server as ms
        pid = ms.running_pid(ctx.layout)
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        assert str(bsrv.launcher(root.resolve() / "App")) in cmd, cmd
        assert api.static_verify(ctx)["status"] == "PASS"
    finally:
        api.uninstall(ctx, "full", report_dir=tmp_path)
    assert not root.exists()
