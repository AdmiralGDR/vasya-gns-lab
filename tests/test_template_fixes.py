# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for defects found on a Pop!_OS 24.04 test install (D1, D2, D3, D6).
Template checks use the public payload metadata (packaging/payload, staged exactly as a release
build stages it); the node start tests need a payload with images and gns3server 2.2.61."""
import json, subprocess, sys, time
from pathlib import Path
import pytest
from conftest import have_gns3, _teardown_root, STAGE_DIR, FIXTURES
from vasya import api
from vasya.catalog import fixups as fx
from vasya.gns3.templates import build_template
from vasya.core.util import sha256_file

STAGE = STAGE_DIR / "Payload"
real = pytest.mark.skipif(not (STAGE / "images").exists(),
                          reason="needs a staged payload with images (VASYA_TEST_STAGE)")
REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def public_payload(tmp_path_factory):
    sys.path.insert(0, str(REPO / "scripts"))
    import build_bundle
    pl = tmp_path_factory.mktemp("pub") / "Payload"
    build_bundle.stage_payload(REPO / "packaging" / "payload", pl, profile="public")
    return pl


@pytest.fixture
def mctx(tmp_path, public_payload):
    return api.open_ctx(tmp_path / "ROOT", public_payload)


@pytest.fixture
def rctx(tmp_path):
    r = tmp_path / "ROOT"
    c = api.open_ctx(r, STAGE)
    yield c
    _teardown_root(r, STAGE)


def _tpl(c, bid):
    b = c.block(bid)
    return b, build_template(b, c.appliance_json(b))


def test_d3_iso_appliances_get_empty_disk_cdrom_and_ram(mctx):
    rctx = mctx
    b, t = _tpl(rctx, "puppy-linux")
    assert t["hda_disk_image"].endswith("empty8G.qcow2") and t["cdrom_image"].endswith(".iso")
    assert t["boot_priority"].startswith("d") and t["ram"] >= 512
    assert any(f.startswith("D3") for f in b["fixups"])
    for bid in ("smoothwall", "IPCop"):
        b, t = _tpl(rctx, bid)
        assert t["hda_disk_image"].endswith("empty8G.qcow2"), bid
        assert t["cdrom_image"].endswith(".iso") and t["boot_priority"].startswith("d"), bid
    # untouched: a normal disk appliance keeps its own hda and boot order
    b, t = _tpl(rctx, "empty-vm")
    assert t["hda_disk_image"] == "empty8G.qcow2"


def test_d2_arm_uses_qemu_system_arm(mctx):
    b, t = _tpl(mctx, "openwrt-realview")
    assert t["qemu_path"] == "qemu-system-arm"
    assert fx.qemu_binary("i386") == "qemu-system-x86_64"
    assert fx.missing_dependency(b, {"qemu-arm": {"present": False}}) == ("qemu-arm", "qemu-system-arm")
    assert fx.missing_dependency(b, {"qemu-arm": {"present": True}}) is None


@real
@pytest.mark.skipif(subprocess.run(["sh", "-c", "command -v qemu-system-arm"]).returncode == 0,
                    reason="qemu-system-arm installed here; BLOCKED path not reachable")
def test_d2_missing_arm_emulator_is_blocked_not_failed(rctx):
    p = api.plan(rctx, "FULL", block_ids=["openwrt-realview", "empty-vm"])
    bl = [o for o in p["operations"] if o["action"] == "BLOCKED_DEPENDENCY"]
    assert bl and bl[0]["package"] == "qemu-system-arm" and "apt-get install" in bl[0]["command"]
    assert p["preview"]["blocked_components"][0]["block_id"] == "openwrt-realview"
    r = api.install(rctx, "FULL", block_ids=["openwrt-realview", "empty-vm"])
    assert r["status"] == "OK", r.get("failed")
    assert r["blocked"] and "qemu-system-arm" in r["blocked"][0]["error"]
    comp = rctx.state.load()["components"]
    assert comp["openwrt-realview"]["installed"] is False and comp["openwrt-realview"]["blocked"]
    assert comp["empty-vm"]["installed"] is True


def test_d1_vde_uplink_rewritten_to_slirp():
    o = "-device e1000,netdev=internet0 -netdev vde,sock=/var/run/vde2/qemu0.ctl,id=internet0"
    assert fx.fix_options(o) == "-net nic,model=e1000 -net user"   # value tested on a real install
    assert fx.fix_options("-nographic " + o) == "-nographic -net nic,model=e1000 -net user"
    assert fx.fix_options("-nographic") == "-nographic"


@real
@have_gns3
def test_d1_internet_node_starts_on_managed_server(rctx):
    from vasya.installer.target import resolve_target
    from vasya.gns3.client import GNS3Client
    r = api.install(rctx, "FULL", block_ids=["internet"])
    assert r["status"] == "OK", r.get("failed")
    tgt = resolve_target(rctx, "FULL", start=True)
    cl = GNS3Client(tgt["api_base"], timeout=200)
    t = cl.find_template(rctx.block("internet")["name"], "qemu")
    assert t["options"] == "-net nic,model=e1000 -net user"
    pid = cl.create_project(f"vasya-d1-{int(time.time())}")["project_id"]
    try:
        n = cl.node_from_template(pid, t["template_id"], 0, 0)
        cl.node_action(pid, n["node_id"], "start", timeout=180)   # 409 here before the fix
        time.sleep(3)
        assert cl.get(f"/v2/projects/{pid}/nodes/{n['node_id']}")["status"] == "started"
        cmds = []
        for c in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                cmds.append(c.read_bytes().replace(b"\0", b" ").decode(errors="replace"))
            except OSError:
                pass
        q = [c for c in cmds if c.startswith("qemu-system") or "/qemu-system" in c.split(" ")[0]]
        assert any("-net user" in c and str(rctx.layout.root) in c for c in q), q
        cl.node_action(pid, n["node_id"], "stop", timeout=120)
    finally:
        cl.delete_project(pid)


@real
@have_gns3
def test_d3_puppy_boots_from_cd_with_empty_disk(rctx):
    from vasya import verifier
    r = api.install(rctx, "FULL", block_ids=["puppy-linux"])
    assert r["status"] == "OK", r.get("failed")
    v = verifier.runtime_verify(rctx, ["puppy-linux"])
    res = v["results"][0]
    assert v["status"] == "PASS", (res.get("steps"), res.get("console"), res.get("error"))


def test_d6_rollback_never_deletes_by_name(tmp_path):
    from vasya.installer.rollback import undo_resource
    f = tmp_path / "vasya-0123456789abcdef-disk.qcow2"
    f.write_bytes(b"user data with the same name")
    st, why = undo_resource(None, {"kind": "file", "path": str(f), "created": True})
    assert st == "KEPT_UNVERIFIED" and f.exists()
    st, _ = undo_resource(None, {"kind": "file", "path": str(f), "created": True, "sha256": "0" * 64})
    assert st == "KEPT_MODIFIED" and f.exists()
    st, _ = undo_resource(None, {"kind": "file", "path": str(f), "created": True, "sha256": sha256_file(f)})
    assert not f.exists()


def test_merged_fix_overrides_template_fields(tmp_path, monkeypatch):
    import json as _j
    from vasya.catalog import fixups
    d = tmp_path / "fixes"; d.mkdir()
    (d / "puppy-linux.json").write_text(_j.dumps({"ram": 1024, "options": "-vga std",
                                                  "hda_disk_image": "evil.qcow2"}))
    out = tmp_path / "af"
    r = subprocess.run([sys.executable, str(Path(__file__).parent.parent / "scripts/merge_template_fixes.py"),
                        str(d), "--out", str(out)], capture_output=True, text=True)
    assert "MERGED" in r.stdout
    rec = _j.loads((out / "puppy-linux.json").read_text())
    assert rec["template"] == {"ram": 1024, "options": "-vga std"}   # image names not overridable
    monkeypatch.setattr(fixups, "template_fix", lambda bid: rec["template"] if bid == "puppy-linux" else {})
    t = fixups.apply_template_fix("puppy-linux", {"ram": 512, "hda_disk_image": "empty8G.qcow2"})
    assert t == {"ram": 1024, "options": "-vga std", "hda_disk_image": "empty8G.qcow2"}


TEMPLATES = FIXTURES / "templates"


@pytest.mark.parametrize("bid", ["internet", "openwrt-realview", "puppy-linux"])
def test_fresh_install_template_equals_tested_fix(mctx, bid):
    """A fresh 1.1.0 install must generate the template that was fixed and tested by hand
    (fixtures/templates/after-*.json), not the broken 1.0.1 one (before-*.json)."""
    after = json.loads((TEMPLATES / f"after-{bid}.json").read_text())
    before = json.loads((TEMPLATES / f"before-{bid}.json").read_text())
    _, t = _tpl(mctx, bid)
    for k in ("qemu_path", "options", "ram", "boot_priority", "adapters", "adapter_type", "console_type",
              "platform", "cdrom_image", "kernel_image"):
        assert (t.get(k) or "") == (after.get(k) or ""), (k, t.get(k), after.get(k))
    a_hda, t_hda = after.get("hda_disk_image") or "", t.get("hda_disk_image") or ""
    if fx.EMPTY_DISK.search(a_hda):   # the hand fix used 1.0.1's alt name for the same blank 8 GB disk
        assert fx.EMPTY_DISK.search(t_hda) and a_hda.endswith(t_hda.split("-")[-1]), t_hda
    else:
        assert t_hda == a_hda
    changed = [k for k in after if after.get(k) != before.get(k)]
    assert changed, "fixture sanity: before/after differ"


def test_shipped_appliance_files_get_the_fix_baked_in():
    d = {"qemu": {"options": "-device e1000,netdev=internet0 -netdev vde,sock=/x,id=internet0", "ram": 64}}
    assert "options" in fx.patch_gns3a("internet", d)
    assert d["qemu"]["options"] == "-net nic,model=e1000 -net user"
    p = {"qemu": {"ram": 256, "arch": "x86_64"}}
    assert set(fx.patch_gns3a("puppy-linux", p)) >= {"ram", "boot_priority"} and p["qemu"]["ram"] == 512
    o = {"qemu": {"ram": 128, "arch": "arm", "options": ""}}
    fx.patch_gns3a("openwrt-realview", o)
    assert o["qemu"]["options"] == "-M realview-eb-mpcore" and o["qemu"]["arch"] == "arm"
    assert fx.patch_gns3a("no-such-block", {"qemu": {}}) == []
    assert d["description"].endswith("GNS3 registry, https://github.com/GNS3/gns3-registry, GPL-3.0.")
    assert "Modified by AdmiralGDR on 2026-10-26" in d["description"] and "options" in d["description"]
