# SPDX-License-Identifier: GPL-3.0-or-later
"""Import the READY payload (images + manifests) from the Linux release archive.

Used by the Windows Setup.exe build: the app is small, the 6+ GB of images are NOT
duplicated into a second Windows archive — the user downloads the same
VASYA-GNS-LAB-<ver>-Linux.tar.zst parts and the Manager pulls only TOP/Payload/*
into <VASYA_ROOT>/Store. Every part is checked (sha256, cached), the joined stream is
checked against the whole-archive sha256, every image is checked against its CAS name,
and nothing becomes visible until the final atomic rename of Store.partial -> Store.
"""
import hashlib, io, json, os, shutil, subprocess, tarfile
from pathlib import Path
from . import parts as P

STORE_PARTIAL = "Store.partial"


class _Chain(io.RawIOBase):
    """Read the parts in order as one stream, hashing everything."""
    def __init__(self, manifest, found, progress=None):
        self.files = [found[p["name"]] for p in manifest["parts"]]
        self.h, self.done, self.total = hashlib.sha256(), 0, manifest["size"]
        self.cur, self.progress = None, progress

    def readable(self):
        return True

    def readinto(self, b):
        while True:
            if self.cur is None:
                if not self.files:
                    return 0
                self.cur = open(self.files.pop(0), "rb")
            n = self.cur.readinto(b)
            if n:
                self.h.update(memoryview(b)[:n]); self.done += n
                if self.progress:
                    self.progress(self.done, self.total)
                return n
            self.cur.close(); self.cur = None


def _decompressor(raw):
    try:
        import zstandard
        return zstandard.ZstdDecompressor().stream_reader(raw, read_size=1 << 20), None
    except ImportError:
        zb = shutil.which("zstd")
        if not zb:
            raise P.PartsError("NO_ZSTD", "neither the zstandard module nor the zstd program is available")
        pr = subprocess.Popen([zb, "-dcq"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        import threading
        def pump():
            try:
                for c in iter(lambda: raw.read(1 << 20), b""):
                    pr.stdin.write(c)
            finally:
                pr.stdin.close()
        threading.Thread(target=pump, daemon=True).start()
        return pr.stdout, pr


def _safe(name, top):
    pre = f"{top}/Payload/"
    if not name.startswith(pre):
        return None
    rel = name[len(pre):]
    parts = Path(rel).parts
    if not rel or rel.startswith("/") or ".." in parts:
        return None
    return Path(*parts)


def import_payload(root, manifest_path, search_dirs=None, progress=None):
    """manifest_path: NAME.parts.json (parts searched next to it and in search_dirs)."""
    root = Path(root)
    man = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    top = man.get("top_dir") or man["archive"].split(".tar")[0]
    dirs = [Path(manifest_path).parent] + [Path(d) for d in (search_dirs or [])]
    try:
        found = P.find_parts(man, dirs)
    except P.PartsError:
        P.unpack_drive_zips(dirs, man["archive"], Path(manifest_path).parent)
        found = P.find_parts(man, dirs)
    P.verify_parts(man, found, progress=(lambda i, n, name, s: progress("verify", i, n)) if progress else None)
    tmp = root / STORE_PARTIAL
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    raw = _Chain(man, found, (lambda d, t: progress("extract", d, t)) if progress else None)
    stream, proc = _decompressor(io.BufferedReader(raw, 1 << 20))
    files, bad = 0, []
    try:
        with tarfile.open(fileobj=stream, mode="r|") as tf:
            for m in tf:
                rel = _safe(m.name, top)
                if rel is None:
                    continue
                dst = tmp / rel
                if m.isdir():
                    dst.mkdir(parents=True, exist_ok=True)
                elif m.isfile():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    h = hashlib.sha256()
                    with tf.extractfile(m) as src, open(dst, "wb") as o:
                        for c in iter(lambda: src.read(1 << 20), b""):
                            h.update(c); o.write(c)
                    if rel.parts[:2] == ("images", "sha256") and h.hexdigest() != rel.name:
                        bad.append(str(rel))
                    files += 1
                elif m.islnk():
                    srcrel = _safe(m.linkname, top)
                    if srcrel and (tmp / srcrel).exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            os.link(tmp / srcrel, dst)
                        except OSError:
                            shutil.copyfile(tmp / srcrel, dst)
                        files += 1
                # symlinks / devices inside Payload are ignored on purpose
        for _ in iter(lambda: raw.read(1 << 20), b""):
            pass  # hash any trailing bytes (tar padding) for the whole-archive check
    finally:
        if proc:
            proc.wait()
    if raw.done != man["size"] or raw.h.hexdigest() != man["sha256"]:
        shutil.rmtree(tmp, ignore_errors=True)
        raise P.PartsError("ARCHIVE_CORRUPT", "joined archive checksum mismatch",
                           {"expected": man["sha256"], "actual": raw.h.hexdigest()})
    if bad or not (tmp / "manifests" / "pack.json").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise P.PartsError("ARCHIVE_CORRUPT", "payload incomplete or damaged", {"bad_images": bad})
    store = root / "Store"
    old = None
    if (store / "user").exists():   # the user's own registered images stay
        os.replace(store / "user", tmp / "user")
    if store.exists():
        old = root / "Store.old"
        shutil.rmtree(old, ignore_errors=True)
        os.replace(store, old)
    os.replace(tmp, store)
    if old:
        shutil.rmtree(old, ignore_errors=True)
    return {"store": str(store), "files": files, "archive_sha256": man["sha256"]}
