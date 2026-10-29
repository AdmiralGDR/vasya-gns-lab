# SPDX-License-Identifier: GPL-3.0-or-later
"""Error scenarios: each one is DETECTED, gets a human message (RU+EN),
leaves a SAFE state, and OFFERS a recovery that is then exercised."""
import json, os, shutil, socket, stat, subprocess, sys, time
from pathlib import Path
import pytest
from conftest import have_gns3, have_docker, make_payload, cli
from vasya import api, errors
from vasya.core import txn as txnmod
from vasya.core.util import sha256_file
from vasya.gns3.client import GNS3Client
from vasya.installer.progress_text import describe
from vasya.runtime import managed_server as ms

pytestmark = have_gns3
REAL_DOCKER = shutil.which("docker")


def _human(x, code):
    for lang in ("ru", "en"):
        e = errors.explain(x, lang)
        assert e["code"] == code, (x, e)
        assert e["title"] and e["recovery"] and e["state"]
    return errors.explain(x, "ru")


def _nothing_written(root):
    return not Path(root).exists() or not any(Path(root, "State", "txn").glob("*")) \
        if Path(root, "State").exists() else True


def _docker_shim(tmp_path, pull_error):
    """A `docker` in front of the real one: pretends the base image is absent and
    the pull fails with a real daemon message; everything else passes through."""
    d = tmp_path / "shim"; d.mkdir(exist_ok=True)
    f = d / "docker"
    f.write_text(f"""#!/bin/sh
for a in "$@"; do
  case "$a" in pull) echo '{pull_error}' >&2; exit 1;; esac
done
pre=""
if [ "$1" = --config ]; then pre="--config $2"; shift 2; fi
if [ "$1" = image ] && [ "$2" = inspect ] && [ "$3" = alpine:latest ]; then echo '[]'; echo 'Error: No such image' >&2; exit 1; fi
exec {REAL_DOCKER} $pre "$@"
""")
    f.chmod(0o755)
    return d


def test_no_internet_detected_safe_and_retry(tmp_path, monkeypatch, shared_daemon):
    _scenario_docker_failure(tmp_path, monkeypatch,
                             "Error response from daemon: Get \"https://registry-1.docker.io/v2/\": dial tcp: "
                             "lookup registry-1.docker.io: no such host", "NO_INTERNET")


def test_partial_docker_pull_detected_safe_and_retry(tmp_path, monkeypatch, shared_daemon):
    _scenario_docker_failure(tmp_path, monkeypatch,
                             "latest: Pulling from library/alpine\nfailed to register layer: unexpected EOF",
                             "PARTIAL_DOCKER_PULL")


@have_docker
def _scenario_docker_failure(tmp_path, monkeypatch, msg, code):
    payload = make_payload(tmp_path / "p", docker=True)
    ctx = api.open_ctx(tmp_path / "root", payload)
    shim = _docker_shim(tmp_path, msg)
    monkeypatch.setenv("PATH", f"{shim}:{os.environ['PATH']}")
    try:
        r = api.install(ctx, "FULL")
        assert r["status"] == "PARTIAL"                                # detected
        f = [x for x in r["failed"] if x["block_id"] == "t-docker"]
        assert f, r["failed"]
        _human(f[0]["error"], code)                                     # message
        txt = describe(1, 1, {"action": "ENSURE_DOCKER_IMAGE", "label": "VASYA Test Docker"},
                       "FAIL", "ru", f[0]["error"])
        assert "VASYA Test Docker" in txt and "ошибка" in txt
        st = ctx.state.load()["components"]                             # safe state
        assert st["t-docker"]["installed"] is False and st["t-docker"]["error"]
        assert all(st[b]["installed"] for b in ("t-qemu0", "t-qemu2", "t-dyn"))
        assert not txnmod.incomplete(ctx.layout)
        assert api.verdict(api.status(ctx)) == "DEGRADED"
        monkeypatch.setenv("PATH", os.environ["PATH"].replace(f"{shim}:", ""))
        rr = api.retry_failed(ctx)                                      # recovery
        assert rr["status"] == "OK" and rr["retried"] == ["t-docker"], rr
        assert ctx.state.load()["components"]["t-docker"]["installed"] is True
    finally:
        monkeypatch.setenv("PATH", os.environ["PATH"].replace(f"{shim}:", ""))
        rep = api.uninstall(ctx, "full", report_dir=tmp_path, remove_docker=True)
        assert rep["residue"]["clean"], rep["residue"]


