# SPDX-License-Identifier: GPL-3.0-or-later
"""'Указать собственный образ' — analyse a user-supplied image and map it to a block.

Never downloads anything. Proprietary images (Cisco IOS/IOU, vendor VMs) are
only accepted from the user's own disk and are stored in the user CAS
(Store/user/sha256), which is never packaged or uploaded.
"""
import json, os, zipfile
from pathlib import Path
from ..core.util import hashes_file, load_json, write_json, utc_now, human_bytes
from ..core.cas import place_file

MAGICS = [
    (0, b"QFI\xfb", "qcow2"),
    (0, b"KDMV", "vmdk"),
    (0, b"conectix", "vhd"),
    (0, b"\x7fELF", "elf"),
    (0, b"PK\x03\x04", "zip"),
    (0, b"\x1f\x8b", "gzip"),
    (0, b"\xfd7zXZ\x00", "xz"),
    (0, b"!<arch>\n", "deb"),
    (0, b"MZ", "pe-exe"),
    (0, b"vhdxfile", "vhdx"),
]


def detect_type(path):
    p = Path(path)
    with open(p, "rb") as f:
        head = f.read(64)
        f.seek(0x8001)
        iso = f.read(5)
        f.seek(510)
        mbr = f.read(2)
    for off, magic, name in MAGICS:
        if head[off:off + len(magic)] == magic:
            if name == "elf":
                return "elf-ios" if _looks_like_ios(p) else "elf"
            return name
    if iso == b"CD001":
        return "iso"
    if mbr == b"\x55\xaa":
        return "raw-disk"
    if head.startswith(b"\x00\x00\x00\x00") and p.stat().st_size % 512 == 0:
        return "raw"
    return "unknown"


def _looks_like_ios(p):
    name = p.name.lower()
    if name.startswith(("c7200", "c3725", "c3745", "c2691", "c3640", "c3660", "c2600", "c1700")):
        return True
    with open(p, "rb") as f:
        blob = f.read(2 * 1024 * 1024)
    return b"Cisco IOS" in blob or b"CW_VERSION" in blob


FORMAT_FOR_EXT = {".qcow2": {"qcow2"}, ".img": {"raw", "raw-disk", "qcow2", "elf-ios", "elf"},
                  ".iso": {"iso"}, ".vmdk": {"vmdk"}, ".image": {"elf-ios", "elf", "zip"},
                  ".bin": {"elf-ios", "elf", "raw", "raw-disk", "zip"}, ".vhd": {"vhd"}}


def _expected_index(catalog):
    idx = []
    for e in catalog.entries:
        for im in e.get("required_images") or []:
            idx.append((e, im))
    return idx


def analyse(path, catalog, quick=False):
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": "file not found"}
    size = p.stat().st_size
    kind = detect_type(p)
    ext = p.suffix.lower()
    fmt_ok = kind in FORMAT_FOR_EXT.get(ext, {kind}) and kind != "unknown"
    sha, md5, _ = (None, None, size) if quick else hashes_file(p)
    matches = []
    for e, im in _expected_index(catalog):
        score, why = 0, []
        if md5 and im.get("md5") and md5 == im["md5"]:
            score += 100; why.append("md5 exact")
        if im.get("filename") and im["filename"].lower() == p.name.lower():
            score += 20; why.append("filename")
        if im.get("size") and int(im["size"]) == size:
            score += 10; why.append("size")
        if score >= 20:
            matches.append({"block_id": e["block_id"], "name": e["name"], "status": e["status"],
                            "filename": im.get("filename"), "score": score, "why": why,
                            "verified": "md5 exact" in why})
    matches.sort(key=lambda m: -m["score"])
    best = matches[0] if matches else None
    verdict = ("VERIFIED_MATCH" if best and best["verified"] else
               "PROBABLE_MATCH" if best else "NO_MATCH")
    return {"ok": True, "path": str(p), "size": size, "size_human": human_bytes(size),
            "type": kind, "extension": ext, "format_ok": fmt_ok, "sha256": sha, "md5": md5,
            "matches": matches[:5], "verdict": verdict,
            "suggested_block": best["block_id"] if best else None,
            "suggested_filename": best["filename"] if best else p.name}


def registry_path(layout):
    return layout.State / "user_images.json"


def load_registry(layout):
    return load_json(registry_path(layout), {})


def register(layout, analysis, block_id, txn, oplog, allow_unverified=False):
    """Copy the user's image into Store/user/sha256 and map it to `block_id`."""
    if analysis.get("verdict") != "VERIFIED_MATCH" and not allow_unverified:
        raise ValueError("checksum does not match the appliance definition; "
                         "pass allow_unverified to register anyway")
    if not analysis.get("format_ok"):
        raise ValueError(f"unexpected format '{analysis.get('type')}' for this file")
    sha = analysis["sha256"]
    dst = layout.user_store / sha
    op = f"import-{sha[:12]}"
    if not dst.exists():
        txn.intent(op, {"kind": "file", "path": str(dst), "sha256": sha, "role": "user_image"})
        place_file(analysis["path"], dst, expected_sha=sha)
        txn.commit(op)
    reg = load_registry(layout)
    fname = analysis.get("suggested_filename") if analysis.get("suggested_block") == block_id \
        else Path(analysis["path"]).name
    reg[block_id] = {"sha256": sha, "md5": analysis["md5"], "size": analysis["size"],
                     "logical_filename": fname, "type": analysis["type"],
                     "verdict": analysis["verdict"], "registered_at": utc_now(),
                     "source_name": Path(analysis["path"]).name}
    write_json(registry_path(layout), reg)
    oplog.log("REGISTER_USER_IMAGE", dst, "OK", operation_id=op, actual_sha256=sha,
              after={"block_id": block_id, "verdict": analysis["verdict"]})
    return reg[block_id]
