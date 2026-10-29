# SPDX-License-Identifier: GPL-3.0-or-later
"""Lifecycle against a real gns3server 2.2.61 (VASYA-managed, isolated in tmp root)."""
import json, os, subprocess, sys
from pathlib import Path
import pytest
from conftest import have_gns3, have_docker, cli, make_payload
from vasya import api
from vasya.core import txn as txnmod
from vasya.core.util import sha256_file
from vasya.gns3.client import GNS3Client
from vasya.gns3.templates import VASYA_USAGE_TAG

pytestmark = have_gns3


def _vasya_templates(ctx):
    base = ctx.state.load()["gns3"]["api_base"]
    return [t for t in GNS3Client(base).templates() if VASYA_USAGE_TAG in (t.get("usage") or "")]


def test_full_install_idempotent_verify_uninstall(ctx, tmp_path):
    r = api.install(ctx, "FULL")
    assert r["status"] == "OK", r["failed"]
    new1 = sum(x["result"] == "NEW" for x in r["results"])
    assert new1 >= 7
    st = ctx.state.load()
    assert st["gns3"]["managed"] and st["gns3"]["port"] >= 3088
    # images linked (hardlink, same fs), not copied
    files = [x for x in txnmod.owned_resources(ctx.layout) if x.get("role") == "image"]
    assert files and all(x["method"] == "hardlink" for x in files)
    assert len(_vasya_templates(ctx)) == 3
    # idempotent second run: nothing new
    r2 = api.install(ctx, "FULL")
    assert r2["status"] == "OK"
    assert sum(x["result"] == "NEW" for x in r2["results"]) == 0
    assert len(_vasya_templates(ctx)) == 3
    v = api.static_verify(ctx)
    assert v["status"] == "PASS", v
    rep = api.uninstall(ctx, "full", report_dir=tmp_path)
    assert rep["residue"]["clean"], rep["residue"]
    assert not ctx.layout.root.exists()
    assert "CLEAN_UNINSTALL: PASS" in Path(rep["report_path"]).read_text()


def test_no_home_gns3_config_created(tmp_path, payload):
    home = tmp_path / "home"; home.mkdir(exist_ok=True)
    r = cli(tmp_path / "root", payload, "install", "--mode", "FULL", "-y",
            env={"HOME": str(home)})
    try:
        assert r.returncode == 0, r.stdout + r.stderr
        assert not (home / ".config" / "GNS3").exists()
        assert not (home / "GNS3").exists()
    finally:
        cli(tmp_path / "root", payload, "uninstall", "--level", "full", "-y", env={"HOME": str(home)})


def test_crash_mid_copy_then_rollback_leaves_zero_residue(tmp_path):
    """Regression for 006: process killed (SIGKILL-equivalent os._exit) during image copy."""
    payload = make_payload(tmp_path / "p", n_images=4)
    root = tmp_path / "root"
    plan = json.loads(cli(root, payload, "plan", "--mode", "FULL", "--allow-copy").stdout)
    places = [o for o in plan["operations"] if o["action"] == "PLACE_IMAGE"]
    crash_op = places[2]["op_id"]
    r = cli(root, payload, "install", "--mode", "FULL", "-y", "--allow-copy",
            env={"VASYA_TEST_CRASH_OP": crash_op, "VASYA_TEST_CRASH_MODE": "mid_copy"})
    assert r.returncode == 137, r.stdout + r.stderr
    ctx = api.open_ctx(root, payload)
    inc = txnmod.incomplete(ctx.layout)
    assert len(inc) == 1 and inc[0]["pending"], inc
    part = Path(inc[0]["pending"][0]["partial"])
    assert part.exists(), "half-written partial must exist after the crash"
    committed = [x for x in inc[0]["committed"] if x.get("role") == "image"]
    assert len(committed) == 2 and all(Path(x["path"]).exists() for x in committed)
    s = api.status(ctx)
    assert api.verdict(s) == "NEEDS_RECOVERY"
    rb = api.rollback(ctx)
    assert rb["undone"] and all(u["result"] in ("REMOVED", "ABSENT") for u in rb["undone"]), rb
    assert sum(u["kind"] == "template" and u["result"] == "REMOVED" for u in rb["undone"]) >= 1
    for x in committed:
        assert not Path(x["path"]).exists()
    assert not part.exists()
    imgdir = Path(ctx.state.load()["gns3"]["images_path"])
    # gns3server itself creates empty*.qcow2 / OVMF in its images dir (inside the VASYA root)
    leftovers = [p for p in imgdir.rglob("*") if p.is_file() and not p.name.startswith(("empty", "OVMF", "config.img"))]
    assert leftovers == [], leftovers
    rep = api.uninstall(api.open_ctx(root, payload), "full", report_dir=tmp_path)
    assert rep["residue"]["clean"], rep["residue"]


