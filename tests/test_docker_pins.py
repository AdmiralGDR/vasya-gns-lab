# SPDX-License-Identifier: GPL-3.0-or-later
"""Docker pins and template fixes: 20 unique images / 21 docker blocks, each pinned to the registry
digest + image ID that was archived and tested; python-go-perl-php name format; stonework empty
start_command; turnkey-wordpress opt-in inithooks preseed (not verified on hardware)."""
import csv, json, os, shlex, subprocess
from pathlib import Path
import pytest
from vasya.runtime import docker_images as di
from vasya.catalog import fixups as fx, turnkey
from vasya.catalog.catalog import Catalog
from vasya.gns3 import templates as tpl

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "docker"
CSV = FIX / "tested-images.csv"
PACK = ROOT / "src" / "vasya" / "data" / "catalog.json"


def _pins():
    return json.loads(di.BUILTIN.read_text())["images"]


def test_builtin_manifest_shape():
    imgs = _pins()
    assert len(imgs) == 20
    assert sum(e["archive_bytes"] for e in imgs) == 3966929514
    assert sum(len(e["blocks"]) for e in imgs) == 21
    ids = set()
    for e in imgs:
        assert e["repo_digest"].startswith("sha256:") and len(e["repo_digest"]) == 71
        assert e["image_id"].startswith("sha256:") and len(e["image_id"]) == 71
        assert e["archive"] == f"{e['blocks'][0]}-{e['repo_digest'][7:19]}.tar.zst"
        assert len(e["archive_sha256"]) == 64 and e["image_id"] not in ids
        ids.add(e["image_id"])
    ovs = di.pin_for_ref("gns3/openvswitch:latest")
    assert ovs["blocks"] == ["openvswitch", "openvswitch-management"]
    assert di.pin_for_ref("ntop/ntopng:latest") and not di.pin_for_ref("ntop/ntopng:stable")
    assert di.pin_for_ref("docker.io/library/alpine:latest")["blocks"] == ["alpine-linux"]