def test_corrupt_payload_detected_nothing_installed_from_it(tmp_path):
    payload = make_payload(tmp_path / "p")
    blob = next((payload / "images/sha256").iterdir())
    blob.chmod(0o644)
    with open(blob, "r+b") as fh:
        fh.seek(100); fh.write(b"CORRUPTED")
    ctx = api.open_ctx(tmp_path / "root", payload)
    r = api.install(ctx, "FULL", allow_copy=True)
    try:
        assert r["status"] == "PARTIAL"
        e = [x for x in r["failed"] if "PAYLOAD_DAMAGED" in (x["error"] or "")]
        assert e
        _human(e[0]["error"], "PAYLOAD_DAMAGED")
        # nothing with the damaged hash was placed into GNS3
        placed = [x for x in txnmod.owned_resources(ctx.layout) if x.get("kind") == "file"]
        assert all(sha256_file(x["path"]) == x["sha256"] for x in placed if x.get("sha256"))
    finally:
        api.uninstall(ctx, "full", report_dir=tmp_path)


def test_corrupt_download_part_message():
    _human("CORRUPT_PART: VASYA-GNS-LAB-1.1.0-Linux.tar.zst.part002 sha256 mismatch", "CORRUPT_DOWNLOAD")


def test_low_disk_blocks_before_any_change(tmp_path, monkeypatch, payload):
    root = tmp_path / "root"
    ctx = api.open_ctx(root, payload)
    monkeypatch.setenv("VASYA_TEST_FREE_BYTES", str(10 * 1024 ** 2))
    r = api.install(ctx, "FULL", allow_copy=True)
    assert r["status"] == "BLOCKED" and r["code"] == "LOW_DISK" and r["changed"] is False
    assert "мест" in r["error_ru"]["title"]
    assert not (root / "State" / "txn").exists() or not any((root / "State" / "txn").iterdir())
    assert ms.running_pid(ctx.layout) is None
    p = json.loads(cli(root, payload, "install", "--mode", "FULL", "-y",
                       env={"VASYA_TEST_FREE_BYTES": str(10 * 1024 ** 2)}).stdout)
    assert p["code"] == "LOW_DISK"
    monkeypatch.delenv("VASYA_TEST_FREE_BYTES")                         # recovery: space freed
    r = api.install(ctx, "FULL", allow_copy=True)
    assert r["status"] == "OK"
    api.uninstall(ctx, "full", report_dir=tmp_path)


