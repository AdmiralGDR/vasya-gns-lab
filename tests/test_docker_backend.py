# SPDX-License-Identifier: GPL-3.0-or-later
"""Docker backend selection: Linux default = rootless podman, Windows = GNS3 VM (UNVERIFIED,
never podman), shared daemon only on explicit choice; missing prerequisites block docker components only."""
from vasya import api
from vasya.runtime import docker_backend as dbk
from conftest import make_payload


def test_linux_default_is_podman_and_missing_podman_blocks_docker_only(tmp_path, monkeypatch):
    monkeypatch.delenv("VASYA_DOCKER_BACKEND", raising=False)
    monkeypatch.delenv("VASYA_PODMAN_GO", raising=False)        # the old opt-in gate is gone
    pl = make_payload(tmp_path / "p", docker=True)
    ctx = api.open_ctx(tmp_path / "R", pl)
    assert dbk.select(ctx) == "podman-rootless" and dbk.podman_active(ctx)
    monkeypatch.setattr(dbk, "podman_prereqs", lambda which=None: ["podman"])
    p = api.plan(ctx, "FULL")
    bl = [o for o in p["operations"] if o["action"] == "BLOCKED_DEPENDENCY"]
    assert [o["block_id"] for o in bl] == ["t-docker"]
    assert "podman" in bl[0]["command"] and "existing Docker is not used" in bl[0]["command"]
    assert not any(o["action"] == "ENSURE_DOCKER_IMAGE" for o in p["operations"])
    assert any(o["action"] == "PLACE_IMAGE" for o in p["operations"])


def test_windows_default_is_gns3_vm_unverified_never_podman(tmp_path, monkeypatch):
    ctx = api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", docker=True))
    monkeypatch.delenv("VASYA_DOCKER_BACKEND", raising=False)
    assert dbk.default_backend("nt") == "gns3-vm" and dbk.select(ctx, osname="nt") == "gns3-vm"
    monkeypatch.setenv("VASYA_DOCKER_BACKEND", "podman-rootless")
    assert dbk.select(ctx, osname="nt") == "gns3-vm"           # podman is never chosen on Windows
    assert not dbk.BACKENDS["gns3-vm"]["implemented"] and "UNVERIFIED" in dbk.BACKENDS["gns3-vm"]["why"]


def test_shared_daemon_only_when_explicit(tmp_path, monkeypatch):
    ctx = api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", docker=True))
    monkeypatch.setenv("VASYA_DOCKER_BACKEND", "shared-daemon")
    assert dbk.select(ctx) == "shared-daemon" and not dbk.podman_active(ctx)
    assert dbk.server_env(ctx) == {} and dbk.engine_cmd(ctx) == (None, None)
    monkeypatch.setenv("VASYA_DOCKER_BACKEND", "bogus")
    assert dbk.select(ctx) == "podman-rootless"


def test_offline_tar_lookup(tmp_path):
    pl = make_payload(tmp_path / "p", docker=True)
    ctx = api.open_ctx(tmp_path / "R", pl)
    assert dbk.offline_tar(ctx, "alpine:latest") is None
    d = pl / "docker"; d.mkdir()
    (d / dbk.tar_name("gns3/openvswitch:latest")).write_bytes(b"x")
    assert dbk.offline_tar(ctx, "gns3/openvswitch:latest").name == "gns3_openvswitch_latest.tar"
