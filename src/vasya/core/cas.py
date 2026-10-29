# SPDX-License-Identifier: GPL-3.0-or-later
"""Content-addressed payload store + crash-safe file placement."""
import os, shutil
from pathlib import Path
from .util import load_json, sha256_file

PARTIAL_SUFFIX = ".vasya-partial"


class Payload:
    """READY-block payload: manifests/pack.json + images/sha256/<hash> + appliances/."""

    def __init__(self, root, user_store=None):
        self.root = Path(root)
        self.manifest = load_json(self.root / "manifests" / "pack.json", {"blocks": []})
        self.user_store = Path(user_store) if user_store else None

    @property
    def blocks(self):
        return self.manifest.get("blocks", [])

    @property
    def version(self):
        return self.manifest.get("product_version") or self.manifest.get("pack_version")

    def block(self, bid):
        return next((b for b in self.blocks if b["block_id"] == bid), None)

    def image_path(self, sha):
        p = self.root / "images" / "sha256" / sha
        if p.exists() or not self.user_store:
            return p
        u = self.user_store / sha
        return u if u.exists() else p

    def appliance_path(self, block):
        return self.root / block["template"] if block.get("template") else None

    def unique_images(self, block_ids=None):
        out = {}
        for b in self.blocks:
            if block_ids is not None and b["block_id"] not in block_ids:
                continue
            for im in b.get("images") or []:
                out[im["sha256"]] = im
        return out

    def verify(self, block_ids=None, deep=True):
        res = []
        for sha, im in sorted(self.unique_images(block_ids).items()):
            p = self.image_path(sha)
            st = "PASS"; detail = ""
            if not p.exists():
                st, detail = "FAIL", "missing"
            elif im.get("size") and p.stat().st_size != im["size"]:
                st, detail = "FAIL", f"size {p.stat().st_size} != {im['size']}"
            elif deep and sha256_file(p) != sha:
                st, detail = "FAIL", "sha256 mismatch"
            res.append({"sha256": sha, "path": str(p), "status": st, "detail": detail,
                        "logical_filename": im.get("logical_filename")})
        return res


def partial_path(dst):
    dst = Path(dst)
    return dst.with_name(f".{dst.name}{PARTIAL_SUFFIX}")


class CopyNotAllowed(RuntimeError):
    pass


def same_device(a, b):
    def dev(p):
        p = Path(p)
        while not p.exists() and p != p.parent:
            p = p.parent
        return os.stat(p).st_dev
    try:
        return dev(a) == dev(b)
    except OSError:
        return False


def place_file(src, dst, expected_sha=None, methods=("copy",), copy_hook=None, verify_link=False):
    """Place src at dst atomically via a hidden partial name, verify, rename.

    methods: ordered preference among "hardlink", "symlink", "copy". Disk is
    tight on real hosts, so big images default to ("hardlink", "symlink") and a
    copy happens only when the caller explicitly allows it (CopyNotAllowed).
    A crash leaves at most the partial file, whose name is deterministic and
    recorded in the WAL INTENT, so rollback can always find it.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = partial_path(dst)
    if part.is_symlink() or part.exists():
        part.unlink()
    method = None
    for m in methods:
        try:
            if m == "hardlink":
                os.link(src, part)
            elif m == "symlink":
                os.symlink(os.path.abspath(src), part)
            elif m == "copy":
                if copy_hook:
                    copy_hook(src, part)
                else:
                    shutil.copyfile(src, part)
            method = m
            break
        except OSError:
            continue
    if method is None:
        raise CopyNotAllowed(f"cannot hardlink/symlink {Path(src).name} into {dst.parent} "
                             f"and copying was not allowed")
    check = expected_sha and (method == "copy" or verify_link)
    actual = sha256_file(part) if check else (expected_sha if method != "copy" else None)
    if check and actual != expected_sha:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"post-copy sha256 mismatch {actual} != {expected_sha}")
    os.replace(part, dst)
    return method, actual
