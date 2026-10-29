# SPDX-License-Identifier: GPL-3.0-or-later
"""After installing from an extracted bundle, keep the payload of the installed blocks
inside <root>/Store (CAS) so verify/repair keep working after the bundle folder is
deleted. Hardlinks when the bundle is on the same filesystem (no extra space);
a copy only when the user allowed copying; otherwise the bundle stays the payload."""
import os, shutil
from pathlib import Path
from ..core.util import load_json, write_json, human_bytes


def _link_or_copy(src, dst, allow_copy):
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return "reuse"
    tmp = dst.with_name(dst.name + ".vasya-partial")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
        how = "link"
    except OSError:
        if not allow_copy:
            return None
        shutil.copyfile(src, tmp)
        how = "copy"
    os.replace(tmp, dst)
    return how


def adopt(ctx, block_ids, allow_copy=False, log=None):
    src = Path(ctx.payload_root).resolve()
    store = ctx.layout.Store.resolve()
    if src == store or not block_ids:
        return {"adopted": src == store, "payload_root": str(src)}
    blocks = [b for b in ctx.payload.blocks if b["block_id"] in set(block_ids)]
    (store / "images" / "sha256").mkdir(parents=True, exist_ok=True)
    stats = {"link": 0, "copy": 0, "reuse": 0, "bytes_copied": 0}
    for b in blocks:
        for im in b.get("images") or []:
            s = ctx.payload.root / "images" / "sha256" / im["sha256"]
            if not s.exists():
                return {"adopted": False, "payload_root": str(src), "reason": f"missing {s.name}"}
            how = _link_or_copy(s, store / "images" / "sha256" / im["sha256"], allow_copy)
            if how is None:
                return {"adopted": False, "payload_root": str(src),
                        "reason": "bundle on another filesystem and copying not allowed: "
                                  "keep the extracted bundle folder for repair"}
            stats[how] += 1
            if how == "copy":
                stats["bytes_copied"] += s.stat().st_size
        if b.get("template"):
            t = store / b["template"]
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ctx.payload.root / b["template"], t)
    man_p = store / "manifests" / "pack.json"
    man = load_json(man_p, None) or {k: v for k, v in ctx.payload.manifest.items() if k != "blocks"}
    have = {b["block_id"]: b for b in man.get("blocks", [])}
    for b in blocks:
        have[b["block_id"]] = b
    man["blocks"] = list(have.values())
    write_json(man_p, man)
    with ctx.state.edit() as st:
        st["payload_root"] = str(store)
        st["payload_source"] = str(src)
    if log:
        log.log("ADOPT_PAYLOAD", str(store), "OK", after=stats)
    return {"adopted": True, "payload_root": str(store), **stats,
            "bytes_copied_human": human_bytes(stats["bytes_copied"])}
