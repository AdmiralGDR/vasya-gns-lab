# SPDX-License-Identifier: GPL-3.0-or-later
"""podman-rootless backend (tested on Pop!_OS 24.04): everything under the root,
storage via the USER storage.conf (never CONTAINERS_STORAGE_CONF), netns="none", registries blocked
(never pull), env passed only to VASYA's gns3server and only when the VASYA socket exists.
No podman is executed here."""
import os, shutil, subprocess, sys
from pathlib import Path
import pytest
from vasya import api
from vasya.runtime import docker_backend as dbk
from conftest import make_payload

from conftest import GNS3RT


def _ctx(tmp_path, monkeypatch):
    monkeypatch.delenv("VASYA_DOCKER_BACKEND", raising=False)
    return api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", docker=True))


def test_server_env_only_when_socket_exists_with_unified_names(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    assert dbk.podman_active(ctx)
    assert dbk.server_env(ctx) == {}                      # no socket -> stock gns3server behaviour
    sock = dbk.podman_paths(ctx)["sock"]
    sock.parent.mkdir(parents=True); sock.touch()
    env = dbk.server_env(ctx)
    assert env == {"VASYA_DOCKER_SOCKET": str(sock), "DOCKER_HOST": f"unix://{sock}",
                   "VASYA_DOCKER_FIX_UID": "0", "VASYA_DOCKER_FIX_GID": "0"}
    assert dbk.LEGACY_SOCK_ENV not in env
    assert "DOCKER_HOST" not in os.environ or os.environ["DOCKER_HOST"] != env["DOCKER_HOST"]  # process-local


def test_paths_env_and_configs_stay_under_root(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    root = ctx.layout.root
    monkeypatch.setenv("CONTAINERS_STORAGE_CONF", "/etc/containers/storage.conf")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    cmd, penv = dbk.engine_cmd(ctx)
    assert cmd == ["podman"]
    assert "CONTAINERS_STORAGE_CONF" not in penv and "DOCKER_HOST" not in penv   # storage.conf root cause
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
              "CONTAINERS_CONF", "CONTAINERS_REGISTRIES_CONF"):
        assert Path(penv[k]).is_relative_to(root), k
    p = dbk.podman_paths(ctx)
    assert p["conf"] == Path(penv["XDG_CONFIG_HOME"]) / "containers" / "storage.conf"   # user config path
    st = p["conf"].read_text()
    assert f'graphroot = "{p["graphroot"]}"' in st and f'runroot = "{p["runroot"]}"' in st
    cc = p["containers_conf"].read_text()
    assert 'netns = "none"' in cc and str(root) in cc and 'cgroup_manager = "cgroupfs"' in cc
    rg = p["registries_conf"].read_text()
    assert all(f'location = "{r}"\nblocked = true' in rg for r in ("docker.io", "quay.io", "ghcr.io"))
    assert oct(p["runtime_dir"].stat().st_mode & 0o777) == "0o700"
    assert dbk.service_cmd(ctx) == ["podman", "system", "service", "--time=0", "unix://" + str(p["sock"])]
    argv = dbk.podman_argv(ctx, which=lambda t: "/usr/bin/podman")
    assert argv[:5] == ["env", "-u", "CONTAINERS_STORAGE_CONF", "-u", "DOCKER_HOST"] and argv[-1] == "/usr/bin/podman"


def test_prepare_server_env_starts_service_restores_then_exports(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(dbk, "podman_prereqs", lambda which=None: [])
    calls = []

    def ensure(c):
        calls.append("service"); s = dbk.podman_paths(c)["sock"]; s.parent.mkdir(parents=True, exist_ok=True); s.touch()
        return {"status": "OK"}
    env = dbk.prepare_server_env(ctx, ensure=ensure, restore=lambda c: calls.append("restore") or [])
    assert calls == ["service", "restore"] and env["VASYA_DOCKER_SOCKET"].endswith("Runtime/podman/run/podman.sock")
    monkeypatch.setattr(dbk, "podman_prereqs", lambda which=None: ["podman"])
    calls.clear()
    dbk.podman_paths(ctx)["sock"].unlink()
    assert dbk.prepare_server_env(ctx, ensure=ensure, restore=lambda c: []) == {} and calls == []


def test_ensure_service_is_a_user_process_with_pidfile(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    seen = {}

    class P:
        pid = 4242

    def fake_popen(argv, env, **k):
        seen.update(argv=argv, env=env, k=k)
        Path(argv[-1][len("unix://"):]).touch()
        return P()
    r = dbk.ensure_service(ctx, popen=fake_popen, wait=2)
    assert r["status"] == "OK" and seen["argv"][:3] == ["podman", "system", "service"]
    assert "systemctl" not in " ".join(seen["argv"]) and seen["k"]["start_new_session"]
    assert "CONTAINERS_STORAGE_CONF" not in seen["env"]
    assert dbk.podman_paths(ctx)["pid"].read_text() == "4242"
    # stop: a pid whose env does not name this root is never signalled
    assert dbk.stop_service(ctx) == "ABSENT" and not dbk.podman_paths(ctx)["sock"].exists()


def test_stop_service_kills_only_own_process(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    p = dbk.podman_paths(ctx); p["run"].mkdir(parents=True)
    env = dict(os.environ, VASYA_MARK=str(ctx.layout.root))
    proc = subprocess.Popen(["sleep", "30"], env=env)
    p["pid"].write_text(str(proc.pid)); p["sock"].touch()
    assert dbk.stop_service(ctx) == "STOPPED"
    assert proc.wait(timeout=5) is not None and not p["sock"].exists()
    other = subprocess.Popen(["sleep", "30"])
    p["pid"].write_text(str(other.pid))
    assert dbk.stop_service(ctx) == "ABSENT" and other.poll() is None
    other.kill(); other.wait()


def test_receipts_route_to_podman_never_shared_daemon(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    root = ctx.layout.root
    r = {"kind": "docker_image", "ref": "alpine:latest", "engine": "podman-rootless", "root": str(root)}
    shared = lambda: ["docker"]
    assert dbk.receipt_cmd(r, root, shared) is None          # storage gone -> nothing left, no podman call
    dbk.podman_paths(root)["graphroot"].mkdir(parents=True)
    monkeypatch.setattr(dbk.shutil, "which", lambda t: "/usr/bin/" + t)
    assert dbk.receipt_cmd(r, root, shared)[-1] == "/usr/bin/podman"
    assert dbk.receipt_cmd({"kind": "docker_image", "ref": "x"}, root, shared) == ["docker"]


def test_teardown_removes_storage_via_unshare_under_root(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    p = dbk.podman_paths(ctx); p["graphroot"].mkdir(parents=True)
    seen = []
    out = dbk.teardown(ctx, run=lambda a, **k: seen.append(a) or subprocess.CompletedProcess(a, 0, "", ""),
                       which=lambda t: "/usr/bin/podman")
    assert out["storage"] == "REMOVED" and seen[0][:4] == ["/usr/bin/podman", "unshare", "rm", "-rf"]
    assert all(Path(x).is_relative_to(ctx.layout.root) for x in seen[0][4:])
    assert dbk.teardown(tmp_path / "nothing") == {"service": "ABSENT", "storage": "ABSENT"}


def test_prereqs_reports_missing(tmp_path):
    sub = tmp_path / "subuid"; sub.write_text("alice:100000:65536\n")
    assert dbk.podman_prereqs(lambda t: "/usr/bin/" + t, str(sub), "alice") == []
    miss = dbk.podman_prereqs(lambda t: None, str(sub), "bob")
    assert "podman" in miss and any("subuid" in m for m in miss)


def test_socket_path_length_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("VASYA_DOCKER_BACKEND", raising=False)
    deep = tmp_path / ("x" * 90)
    ctx = api.open_ctx(deep / "R", make_payload(tmp_path / "p", docker=True))
    monkeypatch.setattr(dbk, "podman_prereqs", lambda which=None: [])
    assert "too long for a unix socket" in dbk.unavailable_reason(ctx)


@pytest.mark.skipif(not (GNS3RT / "py313").exists() or not shutil.which("patch"), reason="no gns3rt build dir")
def test_three_part_patch_on_scratch_copy_is_idempotent_upgrades_legacy_and_keeps_build_tree(tmp_path):
    src = GNS3RT / "py313"
    rt = tmp_path / "rt" / "py313"
    for rel in dbk.PATCH_FILES:
        (rt / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, rt / rel)
    orig = {rel: (src / rel).read_bytes() for rel in dbk.PATCH_FILES}
    assert dbk.patch_state(rt) == "STOCK"
    assert dbk.patch_gns3server(tmp_path / "rt") == [(str(rt / dbk.PATCH_FILES[0]), "PATCHED")]
    patched = {rel: (rt / rel).read_bytes() for rel in dbk.PATCH_FILES}
    assert dbk.patch_gns3server(tmp_path / "rt") == [(str(rt / dbk.PATCH_FILES[0]), "ALREADY")]
    assert all((src / rel).read_bytes() == orig[rel] for rel in dbk.PATCH_FILES), "build tree written through"
    # identical to `patch -p1` of the patch file on the originals (reproducible)
    ref = tmp_path / "ref"
    for rel in dbk.PATCH_FILES:
        (ref / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src / rel, ref / rel)
    subprocess.run(["patch", "-p1", "-s", "-d", str(ref), "-i", str(dbk.PATCH_FILE)], check=True)
    assert all((ref / rel).read_bytes() == patched[rel] for rel in dbk.PATCH_FILES)
    # a tree carrying the pre-merge one-line patch is upgraded to the same bytes
    leg = tmp_path / "leg" / "py313"
    for rel in dbk.PATCH_FILES:
        (leg / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src / rel, leg / rel)
    f = leg / dbk.PATCH_FILES[0]
    f.write_text(f.read_text().replace(dbk.SOCK_PATCH_OLD, dbk.LEGACY_SOCK_PATCH, 1))
    assert dbk.patch_state(leg) == "LEGACY"
    assert dbk.patch_gns3server(tmp_path / "leg")[0][1] == "UPGRADED"
    assert all((leg / rel).read_bytes() == patched[rel] for rel in dbk.PATCH_FILES)
    for rel in dbk.PATCH_FILES:
        compile(patched[rel], rel, "exec")
    rec = dbk.patch_record(tmp_path / "rt", tmp_path)
    assert rec["env"] == ["VASYA_DOCKER_SOCKET", "VASYA_DOCKER_FIX_UID", "VASYA_DOCKER_FIX_GID"] and len(rec["files"]) == 2


def test_managed_server_start_passes_extra_env(tmp_path, monkeypatch):
    from vasya.runtime import managed_server as ms
    import inspect
    assert "extra_env" in inspect.signature(ms.start).parameters
