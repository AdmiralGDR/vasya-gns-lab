# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows path: import Payload/* from the Linux release parts into <root>/Store."""
import json, subprocess, sys, tarfile
from pathlib import Path
import pytest
from conftest import make_payload
from vasya import api
from vasya.delivery import parts as P
from vasya.delivery import payload_import as PI


def _release(tmp_path, part_size=400):
    top = tmp_path / "src" / "VASYA-GNS-LAB-9.9.9"
    make_payload(top / "Payload", n_images=2, size=600_000)
    (top / "install.sh").write_text("#!/bin/sh\n")
    tarp = tmp_path / "rel.tar"
    with tarfile.open(tarp, "w") as tf:
        tf.add(top, arcname=top.name)
    arch = tmp_path / "VASYA-GNS-LAB-9.9.9-Linux.tar.zst"
    subprocess.run(["zstd", "-q", "-f", str(tarp), "-o", str(arch)], check=True)
    out = tmp_path / "dl"
    man = P.split(arch, out, part_size, {"top_dir": top.name, "version": "9.9.9"})
    arch.unlink()
    return out, man


@pytest.mark.parametrize("use_module", [True, False])
def test_import_payload_from_parts(tmp_path, monkeypatch, use_module):
    if not use_module:
        monkeypatch.setitem(sys.modules, "zstandard", None)   # force the zstd-binary path
    elif PI.__dict__.get("zstandard") is None:
        pytest.importorskip("zstandard")
    out, man = _release(tmp_path)
    assert len(man["parts"]) > 1
    ctx = api.open_ctx(tmp_path / "R")
    (tmp_path / "R").mkdir()
    (tmp_path / "R" / "payload_source.txt").write_text(str(out))
    # the user's own registered images must survive a (re-)import
    us = tmp_path / "R" / "Store" / "user" / "sha256"; us.mkdir(parents=True); (us / "x").write_text("u")
    r = api.import_payload(ctx)
    assert r["status"] == "OK", r
    st = tmp_path / "R" / "Store"
    assert (st / "manifests" / "pack.json").exists() and (us / "x").read_text() == "u"
    assert not (st / "install.sh").exists() and not (tmp_path / "R" / PI.STORE_PARTIAL).exists()
    ctx2 = api.open_ctx(tmp_path / "R")
    assert {b["block_id"] for b in ctx2.blocks()} >= {"t-qemu0", "t-dyn"}
    for b in ctx2.payload.blocks:
        for im in b["images"]:
            assert Path(ctx2.payload.image_path(im["sha256"])).exists()


def test_import_payload_corrupt_part_changes_nothing(tmp_path):
    out, man = _release(tmp_path)
    p = out / man["parts"][1]["name"]
    b = bytearray(p.read_bytes()); b[100] ^= 0xFF; p.write_bytes(bytes(b))
    ctx = api.open_ctx(tmp_path / "R")
    r = api.import_payload(ctx, str(out / f"{man['archive']}.parts.json"))
    assert r["status"] == "FAIL" and r["code"] == "PART_CORRUPT"
    assert not (tmp_path / "R" / "Store" / "manifests").exists()