def test_importer_regenerates_identical_manifest(tmp_path):
    out = tmp_path / "m.json"
    r = subprocess.run(["python3", str(ROOT / "scripts" / "import_docker_archives.py"), "--csv", str(CSV),
                        "--index", str(FIX / "index.json"),
                        "--no-files", "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(out.read_text())["images"] == _pins()
    rows = list(csv.DictReader(open(CSV)))
    for row in rows:      # every CSV digest is pinned for its template
        p = di.pin_for_block(row["template"])
        assert p["repo_digest"] == row["digest"] and p["archive_sha256"] == row["archive_sha256"]


def test_pin_applied_to_blocks_templates_catalog():
    cat = Catalog()
    for e in _pins():
        for bid in e["blocks"]:
            b = fx.apply_block({"block_id": bid, "name": bid, "runtime": "docker",
                                "docker_image": cat.get(bid)["docker_image"]}, [], lambda b: None)
            assert (b["docker_image"], b["docker_digest"], b["docker_image_id"]) == \
                (e["refs"][0], e["repo_digest"], e["image_id"])
            assert cat.get(bid)["docker_image"] == e["refs"][0]
            t = tpl.build_template(b, {"category": "guest", "docker": {"image": "x"}})
            assert t["image"] == e["refs"][0]
            assert f"VASYA pin: {e['refs'][0]}@{e['repo_digest']}" in t["usage"]
    b = fx.apply_block({"block_id": "ntopng", "runtime": "docker", "docker_image": "ntop/ntopng:stable"}, [], None)
    assert b["docker_image"] == "ntop/ntopng:latest" and "tested pin" in b["fixups"][0]


def test_unpinned_block_untouched():
    b = {"block_id": "not-pinned", "runtime": "docker", "docker_image": "x/y:1"}
    assert fx.apply_block(b, [], None) is b


def test_labelled_image_carries_pin():
    df = __import__("vasya.runtime.docker_backend", fromlist=["x"]).labelled_dockerfile(
        "gns3/ipterm:latest", "ipterm", Path("/tmp/R"))
    p = di.pin_for_ref("gns3/ipterm:latest")
    assert f"org.vasya.base_digest={p['repo_digest']}" in df and f"org.vasya.base_id={p['image_id']}" in df


def test_archive_dir_without_manifest_uses_pins_and_rejects_conflicts(tmp_path, monkeypatch):
    d = tmp_path / "docker"; d.mkdir()
    e = di.pin_for_ref("alpine")
    (d / e["archive"]).write_bytes(b"x")
    monkeypatch.setattr(di, "archive_dirs", lambda ctx: [d])
    got = di.find(None, "alpine:latest")
    assert got["archive"] == e["archive"] and got["_source"] == "builtin"
    assert di.find(None, "gns3/ipterm:latest") is None         # archive file absent -> no entry
    bad = dict(e, image_id="sha256:" + "0" * 64, refs=["alpine:latest"])
    assert di.pin_conflict(bad) and not di.pin_conflict(e)
    (d / di.MANIFEST).write_text(json.dumps({"format": 1, "images": [dict(bad, archive=e["archive"])]}))
    assert di.find(None, "alpine") is None                       # own manifest contradicts the pin


def test_repo_of():
    assert di.repo_of("alpine") == "alpine" and di.repo_of("gns3/ipterm:latest") == "gns3/ipterm"
    assert di.repo_of("reg:5000/a/b:1@sha256:x") == "reg:5000/a/b"
    assert di.repo_of("ghcr.io/pantheontech/stonework") == "ghcr.io/pantheontech/stonework"


def _blk(bid):
    return fx.apply_block({"block_id": bid, "name": bid, "runtime": "docker",
                           "docker_image": Catalog().get(bid)["docker_image"]}, [], None)


def _gns3a(bid):
    return json.loads((ROOT / "src" / "vasya" / "data" / "appliances" / f"{bid}.gns3a").read_text())


def test_python_go_perl_php_name_format():
    t = tpl.build_template(_blk("python-go-perl-php"), _gns3a("python-go-perl-php"))
    assert t["default_name_format"] == "PythonGoPerlPHP-{0}"
    assert t["default_name_format"].format(1).replace("-", "").isalnum()
    other = tpl.build_template(_blk("ipterm"), _gns3a("ipterm"))
    assert other["default_name_format"] == "{name}-{0}"


def test_stonework_empty_start_command():
    g = _gns3a("stonework")
    assert g["docker"].get("start_command")          # the gns3a still names the missing script
    t = tpl.build_template(_blk("stonework"), g)
    assert t["start_command"] == "" and t["image"] == "ghcr.io/pantheontech/stonework"


def test_turnkey_default_is_stock(monkeypatch):
    monkeypatch.delenv(turnkey.PRESEED_ENV, raising=False)
    g = _gns3a("turnkey-wordpress")
    t = tpl.build_template(_blk("turnkey-wordpress"), g)
    assert t["start_command"] == (g["docker"].get("start_command") or "")
    assert "ROOT_PASS" not in t["environment"] and "preseed" not in t["usage"]


def test_turnkey_preseed_opt_in(monkeypatch):
    monkeypatch.setenv(turnkey.PRESEED_ENV, "1")
    t = tpl.build_template(_blk("turnkey-wordpress"), _gns3a("turnkey-wordpress"))
    env = dict(l.split("=", 1) for l in t["environment"].splitlines())
    assert set(turnkey.VARS) <= set(env) and env["HUB_APIKEY"] == env["SEC_UPDATES"] == "SKIP"
    for k in ("ROOT_PASS", "DB_PASS", "APP_PASS"):
        assert len(env[k]) == 16 and env[k].isalnum() and env[k] in t["usage"]
    assert "UNVERIFIED" in t["usage"]
    assert shlex.split(t["start_command"])[:2] == ["/bin/sh", "-c"]
    t2 = tpl.build_template(_blk("ipterm"), _gns3a("ipterm"))
    assert "ROOT_PASS" not in (t2["environment"] or "")       # only TurnKey blocks


def test_turnkey_wrapper_writes_conf_then_execs_start(tmp_path):
    """Run the exact start_command (via shlex, as gns3server builds Cmd) with conf/start.sh redirected."""
    conf, start = tmp_path / "inithooks.conf", tmp_path / "start.sh"
    start.write_text('#!/bin/sh\necho "START $$"\n'); os.chmod(start, 0o755)
    cmd = shlex.split(turnkey.START_COMMAND.replace(turnkey.CONF, str(conf)).replace(turnkey.START, str(start)))
    vals = dict(turnkey.answers(), APP_EMAIL="a@b.c")
    env = dict(vals, PATH="/usr/bin:/bin")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and r.stdout.startswith("START "), r.stderr
    lines = conf.read_text().splitlines()
    assert lines == [f'export {k}="{vals[k]}"' for k in turnkey.VARS]
    assert oct(conf.stat().st_mode & 0o777) == "0o600"
    sourced = subprocess.run(["/bin/sh", "-c", f". {conf}; echo $APP_PASS $HUB_APIKEY"],
                             capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert sourced.stdout.split() == [vals["APP_PASS"], "SKIP"]
    conf.write_text("export ROOT_PASS=keep\n")                 # an existing conf is never overwritten
    subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
    assert conf.read_text() == "export ROOT_PASS=keep\n"
