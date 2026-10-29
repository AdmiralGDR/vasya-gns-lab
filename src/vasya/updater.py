# SPDX-License-Identifier: GPL-3.0-or-later
"""Updater: delta update of the payload store by CAS hash + idempotent re-apply.

Objects whose SHA-256 is already present in the store are never copied again;
GNS3 targets that already hold an identical image are REUSEd by the planner.
"""
import shutil
from pathlib import Path
from .core.cas import Payload, place_file, CopyNotAllowed
from .core.util import load_json, sha256_file, utc_now, human_bytes, write_json
from .core import txn as txnmod
from .core.state import root_lock


def store_delta(src_root, dst_root, deep=False):
    src, dst = Payload(src_root), Payload(dst_root)
    have = dst.unique_images()
    plan = {"copy": [], "reuse": [], "orphan": []}
    for sha, im in src.unique_images().items():
        p = Path(dst_root) / "images" / "sha256" / sha
        if p.exists() and p.stat().st_size == im.get("size", p.stat().st_size) and \
                (not deep or sha256_file(p) == sha):
            plan["reuse"].append({"sha256": sha, "size": im.get("size", 0)})
        else:
            plan["copy"].append({"sha256": sha, "size": im.get("size", 0),
                                 "source": str(src.image_path(sha))})
    new_shas = set(src.unique_images())
    for sha in have:
        if sha not in new_shas:
            plan["orphan"].append(sha)
    plan["bytes_copy"] = sum(x["size"] for x in plan["copy"])
    plan["bytes_reused"] = sum(x["size"] for x in plan["reuse"])
    plan["from_version"] = dst.version
    plan["to_version"] = src.version
    return plan


def update_store(ctx, src_root, progress=None, allow_copy=False):
    """Bring new CAS objects into <root>/Store: hardlink (zero extra disk); a full copy only
    with allow_copy. If neither is possible the store keeps referencing src_root."""
    lay = ctx.layout
    dst_root = lay.Store
    d = store_delta(src_root, dst_root)
    with root_lock(lay):
        t = txnmod.Transaction(lay, "update", meta={"from": d["from_version"], "to": d["to_version"]})
        log = ctx.oplog(t.txid)
        referenced, methods = [], {}
        for i, x in enumerate(d["copy"], 1):
            dst = dst_root / "images" / "sha256" / x["sha256"]
            op = f"{i:04d}"
            t.intent(op, {"kind": "store_object", "path": str(dst), "sha256": x["sha256"]})
            try:
                m, _ = place_file(x["source"], dst, expected_sha=x["sha256"],
                                  methods=("hardlink", "copy") if allow_copy else ("hardlink",),
                                  verify_link=True)
            except CopyNotAllowed:
                t.abort_op(op, "hardlink impossible, copy not allowed")
                referenced.append(x["sha256"])
                continue
            t.commit(op, {"kind": "store_object", "path": str(dst), "sha256": x["sha256"], "method": m})
            methods[m] = methods.get(m, 0) + 1
            log.log("STORE_" + m.upper(), dst, "NEW", operation_id=op, actual_sha256=x["sha256"])
            if progress:
                progress(i, len(d["copy"]), x["sha256"])
        for x in d["reuse"]:
            log.log("STORE_REUSE", x["sha256"], "REUSE")
        for sub in ("manifests", "appliances", "docker"):
            s = Path(src_root) / sub
            if s.exists():
                shutil.copytree(s, dst_root / sub, dirs_exist_ok=True)
        for sha in d["orphan"]:
            (dst_root / "images" / "sha256" / sha).unlink(missing_ok=True)
            log.log("STORE_DROP_ORPHAN", sha, "REMOVED")
        t.end("OK", {"copied": len(d["copy"]), "reused": len(d["reuse"]),
                     "bytes_copied": d["bytes_copy"], "bytes_reused": d["bytes_reused"]})
        d["methods"] = methods
        d["referenced"] = referenced
        with ctx.state.edit() as st:
            # only switch to the local store when it is complete; else keep referencing src
            st["payload_root"] = str(dst_root if not referenced else Path(src_root))
            st["last_operation"] = {"kind": "update-store", "at": utc_now(), "status": "OK"}
    d["bytes_copy_human"] = human_bytes(d["bytes_copy"])
    d["bytes_reused_human"] = human_bytes(d["bytes_reused"])
    return d
