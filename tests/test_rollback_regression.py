# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression for the 1.0.1 rollback defect (found in the 1.0.1 baseline audit).

1.0.1 archives shipped Pack/lib/rollback.py sha 6f657f7a… which did not sweep the
alternate-name images ``vasya-<sha16>-<file>`` created when a user file blocked the
normal name. The fix (889cffca…) went into the 1.0.1 release candidate; 1.1.0 replaces
the legacy code with the WAL transaction engine. These tests prove, with a real
SIGKILL-style crash (os._exit inside the copy) against a real gns3server 2.2.61:
  * crash during an ALT placement -> rollback -> 0 image blobs, user file intact;
  * crash -> resume -> completes, every image present exactly once, no partials;
  * the legacy fixed/defective scripts behave as documented (when 1.0.1 trees exist).
"""
import json, os, subprocess, sys
from pathlib import Path
import pytest
from conftest import have_gns3, cli, make_payload
from vasya import api
from vasya.core import txn as txnmod
from vasya.core.util import sha256_file

FIXED = "889cffca6d15e6803d3b423fd73d1667cf4f38a570c90e7b66864cbc1eec3698"
DEFECTIVE = "6f657f7a808f5cdf98879d9fe2298d5f85de46ce79239b91d7019a3436ff7dd1"
GNS3_OWN = ("empty", "OVMF", "config.img")  # files gns3server itself creates in its images dir


def _payload_shas(payload):
    return {p.name for p in (Path(payload) / "images" / "sha256").iterdir()}


def _image_blobs_in(root, shas):
    """Every regular file under root whose content is one of the payload images."""
    out = []
    for p in Path(root).rglob("*"):
        if p.is_file() and not p.is_symlink() and p.stat().st_size > 1024 * 1024:
            if sha256_file(p) in shas:
                out.append(str(p))
    return out


def _alt_conflict(root, payload):
    """Create a user-owned file at the normal image name -> installer must use PLACE_IMAGE_ALT."""
    plan = json.loads(cli(root, payload, "plan", "--mode", "FULL", "--allow-copy").stdout)
    op = next(o for o in plan["operations"] if o["action"] == "PLACE_IMAGE")
    user = Path(op["target"]); user.parent.mkdir(parents=True, exist_ok=True)
    user.write_bytes(b"user's own image - must survive everything")
    plan = json.loads(cli(root, payload, "plan", "--mode", "FULL", "--allow-copy").stdout)
    alt = next(o for o in plan["operations"] if o["action"] == "PLACE_IMAGE_ALT")
    return user, alt


@have_gns3
def test_crash_during_alt_placement_rollback_leaves_zero_image_blobs(tmp_path):
    payload = make_payload(tmp_path / "p", n_images=4)
    root = tmp_path / "root"
    user, alt = _alt_conflict(root, payload)
    before = sha256_file(user)
    r = cli(root, payload, "install", "--mode", "FULL", "-y", "--allow-copy",
            env={"VASYA_TEST_CRASH_OP": alt["op_id"], "VASYA_TEST_CRASH_MODE": "mid_copy"})
    assert r.returncode == 137, r.stdout + r.stderr
    ctx = api.open_ctx(root, payload)
    assert api.verdict(api.status(ctx)) == "NEEDS_RECOVERY"
    rb = api.rollback(ctx)
    assert rb["undone"] and all(u["result"] in ("REMOVED", "ABSENT") for u in rb["undone"]), rb
    img_root = Path(ctx.state.load()["gns3"]["images_path"])
    assert not list(img_root.rglob("vasya-*")), "alternate-name leftovers (the 1.0.1 defect)"
    assert not list(Path(root).rglob("*.vasya-partial"))
    assert _image_blobs_in(root, _payload_shas(payload)) == []          # residue = 0 image blobs
    assert user.exists() and sha256_file(user) == before                  # user's file untouched
    assert txnmod.incomplete(ctx.layout) == []
    rep = api.uninstall(api.open_ctx(root, payload), "full", report_dir=tmp_path)
    assert rep["residue"]["clean"], rep["residue"]


@have_gns3
def test_crash_then_resume_places_each_image_once(tmp_path):
    payload = make_payload(tmp_path / "p", n_images=4)
    root = tmp_path / "root"
    plan = json.loads(cli(root, payload, "plan", "--mode", "FULL", "--allow-copy").stdout)
    places = [o for o in plan["operations"] if o["action"] == "PLACE_IMAGE"]
    r = cli(root, payload, "install", "--mode", "FULL", "-y", "--allow-copy",
            env={"VASYA_TEST_CRASH_OP": places[-1]["op_id"], "VASYA_TEST_CRASH_MODE": "mid_copy"})
    assert r.returncode == 137
    r = cli(root, payload, "resume")
    assert r.returncode == 0, r.stdout + r.stderr
    ctx = api.open_ctx(root, payload)
    assert api.static_verify(ctx)["status"] == "PASS"
    img_root = Path(ctx.state.load()["gns3"]["images_path"])
    placed = [p for p in img_root.rglob("*") if p.is_file() and not p.name.startswith(GNS3_OWN)]
    assert len(placed) == len(places) == len({str(p) for p in placed})
    assert sorted(str(p) for p in placed) == sorted(o["target"] for o in places)
    assert not list(Path(root).rglob("*.vasya-partial"))
    rep = api.uninstall(ctx, "full", report_dir=tmp_path)
    assert rep["residue"]["clean"], rep["residue"]
    assert not Path(root).exists() or _image_blobs_in(root, _payload_shas(payload)) == []


from conftest import LEGACY, RC_PACK, OLD_PACK
LEGACY_TEST = LEGACY / "phaseA" / "test_rollback_regression.py"


@pytest.mark.skipif(not (LEGACY_TEST.exists() and RC_PACK.exists()), reason="1.0.1 code base not available (VASYA_TEST_LEGACY, VASYA_TEST_RC_PACK)")
def test_legacy_fixed_rollback_sweeps_alt_leftovers():
    assert sha256_file(RC_PACK / "lib" / "rollback.py") == FIXED
    r = subprocess.run([sys.executable, str(LEGACY_TEST), str(RC_PACK)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(not (LEGACY_TEST.exists() and OLD_PACK.exists()), reason="1.0.1 code base not available (VASYA_TEST_LEGACY, VASYA_TEST_OLD_PACK)")
def test_legacy_shipped_rollback_is_the_defective_one():
    """Documents WHY 1.1.0 must not reuse the shipped 1.0.1 code."""
    assert sha256_file(OLD_PACK / "lib" / "rollback.py") == DEFECTIVE
    r = subprocess.run([sys.executable, str(LEGACY_TEST), str(OLD_PACK)], capture_output=True, text=True)
    assert r.returncode != 0, r.stdout


def test_110_ships_neither_legacy_file():
    repo = Path(__file__).resolve().parent.parent
    for p in list((repo / "src").rglob("*.py")) + list((repo / "packaging").rglob("*")):
        if p.is_file():
            assert sha256_file(p) not in (FIXED, DEFECTIVE), p