def test_crash_then_resume_completes(tmp_path):
    payload = make_payload(tmp_path / "p", n_images=4)
    root = tmp_path / "root"
    plan = json.loads(cli(root, payload, "plan", "--mode", "FULL", "--allow-copy").stdout)
    tmpl_ops = [o for o in plan["operations"] if o["action"] == "PLACE_IMAGE"]
    r = cli(root, payload, "install", "--mode", "FULL", "-y", "--allow-copy",
            env={"VASYA_TEST_CRASH_OP": tmpl_ops[1]["op_id"]})
    assert r.returncode == 137
    r = cli(root, payload, "resume")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "OK" and out["recovered"]
    ctx = api.open_ctx(root, payload)
    assert txnmod.incomplete(ctx.layout) == []
    assert api.static_verify(ctx)["status"] == "PASS"
    assert api.verdict(api.status(ctx)) in ("INSTALLED_UNVERIFIED", "HEALTHY_VERIFIED")
    # no stray partial files anywhere under the target
    imgdir = Path(ctx.state.load()["gns3"]["images_path"])
    assert not [p for p in imgdir.rglob("*.vasya-partial")]
    rep = api.uninstall(ctx, "full", report_dir=tmp_path)
    assert rep["residue"]["clean"], rep["residue"]


def test_cancel_rolls_back(ctx):
    import threading
    ev = threading.Event()
    seen = []

    def prog(i, n, op, res):
        seen.append(op["action"])
        if op["action"] == "PLACE_IMAGE":
            ev.set()
    r = api.install(ctx, "FULL", cancel=ev, progress=prog)
    assert r["status"] == "CANCELLED"
    imgdir = Path(ctx.state.load()["gns3"]["images_path"])
    assert [p for p in imgdir.rglob("*") if p.is_file() and not p.name.startswith(("empty", "OVMF", "config.img"))] == []
    api.uninstall(ctx, "full")


def test_repair_restores_damaged_and_missing(ctx):
    assert api.install(ctx, "FULL", allow_copy=True)["status"] == "OK"
    files = [x for x in txnmod.owned_resources(ctx.layout) if x.get("role") == "image"]
    victim = Path(files[0]["path"])
    data = bytearray(victim.read_bytes()); data[10:17] = b"CORRUPT"
    victim.unlink(); victim.write_bytes(bytes(data))  # damaged copy (new inode)
    Path(files[1]["path"]).unlink()
    t = _vasya_templates(ctx)[0]
    GNS3Client(ctx.state.load()["gns3"]["api_base"]).delete_template(t["template_id"])
    v = api.static_verify(ctx)
    assert v["failed"] >= 3
    r = api.repair(ctx)
    assert r["status"] == "OK" and r["failed_after"] == 0, r
    assert len(r["quarantined"]) == 1
    assert api.static_verify(ctx)["status"] == "PASS"
    rep = api.uninstall(ctx, "full")
    assert rep["residue"]["clean"], rep["residue"]


def test_inplace_damage_of_hardlink_is_reported_as_payload_damage(ctx):
    assert api.install(ctx, "FULL")["status"] == "OK"
    f = next(x for x in txnmod.owned_resources(ctx.layout) if x.get("role") == "image")
    with open(f["path"], "r+b") as fh:  # in-place write also hits the CAS (same inode)
        fh.seek(10); fh.write(b"CORRUPT")
    r = api.repair(ctx)
    assert r["status"] == "PARTIAL"
    assert any("PAYLOAD_DAMAGED" in (x["error"] or "") for x in r["failed"])
    api.uninstall(ctx, "full")


def test_conflict_never_overwrites_user_file(ctx, tmp_path):
    r = api.plan(ctx, "FULL")
    img_op = next(o for o in r["operations"] if o["action"] == "PLACE_IMAGE")
    user = Path(img_op["target"]); user.parent.mkdir(parents=True, exist_ok=True)
    user.write_bytes(b"user's own different image")
    before = sha256_file(user)
    res = api.install(ctx, "FULL")
    assert res["status"] == "OK"
    assert sha256_file(user) == before
    alt = [x for x in txnmod.owned_resources(ctx.layout) if x.get("path", "").endswith(user.name)
           and Path(x["path"]).name.startswith("vasya-")]
    assert alt, "conflict must be installed under an alternate VASYA name"
    tmpl = [t for t in _vasya_templates(ctx) if Path(alt[0]["path"]).name in json.dumps(t)]
    assert tmpl, "template must reference the alternate name"
    rep = api.uninstall(ctx, "components")
    assert user.exists() and sha256_file(user) == before
    assert rep["residue"]["clean"], rep["residue"]
    api.uninstall(ctx, "full")


def test_uninstall_level1_keeps_app_level2_removes_all(ctx, tmp_path):
    assert api.install(ctx, "FULL")["status"] == "OK"
    reg = api.register_desktop(ctx)
    assert reg["status"] == "REGISTERED" and Path(reg["path"]).exists()
    rep1 = api.uninstall(ctx, "components", report_dir=tmp_path)
    assert rep1["residue"]["clean"]
    assert ctx.layout.root.exists() and Path(reg["path"]).exists()
    assert _vasya_templates(ctx) == []
    rep2 = api.uninstall(ctx, "full", report_dir=tmp_path)
    assert rep2["residue"]["clean"], rep2["residue"]
    assert not Path(reg["path"]).exists() and not ctx.layout.root.exists()


