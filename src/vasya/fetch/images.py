# SPDX-License-Identifier: GPL-3.0-or-later
"""Get every image a set of blocks needs, before the install plan is built.

Order for each image (identified by SHA-256 of its final, uncompressed content):
  1. already present (payload, or <root>/Store/user/sha256/<sha>)       -> nothing to do
  2. public, pinned in third_party.lock                                 -> official upstream URL
  3. listed in the user's private manifest                              -> private sources
Every file is verified against its SHA-256 before it is moved into the store. Anything that
cannot be obtained is reported as IMAGE_NOT_AVAILABLE; the plan then skips those devices.
"""
import os, shutil, subprocess
from pathlib import Path
from ..core.util import utc_now, write_json
from . import download, lock as L, private, unpack


def _place(layout, sha):
    dst = layout.user_store / sha

    def put(src):
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".partial")
        tmp.unlink(missing_ok=True)
        try:
            os.link(src, tmp)
        except OSError:
            shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    return put


def fetch_public(layout, sha, e, opener=None, progress=None):
    """Download one lock entry into the user store. {"status": "FETCHED"|"FAIL"|"OFFLINE", ...}"""
    dst = layout.user_store / sha
    if not e.get("urls"):
        return {"status": "FAIL", "reason": "no public download URL"}
    if not e.get("compression"):
        r = download.fetch(e["urls"], dst, sha, size=e.get("size"), opener=opener, progress=progress,
                           timeout=120)
        return ({"status": "FETCHED", "url": r.get("url")} if r["status"] == "OK" else
                {"status": r["status"], "reason": "; ".join(r["errors"])[-400:]})
    cache = download.cache_dir(layout) / sha[:16]
    arc = cache / (e.get("download_name") or Path(e["urls"][0]).name)
    r = download.fetch(e["urls"], arc, e.get("download_sha256"), size=e.get("download_size"),
                       opener=opener, progress=progress, timeout=120)
    if r["status"] != "OK":
        return {"status": r["status"], "reason": "; ".join(r["errors"])[-400:]}
    tmp = cache / (sha + ".unpacked")
    try:
        unpack.decompress(arc, tmp, e["compression"], e.get("archive_member"))
        if (e.get("size") and tmp.stat().st_size != e["size"]) or download.sha256_file(tmp) != sha:
            return {"status": "FAIL", "reason": f"unpacked {e.get('filename')} does not match the pinned sha256"}
        _place(layout, sha)(tmp)
    except Exception as ex:
        return {"status": "FAIL", "reason": f"cannot unpack {arc.name}: {ex}"}
    finally:
        tmp.unlink(missing_ok=True)
    arc.unlink(missing_ok=True)       # keep only the verified image, not the archive
    return {"status": "FETCHED", "url": r.get("url")}


def needed(ctx, block_ids=None):
    """{sha: {"filename", "size", "blocks": [...]}} for images not yet available locally."""
    out = {}
    for b in ctx.blocks():
        if block_ids is not None and b["block_id"] not in block_ids:
            continue
        for im in b.get("images") or []:
            if ctx.payload.image_path(im["sha256"]).exists():
                continue
            rec = out.setdefault(im["sha256"], {"filename": im.get("logical_filename"),
                                                "size": im.get("size"), "blocks": []})
            rec["blocks"].append(b["block_id"])
    return out


def ensure(ctx, block_ids=None, use_private=True, opener=None, run=subprocess.run, progress=None,
           log=None):
    """Fetch what `block_ids` (None = all) need. Never raises for a missing image."""
    lay = ctx.layout
    rep = {"at": utc_now(), "offline": download.offline(), "private_manifest": None, "images": {}}
    if use_private:
        srcs = private.sources(run)
        rep["private_sources"] = [private.describe(s) for s in srcs]
        try:
            rep["private_manifest"] = private.sync_manifest(lay, srcs, run=run)
        except Exception as ex:
            rep["private_manifest"] = {"status": "NONE", "errors": [str(ex)]}
    else:
        srcs = []
    lk = L.load()
    priv = private.manifest_images(lay) if use_private else {}
    for sha, need in sorted(needed(ctx, block_ids).items()):
        e = lk.get("images", {}).get(sha)
        if e and not e.get("private"):
            r = fetch_public(lay, sha, e, opener=opener, progress=progress)
            src = "public"
        elif sha in priv:
            r = private.fetch_image(lay, sha, priv[sha].get("logical_filename") or need["filename"],
                                    size=need.get("size"), srcs=srcs, run=run, place=_place(lay, sha))
            src = "private"
        else:
            r, src = {"status": "NOT_AVAILABLE", "reason": "no public or private source for this image"}, None
        if r["status"] != "FETCHED":
            r = dict(r, status="NOT_AVAILABLE", detail=r["status"])
        rep["images"][sha] = dict(need, kind=src, **r)
        if log:
            log.log("FETCH_IMAGE", need["filename"] or sha, "OK" if r["status"] == "FETCHED" else "WARN",
                    actual_sha256=sha, after={k: r.get(k) for k in ("status", "source", "url", "reason")})
    rep["fetched"] = sorted(s for s, v in rep["images"].items() if v["status"] == "FETCHED")
    rep["not_available"] = sorted(s for s, v in rep["images"].items() if v["status"] != "FETCHED")
    try:
        write_json(lay.State / "fetch-report.json", rep)
    except OSError:
        pass
    return rep
