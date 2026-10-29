# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests that need no GNS3 server."""
import json, os, stat
from pathlib import Path, PureWindowsPath
import pytest
from vasya.core.cas import Payload, place_file, partial_path, CopyNotAllowed
from vasya.core.util import sha256_file
from vasya.core import txn as txnmod
from vasya.core.layout import Layout
from vasya.platform import by_name
from vasya.platform.base import windows_path_problems
from vasya.gns3.templates import build_template, map_category, VALID_CATEGORIES
from vasya.catalog.catalog import Catalog
from vasya.catalog import image_import
from vasya.installer.plan import classify, link_methods
from vasya.tools.registry import detect_all, metadata
from vasya.tools import packet_tracer
from vasya import diagnostics

PUBLIC = Path(__file__).resolve().parent.parent / "packaging" / "payload"   # public payload metadata


# ---------------- manifest / checksum
def test_payload_verify_detects_corruption(payload):
    p = Payload(payload)
    assert all(r["status"] == "PASS" for r in p.verify())
    victim = next((payload / "images/sha256").iterdir())
    with open(victim, "r+b") as f:
        f.seek(100); f.write(b"XXXX")
    bad = [r for r in p.verify() if r["status"] == "FAIL"]
    assert len(bad) == 1 and bad[0]["detail"] == "sha256 mismatch"


def test_payload_verify_detects_missing_and_size(payload):
    p = Payload(payload)
    files = sorted((payload / "images/sha256").iterdir())
    files[0].unlink()
    with open(files[1], "ab") as f:
        f.write(b"x")
    det = {r["detail"].split()[0] for r in p.verify() if r["status"] == "FAIL"}
    assert det == {"missing", "size"}


def test_real_manifest_counts():
    p = Payload(PUBLIC)
    rts = [b["runtime"] for b in p.blocks]
    # the 3 Cisco IOS (dynamips) blocks are not public; they come from the private manifest
    assert (len(rts), rts.count("qemu"), rts.count("dynamips"), rts.count("docker")) == (41, 20, 0, 21)
    assert len(p.unique_images()) == 22


def test_place_file_copy_verifies_checksum(tmp_path):
    src = tmp_path / "a"; src.write_bytes(b"hello" * 1000)
    with pytest.raises(RuntimeError):
        place_file(src, tmp_path / "out/b", expected_sha="0" * 64)
    assert not (tmp_path / "out/b").exists() and not partial_path(tmp_path / "out/b").exists()
    m, sha = place_file(src, tmp_path / "out/b", expected_sha=sha256_file(src))
    assert m == "copy" and sha == sha256_file(src)


def test_place_file_link_policy(tmp_path):
    src = tmp_path / "a"; src.write_bytes(b"x" * 4096)
    m, _ = place_file(src, tmp_path / "h", methods=("hardlink", "symlink"))
    assert m == "hardlink" and os.stat(src).st_nlink == 2
    m, _ = place_file(src, tmp_path / "s", methods=("symlink",))
    assert m == "symlink" and (tmp_path / "s").is_symlink()
    with pytest.raises(CopyNotAllowed):
        place_file(src, tmp_path / "n", methods=())


def test_link_methods_never_copy_unless_allowed(tmp_path):
    assert "copy" not in link_methods(tmp_path, tmp_path)
    assert link_methods(tmp_path, tmp_path)[:2] == ["hardlink", "symlink"]
    assert link_methods(tmp_path, tmp_path, allow_copy=True)[-1] == "copy"


# ---------------- paths (Linux + Windows)
def test_linux_paths(tmp_path):
    lp = by_name("linux", home=tmp_path, env={})
    assert lp.default_root() == tmp_path / "VASYA-GNS-LAB"
    assert lp.validate_root("/usr/lib/x")
    assert lp.validate_root("relative/dir")
    assert lp.validate_root(str(tmp_path / "ok")) == []
    assert lp.applications_dir() == tmp_path / ".local/share/applications"
    lp2 = by_name("linux", home=tmp_path, env={"XDG_DATA_HOME": "/x/data", "VASYA_ROOT": "/opt/v"})
    assert str(lp2.applications_dir()) == "/x/data/applications" and str(lp2.default_root()) == "/opt/v"