def test_integration_mode_existing_config_untouched(tmp_path, payload):
    """Existing GNS3 (its own config) -> integration; config byte-identical after."""
    from vasya.runtime import managed_server as ms
    from vasya.core.layout import Layout
    other = Layout(tmp_path / "users-gns3").ensure()  # simulate a user's own GNS3 server
    port = ms.free_port(3150)
    ms.write_config(other, port)
    cfg = ms.paths(other)["config"]
    cfg.write_text(cfg.read_text() + "\n# user comment\n")
    before = cfg.read_bytes()
    ms.start(other, os.environ["VASYA_GNS3SERVER_BIN"], port)
    try:
        ctx = api.open_ctx(tmp_path / "root", payload)
        tgt = {"api_base": f"http://127.0.0.1:{port}", "images_path": str(ms.paths(other)["images_path"]),
               "appliances_path": str(ms.paths(other)["appliances_path"]), "config": str(cfg)}
        r = api.install(ctx, "INTEGRATION", explicit_target=tgt)
        assert r["status"] == "OK", r["failed"]
        assert cfg.read_bytes() == before
        assert api.gns3_config_check(ctx)["status"] == "UNCHANGED"
        cfg.write_text("damaged")
        assert api.gns3_config_restore(ctx)["status"] == "RESTORED_BYTE_IDENTICAL"
        assert cfg.read_bytes() == before
        rep = api.uninstall(ctx, "full", report_dir=tmp_path)
        assert rep["residue"]["clean"], rep["residue"]
        assert cfg.read_bytes() == before
        # user's server still running, its builtin templates intact
        assert GNS3Client(tgt["api_base"]).version()
    finally:
        ms.stop(other)


def test_update_delta_copies_only_new_objects(ctx, tmp_path):
    import shutil
    v1 = make_payload(tmp_path / "v1", n_images=3)
    api.update_store(ctx, v1)
    v2 = make_payload(tmp_path / "v2", n_images=5)  # 3 identical + 2 new objects
    d = api.store_delta(v2, ctx.layout.Store)
    assert len(d["reuse"]) == 3 and len(d["copy"]) == 2
    d2 = api.update_store(ctx, v2)
    assert len(d2["copy"]) == 2
    assert len(api.store_delta(v2, ctx.layout.Store)["copy"]) == 0


def test_cli_gui_same_state(ctx):
    """CLI `status` and the GUI Home screen render the same verdict from the same store."""
    assert api.install(ctx, "FULL")["status"] == "OK"
    out = json.loads(cli(ctx.layout.root, ctx.payload_root, "status").stdout)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from vasya.gui.screens.home import HomeScreen
    app = QApplication.instance() or QApplication([])
    from vasya.gui.app import Backend
    h = HomeScreen(Backend(ctx.layout.root, ctx.payload_root))
    h.refresh_sync()
    assert h.verdict_value == out["verdict"]
    assert h.counts_value == {k: out["components"][k] for k in
                              ("catalog", "ready", "installed", "runtime_verified", "errors")}
    h.close(); h.deleteLater(); app.processEvents()
    api.uninstall(ctx, "full")


@have_docker
def test_docker_labelled_and_shared_daemon_safe(tmp_path, shared_daemon):
    payload = make_payload(tmp_path / "p", n_images=2, docker=True)
    ctx = api.open_ctx(tmp_path / "root", payload)
    # a non-VASYA container using the same base image must keep it alive
    subprocess.run(["docker", "pull", "-q", "alpine:latest"], capture_output=True)
    foreign = subprocess.run(["docker", "create", "--name", f"user-ctr-{os.getpid()}", "alpine:latest"],
                             capture_output=True, text=True).stdout.strip()
    try:
        r = api.install(ctx, "FULL")
        assert r["status"] == "OK", r["failed"]
        lab = [x for x in txnmod.owned_resources(ctx.layout) if x["kind"] == "docker_labeled_image"]
        assert lab
        lbl = subprocess.run(["docker", "image", "inspect", "-f",
                              "{{index .Config.Labels \"org.vasya.owner\"}}", lab[0]["ref"]],
                             capture_output=True, text=True).stdout.strip()
        assert lbl == "vasya-gns-lab"
        t = [t for t in _vasya_templates(ctx) if t["template_type"] == "docker"][0]
        assert t["image"] == lab[0]["ref"] and t["category"] == "switch"
        rep = api.uninstall(ctx, "full", report_dir=tmp_path)
        assert rep["residue"]["clean"], rep["residue"]
        assert subprocess.run(["docker", "image", "inspect", lab[0]["ref"]],
                              capture_output=True).returncode != 0
        assert subprocess.run(["docker", "image", "inspect", "alpine:latest"],
                              capture_output=True).returncode == 0, "base image used by user container kept"
    finally:
        subprocess.run(["docker", "rm", "-f", foreign], capture_output=True)
