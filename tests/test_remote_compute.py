# SPDX-License-Identifier: GPL-3.0-or-later
"""GNS3 VM backend (Windows path) exercised on Linux with a real remote compute:
controller gns3server + a second gns3server registered as compute 'remote-vm'.
Same API calls the GNS3 VM gets; a real GNS3 VM on Windows stays UNVERIFIED."""
import os, time
from pathlib import Path
import pytest
from conftest import have_gns3, make_payload
from vasya import api
from vasya.gns3.client import GNS3Client
from vasya.gns3 import remote_compute as rc
from vasya.runtime import managed_server as ms
from vasya.core.layout import Layout


@pytest.fixture
def two_servers(tmp_path):
    ctl, vm = Layout(tmp_path / "ctl").ensure(), Layout(tmp_path / "vm").ensure()
    pc, pv = ms.free_port(3170), ms.free_port(3190)
    ms.write_config(ctl, pc); ms.write_config(vm, pv)
    ms.start(ctl, os.environ["VASYA_GNS3SERVER_BIN"], pc)
    ms.start(vm, os.environ["VASYA_GNS3SERVER_BIN"], pv)
    cl = GNS3Client(f"http://127.0.0.1:{pc}")
    cl.post("/v2/computes", {"compute_id": "remote-vm", "name": "remote-vm", "protocol": "http",
                             "host": "127.0.0.1", "port": pv})
    for _ in range(50):
        if any(c["compute_id"] == "remote-vm" and c.get("connected") for c in rc.computes(cl)):
            break
        time.sleep(0.2)
    try:
        yield cl, ms.paths(ctl)["images_path"], ms.paths(vm)["images_path"]
    finally:
        ms.stop(ctl); ms.stop(vm)


def _files(d):
    return sorted(str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file() and p.name.startswith(("t-", "vasya-")) and not p.name.endswith(".md5sum"))


@have_gns3
def test_install_uploads_to_compute_then_reuses_and_uninstall_lists_manual_steps(tmp_path, two_servers):
    cl, ctl_images, vm_images = two_servers
    payload = make_payload(tmp_path / "payload", docker=True, dyn_elf=True)
    ctx = api.open_ctx(tmp_path / "root", payload)
    tgt = {"api_base": cl.base, "compute_id": "remote-vm"}
    r = api.install(ctx, "INTEGRATION", explicit_target=tgt)
    assert r["status"] == "OK", r.get("failed")
    assert _files(ctl_images) == []                       # nothing placed on the host side
    assert set(_files(vm_images)) == {"QEMU/t-disk0.qcow2", "QEMU/t-disk1.qcow2", "QEMU/t-disk2.qcow2",
                                      "IOS/t-ios.image"}
    ours = [t for t in cl.templates() if "[VASYA GNS LAB]" in (t.get("usage") or "")]
    assert len(ours) == 4 and {t["compute_id"] for t in ours} == {"remote-vm"}
    dk = next(t for t in ours if t["template_type"] == "docker")
    assert dk["image"] == "alpine:latest"                  # pulled by the VM itself
    # second run: identical images detected by md5 on the compute -> nothing uploaded again
    ctx2 = api.open_ctx(tmp_path / "root", payload)
    r2 = api.install(ctx2, "INTEGRATION", explicit_target=tgt)
    assert r2["status"] == "OK"
    assert "UPLOAD_IMAGE" not in str(r2)
    rep = api.uninstall(ctx2, "full", report_dir=tmp_path)
    assert not [t for t in cl.templates() if "[VASYA GNS LAB]" in (t.get("usage") or "")]
    assert rep["residue"]["clean"], rep["residue"]
    steps = rep["manual_remote_steps"]
    assert len(steps) == 4 and all("/opt/gns3/images/" in s and "remote-vm" in s for s in steps)


@have_gns3
def test_conflicting_file_on_compute_is_never_overwritten(tmp_path, two_servers):
    cl, _, vm_images = two_servers
    payload = make_payload(tmp_path / "payload", dyn_elf=True)
    (Path(vm_images) / "QEMU").mkdir(parents=True, exist_ok=True)
    mine = Path(vm_images) / "QEMU" / "t-disk0.qcow2"
    mine.write_bytes(b"user's own different image")
    ctx = api.open_ctx(tmp_path / "root", payload)
    r = api.install(ctx, "INTEGRATION", explicit_target={"api_base": cl.base, "compute_id": "remote-vm"})
    assert r["status"] == "OK", r.get("failed")
    assert mine.read_bytes() == b"user's own different image"
    alts = [p.name for p in (Path(vm_images) / "QEMU").iterdir() if p.name.startswith("vasya-")
            and p.name.endswith("t-disk0.qcow2")]
    assert len(alts) == 1
    t = next(t for t in cl.templates() if t["name"] == "VASYA Test QEMU 0")
    assert t["hda_disk_image"] == alts[0]
    api.uninstall(ctx, "full", report_dir=tmp_path)


@have_gns3
def test_unknown_or_auto_compute_selection(tmp_path, two_servers):
    cl, _, _ = two_servers
    assert rc.pick("linux", cl, "auto") == "local"
    assert rc.pick("windows", cl, "auto") == "local"        # no 'vm' compute registered here
    assert rc.pick("windows", cl, "remote-vm") == "remote-vm"
    with pytest.raises(rc.ComputeError):
        rc.pick("windows", cl, "vm")
