# SPDX-License-Identifier: GPL-3.0-or-later
"""Rollback deletes only receipt-owned files whose state (size + sha256) still matches."""
import os
from pathlib import Path
from conftest import have_gns3
from vasya import api
from vasya.core.util import sha256_file


def _images_dir(ctx):
    return Path(ctx.state.load()["gns3"]["images_path"]) / "QEMU"


@have_gns3
def test_rollback_keeps_unowned_and_modified_handles_hardlinks(ctx, payload):
    r = api.install(ctx, "FULL")
    assert r["status"] == "OK", r.get("failed")
    d = _images_dir(ctx)
    t0, t1 = d / "t-disk0.qcow2", d / "t-disk1.qcow2"
    blk = ctx.block("t-qemu0")
    src0 = payload / "images/sha256" / blk["images"][0]["sha256"]
    # hardlinked placement: same inode as the CAS object, link count > 1
    assert os.stat(t0).st_ino == os.stat(src0).st_ino and os.stat(t0).st_nlink >= 2
    # not in any receipt: same directory, VASYA-looking names
    stranger = d / "user-router.qcow2"; stranger.write_bytes(b"mine")
    lookalike = d / f"vasya-{blk['images'][0]['sha256'][:16]}-t-disk0.qcow2"; lookalike.write_bytes(b"mine too")
    # owned name, but the bytes were replaced by the user (break the link, new content)
    t1.unlink(); t1.write_bytes(b"user replaced this disk")
    api.rollback(ctx, r["txid"])
    assert stranger.read_bytes() == b"mine" and lookalike.read_bytes() == b"mine too"
    assert t1.read_bytes() == b"user replaced this disk"          # hash mismatch -> kept
    assert not t0.exists()                                          # owned + matching -> removed
    assert src0.exists() and sha256_file(src0) == blk["images"][0]["sha256"]  # CAS data intact
    logs = "".join(p.read_text() for p in ctx.layout.Logs.rglob("*.jsonl"))
    assert "KEPT_MODIFIED" in logs


def test_receipt_size_mismatch_is_kept(tmp_path):
    from vasya.installer.rollback import undo_resource
    f = tmp_path / "x.qcow2"; f.write_bytes(b"abc")
    st, why = undo_resource(None, {"kind": "file", "path": str(f), "sha256": sha256_file(f), "size": 4})
    assert st == "KEPT_MODIFIED" and "size" in why and f.exists()
