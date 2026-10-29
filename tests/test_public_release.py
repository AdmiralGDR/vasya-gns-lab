# SPDX-License-Identifier: GPL-3.0-or-later
"""The public source tree and public release outputs never contain disk images, proprietary
images or prebuilt binaries; everything third-party is pinned in third_party.lock."""
import json, os, re, subprocess, sys
from pathlib import Path
import pytest
from conftest import make_payload
from vasya.catalog.catalog import Catalog
from vasya.fetch import lock as L

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import build_bundle  # noqa: E402

IMAGE_EXT = re.compile(r"\.(image|bin|qcow2?|img|iso|vmdk|vdi|vhdx?|ova|elf|raw|deb|rpm|so(\.\d+)*|exe|dll|"
                       r"tar|tgz|gz|bz2|xz|zst|zip|7z)$", re.I)


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
        files = [REPO / f for f in out.decode().split("\0") if f]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    skip = {".git", "__pycache__", ".pytest_cache", "build", "dist", "tmp"}
    return [p for p in REPO.rglob("*") if p.is_file() and not skip & set(p.relative_to(REPO).parts)]


def test_source_tree_has_no_images_or_binaries():
    bad = []
    for p in _tracked():
        rel = p.relative_to(REPO).as_posix()
        if not p.is_file():
            continue
        with open(p, "rb") as f:
            head = f.read(4)
        if head == b"\x7fELF" or head[:2] == b"MZ" or IMAGE_EXT.search(p.name) or p.stat().st_size > 5 * 1024 * 1024:
            bad.append(rel)
    assert not bad, bad


def test_no_proprietary_entry_in_the_lock():
    lk = L.load()
    for sha, e in lk["images"].items():
        assert not e["filename"].lower().endswith(".image"), e["filename"]
        assert not any(b.startswith("cisco") for b in e["blocks"]), e
        assert not e.get("private")


def test_lock_shape():
    lk = L.load()
    assert lk["format"] == 1 and lk["tools"] and lk["libraries"] and lk["images"] and lk["docker"]
    hexd = re.compile(r"^[0-9a-f]{64}$")
    for kind in ("tools", "libraries"):
        for n, e in lk[kind].items():
            pk = e["package"]
            assert hexd.match(pk["sha256"]) and hexd.match(pk["member_sha256"]) and pk["size"] > 0, n
            assert pk["urls"] and all(u.startswith("https://") for u in pk["urls"]), n
            assert e["verified"]["level"] in ("VERIFIED", "UNVERIFIED") and e.get("license"), n
    for sha, e in lk["images"].items():
        assert hexd.match(sha) and e["size"] > 0 and e["urls"], e["filename"]
        assert all(u.startswith("https://") for u in e["urls"]), e["filename"]
        assert e["verified"]["level"] in ("VERIFIED", "UNVERIFIED")
        if e["verified"]["level"] == "VERIFIED" and e.get("compression"):
            assert hexd.match(e["download_sha256"]) and e["download_size"] > 0, e["filename"]
    for ref, d in lk["docker"].items():
        assert "@sha256:" in d["pinned"] and d["pinned"].split("/", 1)[0] in ("docker.io", "ghcr.io"), ref


def test_every_public_payload_image_is_pinned():
    man = json.loads((REPO / "packaging/payload/manifests/pack.json").read_text())
    lk = L.load()
    for b in man["blocks"]:
        assert b["runtime"] != "dynamips" and not b["block_id"].startswith("cisco"), b["block_id"]
        for im in b.get("images") or []:
            assert im["sha256"] in lk["images"], (b["block_id"], im["logical_filename"])


def test_public_stage_has_no_images_and_no_private_blocks(tmp_path):
    pack = make_payload(tmp_path / "pack")
    man = json.loads((pack / "manifests/pack.json").read_text())
    q = next(b for b in man["blocks"] if b["block_id"] == "t-qemu0")
    lock = {"images": {im["sha256"]: {"urls": ["https://example.invalid/x"]} for im in q["images"]}}
    out, n = build_bundle.stage_payload(pack, tmp_path / "pub" / "Payload", profile="public", lock=lock)
    ids = [b["block_id"] for b in out["blocks"]]
    assert ids == ["t-qemu0"] and n == 0
    assert set(out["excluded_private_blocks"]) == {"t-qemu2", "t-dyn"}      # t-dyn: an IOS-style block
    pl = tmp_path / "pub" / "Payload"
    assert not (pl / "images").exists()
    assert {p.relative_to(pl).parts[0] for p in pl.rglob("*") if p.is_file()} <= {"manifests", "appliances"}
    # the private profile keeps the offline behaviour (images hardlinked)
    out, n = build_bundle.stage_payload(pack, tmp_path / "priv" / "Payload", profile="private", lock=lock)
    assert n == len({im["sha256"] for b in man["blocks"] for im in b["images"]})


def test_real_public_stage_excludes_ios(tmp_path):
    out, n = build_bundle.stage_payload(REPO / "packaging/payload", tmp_path / "Payload", profile="public")
    assert n == 0 and len(out["blocks"]) == 41 and out["excluded_private_blocks"] == []
    assert not any(b["runtime"] == "dynamips" for b in out["blocks"])
    assert not list((tmp_path / "Payload").rglob("*.image"))


def test_public_build_refuses_image_options(tmp_path):
    for extra in (["--images", str(tmp_path)], ["--docker-archives", str(tmp_path)]):
        r = subprocess.run([sys.executable, str(REPO / "scripts/build_bundle.py"), "--out", str(tmp_path / "o"),
                            "--pyside", "x", "--gns3rt", "x"] + extra, capture_output=True, text=True)
        assert r.returncode != 0 and "only allowed with --profile private" in r.stderr
        assert not (tmp_path / "o").exists()


def test_catalog_marks_proprietary_images_as_user_supplied():
    for e in Catalog().entries:
        if e["block_id"].startswith("cisco-ios"):
            assert e["status"] in ("NEEDS_IMAGE", "NEEDS_LICENSE") and not e.get("packaged"), e["block_id"]


def test_bundle_carries_license_notice_and_third_party_list(tmp_path):
    top, app = tmp_path / "top", tmp_path / "top" / "App"
    di = app / "site-packages" / "demo-1.0.dist-info"
    di.mkdir(parents=True)
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: demo\nVersion: 1.0\nLicense: MIT\n\nbody\n")
    build_bundle.write_third_party(top, app)
    for n in ("LICENSE", "NOTICE", "THIRD_PARTY.md"):
        assert (top / n).read_bytes() == (REPO / n).read_bytes()
    tp = top / "THIRD_PARTY"
    assert "GNU GENERAL PUBLIC LICENSE" in (tp / "GPL-3.0.txt").read_text()
    assert "LESSER" in (tp / "LGPL-3.0.txt").read_text()
    assert "demo 1.0: MIT" in (tp / "python-licenses.txt").read_text()


def test_notice_names_the_registry_snapshot_and_disclaims_affiliation():
    t = (REPO / "NOTICE").read_text()
    assert "0c04ba6100a2fed7f25d9bac5fc289d836db27fa" in t and "not affiliated" in t
    assert (REPO / "LICENSE").read_text().startswith("                    GNU GENERAL PUBLIC LICENSE\n")