def test_windows_paths():
    wp = by_name("windows", env={"LOCALAPPDATA": r"C:\Users\Вася\AppData\Local",
                                 "APPDATA": r"C:\Users\Вася\AppData\Roaming"})
    assert wp.default_root() == PureWindowsPath(r"C:\Users\Вася\AppData\Local\VASYA-GNS-LAB")
    assert wp.validate_root(r"C:\Labs\VASYA") == []
    assert windows_path_problems(r"C:\Labs\CON\x")
    assert windows_path_problems(r"C:\Labs\bad|name")
    assert windows_path_problems(r"Labs\relative")
    assert windows_path_problems("C:\\" + "a" * 210)
    assert wp.needs_admin_for(r"C:\Program Files\VASYA")
    assert str(wp.gns3_config_candidates()[0]).endswith(r"GNS3\2.2\gns3_server.ini")
    assert str(wp.applications_dir()).endswith(r"Start Menu\Programs")


# ---------------- permissions
@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permissions")
def test_needs_admin_for_readonly(tmp_path):
    ro = tmp_path / "ro"; ro.mkdir(); ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    lp = by_name("linux", home=tmp_path, env={})
    try:
        assert lp.needs_admin_for(ro / "sub" / "file")
        assert not lp.needs_admin_for(tmp_path / "rw" / "file")
    finally:
        ro.chmod(0o755)


# ---------------- dependency discovery
def test_dep_discovery_uses_path(tmp_path, monkeypatch):
    b = tmp_path / "bin"; b.mkdir()
    for n in ("dynamips", "ubridge"):
        f = b / n; f.write_text("#!/bin/sh\necho 1\n"); f.chmod(0o755)
    monkeypatch.setenv("PATH", str(b))
    monkeypatch.delenv("VASYA_GNS3SERVER_BIN", raising=False)
    d = detect_all(by_name("linux", home=tmp_path, env={}))
    assert d["dynamips"]["present"] and d["ubridge"]["present"]
    assert not d["docker"]["present"] and not d["gns3server"]["present"]
    assert {t["id"] for t in metadata()} >= {"gns3server", "qemu", "dynamips", "ubridge", "docker",
                                             "wireshark", "packettracer"}


def test_tool_registry_fields():
    for t in metadata():
        for k in ("why_ru", "why_en", "functions", "source", "update", "removal"):
            assert t.get(k), (t["id"], k)


# ---------------- planning classification
def test_classify(tmp_path):
    f = tmp_path / "x"; f.write_bytes(b"abc")
    sha = sha256_file(f)
    assert classify(tmp_path / "nope", sha, 3) == "NEW"
    assert classify(f, sha, 3) == "IDENTICAL"
    assert classify(f, "0" * 64, 3) == "CONFLICT"
    assert classify(f, sha, 4) == "CONFLICT"


# ---------------- templates / GNS3 compat (static)
def test_all_public_templates_build():
    p = Payload(PUBLIC)
    for b in p.blocks:
        g = json.load(open(PUBLIC / b["template"])) if b.get("template") else None
        t = build_template(b, g)
        assert t and t["category"] in VALID_CATEGORIES and t["template_type"] == b["runtime"]
        if b["runtime"] == "dynamips":
            assert "console_auto_start" not in t and t["image"]
        if b["runtime"] == "qemu":
            assert t["hda_disk_image"] or t.get("cdrom_image") or t.get("kernel_image")


def test_docker_category_switch():
    assert map_category("multilayer_switch") == "switch"
    b = {"block_id": "onos", "name": "ONOS", "runtime": "docker", "category": "multilayer_switch",
         "docker_image": "onosproject/onos:latest"}
    t = build_template(b, {"category": "multilayer_switch", "docker": {"adapters": 16}})
    assert t["category"] == "switch" and t["image"] == "onosproject/onos:latest"
    t2 = build_template(b, {"category": "multilayer_switch"}, {"__docker__:onos": "vasya-gns-lab/onos:x"})
    assert t2["image"] == "vasya-gns-lab/onos:x"


# ---------------- catalog
def test_catalog_186():
    c = Catalog()
    cnt = c.counts()
    assert cnt["TOTAL"] == 186 and cnt["READY"] == 41
    assert sum(v for k, v in cnt.items() if k != "TOTAL") == 186
    for e in c.entries:
        assert e["status"] and e["reason"] is not None and e["purpose_ru"] and e["runtime"]
        if e["status"] != "READY":
            assert e["reason"]
    assert c.search("frr")[0]["block_id"] == "frr"
    assert all(e["runtime"] == "docker" for e in c.search(runtime="docker"))
    assert all(e["status"] == "NEEDS_LICENSE" for e in c.search(status="NEEDS_LICENSE"))