def test_interrupted_operation_blocks_new_install_offers_resume(tmp_path):
    payload = make_payload(tmp_path / "p", n_images=4)
    root = tmp_path / "root"
    plan = json.loads(cli(root, payload, "plan", "--mode", "FULL", "--allow-copy").stdout)
    op = next(o for o in plan["operations"] if o["action"] == "PLACE_IMAGE")["op_id"]
    r = cli(root, payload, "install", "--mode", "FULL", "-y", "--allow-copy",
            env={"VASYA_TEST_CRASH_OP": op, "VASYA_TEST_CRASH_MODE": "mid_copy"})
    assert r.returncode == 137
    ctx = api.open_ctx(root, payload)
    assert api.verdict(api.status(ctx)) == "NEEDS_RECOVERY"
    b = api.install(ctx, "FULL", allow_copy=True)
    assert b["status"] == "BLOCKED" and b["code"] == "INTERRUPTED"
    _human(b["code"], "INTERRUPTED")
    rr = api.resume(ctx, allow_copy=True)
    assert rr["status"] == "OK"
    assert api.static_verify(ctx)["status"] == "PASS"
    rep = api.uninstall(ctx, "full", report_dir=tmp_path)
    assert rep["residue"]["clean"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_no_admin_target_blocks_cleanly(tmp_path, payload):
    locked = tmp_path / "locked"; locked.mkdir()
    locked.chmod(0o555)
    try:
        ctx = api.open_ctx(locked / "VASYA-GNS-LAB", payload)
        r = api.install(ctx, "FULL")
        assert r["status"] == "BLOCKED" and r["code"] == "NO_ADMIN" and not r["changed"]
        assert not (locked / "VASYA-GNS-LAB").exists()
        assert "домашнем" in r["error_ru"]["recovery"]
        pv = api.plan(ctx, "FULL")["preview"]
        assert pv["target_writable"] is False
    finally:
        locked.chmod(0o755)


def test_existing_gns3_detected_and_its_config_untouched(tmp_path, payload, isolated_home):
    cfgd = isolated_home / ".config" / "GNS3" / "2.2"; cfgd.mkdir(parents=True)
    cfg = cfgd / "gns3_server.conf"
    cfg.write_text("[Server]\nhost = 127.0.0.1\nport = 3080\nimages_path = /nonexistent/imgs\n# mine\n")
    before = cfg.read_bytes()
    ctx = api.open_ctx(tmp_path / "root", payload)
    pv = api.plan(ctx, "FULL")["preview"]
    assert pv["existing_gns3"]["found"] and pv["existing_gns3"]["config"] == str(cfg)
    _human("EXISTING_GNS3", "EXISTING_GNS3")
    r = api.install(ctx, "FULL")
    assert r["status"] == "OK"
    assert ctx.state.load()["gns3"]["port"] != 3080
    assert cfg.read_bytes() == before
    api.uninstall(ctx, "full", report_dir=tmp_path)
    assert cfg.read_bytes() == before


def test_port_conflict_relocates_vasya_server_not_the_other_program(tmp_path, payload):
    ctx = api.open_ctx(tmp_path / "root", payload)
    assert api.install(ctx, "FULL")["status"] == "OK"
    port = ctx.state.load()["gns3"]["port"]
    ms.stop(ctx.layout)
    squatter = socket.socket(); squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    for _ in range(50):
        try:
            squatter.bind(("127.0.0.1", port)); break
        except OSError:
            time.sleep(0.2)
    squatter.listen(1)
    try:
        from vasya.installer.target import resolve_target
        tgt = resolve_target(ctx)
        assert tgt["port_moved_from"] == port and tgt["port"] != port and tgt["api_ok"]
        assert ctx.state.load()["gns3"]["port"] == tgt["port"]
        assert f"port = {tgt['port']}" in ms.paths(ctx.layout)["config"].read_text()
        _human("listen tcp 127.0.0.1:3088: bind: address already in use", "PORT_CONFLICT")
        squatter.getsockname()  # other program's socket still alive
        assert api.static_verify(ctx)["status"] == "PASS"
    finally:
        squatter.close()
        api.uninstall(ctx, "full", report_dir=tmp_path)


@have_docker
def test_busy_vm_blocks_uninstall_and_repair_until_stopped(tmp_path, shared_daemon):
    payload = make_payload(tmp_path / "p", docker=True)
    ctx = api.open_ctx(tmp_path / "root", payload)
    assert api.install(ctx, "FULL")["status"] == "OK"
    cl = GNS3Client(ctx.state.load()["gns3"]["api_base"])
    t = cl.find_template("VASYA Test Docker", "docker")
    p = cl.create_project("user-lab")
    n = cl.node_from_template(p["project_id"], t["template_id"])
    cl.node_action(p["project_id"], n["node_id"], "start", timeout=180)
    try:
        busy = api.busy_nodes(ctx)
        assert [b["node_id"] for b in busy] == [n["node_id"]]
        u = api.uninstall(ctx, "full", report_dir=tmp_path)
        assert u["status"] == "BLOCKED" and u["code"] == "BUSY_VM"
        assert ctx.layout.root.exists() and api.static_verify(ctx)["status"] == "PASS"
        rp = api.repair(ctx)
        assert rp["status"] == "BLOCKED" and rp["code"] == "BUSY_VM"
        _human(u["code"], "BUSY_VM")
        assert api.stop_busy_nodes(ctx) == [n["name"]]                  # recovery offered
        time.sleep(1)
        assert api.busy_nodes(ctx) == []
    finally:
        rep = api.uninstall(ctx, "full", report_dir=tmp_path, force=True, projects="delete")
        assert rep["residue"]["clean"], rep["residue"]


def test_image_name_conflict_never_overwrites(tmp_path, payload):
    ctx = api.open_ctx(tmp_path / "root", payload)
    op = next(o for o in api.plan(ctx, "FULL")["operations"] if o["action"] == "PLACE_IMAGE")
    user = Path(op["target"]); user.parent.mkdir(parents=True, exist_ok=True)
    user.write_bytes(b"mine")
    p2 = api.plan(ctx, "FULL")
    assert p2["preview"]["conflicts"]
    r = api.install(ctx, "FULL")
    assert r["status"] == "OK" and user.read_bytes() == b"mine"
    alt = next(o for o in r["plan"]["operations"] if o["action"] == "PLACE_IMAGE_ALT")
    assert "отдельным именем" in describe(3, 9, alt, "NEW", "ru")
    _human("target appeared with different content; not overwritten", "IMAGE_NAME_CONFLICT")
    api.uninstall(ctx, "components", report_dir=tmp_path)
    assert user.read_bytes() == b"mine"  # (FULL-mode root is VASYA's own; level 2 removes it)
    api.uninstall(ctx, "full", report_dir=tmp_path)


def test_reinstall_reuses_without_duplicates(tmp_path, payload):
    ctx = api.open_ctx(tmp_path / "root", payload)
    assert api.install(ctx, "FULL")["status"] == "OK"
    pv = api.plan(ctx, "FULL")["preview"]
    assert pv["reinstall"] and pv["bytes_to_copy"] == 0
    r = api.install(ctx, "FULL")
    assert r["status"] == "OK" and not [x for x in r["results"] if x["result"] == "NEW"]
    tm = [t for t in GNS3Client(ctx.state.load()["gns3"]["api_base"]).templates()
          if t["name"].startswith("VASYA Test")]
    assert len(tm) == len({t["name"] for t in tm}) == 3
    api.uninstall(ctx, "full", report_dir=tmp_path)


@pytest.mark.parametrize("damage", ["delete", "corrupt"])
def test_deleted_or_corrupt_image_detected_and_repaired(tmp_path, payload, damage):
    ctx = api.open_ctx(tmp_path / "root", payload)
    assert api.install(ctx, "FULL", allow_copy=True)["status"] == "OK"
    f = next(x for x in txnmod.owned_resources(ctx.layout) if x.get("role") == "image")
    p = Path(f["path"])
    if damage == "delete":
        p.unlink()
    else:
        p.unlink(); p.write_bytes(b"garbage" * 100)  # break the link, keep the store intact
    v = api.static_verify(ctx)
    bad = [c for c in v["checks"] if c["status"] == "FAIL"]
    code = "IMAGE_MISSING" if damage == "delete" else "IMAGE_CORRUPT"
    assert bad and bad[0]["code"] == code
    _human(code, code)
    r = api.repair(ctx)
    assert r["status"] == "OK" and r["failed_after"] == 0
    assert sha256_file(p) == f["sha256"]
    api.uninstall(ctx, "full", report_dir=tmp_path)


def test_gns3_unreachable_blocks_integration_install(tmp_path, payload):
    port = ms.free_port(3190)
    ctx = api.open_ctx(tmp_path / "root", payload)
    tgt = {"api_base": f"http://127.0.0.1:{port}", "images_path": str(tmp_path / "imgs"),
           "appliances_path": str(tmp_path / "apps")}
    r = api.install(ctx, "INTEGRATION", explicit_target=tgt)
    assert r["status"] == "BLOCKED" and r["code"] == "GNS3_UNREACHABLE" and not r["changed"]
    assert not (tmp_path / "imgs").exists()
    _human(r["code"], "GNS3_UNREACHABLE")
    # GNS3 VM address unreachable: same detection path (remote compute)
    tgt["api_base"] = "http://192.0.2.10:80"  # TEST-NET-1, never routable
    r2 = api.install(ctx, "INTEGRATION", explicit_target=tgt)
    assert r2["code"] == "GNS3_UNREACHABLE"


def test_every_error_code_has_ru_en_texts():
    for code in errors.E:
        for lang in ("ru", "en"):
            e = errors.explain(code, lang)
            assert e["title"] and e["recovery"], code
    assert errors.classify("No busybox executable found") == "MISSING_PROGRAMS"
    assert errors.classify("uBridge requires root access or the capability to interact with network adapters") == "UBRIDGE_CAPS"
