# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline image archives: one archive per unique image, automatic restore with sha256 +
archive manifest + image ID + tag verification, never a pull. Driven by a fake engine CLI that really
reads the (zstd) docker-archive stream; no podman/docker is touched."""
import hashlib, io, json, subprocess, sys, tarfile
from pathlib import Path
import pytest
from vasya import api
from vasya.runtime import docker_images as di
from vasya.runtime import docker_backend as dbk
from conftest import make_payload

FAKE = r'''
import json, sys, tarfile, os
st_p = os.environ["FAKE_ENGINE_STATE"]
st = json.load(open(st_p)) if os.path.exists(st_p) else {"tags": {}, "ids": [], "calls": []}
a = sys.argv[1:]; st["calls"].append(a[:2])
def save(): json.dump(st, open(st_p, "w"))
def rid(x):
    x = x.split(":", 1)[-1] if x.startswith("sha256:") else x
    for i in st["ids"]:
        if i.startswith(x): return i
    t = x if ":" in x.rsplit("/", 1)[-1] else x + ":latest"
    return st["tags"].get(t)
if a[:2] == ["image", "inspect"]:
    i = rid(a[-1]); save()
    if not i: sys.exit(125)
    print("sha256:" + i); sys.exit(0)
if a[0] == "load":
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tf:
        for m in tf:
            if m.name == "manifest.json":
                man = json.load(tf.extractfile(m))
    for e in man:
        i = e["Config"].replace(".json", "").split(":")[-1]
        st["ids"].append(i)
        for t in e.get("RepoTags") or []: st["tags"][t] = i
    save(); print("Loaded image"); sys.exit(0)
if a[0] == "tag":
    i = rid(a[1]); st["tags"][a[2]] = i; save(); sys.exit(0 if i else 125)
if a[0] == "pull":
    save(); sys.exit(125)
save(); sys.exit(2)
'''



@pytest.fixture(autouse=True)
def _no_builtin_pins(tmp_path, monkeypatch):
    """Mechanism tests use synthetic image IDs for real refs (alpine); the shipped pins
    would (correctly) reject them. Pins are tested in test_docker_pins.py."""
    monkeypatch.setattr(di, "BUILTIN", tmp_path / "no-builtin-pins.json")


def _archive(d, name, iid, tags, zst=True):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for n, b in ((f"{iid}.json", b"{}"), ("manifest.json",
                     json.dumps([{"Config": f"{iid}.json", "RepoTags": tags, "Layers": []}]).encode())):
            ti = tarfile.TarInfo(n); ti.size = len(b); tf.addfile(ti, io.BytesIO(b))
    raw = buf.getvalue()
    p = d / name
    if zst:
        p.write_bytes(subprocess.run(["zstd", "-q", "-c"], input=raw, capture_output=True, check=True).stdout)
    else:
        p.write_bytes(raw)
    return p


def _setup(tmp_path, monkeypatch, zst=True):
    ctx = api.open_ctx(tmp_path / "R", make_payload(tmp_path / "p", docker=True))
    d = ctx.layout.root / "Images" / "docker"; d.mkdir(parents=True)
    iid = hashlib.sha256(b"alpine").hexdigest()
    name = f"alpine-{iid[:12]}.tar" + (".zst" if zst else "")
    p = _archive(d, name, iid, ["docker.io/library/alpine:latest"], zst)
    man = {"format": 1, "images": [{"refs": ["alpine:latest", "docker.io/library/alpine:3.24"], "archive": name,
                                    "archive_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                    "archive_bytes": p.stat().st_size, "image_id": "sha256:" + iid,
                                    "repo_digest": "sha256:c26612752c78"}]}
    (d / di.MANIFEST).write_text(json.dumps(man))
    fake = tmp_path / "fake_engine.py"; fake.write_text(FAKE)
    state = tmp_path / "engine.json"
    monkeypatch.setenv("FAKE_ENGINE_STATE", str(state))
    return ctx, d, p, iid, [sys.executable, str(fake)], state


@pytest.mark.parametrize("zst", [True, False])
def test_restore_verifies_and_tags_and_is_idempotent(tmp_path, monkeypatch, zst):
    ctx, d, p, iid, cmd, state = _setup(tmp_path, monkeypatch, zst)
    r = di.restore(ctx, "alpine", cmd)
    assert r["status"] == "RESTORED" and r["image_id"] == "sha256:" + iid
    assert set(r["retagged"]) == {"alpine:latest", "docker.io/library/alpine:3.24"}
    st = json.loads(state.read_text())
    assert ["pull"] not in [c[:1] for c in st["calls"]]
    assert di.restore(ctx, "alpine:latest", cmd)["status"] == "PRESENT"
    assert di.validate_dir(d) == []


def test_restore_refuses_corrupt_or_wrong_archives(tmp_path, monkeypatch):
    ctx, d, p, iid, cmd, state = _setup(tmp_path, monkeypatch)
    good = p.read_bytes()
    p.write_bytes(good[:-1] + bytes([good[-1] ^ 1]))
    m = json.loads((d / di.MANIFEST).read_text())
    m["images"][0]["archive_bytes"] = None
    (d / di.MANIFEST).write_text(json.dumps(m))
    r = di.restore(ctx, "alpine", cmd)
    assert r["status"] == "ARCHIVE_INVALID" and "sha256" in r["error"]
    other = _archive(d, p.name, hashlib.sha256(b"evil").hexdigest(), ["alpine:latest"])  # right name, wrong image
    m["images"][0]["archive_sha256"] = hashlib.sha256(other.read_bytes()).hexdigest()
    (d / di.MANIFEST).write_text(json.dumps(m))
    r = di.restore(ctx, "alpine", cmd)
    assert r["status"] == "ARCHIVE_INVALID" and "expected" in r["error"]
    assert not state.exists() or not json.loads(state.read_text())["ids"], "nothing may be loaded"
    assert di.restore(ctx, "busybox", cmd)["status"] == "NO_ARCHIVE"


def test_validate_dir_flags_tar_and_zstd_duplicates_and_strays(tmp_path, monkeypatch):
    ctx, d, p, iid, cmd, state = _setup(tmp_path, monkeypatch)
    _archive(d, p.name[:-4], iid, ["alpine:latest"], zst=False)          # same image as plain .tar too
    (d / "stray.tar").write_bytes(b"x")
    issues = di.validate_dir(d)
    assert any(i.startswith("DUPLICATE_FORMAT") for i in issues) and "UNLISTED stray.tar" in issues


def test_ensure_images_restores_missing_receipted_image_before_server_start(tmp_path, monkeypatch):
    ctx, d, p, iid, cmd, state = _setup(tmp_path, monkeypatch)
    lref = "vasya-gns-lab/rX/alpine:latest"
    monkeypatch.setattr(dbk, "receipted_images", lambda c, engine=None: [("alpine:latest", lref, "t-docker")])
    monkeypatch.setattr(dbk, "engine_cmd", lambda c: (cmd, None))
    built = []

    def fake_build(c, cm, env, ref, lr, bid, tag="x"):
        built.append((ref, lr)); subprocess.run(cm + ["tag", ref, lr])
        return subprocess.CompletedProcess([], 0, "", "")
    monkeypatch.setattr(dbk, "build_labelled", fake_build)
    out = dbk.ensure_images(ctx)
    assert out[0]["status"] == "RESTORED" and out[0]["labelled_status"] == "REBUILT" and built == [("alpine:latest", lref)]
    out = dbk.ensure_images(ctx)
    assert out[0]["status"] == "PRESENT" and "labelled_status" not in out[0] and len(built) == 1


def test_manifest_from_tested_images_csv(tmp_path):
    c = tmp_path / "docker_images.csv"
    c.write_text("component,image,amd64_digest,image_id,archive,sha256,bytes\n"
                 "openvswitch,gns3/openvswitch:latest,sha256:aa,sha256:11,/home/u/VASYA-GNS-LAB/Images/docker/ovs-11.tar.zst,ff,10\n"
                 "openvswitch-management,gns3/openvswitch:latest;gns3/ovs-mgmt:latest,sha256:aa,sha256:11,ovs-11.tar.zst,ff,10\n"
                 "alpine,alpine:latest,sha256:c2,sha256:b9,alpine-b9.tar.zst,ee,5\n")
    m = di.manifest_from_csv(c)
    assert len(m["images"]) == 2                                          # one archive per unique image
    ovs = m["images"][0]
    assert ovs["archive"] == "ovs-11.tar.zst" and ovs["refs"] == ["gns3/openvswitch:latest", "gns3/ovs-mgmt:latest"]
    assert ovs["repo_digest"] == "sha256:aa" and ovs["image_id"] == "sha256:11" and ovs["archive_bytes"] == 10
    bad = tmp_path / "bad.csv"; bad.write_text("x,y\n1,2\n")
    with pytest.raises(ValueError):
        di.manifest_from_csv(bad)