def test_image_import_detect_and_match(tmp_path):
    c = Catalog()
    target = next(e for e in c.entries if e["status"] != "READY" and e["required_images"]
                  and e["required_images"][0].get("filename", "").endswith(".qcow2"))
    im = target["required_images"][0]
    f = tmp_path / im["filename"]
    f.write_bytes(b"QFI\xfb" + b"\0" * 2000)
    a = image_import.analyse(f, c)
    assert a["type"] == "qcow2" and a["format_ok"]
    assert a["verdict"] == "PROBABLE_MATCH" and a["suggested_block"] == target["block_id"]
    # exact md5 match -> VERIFIED
    c.by_id[target["block_id"]]["required_images"][0]["md5"] = a["md5"]
    assert image_import.analyse(f, c)["verdict"] == "VERIFIED_MATCH"
    iso = tmp_path / "x.iso"
    data = bytearray(0x9000); data[0x8001:0x8006] = b"CD001"; iso.write_bytes(bytes(data))
    assert image_import.detect_type(iso) == "iso"


def test_image_register_refuses_unverified(tmp_path):
    from vasya.core.oplog import OpLog
    lay = Layout(tmp_path / "r").ensure()
    t = txnmod.Transaction(lay)
    with pytest.raises(ValueError):
        image_import.register(lay, {"verdict": "NO_MATCH", "format_ok": True}, "x", t, OpLog(lay.Logs))


# ---------------- packet tracer
def test_packet_tracer_detection_never_bundles(tmp_path):
    lp = by_name("linux", home=tmp_path, env={})
    d = packet_tracer.detect(lp)
    assert d["official_url"] == "https://www.netacad.com/resources/lab-downloads"
    assert d["status"] in packet_tracer.STATES
    fake = tmp_path / "pt.deb"; fake.write_bytes(b"MZ" + b"0" * 100)
    v = packet_tracer.verify_installer(fake, "linux")
    assert v["verified"] is False


def test_packet_tracer_deb_control(tmp_path):
    import io, tarfile, gzip
    ctl = b"Package: packettracer\nVersion: 8.2.2\nMaintainer: Cisco Systems <x@cisco.com>\n"
    tb = io.BytesIO()
    with tarfile.open(fileobj=tb, mode="w:gz") as t:
        ti = tarfile.TarInfo("./control"); ti.size = len(ctl); t.addfile(ti, io.BytesIO(ctl))
    data = tb.getvalue()
    def member(name, d):
        h = f"{name:<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(d):<10}`\n".encode()
        return h + d + (b"\n" if len(d) % 2 else b"")
    deb = b"!<arch>\n" + member("debian-binary", b"2.0\n") + member("control.tar.gz", data) + \
        member("data.tar.xz", b"\0" * (60 * 1024 * 1024))
    f = tmp_path / "CiscoPacketTracer_822_Ubuntu_64bit.deb"; f.write_bytes(deb)
    v = packet_tracer.verify_installer(f, "linux")
    assert v["package"] == "packettracer" and v["verified"], v


# ---------------- diagnostics redaction
def test_redaction():
    txt = ("password = hunter2\nuser=x\n{\"token\": \"abc\"}\nAuthorization: Basic Zm9vOmJhcg==\n"
           "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n"
           "ghp_abcdefghijklmnopqrstuvwxyz0123\n/home/vasya/projects")
    r = diagnostics.redact(txt, home="/home/vasya")
    for secret in ("hunter2", "\"abc\"", "Zm9vOmJhcg", "AAAA", "ghp_abcdef", "/home/vasya"):
        assert secret not in r, secret


# ---------------- WAL
def test_wal_torn_line_and_pending(tmp_path):
    lay = Layout(tmp_path).ensure()
    t = txnmod.Transaction(lay)
    t.intent("0001", {"kind": "file", "path": "/a"}); t.commit("0001")
    t.intent("0002", {"kind": "file", "path": "/b"})
    with open(t.path, "a") as f:
        f.write('{"type": "COMMIT", "op_')  # torn write from a crash
    r = txnmod.receipt_from_wal(t.path)
    assert r["status"] == txnmod.INCOMPLETE
    assert [x["path"] for x in r["committed"]] == ["/a"] and [x["path"] for x in r["pending"]] == ["/b"]
    assert len(txnmod.owned_resources(lay)) == 2


# ---------------- legacy defect regression
def test_package_never_ships_defective_legacy_rollback():
    """1.0.1 archives shipped Pack/lib/rollback.py sha 6f657f7a… (defective). 1.1.0 ships no
    Pack/lib at all; the payload builder copies data only."""
    root = Path(__file__).resolve().parent.parent
    bad = "6f657f7a808f5cdf98879d9fe2298d5f85de46ce79239b91d7019a3436ff7dd1"
    for p in list((root / "src").rglob("*.py")) + list((root / "scripts").rglob("*")):
        if p.is_file():
            assert sha256_file(p) != bad, p
    src = (root / "scripts/make_payload.py").read_text()
    assert "copytree" not in src and "lib" not in [s.strip("'\"") for s in src.split()]
